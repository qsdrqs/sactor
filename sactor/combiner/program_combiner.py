import os
from typing import override

from sactor import utils
from sactor.c_parser import FunctionInfo, StructInfo
from sactor.thirdparty.rustfmt import RustFmt
from sactor.verifier import E2EVerifier, VerifyResult

from .combiner import Combiner
from .combiner_types import CombineResult
from .rust_code import RustCode


class ProgramCombiner(Combiner):
    def __init__(self, functions: list[FunctionInfo], structs: list[StructInfo], test_cmd_path, build_path):
        self.functions = functions
        self.structs = structs

        self.verifier = E2EVerifier(test_cmd_path, build_path)

    @override
    def combine(self, result_dir_with_type: str) -> tuple[CombineResult, str | None]:
        function_code: dict[str, RustCode] = {}
        struct_code: dict[str, RustCode] = {}
        for function in self.functions:
            function_name = function.name
            with open(os.path.join(result_dir_with_type, 'functions', f'{function_name}.rs'), "r") as f:
                f_code = f.read()
                function_code[function_name] = RustCode(f_code)

        for struct in self.structs:
            struct_name = struct.name
            with open(os.path.join(result_dir_with_type, 'structs', f'{struct_name}.rs'), "r") as f:
                s_code = f.read()
                struct_code[struct_name] = RustCode(s_code)

        output_code = self._combine_code(function_code, struct_code)

        # verify the combined code
        result = self.verifier.e2e_verify(output_code, executable=True)
        if result[0] != VerifyResult.SUCCESS:
            print(f"Error: Failed to verify the combined code: {result[1]}")
            match result[0]:
                case VerifyResult.COMPILE_ERROR:
                    return CombineResult.COMPILE_FAILED, None
                case VerifyResult.TEST_ERROR:
                    return CombineResult.TEST_FAILED, None
                case _:
                    raise ValueError(
                        f"Unexpected error during verification: {result[0]}")

        # save the combined code
        file_path = os.path.join(result_dir_with_type, 'combined.rs')
        utils.save_code(
            path=file_path,
            code=output_code
        )

        # format the code
        rustfmt = RustFmt(file_path)
        try:
            rustfmt.format()
        except OSError as e:
            print(e)
            return CombineResult.RUSTFMT_FAILED, None


        return CombineResult.SUCCESS, output_code
