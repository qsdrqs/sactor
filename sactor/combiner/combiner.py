import os
from sys import executable

from sactor import utils
from sactor.c_parser import FunctionInfo, StructInfo
from sactor.thirdparty.rustfmt import RustFmt
from sactor.verifier import E2EVerifier, VerifyResult

from .combiner_types import CombineResult
from .rust_code import RustCode


class Combiner():
    def __init__(self, functions: list[FunctionInfo], structs: list[StructInfo], test_cmd, build_path):
        self.functions = functions
        self.structs = structs

        self.verifier = E2EVerifier(test_cmd, build_path)

    def _merge_uses(self, all_uses: list[list[str]]) -> list[str]:
        return [
            f'use {"::".join(use)};'
            for use in all_uses
        ]

    def combine(self, result_dir_with_type: str) -> CombineResult:
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


        # collect all uses in the functions and structs
        all_uses: list[list[str]] = []
        for function in function_code.keys():
            all_uses += function_code[function].used_code_list

        for struct in struct_code.keys():
            all_uses += struct_code[struct].used_code_list

        # deduplicate
        all_uses_tuples = set(tuple(x) for x in all_uses)
        all_uses = [list(x) for x in all_uses_tuples]

        # uses + structs + functions
        output_code = []
        uses_code = self._merge_uses(all_uses)
        output_code += uses_code

        for struct in struct_code.keys():
            output_code.append(struct_code[struct].remained_code)

        for function in function_code.keys():
            output_code.append(function_code[function].remained_code)

        output_code = '\n'.join(output_code)

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
            return CombineResult.RUSTFMT_FAILED

        # verify the combined code
        result = self.verifier.e2e_verify(output_code, executable=True)
        if result[0] != VerifyResult.SUCCESS:
            print(f"Error: Failed to verify the combined code: {result[1]}")

        return CombineResult.SUCCESS
