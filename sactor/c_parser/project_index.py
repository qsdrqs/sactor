import heapq
import os
from functools import lru_cache
from typing import Optional

from sactor import logging as sactor_logging, utils
from sactor.c_parser import CParser

logger = sactor_logging.get_logger(__name__)


def order_translation_units_by_dependencies(
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
                    "Hint: ensure defining .c is in compile_commands.json and flags are correct."
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


def build_project_usr_owner_maps(
    translation_units: list[str],
    compile_commands_file: str,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    """Return project-wide USR owner maps for symbols visible in the compile DB.

    Returns (func_usr_to_tu, struct_usr_to_tu, enum_usr_to_tu, global_usr_to_tu),
    where values are the owning translation unit absolute paths.

    Ownership rule:
    - First writer wins in `translation_units` order (stable).
    - We warn on conflicting ownership (same USR seen from different TUs).
    """
    function_usr_to_tu: dict[str, str] = {}
    struct_usr_to_tu: dict[str, str] = {}
    enum_usr_to_tu: dict[str, str] = {}
    global_usr_to_tu: dict[str, str] = {}
    for tu_path in translation_units:
        commands = utils.load_compile_commands_from_file(
            compile_commands_file,
            tu_path,
        )
        compile_flags = utils.get_compile_flags_from_commands(commands)
        parser = CParser(tu_path, extra_args=compile_flags, omit_error=True)
        for function in parser.get_functions() or []:
            usr = getattr(function, "usr", "") or ""
            if not usr:
                continue
            existing_owner = function_usr_to_tu.get(usr)
            if existing_owner and existing_owner != tu_path:
                logger.warning(
                    "Function USR %s defined in multiple translation units (%s, %s); owner selection may be ambiguous.",
                    usr,
                    existing_owner,
                    tu_path,
                )
            else:
                function_usr_to_tu.setdefault(usr, tu_path)

        for struct in parser.get_structs() or []:
            usr = None
            try:
                usr = struct.node.get_usr()  # type: ignore[attr-defined]
            except Exception:
                usr = None
            if not usr:
                continue
            existing_owner = struct_usr_to_tu.get(usr)
            if existing_owner and existing_owner != tu_path:
                logger.warning(
                    "Struct USR %s observed in multiple translation units (%s, %s); owner selection may be ambiguous.",
                    usr,
                    existing_owner,
                    tu_path,
                )
            else:
                struct_usr_to_tu.setdefault(usr, tu_path)

        for enum in parser.get_enums() or []:
            usr = None
            try:
                usr = enum.node.get_usr()  # type: ignore[attr-defined]
            except Exception:
                usr = None
            if not usr:
                continue
            existing_owner = enum_usr_to_tu.get(usr)
            if existing_owner and existing_owner != tu_path:
                logger.warning(
                    "Enum USR %s observed in multiple translation units (%s, %s); owner selection may be ambiguous.",
                    usr,
                    existing_owner,
                    tu_path,
                )
            else:
                enum_usr_to_tu.setdefault(usr, tu_path)

        for g in parser.get_global_vars() or []:
            usr = None
            try:
                usr = g.node.get_usr()  # type: ignore[attr-defined]
            except Exception:
                usr = None
            if not usr:
                continue
            existing_owner = global_usr_to_tu.get(usr)
            if existing_owner and existing_owner != tu_path:
                logger.warning(
                    "Global USR %s observed in multiple translation units (%s, %s); owner selection may be ambiguous.",
                    usr,
                    existing_owner,
                    tu_path,
                )
            else:
                global_usr_to_tu.setdefault(usr, tu_path)
    return function_usr_to_tu, struct_usr_to_tu, enum_usr_to_tu, global_usr_to_tu


def build_link_closure(
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
        raise ValueError("No C translation units found in compile_commands.json")

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
                if function.name == "main":
                    main_tus.append(tu_path)
            except Exception:
                pass

            usr = getattr(function, "usr", "") or ""
            owner = function_usr_to_tu.get(usr)
            if usr and owner and owner != tu_path:
                logger.warning(
                    "Function USR %s defined in multiple translation units (%s, %s); ordering may be ambiguous.",
                    usr or function.name,
                    owner,
                    tu_path,
                )
            else:
                if usr:
                    function_usr_to_tu.setdefault(usr, tu_path)

            for ref in getattr(function, "function_dependencies", []) or []:
                if getattr(ref, "usr", None):
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
                "No main function found in project. Please specify --entry-tu-file to select the entry translation unit."
            )
        else:
            raise ValueError(
                "Multiple main functions detected. Please specify --entry-tu-file. Candidates: "
                + ", ".join(unique_mains)
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
                f"Entry TU {entry_tu_file} not present in compile_commands.json")
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
                    f"Unresolved reference from {cur}: function USR={usr}. "
                    "Hint: ensure defining .c is in compile_commands.json and flags are correct."
                )
            if owner != cur and owner not in seen:
                queue.append(owner)

    # Keep stable order by input index
    closure.sort(key=lambda p: index_lookup[p])
    return closure


@lru_cache(maxsize=4)
def build_nonfunc_def_maps(compile_commands_file: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
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
                    struct_def_map.setdefault(usr, getattr(struct.node.location.file, "name", tu_path))

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
                    enum_def_map.setdefault(usr, getattr(enum.node.location.file, "name", tu_path))

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
                    global_def_map.setdefault(usr, getattr(g.node.location.file, "name", tu_path))
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Skipping %s during backfill indexing due to error: %s", tu_path, exc)

    return struct_def_map, enum_def_map, global_def_map
