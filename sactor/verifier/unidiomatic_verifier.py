import os
import subprocess
from typing import override

from sactor import rust_ast_parser
from sactor.c_parser import FunctionInfo
from sactor.combiner.partial_combiner import CombineResult, PartialCombiner

from .verifier import Verifier
from .verifier_types import VerifyResult


class UnidiomaticVerifier(Verifier):
    def __init__(
        self,
        test_cmd_path: str,
        config,
        build_path=None,
        no_feedback=False,
        extra_compile_command=None,
    ):
        super().__init__(
            test_cmd_path,
            config=config,
            build_path=build_path,
            no_feedback=no_feedback,
            extra_compile_command=extra_compile_command
        )

    @override
    def verify_function(
        self,
        function: FunctionInfo,
        function_code: str,
        struct_code: dict[str, str],
        function_dependency_signatures,
        has_prefix,
    ) -> tuple[VerifyResult, str | None]:
        functions = {function.name: function_code}
        combiner = PartialCombiner(functions, struct_code)
        result, combined_code = combiner.combine()
        if result != CombineResult.SUCCESS or combined_code is None:
            raise ValueError(f"Failed to combine the function {function.name}")

        # Try to compile the Rust code
        compile_result = self._try_compile_rust_code(
            combined_code,
            function_dependency_signatures=function_dependency_signatures
        )
        if compile_result[0] != VerifyResult.SUCCESS:
            return compile_result

        # Run the tests
        test_error = self._embed_test_rust(
            function, combined_code, function_dependency_signatures, has_prefix)

        if test_error[0] != VerifyResult.SUCCESS:
            print(f"Error: Failed to run tests for function {function.name}")
            return test_error

        return (VerifyResult.SUCCESS, None)

    @override
    def _try_compile_rust_code(self, rust_code, executable=False, function_dependency_signatures=None) -> tuple[VerifyResult, str | None]:
        if function_dependency_signatures:
            joint_function_depedency_signatures = '\n'.join(
                function_dependency_signatures)
            rust_code = f'''
extern "C" {{
{joint_function_depedency_signatures}
}}
{rust_code}
'''
        return self._try_compile_rust_code_impl(rust_code, executable)
