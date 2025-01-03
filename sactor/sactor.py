import os

from sactor import c_parser, thirdparty, utils
from sactor.c_parser import CParser
from sactor.combiner import ProgramCombiner, CombineResult
from sactor.divider import Divider
from sactor.llm import AzureOpenAILLM, OllamaLLM, OpenAILLM
from sactor.thirdparty import C2Rust, Crown
from sactor.translator import (IdiomaticTranslator, TranslateResult, Translator,
                               UnidiomaticTranslator)
from sactor.verifier import Verifier, idiomatic_verifier


class Sactor:
    def __init__(
        self,
        input_file: str,
        test_cmd_path: str,
        build_dir=None,
        result_dir=None,
        config_file=None,
        no_verify=False,
        unidiomatic_only=False,
    ):
        self.input_file = input_file
        if not Verifier.verify_test_cmd(test_cmd_path):
            raise ValueError("Invalid test command path or format")
        self.test_cmd_path = test_cmd_path
        self.build_dir = os.path.join(
            utils.get_temp_dir(), "build") if build_dir is None else build_dir

        self.result_dir = os.path.join(utils.get_temp_dir(
        ), "result") if result_dir is None else result_dir

        self.config_file = config_file
        self.no_verify = no_verify
        self.unidiomatic_only = unidiomatic_only

        self.config = utils.try_load_config(self.config_file)

        # Check necessary requirements
        missing_requirements = thirdparty.check_all_requirements()
        if missing_requirements:
            raise OSError(
                f"Missing requirements: {', '.join(missing_requirements)}")

        # Initialize Processors
        self.c_parser = CParser(self.input_file)
        self.divider = Divider(self.c_parser)

        self.struct_order = self.divider.get_struct_order()
        self.function_order = self.divider.get_function_order()

        self.c2rust = C2Rust(self.input_file)
        self.combiner = ProgramCombiner(self.c_parser.get_functions(), self.c_parser.get_structs(),
                                 self.test_cmd_path, self.build_dir)

        # Initialize LLM
        match self.config['general'].get("llm"):
            case "AzureOpenAI":
                self.llm = AzureOpenAILLM(self.config)
            case "OpenAI":
                self.llm = OpenAILLM(self.config)
            case "Ollama":
                self.llm = OllamaLLM(self.config)
            case _:
                raise ValueError(
                    f"Invalid LLM type: {self.config['general'].get('llm')}")

        self.c2rust_translation = None

    def run(self):
        result, unidiomatic_translator = self._run_unidomatic_translation()
        # Collect failure info
        unidiomatic_translator.save_failure_info(os.path.join(
            self.result_dir, "unidiomatic_failure_info.json"))
        if result != TranslateResult.SUCCESS:
            raise ValueError(
                f"Failed to translate unidiomatic code: {result}")
        combine_result, _ = self.combiner.combine(os.path.join(
            self.result_dir, "translated_code_unidiomatic"))
        if combine_result != CombineResult.SUCCESS:
            raise ValueError(
                f"Failed to combine translated code for unidiomatic translation: {combine_result}")
        if not self.unidiomatic_only:
            result, idiomatic_translator = self._run_idiomatic_translation()
            # Collect failure info
            idiomatic_translator.save_failure_info(os.path.join(
                self.result_dir, "idiomatic_failure_info.json"))
            if result != TranslateResult.SUCCESS:
                raise ValueError(
                    f"Failed to translate idiomatic code: {result}")

            combine_result, _ = self.combiner.combine(os.path.join(
                self.result_dir, "translated_code_idiomatic"))
            if combine_result != CombineResult.SUCCESS:
                raise ValueError(
                    f"Failed to combine translated code for idiomatic translation: {combine_result}")

        # LLM statistics
        self.llm.statistic(os.path.join(self.result_dir, "llm_statistic.json"))

    def _new_unidiomatic_translator(self):
        if self.c2rust_translation is None:
            self.c2rust_translation = self.c2rust.get_c2rust_translation()

        translator = UnidiomaticTranslator(
            self.llm,
            self.c2rust_translation,
            self.c_parser,
            self.test_cmd_path,
            max_attempts=self.config['general']['max_translation_attempts'],
            build_path=self.build_dir,
            result_path=self.result_dir,
        )
        return translator

    def _run_unidomatic_translation(self) -> tuple[TranslateResult, Translator]:
        translator = self._new_unidiomatic_translator()

        for struct_pairs in self.struct_order:
            for struct in struct_pairs:
                result = translator.translate_struct(struct)
                if result != TranslateResult.SUCCESS:
                    print(f"Failed to translate struct {struct}")
                    return result, translator

        for function_pairs in self.function_order:
            for function in function_pairs:
                # TODO: support multiple functions for each translation
                result = translator.translate_function(function)
                if result != TranslateResult.SUCCESS:
                    print(f"Failed to translate function {function}")
                    return result, translator

        return TranslateResult.SUCCESS, translator

    def _new_idiomatic_translator(self):
        if self.c2rust_translation is None:
            self.c2rust_translation = self.c2rust.get_c2rust_translation()

        crown = Crown(self.build_dir)
        crown.analyze(self.c2rust_translation)

        translator = IdiomaticTranslator(
            self.llm,
            c2rust_translation=self.c2rust_translation,
            crown_result=crown,
            c_parser=self.c_parser,
            test_cmd_path=self.test_cmd_path,
            max_attempts=self.config['general']['max_translation_attempts'],
            max_verifier_harness_attempts=self.config['general']['max_verifier_harness_attempts'],
            build_path=self.build_dir,
            result_path=self.result_dir,
        )

        return translator

    def _run_idiomatic_translation(self) -> tuple[TranslateResult, Translator]:
        translator = self._new_idiomatic_translator()

        for struct_pairs in self.struct_order:
            for struct in struct_pairs:
                # TODO: support multiple structs for each translation
                result = translator.translate_struct(struct)
                if result != TranslateResult.SUCCESS:
                    print(f"Failed to translate struct {struct}")
                    return result, translator

        for function_pairs in self.function_order:
            for function in function_pairs:
                # TODO: support multiple functions for each translation
                result = translator.translate_function(function)
                if result != TranslateResult.SUCCESS:
                    print(f"Failed to translate function {function}")
                    return result, translator

        return TranslateResult.SUCCESS, translator
