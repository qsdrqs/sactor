import os
import subprocess
from typing import override

from sactor.c_parser import FunctionInfo
from sactor import rust_ast_parser

from .verifier import Verifier
from .verifier_types import VerifyResult


class UnidiomaticVerifier(Verifier):
    def __init__(self, test_cmd_path, build_path=None):
        super().__init__(test_cmd_path, build_path)

    @override
    def verify_function(self, function: FunctionInfo, function_code, struct_code, function_dependency_signatures, has_prefix) -> tuple[VerifyResult, str | None]:
        combined_code = rust_ast_parser.combine_struct_function(
            struct_code, function_code)

        # Try to compile the Rust code
        compile_result = self._try_compile_rust_code(
            combined_code, function_dependency_signatures)
        if compile_result[0] != VerifyResult.SUCCESS:
            return compile_result

        # Run the tests
        test_error = self._embed_test_rust(
            function, combined_code, function_dependency_signatures, has_prefix)

        if test_error[0] != VerifyResult.SUCCESS:
            print(f"Error: Failed to run tests for function {function.name}")
            return test_error

        return (VerifyResult.SUCCESS, None)
