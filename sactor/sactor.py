import os

from sactor import thirdparty, utils
from sactor.c_parser import CParser
from sactor.combiner import Combiner
from sactor.combiner import CombineResult
from sactor.divider import Divider
from sactor.llm import AzureOpenAILLM, OpenAILLM
from sactor.thirdparty import C2Rust
from sactor.translator import TranslateResult, UnidiomaticTranslator


class Sactor:
    def __init__(
        self,
        input_file: str,
        test_cmd: str,
        build_dir=None,
        result_dir=None,
        config_file=None,
        no_verify=False,
        unidiomatic_only=False,
    ):
        self.input_file = input_file
        self.test_cmd = test_cmd.split()
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
        self.combiner = Combiner(self.c_parser.get_functions(), self.c_parser.get_structs(),
                                 self.test_cmd, self.build_dir)

        # Initialize LLM
        match self.config['general'].get("llm"):
            case "AzureOpenAI":
                self.llm = AzureOpenAILLM(self.config)
            case "OpenAI":
                self.llm = OpenAILLM(self.config)
            case _:
                raise ValueError(
                    f"Invalid LLM type: {self.config['general'].get('llm')}")

    def run(self):
        self._run_unidomatic_translation()
        combine_result = self.combiner.combine(os.path.join(
            self.result_dir, "translated_code_unidiomatic"))
        if combine_result != CombineResult.SUCCESS:
            raise ValueError("Failed to combine translated code for unidiomatic translation")
        if not self.unidiomatic_only:
            self._run_idiomatic_translation()
            result = self.combiner.combine(os.path.join(
                self.result_dir, "translated_code_idiomatic"))
            if result != CombineResult.SUCCESS:
                raise ValueError("Failed to combine translated code for idiomatic translation")

    def _run_unidomatic_translation(self):
        self.c2rust_translation = self.c2rust.get_c2rust_translation()

        translator = UnidiomaticTranslator(
            self.llm,
            self.c2rust_translation,
            self.c_parser,
            self.test_cmd,
            build_path=self.build_dir,
            result_path=self.result_dir,
            max_attempts=self.config['general']['max_translation_attempts'],
        )

        for struct_pairs in self.struct_order:
            for struct in struct_pairs:
                result = translator.translate_struct(struct)
                if result != TranslateResult.SUCCESS:
                    print(f"Failed to translate struct {struct}")
                    return

        for function_pairs in self.function_order:
            for function in function_pairs:
                # TODO: support multiple functions for each translation
                result = translator.translate_function(function)
                if result != TranslateResult.SUCCESS:
                    print(f"Failed to translate function {function}")
                    return

    def _run_idiomatic_translation(self):
        self.c2rust_translation = self.c2rust.get_c2rust_translation()

        translator = UnidiomaticTranslator(
            self.llm,
            self.c2rust_translation,
            self.c_parser,
            self.test_cmd,
            build_path=self.build_dir,
            result_path=self.result_dir,
            max_attempts=self.config['general']['max_translation_attempts'],
        )

        for struct_pairs in self.struct_order:
            for struct in struct_pairs:
                # TODO: support multiple structs for each translation
                result = translator.translate_struct(struct)
                if result != TranslateResult.SUCCESS:
                    print(f"Failed to translate struct {struct}")
                    return

        for function_pairs in self.function_order:
            for function in function_pairs:
                # TODO: support multiple functions for each translation
                result = translator.translate_function(function)
                if result != TranslateResult.SUCCESS:
                    print(f"Failed to translate function {function}")
                    return
