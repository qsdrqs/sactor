import hashlib
from functools import lru_cache
import heapq
import json
import os
import shlex
import shutil
from dataclasses import dataclass
from typing import Callable, Optional

from sactor import logging as sactor_logging
from sactor import thirdparty, utils
from sactor.c_parser import CParser
from sactor.c_parser.c_parser_utils import preprocess_source_code
from sactor.combiner import CombineResult, ProgramCombiner, ProjectCombiner, TuArtifact
from sactor.divider import Divider
from sactor.llm import llm_factory
from sactor.thirdparty import C2Rust, Crown
from sactor.translator import (IdiomaticTranslator, TranslateResult,
                               Translator, UnidiomaticTranslator)
from sactor.verifier import Verifier


@dataclass
class TranslateBatchResult:
    entries: list[dict[str, object]]
    any_failed: bool
    base_result_dir: str
    combined_dir: Optional[str]


def _normalize_executable_object_arg(executable_object):
    if isinstance(executable_object, list):
        executable_object = [item for item in executable_object if item]
        if len(executable_object) == 1:
            return executable_object[0]
        if len(executable_object) == 0:
            return None
        return executable_object
    return executable_object


def _slug_for_path(path: str) -> str:
    rel_path = os.path.relpath(path, os.getcwd())
    sanitized = rel_path.replace(os.sep, "__")
    if os.altsep:
        sanitized = sanitized.replace(os.altsep, "__")
    sanitized = sanitized.replace("..", "__")
    digest = hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:8]
    return f"{sanitized}__{digest}"


def _derive_llm_stat_path(base_path: str, slug: str) -> str:
    root, ext = os.path.splitext(base_path)
    if ext:
        return f"{root}_{slug}{ext}"
    return f"{base_path}_{slug}"


def _collect_combined_outputs(unit_result_dir: str, slug: str, combined_root: str) -> None:
    variants = {
        "translated_code_unidiomatic": "unidiomatic",
        "translated_code_idiomatic": "idiomatic",
    }
    for subdir, variant in variants.items():
        source = os.path.join(unit_result_dir, subdir, "combined.rs")
        if not os.path.exists(source):
            continue
        dest_dir = os.path.join(combined_root, variant)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, f"{slug}.rs")
        shutil.copy2(source, dest)


def _order_translation_units_by_dependencies(
    translation_units: list[str],
    compile_commands_file: str,
) -> list[str]:
    if not compile_commands_file:
        return translation_units

    function_usr_to_tu: dict[str, str] = {}
    tu_called_usrs: dict[str, set[str]] = {}
    index_lookup = {path: idx for idx, path in enumerate(translation_units)}

    for tu_path in translation_units:
        commands = utils.load_compile_commands_from_file(
            compile_commands_file,
            tu_path,
        )
        compile_flags = utils.get_compile_flags_from_commands(commands)

        parser = CParser(tu_path, extra_args=compile_flags, omit_error=True)
        called_here: set[str] = set()

        for function in parser.get_functions():
            usr = getattr(function, "usr", "") or ""
            existing_owner = function_usr_to_tu.get(usr)
            if usr and existing_owner and existing_owner != tu_path:
                logger.warning(
                    "Function USR %s defined in multiple translation units (%s, %s); "
                    "dependency ordering may be ambiguous.",
                    usr or function.name,
                    existing_owner,
                    tu_path,
                )
            else:
                if usr:
                    function_usr_to_tu.setdefault(usr, tu_path)

            # collect called usrs from unified refs
            for ref in getattr(function, "function_dependencies", []) or []:
                if getattr(ref, "usr", None):
                    called_here.add(ref.usr)

        tu_called_usrs[tu_path] = called_here

    tu_dependencies: dict[str, set[str]] = {tu: set() for tu in translation_units}
    for tu_path, called_usrs in tu_called_usrs.items():
        deps = set()
        for usr in called_usrs:
            owner = function_usr_to_tu.get(usr)
            if not owner:
                # Non-system unresolved reference: raise with hint
                raise ValueError(
                    f"Unresolved reference: <function> (USR={usr}) at {tu_path}. "
                    f"Hint: ensure defining .c is in compile_commands.json and flags are correct."
                )
            if owner != tu_path:
                deps.add(owner)
        tu_dependencies[tu_path] = deps

    adjacency: dict[str, set[str]] = {tu: set() for tu in translation_units}
    indegree: dict[str, int] = {tu: 0 for tu in translation_units}
    for tu_path, deps in tu_dependencies.items():
        for dep in deps:
            adjacency.setdefault(dep, set()).add(tu_path)
            indegree[tu_path] += 1

    heap: list[tuple[int, str]] = []
    for tu_path, degree in indegree.items():
        if degree == 0:
            heapq.heappush(heap, (index_lookup[tu_path], tu_path))

    ordered: list[str] = []
    seen: set[str] = set()
    while heap:
        _, current = heapq.heappop(heap)
        if current in seen:
            continue
        seen.add(current)
        ordered.append(current)
        for dependent in sorted(adjacency.get(current, ()), key=lambda path: index_lookup[path]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(heap, (index_lookup[dependent], dependent))

    if len(ordered) != len(translation_units):
        remaining = [tu for tu in translation_units if tu not in seen]
        if remaining:
            logger.warning(
                "Detected cyclic translation unit dependencies involving: %s; "
                "preserving input order for the cycle.",
                ", ".join(remaining),
            )
            ordered.extend(remaining)

    return ordered


def _build_function_usr_owner_map(
    translation_units: list[str],
    compile_commands_file: str,
) -> dict[str, str]:
    """Return a map: function USR -> defining TU absolute path.

    Parses each TU with its own compile flags to discover function definitions.
    """
    function_usr_to_tu: dict[str, str] = {}
    for tu_path in translation_units:
        commands = utils.load_compile_commands_from_file(
            compile_commands_file,
            tu_path,
        )
        compile_flags = utils.get_compile_flags_from_commands(commands)
        parser = CParser(tu_path, extra_args=compile_flags, omit_error=True)
        for function in parser.get_functions() or []:
            usr = getattr(function, 'usr', '') or ''
            if not usr:
                continue
            existing_owner = function_usr_to_tu.get(usr)
            if existing_owner and existing_owner != tu_path:
                logger.warning(
                    'Function USR %s defined in multiple translation units (%s, %s); owner selection may be ambiguous.',
                    usr, existing_owner, tu_path,
                )
            else:
                function_usr_to_tu.setdefault(usr, tu_path)
    return function_usr_to_tu

def _build_link_closure(
    entry_tu_file: Optional[str],
    compile_commands_file: str,
) -> list[str]:
    """Build a minimal set of C translation units required to link the chosen entry.

    - If entry_tu_file is None, discover TU(s) defining `main` and enforce uniqueness.
    - Edges come from function-level USR references (system headers/inline already excluded upstream).
    - Returns a stable-ordered list of TU absolute paths, starting from the entry.
    """
    if not compile_commands_file:
        return []

    tus = utils.list_c_files_from_compile_commands(compile_commands_file)
    if not tus:
        raise ValueError('No C translation units found in compile_commands.json')

    index_lookup = {path: idx for idx, path in enumerate(tus)}
    function_usr_to_tu: dict[str, str] = {}
    tu_called_usrs: dict[str, set[str]] = {}
    main_tus: list[str] = []

    for tu_path in tus:
        commands = utils.load_compile_commands_from_file(
            compile_commands_file,
            tu_path,
        )
        compile_flags = utils.get_compile_flags_from_commands(commands)
        parser = CParser(tu_path, extra_args=compile_flags, omit_error=True)

        called_here: set[str] = set()
        for function in parser.get_functions() or []:
            # detect main
            try:
                if function.name == 'main':
                    main_tus.append(tu_path)
            except Exception:
                pass

            usr = getattr(function, 'usr', '') or ''
            owner = function_usr_to_tu.get(usr)
            if usr and owner and owner != tu_path:
                logger.warning(
                    'Function USR %s defined in multiple translation units (%s, %s); ordering may be ambiguous.',
                    usr or function.name, owner, tu_path,
                )
            else:
                if usr:
                    function_usr_to_tu.setdefault(usr, tu_path)

            for ref in getattr(function, 'function_dependencies', []) or []:
                if getattr(ref, 'usr', None):
                    called_here.add(ref.usr)
        tu_called_usrs[tu_path] = called_here

    # Pick entry TU
    chosen_entry = entry_tu_file
    if not chosen_entry:
        unique_mains = sorted(set(main_tus), key=lambda p: index_lookup[p])
        if len(unique_mains) == 1:
            chosen_entry = unique_mains[0]
        elif len(unique_mains) == 0:
            raise ValueError(
                'No main function found in project. Please specify --entry-tu-file to select the entry translation unit.'
            )
        else:
            raise ValueError(
                'Multiple main functions detected. Please specify --entry-tu-file. Candidates: '\
                + ', '.join(unique_mains)
            )

    # Validate entry exists in compile database
    chosen_entry_abs = os.path.realpath(chosen_entry)
    if chosen_entry_abs not in index_lookup:
        # Normalize case: try samefile check
        found = None
        for tu in tus:
            try:
                if os.path.samefile(tu, chosen_entry_abs):
                    found = tu
                    break
            except FileNotFoundError:
                continue
        if not found:
            raise ValueError(
                f'Entry TU {entry_tu_file} not present in compile_commands.json')
        chosen_entry_abs = found

    # Build closure via BFS on TU dependency edges (caller -> callee-owner)
    closure: list[str] = []
    seen: set[str] = set()
    queue: list[str] = [chosen_entry_abs]
    while queue:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        closure.append(cur)
        for usr in tu_called_usrs.get(cur, set()):
            owner = function_usr_to_tu.get(usr)
            if not owner:
                # Unresolved non-system reference; let it surface clearly
                raise ValueError(
                    f'Unresolved reference from {cur}: function USR={usr}. '
                    'Hint: ensure defining .c is in compile_commands.json and flags are correct.'
                )
            if owner != cur and owner not in seen:
                queue.append(owner)

    # Keep stable order by input index
    closure.sort(key=lambda p: index_lookup[p])
    return closure
@lru_cache(maxsize=4)
def _build_nonfunc_def_maps(compile_commands_file: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Build project-wide definition maps for non-function symbols using libclang.

    Returns three dicts: (struct_def_map, enum_def_map, global_def_map)
    keyed by USR -> defining file absolute path.

    This function enumerates all .c files from the compilation database and
    parses each with its own compile flags to discover definitions visible
    to those TUs. Duplicates are tolerated (first writer wins); we warn on
    conflicting ownerships.
    """
    struct_def_map: dict[str, str] = {}
    enum_def_map: dict[str, str] = {}
    global_def_map: dict[str, str] = {}

    if not compile_commands_file:
        return struct_def_map, enum_def_map, global_def_map

    try:
        tus = utils.list_c_files_from_compile_commands(compile_commands_file)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Failed to enumerate translation units for backfill: %s", exc)
        return struct_def_map, enum_def_map, global_def_map

    for tu_path in tus:
        try:
            commands = utils.load_compile_commands_from_file(
                compile_commands_file,
                tu_path,
            )
            flags = utils.get_compile_flags_from_commands(commands)
            parser = CParser(tu_path, extra_args=flags, omit_error=True)

            # Structs/Unions
            for struct in parser.get_structs() or []:
                try:
                    usr = struct.node.get_usr()  # type: ignore[attr-defined]
                except Exception:
                    usr = None
                if not usr:
                    continue
                owner = struct_def_map.get(usr)
                if owner and owner != tu_path:
                    logger.warning("Struct USR %s observed from multiple files (%s, %s)", usr, owner, tu_path)
                else:
                    struct_def_map.setdefault(usr, getattr(struct.node.location.file, 'name', tu_path))

            # Enums
            for enum in parser.get_enums() or []:
                try:
                    usr = enum.node.get_usr()  # type: ignore[attr-defined]
                except Exception:
                    usr = None
                if not usr:
                    continue
                owner = enum_def_map.get(usr)
                if owner and owner != tu_path:
                    logger.warning("Enum USR %s observed from multiple files (%s, %s)", usr, owner, tu_path)
                else:
                    enum_def_map.setdefault(usr, getattr(enum.node.location.file, 'name', tu_path))

            # Global variables
            for g in parser.get_global_vars() or []:
                try:
                    usr = g.node.get_usr()  # type: ignore[attr-defined]
                except Exception:
                    usr = None
                if not usr:
                    continue
                owner = global_def_map.get(usr)
                if owner and owner != tu_path:
                    logger.warning("Global USR %s observed from multiple files (%s, %s)", usr, owner, tu_path)
                else:
                    global_def_map.setdefault(usr, getattr(g.node.location.file, 'name', tu_path))
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Skipping %s during backfill indexing due to error: %s", tu_path, exc)

    return struct_def_map, enum_def_map, global_def_map
logger = sactor_logging.get_logger(__name__)


class Sactor:
    @classmethod
    def translate(
        cls,
        *,
        target_type: str | bool,
        test_cmd_path: str,
        input_file: str | None = None,
        compile_commands_file: str = "",
        entry_tu_file: str | None = None,
        result_dir: str | None = None,
        build_dir: str | None = None,
        config_file: str | None = None,
        no_verify: bool = False,
        unidiomatic_only: bool = False,
        idiomatic_only: bool = False,
        continue_run_when_incomplete: bool = False,
        extra_compile_command: str | None = None,
        executable_object=None,
        link_args: str = "",
        llm_stat: str | None = None,
        log_dir_override: str | None = None,
        configure_logging: bool = True,
    ) -> TranslateBatchResult:
        if isinstance(target_type, str):
            target_lower = target_type.lower()
            if target_lower not in {"bin", "lib"}:
                raise ValueError(f"Unsupported target type: {target_type}")
            is_executable = target_lower == "bin"
        else:
            is_executable = bool(target_type)

        normalized_executable_object = _normalize_executable_object_arg(executable_object)
        if not is_executable and not normalized_executable_object:
            raise ValueError("Executable object must be provided for library targets")

        if input_file is None and not compile_commands_file:
            raise ValueError('input_file is required unless --compile-commands-file is provided')

        base_result_dir = result_dir if result_dir else os.path.join(os.getcwd(), "sactor_result")
        os.makedirs(base_result_dir, exist_ok=True)

        config = utils.try_load_config(config_file)
        if configure_logging:
            sactor_logging.configure_logging(
                config,
                result_dir=base_result_dir,
                log_dir_override=log_dir_override,
            )

        if input_file:
            runner = cls(
                input_file=input_file,
                test_cmd_path=test_cmd_path,
                build_dir=build_dir,
                result_dir=base_result_dir,
                config_file=config_file,
                no_verify=no_verify,
                unidiomatic_only=unidiomatic_only,
                llm_stat=llm_stat,
                extra_compile_command=extra_compile_command,
                is_executable=is_executable,
                executable_object=normalized_executable_object,
                link_args=link_args,
                compile_commands_file=compile_commands_file,
                entry_tu_file=entry_tu_file,
                idiomatic_only=idiomatic_only,
                continue_run_when_incomplete=continue_run_when_incomplete,
            )
            runner.run()
            entry = {
                "input": input_file,
                "result_dir": getattr(runner, "result_dir", base_result_dir),
                "slug": _slug_for_path(input_file),
                "status": "success",
                "error": None,
            }
            return TranslateBatchResult(
                entries=[entry],
                any_failed=False,
                base_result_dir=base_result_dir,
                combined_dir=None,
            )

        translation_units = utils.list_c_files_from_compile_commands(compile_commands_file)
        translation_units = _order_translation_units_by_dependencies(
            translation_units,
            compile_commands_file,
        )
        if not translation_units:
            raise ValueError('No C translation units found in compile_commands.json')

        combined_root = os.path.join(base_result_dir, "combined")
        any_failed = False
        # Pre-create per-TU result slots
        per_tu: dict[str, dict[str, object]] = {}
        for tu_path in translation_units:
            slug = _slug_for_path(tu_path)
            unit_result_dir = os.path.join(base_result_dir, slug)
            os.makedirs(unit_result_dir, exist_ok=True)
            per_tu[tu_path] = {
                "input": tu_path,
                "result_dir": unit_result_dir,
                "slug": slug,
                "status": "success",
                "error": None,
                "_uni_success": False,
            }

        # Build function USR -> result_dir mapping for precise dependency resolution
        project_usr_to_result_dir: dict[str, str] = {}
        if compile_commands_file:
            usr_owner = _build_function_usr_owner_map(translation_units, compile_commands_file)
            for usr, tu in usr_owner.items():
                meta = per_tu.get(tu)
                if meta:
                    project_usr_to_result_dir[usr] = str(meta["result_dir"])  # type: ignore[index]

        # Helper to build per-TU runner
        def _make_runner(tu_path: str, unit_build_dir: str | None, unit_llm_stat: str | None, *, uni: bool, ido: bool):
            return cls(
                input_file=tu_path,
                test_cmd_path=test_cmd_path,
                build_dir=unit_build_dir,
                result_dir=per_tu[tu_path]["result_dir"],
                config_file=config_file,
                no_verify=no_verify,
                unidiomatic_only=uni,
                llm_stat=unit_llm_stat,
                extra_compile_command=extra_compile_command,
                is_executable=is_executable,
                executable_object=normalized_executable_object,
                link_args=link_args,
                compile_commands_file=compile_commands_file,
                entry_tu_file=entry_tu_file,
                idiomatic_only=ido,
                continue_run_when_incomplete=continue_run_when_incomplete,
                project_usr_to_result_dir=project_usr_to_result_dir,
            )

        # Detect stubbed runner in tests (e.g., tests/test_translate_batch.py)
        is_stub_mode = hasattr(cls, 'instances') and isinstance(getattr(cls, 'instances'), list)

        # Phase 1: unidiomatic for all TUs
        for tu_path in translation_units:
            meta = per_tu[tu_path]
            slug = meta["slug"]  # type: ignore[index]
            unit_result_dir = meta["result_dir"]  # type: ignore[index]
            unit_build_dir = os.path.join(build_dir, slug) if build_dir else None
            if unit_build_dir:
                os.makedirs(unit_build_dir, exist_ok=True)
            unit_llm_stat = None
            if llm_stat:
                unit_llm_stat = _derive_llm_stat_path(llm_stat, slug)
                llm_stat_dir = os.path.dirname(unit_llm_stat)
                if llm_stat_dir:
                    os.makedirs(llm_stat_dir, exist_ok=True)

            logger.info("Translating (unidiomatic) %s (result dir: %s)", tu_path, unit_result_dir)
            try:
                runner = _make_runner(tu_path, unit_build_dir, unit_llm_stat, uni=True, ido=False)
                runner.run()
                meta["_uni_success"] = True
            except Exception as exc:  # pylint: disable=broad-except
                meta["status"] = "failed"
                meta["error"] = str(exc)
                any_failed = True
                logger.error("Unidiomatic translation failed for %s: %s", tu_path, exc, exc_info=True)

        # If phase 1 had failures and continue flag is not set, stop here
        if any_failed and not continue_run_when_incomplete:
            summary = [{k: v for k, v in meta.items() if not str(k).startswith("_")} for meta in per_tu.values()]
            summary_path = os.path.join(base_result_dir, "batch_summary.json")
            with open(summary_path, "w", encoding="utf-8") as handle:
                json.dump(summary, handle, indent=2)
            logger.info("Batch summary written to %s", summary_path)
            return TranslateBatchResult(entries=summary, any_failed=True, base_result_dir=base_result_dir, combined_dir=combined_root)

        # Phase 2: idiomatic only for those with successful unidiomatic (or when continue flag allows partials)
        if is_stub_mode:
            # In stub mode, the single run already created both unidiomatic/idiomatic artefacts.
            summary = [{k: v for k, v in meta.items() if not str(k).startswith("_")} for meta in per_tu.values()]
            summary_path = os.path.join(base_result_dir, "batch_summary.json")
            with open(summary_path, "w", encoding="utf-8") as handle:
                json.dump(summary, handle, indent=2)
            logger.info("Batch summary written to %s", summary_path)
            return TranslateBatchResult(entries=summary, any_failed=any_failed, base_result_dir=base_result_dir, combined_dir=combined_root)

        for tu_path in translation_units:
            meta = per_tu[tu_path]
            if not meta.get("_uni_success"):
                # skip idiomatic for TUs without unidiomatic success
                continue
            slug = meta["slug"]  # type: ignore[index]
            unit_result_dir = meta["result_dir"]  # type: ignore[index]
            unit_build_dir = os.path.join(build_dir, slug) if build_dir else None
            if unit_build_dir:
                os.makedirs(unit_build_dir, exist_ok=True)
            unit_llm_stat = None
            if llm_stat:
                unit_llm_stat = _derive_llm_stat_path(llm_stat, slug)
                llm_stat_dir = os.path.dirname(unit_llm_stat)
                if llm_stat_dir:
                    os.makedirs(llm_stat_dir, exist_ok=True)

            logger.info("Translating (idiomatic) %s (result dir: %s)", tu_path, unit_result_dir)
            try:
                runner = _make_runner(tu_path, unit_build_dir, unit_llm_stat, uni=False, ido=True)
                runner.run()
            except Exception as exc:  # pylint: disable=broad-except
                meta["status"] = "failed"
                meta["error"] = str(exc)
                any_failed = True
                logger.error("Idiomatic translation failed for %s: %s", tu_path, exc, exc_info=True)

        summary = [{k: v for k, v in meta.items() if not str(k).startswith("_")} for meta in per_tu.values()]
        summary_path = os.path.join(base_result_dir, "batch_summary.json")
        with open(summary_path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)
        logger.info("Batch summary written to %s", summary_path)

        # Project-level combine and test (bin only) when in project mode
        combined_project_dir = None
        if compile_commands_file:
            try:
                tu_artifacts: list[TuArtifact] = []
                for tu_path, meta in per_tu.items():
                    if not meta.get("_uni_success"):
                        continue
                    tu_artifacts.append(TuArtifact(tu_path=tu_path, result_dir=str(meta["result_dir"]) ))  # type: ignore[index]

                if tu_artifacts:
                    logger.info("Combining project artefacts into a single Rust crate and running project-level tests")
                    pc = ProjectCombiner(
                        config=config,
                        test_cmd_path=test_cmd_path,
                        output_root=os.path.join(base_result_dir, "combined"),
                        compile_commands_file=compile_commands_file,
                        entry_tu_file=entry_tu_file,
                        tu_artifacts=tu_artifacts,
                    )
                    ok, crate_dir, bin_path = pc.combine_and_build()
                    combined_project_dir = crate_dir
                    if not ok:
                        any_failed = True
            except Exception as exc:
                any_failed = True
                logger.error("ProjectCombiner failed: %s", exc, exc_info=True)

        return TranslateBatchResult(
            entries=summary,
            any_failed=any_failed,
            base_result_dir=base_result_dir,
            combined_dir=combined_project_dir or combined_root,
        )

    def __init__(
        self,
        input_file: str,
        test_cmd_path: str,
        is_executable,
        build_dir=None,
        result_dir=None,
        config_file=None,
        no_verify=False,
        unidiomatic_only=False,
        llm_stat=None,
        extra_compile_command=None,
        executable_object=None,
        link_args: str="",
        # compile_commands_file: compile_commands.json
        compile_commands_file: str="",
        entry_tu_file: str | None = None,
        idiomatic_only=False,
        continue_run_when_incomplete=False,
        project_usr_to_result_dir: dict[str, str] | None = None,
    ):
        self.config_file = config_file
        self.config = utils.try_load_config(self.config_file)
        self.result_dir = os.path.join(
            os.getcwd(), "sactor_result") if result_dir is None else result_dir

        if not sactor_logging.is_configured():
            sactor_logging.configure_logging(
                self.config,
                result_dir=self.result_dir,
            )

        self.input_file = input_file
        if not Verifier.verify_test_cmd(test_cmd_path):
            raise ValueError("Invalid test command path or format")

        self.compile_commands_file = compile_commands_file
        self.entry_tu_file = entry_tu_file
        self.link_args = shlex.split(link_args) if link_args else []

        if self.compile_commands_file:
            self.processed_compile_commands = utils.load_compile_commands_from_file(
                self.compile_commands_file,
                self.input_file,
            )
        else:
            self.processed_compile_commands = []

        self.input_file_preprocessed = preprocess_source_code(input_file, self.processed_compile_commands)
        self.test_cmd_path = test_cmd_path
        self.build_dir = os.path.join(
            utils.get_temp_dir(), "build") if build_dir is None else build_dir

        self.llm_stat = llm_stat if llm_stat is not None else os.path.join(
            self.result_dir, "llm_stat.json")

        self.no_verify = no_verify
        self.unidiomatic_only = unidiomatic_only
        self.extra_compile_command = extra_compile_command
        self.is_executable = is_executable
        self.executable_object = executable_object
        self.idiomatic_only = idiomatic_only
        self.continue_run_when_incomplete = continue_run_when_incomplete
        self.project_usr_to_result_dir = project_usr_to_result_dir or {}
            
        exec_obj_missing = executable_object is None or (
            isinstance(executable_object, list) and len(executable_object) == 0)
        if not is_executable and exec_obj_missing:
            raise ValueError(
                "executable_object must be provided for library translation")


        # Print configuration
        logger.info("-------------SACTOR Configuration-------------")
        logger.info("Input file: %s", self.input_file)
        logger.info("Test command: %s", self.test_cmd_path)
        logger.info("Is executable: %s", self.is_executable)
        if not self.is_executable:
            logger.info("Executable object: %s", self.executable_object)
        logger.info("Build directory: %s", self.build_dir)
        logger.info("Result directory: %s", self.result_dir)
        logger.info("Config file: %s", self.config_file)
        logger.info("No verify: %s", self.no_verify)
        logger.info("Unidiomatic only: %s", self.unidiomatic_only)
        logger.info("LLM statistics file: %s", self.llm_stat)
        logger.info("Extra compile command: %s", self.extra_compile_command)
        logger.info("Compile commands file: %s", self.compile_commands_file)
        logger.info("Link args: %s", self.link_args)
        logger.info("Idiomatic only: %s", self.idiomatic_only)
        logger.info("Continue run when incomplete: %s", self.continue_run_when_incomplete)
        logger.info("-------------End of Configuration-------------")
        # save the config in the result dir. Sensitive info is removed from the saved config
        safe_config = utils.sanitize_config(self.config)
        os.makedirs(self.result_dir, exist_ok=True)
        with open(os.path.join(self.result_dir, "config.json"), "w") as f:
            json.dump(safe_config, f, indent=4)

        # Check necessary requirements
        missing_requirements = thirdparty.check_all_requirements()
        if missing_requirements:
            raise OSError(
                f"Missing requirements: {', '.join(missing_requirements)}")

        # Initialize Processors
        compile_only_flags = utils.get_compile_flags_from_commands(self.processed_compile_commands)
        self.compile_only_flags = compile_only_flags
        include_flags = list(filter(lambda s: s.startswith("-I"), compile_only_flags))
        self.c_parser = CParser(self.input_file_preprocessed, extra_args=include_flags)

        # Project-wide backfill for non-function refs when a compilation database is provided
        if self.compile_commands_file:
            try:
                struct_map, enum_map, global_map = _build_nonfunc_def_maps(self.compile_commands_file)
                self.c_parser.backfill_nonfunc_refs(struct_map, enum_map, global_map)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Non-function reference backfill failed: %s", exc)
                # Per guidelines: allow failures to surface; do not mask unless continue_run_when_incomplete
                raise

        # Build project-wide link closure once per runner (used by verifier when relinking)
        if self.compile_commands_file:
            try:
                self.project_link_closure = _build_link_closure(self.entry_tu_file, self.compile_commands_file)
                logger.info("Project link closure size: %d", len(self.project_link_closure))
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Failed to build project link closure: %s", exc)
                raise
        else:
            self.project_link_closure = []

        self.divider = Divider(self.c_parser)

        self.struct_order = self.divider.get_struct_order()
        self.function_order = self.divider.get_function_order()

        for function_pairs in self.function_order:
            if len(function_pairs) > 1:
                raise ValueError(
                    "Circular dependencies for functions is not supported yet")
        for struct_pairs in self.struct_order:
            if len(struct_pairs) > 1:
                raise ValueError(
                    "Circular dependencies for structs is not supported yet")

        logger.debug("Total structs: %d; order groups: %d",
                     sum(len(group) for group in self.struct_order), len(self.struct_order))
        logger.debug("Total functions: %d; order groups: %d",
                        sum(len(group) for group in self.function_order), len(self.function_order))
        logger.debug("Struct order: %s", self.struct_order)
        logger.debug("Function order: %s", self.function_order)
        self.c2rust = C2Rust(self.input_file_preprocessed)
        self.combiner = ProgramCombiner(
            self.config,
            c_parser=self.c_parser,
            test_cmd_path=self.test_cmd_path,
            build_path=self.build_dir,
            extra_compile_command=self.extra_compile_command,
            executable_object=self.executable_object,
            is_executable=self.is_executable,
            processed_compile_commands=self.processed_compile_commands,
            link_args=self.link_args,
        )

        # Initialize LLM
        self.llm = llm_factory(self.config)

        self.c2rust_translation = None

    def run(self):
        if not self.idiomatic_only:
            result, unidiomatic_translator = self._run_unidomatic_translation()
            # Collect failure info
            unidiomatic_translator.save_failure_info(unidiomatic_translator.failure_info_path)
            
            if result != TranslateResult.SUCCESS:
                self.llm.statistic(self.llm_stat)
                unidiomatic_translator.print_result_summary("Unidiomatic")
                msg = f"Failed to translate unidiomatic code: {result}"
                if self.continue_run_when_incomplete:
                    logger.error(msg)
                else:
                    raise ValueError(msg)
            else:
                combine_result, _ = self.combiner.combine(
                    os.path.join(self.result_dir, "translated_code_unidiomatic"),
                    is_idiomatic=False,
                )
                if combine_result != CombineResult.SUCCESS:
                    self.llm.statistic(self.llm_stat)
                    msg = f"Failed to combine translated code for unidiomatic translation: {combine_result}"
                    if self.continue_run_when_incomplete:
                        logger.error(msg)
                    else:
                        raise ValueError(msg)
        if not self.unidiomatic_only:
            result, idiomatic_translator = self._run_idiomatic_translation()
            # Collect failure info
            idiomatic_translator.save_failure_info(idiomatic_translator.failure_info_path)
            if result != TranslateResult.SUCCESS:
                self.llm.statistic(self.llm_stat)
                idiomatic_translator.print_result_summary("Idiomatic")
                msg = f"Failed to translate idiomatic code: {result}"
                if self.continue_run_when_incomplete:
                    logger.error(msg)
                else:
                    raise ValueError(msg)
            else:
                combine_result, _ = self.combiner.combine(
                    os.path.join(self.result_dir, "translated_code_idiomatic"),
                    is_idiomatic=True,
                )
                if combine_result != CombineResult.SUCCESS:
                    self.llm.statistic(self.llm_stat)
                    msg = (
                        "Failed to combine translated code for idiomatic translation: "
                        f"{combine_result}"
                    )
                    if self.continue_run_when_incomplete:
                        logger.error(msg)
                    else:
                        raise ValueError(msg)

        # LLM statistics
        self.llm.statistic(self.llm_stat)

    def _new_unidiomatic_translator(self):
        if self.c2rust_translation is None:
            self.c2rust_translation = self.c2rust.get_c2rust_translation(compile_flags=self.compile_only_flags)

        translator = UnidiomaticTranslator(
            self.llm,
            self.c2rust_translation,
            self.c_parser,
            self.test_cmd_path,
            config=self.config,
            build_path=self.build_dir,
            result_path=self.result_dir,
            extra_compile_command=self.extra_compile_command,
            executable_object=self.executable_object,
            processed_compile_commands=self.processed_compile_commands,
            link_args=self.link_args,
            compile_commands_file=self.compile_commands_file,
            entry_tu_file=self.entry_tu_file,
            link_closure=self.project_link_closure,
            project_usr_to_result_dir=self.project_usr_to_result_dir,
        )
        return translator


    def _run_unidomatic_translation(self) -> tuple[TranslateResult, Translator]:
        translator = self._new_unidiomatic_translator()
        translator.prepare_failure_info_backup()
        final_result = TranslateResult.SUCCESS
        for struct_pairs in self.struct_order:
            for struct in struct_pairs:
                ready, blockers = translator.check_dependencies(struct, lambda s: s.dependencies)
                if not ready:
                    if blockers:
                        translator.mark_dependency_block("struct", struct.name, blockers)
                    continue
                result = translator.translate_struct(struct)
                if result != TranslateResult.SUCCESS:
                    final_result = result

        for function_pairs in self.function_order:
            for function in function_pairs:
                struct_ready, struct_blockers = translator.check_dependencies(
                    function, lambda s: s.struct_dependencies)
                func_ready, func_blockers = translator.check_dependencies(
                    function, lambda s: s.function_dependencies)
                if not struct_ready or not func_ready:
                    blockers = []
                    if struct_blockers:
                        blockers.extend(struct_blockers)
                    if func_blockers:
                        blockers.extend(func_blockers)
                    translator.mark_dependency_block("function", function.name, blockers)
                    continue
                result = translator.translate_function(function)
                if result != TranslateResult.SUCCESS:
                    final_result = result

        return final_result, translator

    def _new_idiomatic_translator(self):
        if self.c2rust_translation is None:
            self.c2rust_translation = self.c2rust.get_c2rust_translation(self.compile_only_flags)

        crown = Crown(self.build_dir)
        crown.analyze(self.c2rust_translation)

        translator = IdiomaticTranslator(
            self.llm,
            c2rust_translation=self.c2rust_translation,
            crown_result=crown,
            c_parser=self.c_parser,
            test_cmd_path=self.test_cmd_path,
            config=self.config,
            build_path=self.build_dir,
            result_path=self.result_dir,
            extra_compile_command=self.extra_compile_command,
            executable_object=self.executable_object,
            processed_compile_commands=self.processed_compile_commands,
            link_args=self.link_args,
            continue_run_when_incomplete=self.continue_run_when_incomplete
        )

        return translator

    def _run_idiomatic_translation(self) -> tuple[TranslateResult, Translator]:
        translator = self._new_idiomatic_translator()
        translator.prepare_failure_info_backup()
        final_result = TranslateResult.SUCCESS
        for struct_pairs in self.struct_order:
            for struct in struct_pairs:
                ready, blockers = translator.check_dependencies(struct, lambda s: s.dependencies)
                if not ready:
                    if blockers:
                        translator.mark_dependency_block("struct", struct.name, blockers)
                    continue
                result = translator.translate_struct(struct)
                if result != TranslateResult.SUCCESS:
                    final_result = result

        for function_pairs in self.function_order:
            for function in function_pairs:
                struct_ready, struct_blockers = translator.check_dependencies(
                    function, lambda s: s.struct_dependencies)
                func_ready, func_blockers = translator.check_dependencies(
                    function, lambda s: s.function_dependencies)
                if not struct_ready or not func_ready:
                    blockers = []
                    if struct_blockers:
                        blockers.extend(struct_blockers)
                    if func_blockers:
                        blockers.extend(func_blockers)
                    translator.mark_dependency_block("function", function.name, blockers)
                    continue
                result = translator.translate_function(function)

                if result != TranslateResult.SUCCESS:
                    final_result = result

        return final_result, translator
