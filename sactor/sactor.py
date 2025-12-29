import json
import os
import shlex

from sactor import logging as sactor_logging
from sactor import thirdparty, utils
from sactor.c_parser import CParser
from sactor.c_parser.c_parser_utils import preprocess_source_code
from sactor.c_parser.project_index import build_link_closure, build_nonfunc_def_maps
from sactor.combiner import CombineResult, ProgramCombiner
from sactor.divider import Divider
from sactor.llm import llm_factory
from sactor.thirdparty import C2Rust, Crown
from sactor.translator import (IdiomaticTranslator, TranslateResult,
                               Translator, UnidiomaticTranslator)
from sactor.translator.batch_runner import run_translate_batch
from sactor.translator.translator_types import TranslateBatchResult
from sactor.verifier import Verifier


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
        if unidiomatic_only and idiomatic_only:
            raise ValueError("Only one of unidiomatic_only and idiomatic_only can be set")

        if isinstance(target_type, str):
            target_lower = target_type.lower()
            if target_lower not in {"bin", "lib"}:
                raise ValueError(f"Unsupported target type: {target_type}")
            is_executable = target_lower == "bin"
        else:
            is_executable = bool(target_type)

        normalized_executable_object = utils._normalize_executable_object_arg(executable_object)
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
                "slug": utils._slug_for_path(input_file),
                "status": "success",
                "error": None,
            }
            return TranslateBatchResult(
                entries=[entry],
                any_failed=False,
                base_result_dir=base_result_dir,
                combined_dir=None,
            )

        return run_translate_batch(
            runner_cls=cls,
            base_result_dir=base_result_dir,
            config=config,
            test_cmd_path=test_cmd_path,
            compile_commands_file=compile_commands_file,
            entry_tu_file=entry_tu_file,
            build_dir=build_dir,
            config_file=config_file,
            no_verify=no_verify,
            unidiomatic_only=unidiomatic_only,
            idiomatic_only=idiomatic_only,
            continue_run_when_incomplete=continue_run_when_incomplete,
            extra_compile_command=extra_compile_command,
            is_executable=is_executable,
            executable_object=normalized_executable_object,
            link_args=link_args,
            llm_stat=llm_stat,
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
        project_struct_usr_to_result_dir: dict[str, str] | None = None,
        project_enum_usr_to_result_dir: dict[str, str] | None = None,
        project_global_usr_to_result_dir: dict[str, str] | None = None,
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
        self.project_struct_usr_to_result_dir = project_struct_usr_to_result_dir or {}
        self.project_enum_usr_to_result_dir = project_enum_usr_to_result_dir or {}
        self.project_global_usr_to_result_dir = project_global_usr_to_result_dir or {}
            
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
        logger.info("LLM statistics base path: %s", self.llm_stat)
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
        self.c_parser = CParser(
            self.input_file_preprocessed,
            extra_args=include_flags,
            raw_filename=self.input_file,
        )

        # Project-wide backfill for non-function refs when a compilation database is provided
        if self.compile_commands_file:
            try:
                struct_map, enum_map, global_map = build_nonfunc_def_maps(self.compile_commands_file)
                self.c_parser.backfill_nonfunc_refs(struct_map, enum_map, global_map)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Non-function reference backfill failed: %s", exc)
                # Per guidelines: allow failures to surface; do not mask unless continue_run_when_incomplete
                raise

        # Build project-wide link closure once per runner (used by verifier when relinking)
        if self.compile_commands_file:
            try:
                self.project_link_closure = build_link_closure(self.entry_tu_file, self.compile_commands_file)
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
        def _stage_stat_path(stage: str) -> str:
            return utils._derive_llm_stat_path(self.llm_stat, stage=stage)

        if not self.idiomatic_only:
            self.llm.reset_statistics()
            unidiomatic_stat_path = _stage_stat_path("unidiomatic")
            result, unidiomatic_translator = self._run_unidomatic_translation()
            # Collect failure info
            unidiomatic_translator.save_failure_info(unidiomatic_translator.failure_info_path)

            stage_error = None
            if result != TranslateResult.SUCCESS:
                unidiomatic_translator.print_result_summary("Unidiomatic")
                stage_error = f"Failed to translate unidiomatic code: {result}"
            else:
                combine_result, _ = self.combiner.combine(
                    os.path.join(self.result_dir, "translated_code_unidiomatic"),
                    is_idiomatic=False,
                )
                if combine_result != CombineResult.SUCCESS:
                    stage_error = (
                        "Failed to combine translated code for unidiomatic translation: "
                        f"{combine_result}"
                    )

            self.llm.statistic(unidiomatic_stat_path)

            if stage_error:
                if self.continue_run_when_incomplete:
                    logger.error(stage_error)
                else:
                    raise ValueError(stage_error)

        if not self.unidiomatic_only:
            self.llm.reset_statistics()
            idiomatic_stat_path = _stage_stat_path("idiomatic")
            result, idiomatic_translator = self._run_idiomatic_translation()
            # Collect failure info
            idiomatic_translator.save_failure_info(idiomatic_translator.failure_info_path)

            stage_error = None
            if result != TranslateResult.SUCCESS:
                idiomatic_translator.print_result_summary("Idiomatic")
                stage_error = f"Failed to translate idiomatic code: {result}"
            else:
                combine_result, _ = self.combiner.combine(
                    os.path.join(self.result_dir, "translated_code_idiomatic"),
                    is_idiomatic=True,
                )
                if combine_result != CombineResult.SUCCESS:
                    stage_error = (
                        "Failed to combine translated code for idiomatic translation: "
                        f"{combine_result}"
                    )

            self.llm.statistic(idiomatic_stat_path)

            if stage_error:
                if self.continue_run_when_incomplete:
                    logger.error(stage_error)
                else:
                    raise ValueError(stage_error)

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
            project_struct_usr_to_result_dir=self.project_struct_usr_to_result_dir,
            project_enum_usr_to_result_dir=self.project_enum_usr_to_result_dir,
            project_global_usr_to_result_dir=self.project_global_usr_to_result_dir,
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
                logger.debug("Checking function %s: struct_ready=%s, struct_blockers=%s",
                             function.name, struct_ready, struct_blockers)
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
            compile_commands_file=self.compile_commands_file,
            entry_tu_file=self.entry_tu_file,
            link_closure=self.project_link_closure,
            project_usr_to_result_dir=self.project_usr_to_result_dir,
            project_struct_usr_to_result_dir=self.project_struct_usr_to_result_dir,
            project_enum_usr_to_result_dir=self.project_enum_usr_to_result_dir,
            project_global_usr_to_result_dir=self.project_global_usr_to_result_dir,
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
