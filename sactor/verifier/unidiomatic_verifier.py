import os
import subprocess
from typing import override

from sactor.c_parser import FunctionInfo

from .verifier_types import VerifyResult
from .verifier import Verifier


class UnidiomaticVerifier(Verifier):
    def __init__(self, test_cmd, build_path=None):
        super().__init__(test_cmd, build_path)

    @override
    def verify_function(self, function: FunctionInfo, rust_code, function_dependency_signatures, has_prefix) -> tuple[VerifyResult, str | None]:
        # Try to compile the Rust code
        compile_result = self._try_compile_rust_code(
            rust_code, function_dependency_signatures)
        if compile_result[0] != VerifyResult.SUCCESS:
            return compile_result

        # Run the tests
        test_error = self._embed_test_rust(
            function, rust_code, function_dependency_signatures, has_prefix)

        if test_error[0] != VerifyResult.SUCCESS:
            print(f"Error: Failed to run tests for function {function.name}")
            return test_error

        return (VerifyResult.SUCCESS, None)

