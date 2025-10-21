import os
import json

from sactor import logging as sactor_logging
from sactor import thirdparty, utils
from sactor.c_parser import CParser
from sactor.c_parser.c_parser_utils import preprocess_source_code
from sactor.combiner import CombineResult, ProgramCombiner
from sactor.divider import Divider
from sactor.llm import llm_factory
from sactor.thirdparty import C2Rust, Crown
from sactor.translator import (IdiomaticTranslator, TranslateResult,
                               Translator, UnidiomaticTranslator)
from sactor.verifier import Verifier


logger = sactor_logging.get_logger(__name__)


class Sactor:
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
        all_compile_commands: str="",
        # compile_commands_file: compile_commands.json
        compile_commands_file: str="",
        idiomatic_only=False,
        continue_run_when_incomplete=False
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

        self.all_compile_commands = all_compile_commands
        self.processed_compile_commands = utils.process_commands_to_list(
            self.all_compile_commands,
            self.input_file
        )
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
            
        self.compile_commands_file = compile_commands_file
        if not is_executable and executable_object is None:
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
        logger.info("All compile commands: %s", self.all_compile_commands)
        logger.info("Compile commands file: %s", self.compile_commands_file)
        logger.info("Idiomatic only: %s", self.idiomatic_only)
        logger.info("Continue run when incomplete: %s", self.continue_run_when_incomplete)
        logger.info("-------------End of Configuration-------------")
        # save the config in the result dir. Sensitive info is removed from the saved config
        safe_config = utils.remove_keys_from_collection(self.config)
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
            processed_compile_commands=self.processed_compile_commands
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
                    print(msg)
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
                        print(msg)
                    else:
                        raise ValueError(msg)
        if not self.unidiomatic_only:
            result, idiomatic_translator = self._run_idiomatic_translation()
            # Collect failure info
            idiomatic_translator.save_failure_info(idiomatic_translator.failure_info_path)
            if result != TranslateResult.SUCCESS:
                self.llm.statistic(self.llm_stat)
                raise ValueError(
                    f"Failed to translate idiomatic code: {result}")

            combine_result, _ = self.combiner.combine(
                os.path.join(self.result_dir, "translated_code_idiomatic"),
                is_idiomatic=True,
            )
            if combine_result != CombineResult.SUCCESS:
                self.llm.statistic(self.llm_stat)
                raise ValueError(
                    f"Failed to combine translated code for idiomatic translation: {combine_result}")

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
        )
        return translator




    def _run_unidomatic_translation(self) -> tuple[TranslateResult, Translator]:
        translator = self._new_unidiomatic_translator()
        translator.prepare_failure_info_backup()
        final_result = TranslateResult.SUCCESS
        for struct_pairs in self.struct_order:
            for struct in struct_pairs:
                if not translator.has_dependencies_all_translated(struct, lambda s: s.dependencies, ty="struct"):
                    translator.init_failure_info("struct", struct.name)
                    translator.append_failure_info(
                        struct.name, 
                        "DEPENDENCY_ERROR", 
                        f"Not all dependencies are translated. Dependencies are: {str(struct.dependencies)}",
                        "")                    
                    continue
                result = translator.translate_struct(struct)
                if result != TranslateResult.SUCCESS:
                    final_result = result

        for function_pairs in self.function_order:
            for function in function_pairs:
                if not translator.has_dependencies_all_translated(function, lambda s: s.struct_dependencies, ty="struct") \
                    or not translator.has_dependencies_all_translated(function, lambda s: s.function_dependencies, ty="function"):
                    translator.init_failure_info("function", function.name)
                    translator.append_failure_info(
                        function.name, 
                        "DEPENDENCY_ERROR", 
                        (f"Not all dependencies are translated. Function dependencies are: {str(function.function_dependencies)}\n"
                         f"Struct dependencies are: {str(function.struct_dependencies)}"),
                         "")                    
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
            continue_run_when_incomplete=self.continue_run_when_incomplete
        )

        return translator

    def _run_idiomatic_translation(self) -> tuple[TranslateResult, Translator]:
        translator = self._new_idiomatic_translator()
        translator.prepare_failure_info_backup()
        final_result = TranslateResult.SUCCESS
        for struct_pairs in self.struct_order:
            for struct in struct_pairs:
                if not translator.has_dependencies_all_translated(struct, lambda s: s.dependencies, ty="struct"):
                    translator.init_failure_info("struct", struct.name)
                    translator.append_failure_info(
                        struct.name, 
                        "DEPENDENCY_ERROR", 
                        f"Not all dependencies are translated. Dependencies are: {str(struct.dependencies)}",
                        "")
                    continue
                result = translator.translate_struct(struct)
                if result != TranslateResult.SUCCESS:
                    final_result = result

        for function_pairs in self.function_order:
            for function in function_pairs:
                if not translator.has_dependencies_all_translated(function, lambda s: s.struct_dependencies, ty="struct") \
                    or not translator.has_dependencies_all_translated(function, lambda s: s.function_dependencies, ty="function"):
                    translator.init_failure_info("function", function.name)
                    translator.append_failure_info(
                        function.name, 
                        "DEPENDENCY_ERROR", 
                        (f"Not all dependencies are translated. Function dependencies are: {str(function.function_dependencies)}\n"
                         f"Struct dependencies are: {str(function.struct_dependencies)}"),
                         "")
                    continue
                result = translator.translate_function(function)

                if result != TranslateResult.SUCCESS:
                    final_result = result

        return final_result, translator
