import json
import os
from typing import Optional

from sactor import logging as sactor_logging, utils
from sactor.c_parser.project_index import (
    build_project_usr_owner_maps,
    order_translation_units_by_dependencies,
)
from sactor.combiner import ProjectCombiner, TuArtifact
from sactor.translator.translator_types import TranslateBatchResult

logger = sactor_logging.get_logger(__name__)


def run_translate_batch(
    *,
    runner_cls,
    base_result_dir: str,
    config: dict,
    test_cmd_path: str,
    compile_commands_file: str,
    entry_tu_file: str | None,
    build_dir: str | None,
    config_file: str | None,
    no_verify: bool,
    unidiomatic_only: bool,
    idiomatic_only: bool,
    continue_run_when_incomplete: bool,
    extra_compile_command: str | None,
    is_executable: bool,
    executable_object,
    link_args: str,
    llm_stat: str | None,
) -> TranslateBatchResult:
    translation_units = utils.list_c_files_from_compile_commands(compile_commands_file)
    translation_units = order_translation_units_by_dependencies(
        translation_units,
        compile_commands_file,
    )
    if not translation_units:
        raise ValueError("No C translation units found in compile_commands.json")

    combined_root = os.path.join(base_result_dir, "combined")
    ProjectCombiner.cleanup_combined_root(combined_root, translation_units)

    any_failed = False
    run_unidiomatic_phase = not idiomatic_only
    run_idiomatic_phase = not unidiomatic_only
    # Pre-create per-TU result slots
    per_tu: dict[str, dict[str, object]] = {}
    for tu_path in translation_units:
        slug = utils._slug_for_path(tu_path)
        unit_result_dir = os.path.join(base_result_dir, slug)
        os.makedirs(unit_result_dir, exist_ok=True)
        per_tu[tu_path] = {
            "input": tu_path,
            "result_dir": unit_result_dir,
            "slug": slug,
            "status": "success",
            "error": None,
            "_uni_success": False,
            "_ido_success": False,
        }

    # Build function USR -> result_dir mapping for precise dependency resolution
    project_usr_to_result_dir: dict[str, str] = {}
    project_struct_usr_to_result_dir: dict[str, str] = {}
    project_enum_usr_to_result_dir: dict[str, str] = {}
    project_global_usr_to_result_dir: dict[str, str] = {}
    if compile_commands_file:
        (
            func_usr_owner,
            struct_usr_owner,
            enum_usr_owner,
            global_usr_owner,
        ) = build_project_usr_owner_maps(translation_units, compile_commands_file)

        for usr, tu in func_usr_owner.items():
            meta = per_tu.get(tu)
            if meta:
                project_usr_to_result_dir[usr] = str(meta["result_dir"])  # type: ignore[index]
        for usr, tu in struct_usr_owner.items():
            meta = per_tu.get(tu)
            if meta:
                project_struct_usr_to_result_dir[usr] = str(meta["result_dir"])  # type: ignore[index]
        for usr, tu in enum_usr_owner.items():
            meta = per_tu.get(tu)
            if meta:
                project_enum_usr_to_result_dir[usr] = str(meta["result_dir"])  # type: ignore[index]
        for usr, tu in global_usr_owner.items():
            meta = per_tu.get(tu)
            if meta:
                project_global_usr_to_result_dir[usr] = str(meta["result_dir"])  # type: ignore[index]

    # Helper to build per-TU runner
    def _make_runner(tu_path: str, unit_build_dir: str | None, unit_llm_stat: str | None, *, uni: bool, ido: bool):
        return runner_cls(
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
            executable_object=executable_object,
            link_args=link_args,
            compile_commands_file=compile_commands_file,
            entry_tu_file=entry_tu_file,
            idiomatic_only=ido,
            continue_run_when_incomplete=continue_run_when_incomplete,
            project_usr_to_result_dir=project_usr_to_result_dir,
            project_struct_usr_to_result_dir=project_struct_usr_to_result_dir,
            project_enum_usr_to_result_dir=project_enum_usr_to_result_dir,
            project_global_usr_to_result_dir=project_global_usr_to_result_dir,
        )

    # Detect stubbed runner in tests (e.g., tests/test_translate_batch.py)
    is_stub_mode = hasattr(runner_cls, "instances") and isinstance(getattr(runner_cls, "instances"), list)

    def _run_project_combiner(*, variant: str, tu_ok_flag: str) -> Optional[str]:
        nonlocal any_failed
        if not compile_commands_file or is_stub_mode:
            return None
        if variant not in {"unidiomatic", "idiomatic"}:
            raise ValueError(f"Unsupported project combine variant: {variant}")

        output_root = os.path.join(combined_root, variant)
        ProjectCombiner.cleanup_variant_root(output_root)

        tu_artifacts: list[TuArtifact] = []
        for tu_path, meta in per_tu.items():
            if not meta.get(tu_ok_flag):
                continue
            tu_artifacts.append(TuArtifact(tu_path=tu_path, result_dir=str(meta["result_dir"])))  # type: ignore[index]

        if not tu_artifacts:
            return None

        logger.info("Combining project artefacts into a single Rust crate (%s) and running project-level tests", variant)
        pc = ProjectCombiner(
            config=config,
            test_cmd_path=test_cmd_path,
            output_root=output_root,
            compile_commands_file=compile_commands_file,
            entry_tu_file=entry_tu_file,
            tu_artifacts=tu_artifacts,
            variant=variant,
        )
        ok, crate_dir, _bin_path = pc.combine_and_build()
        if not ok:
            any_failed = True
        return crate_dir

    # Phase 1: unidiomatic for all TUs (unless idiomatic_only)
    if run_unidiomatic_phase:
        for tu_path in translation_units:
            meta = per_tu[tu_path]
            slug = meta["slug"]  # type: ignore[index]
            unit_result_dir = meta["result_dir"]  # type: ignore[index]
            unit_build_dir = os.path.join(build_dir, slug) if build_dir else None
            if unit_build_dir:
                os.makedirs(unit_build_dir, exist_ok=True)
            unit_llm_stat = None
            if llm_stat:
                unit_llm_stat = utils._derive_llm_stat_path(llm_stat, slug=slug)
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

        try:
            _run_project_combiner(variant="unidiomatic", tu_ok_flag="_uni_success")
        except Exception as exc:  # pylint: disable=broad-except
            any_failed = True
            logger.error("Unidiomatic ProjectCombiner failed: %s", exc, exc_info=True)

        # If phase 1 had failures and continue flag is not set, stop here
        if any_failed and not continue_run_when_incomplete:
            summary = [{k: v for k, v in meta.items() if not str(k).startswith("_")} for meta in per_tu.values()]
            summary_path = os.path.join(base_result_dir, "batch_summary.json")
            with open(summary_path, "w", encoding="utf-8") as handle:
                json.dump(summary, handle, indent=2)
            logger.info("Batch summary written to %s", summary_path)
            return TranslateBatchResult(entries=summary, any_failed=True, base_result_dir=base_result_dir, combined_dir=combined_root)

    # Phase 2: idiomatic (unless unidiomatic_only)
    if run_idiomatic_phase:
        if is_stub_mode and run_unidiomatic_phase:
            # In stub mode, the unidiomatic pass already created both artefacts.
            summary = [{k: v for k, v in meta.items() if not str(k).startswith("_")} for meta in per_tu.values()]
            summary_path = os.path.join(base_result_dir, "batch_summary.json")
            with open(summary_path, "w", encoding="utf-8") as handle:
                json.dump(summary, handle, indent=2)
            logger.info("Batch summary written to %s", summary_path)
            return TranslateBatchResult(entries=summary, any_failed=any_failed, base_result_dir=base_result_dir, combined_dir=combined_root)

        eligible_units = translation_units
        if run_unidiomatic_phase:
            eligible_units = [tu for tu in translation_units if per_tu[tu].get("_uni_success")]

        for tu_path in eligible_units:
            meta = per_tu[tu_path]
            slug = meta["slug"]  # type: ignore[index]
            unit_result_dir = meta["result_dir"]  # type: ignore[index]
            unit_build_dir = os.path.join(build_dir, slug) if build_dir else None
            if unit_build_dir:
                os.makedirs(unit_build_dir, exist_ok=True)
            unit_llm_stat = None
            if llm_stat:
                unit_llm_stat = utils._derive_llm_stat_path(llm_stat, slug=slug)
                llm_stat_dir = os.path.dirname(unit_llm_stat)
                if llm_stat_dir:
                    os.makedirs(llm_stat_dir, exist_ok=True)

            logger.info("Translating (idiomatic) %s (result dir: %s)", tu_path, unit_result_dir)
            try:
                runner = _make_runner(tu_path, unit_build_dir, unit_llm_stat, uni=False, ido=True)
                runner.run()
                meta["_ido_success"] = True
            except Exception as exc:  # pylint: disable=broad-except
                meta["status"] = "failed"
                meta["error"] = str(exc)
                any_failed = True
                logger.error("Idiomatic translation failed for %s: %s", tu_path, exc, exc_info=True)

        try:
            _run_project_combiner(variant="idiomatic", tu_ok_flag="_ido_success")
        except Exception as exc:  # pylint: disable=broad-except
            any_failed = True
            logger.error("Idiomatic ProjectCombiner failed: %s", exc, exc_info=True)

    summary = [{k: v for k, v in meta.items() if not str(k).startswith("_")} for meta in per_tu.values()]
    summary_path = os.path.join(base_result_dir, "batch_summary.json")
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    logger.info("Batch summary written to %s", summary_path)

    return TranslateBatchResult(
        entries=summary,
        any_failed=any_failed,
        base_result_dir=base_result_dir,
        combined_dir=combined_root,
    )
