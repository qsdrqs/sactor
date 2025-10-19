from typing import Optional, override

from sactor import logging as sactor_logging
from sactor import rust_ast_parser
from sactor.c_parser import FunctionInfo
from sactor.combiner.combiner import RustCode, merge_uses
from sactor.combiner.partial_combiner import CombineResult, PartialCombiner
from .verifier import Verifier
from .verifier_types import VerifyResult

from ..combiner.rust_code import RustCode
from ..combiner.combiner import Combiner

logger = sactor_logging.get_logger(__name__)

class UnidiomaticVerifier(Verifier):
    def __init__(
        self,
        test_cmd_path: str,
        config: dict,
        build_path=None,
        no_feedback=False,
        extra_compile_command=None,
        executable_object=None,
        processed_compile_commands: list[list[str]] = [],

    ):
        super().__init__(
            test_cmd_path,
            config=config,
            build_path=build_path,
            no_feedback=no_feedback,
            extra_compile_command=extra_compile_command,
            executable_object=executable_object,
            processed_compile_commands=processed_compile_commands,
        )

    @override
    def verify_function(
        self,
        function: FunctionInfo,
        function_code: str,
        data_type_code: dict[str, str],
        function_dependency_signatures,
        has_prefix,
        function_dependency_uses=None,
    ) -> tuple[VerifyResult, Optional[str]]:
        functions = {function.name: function_code}
        combiner = PartialCombiner(functions, data_type_code)
        result, combined_code = combiner.combine()
        if result != CombineResult.SUCCESS or combined_code is None:
            raise ValueError(f"Failed to combine the function {function.name}")

        # Try to compile the Rust code
        compile_result = self.try_compile_rust_code(
            combined_code,
            function_dependency_signatures=function_dependency_signatures,
            function_dependency_uses=function_dependency_uses
        )
        if compile_result[0] != VerifyResult.SUCCESS:
            return compile_result

        try:
            rust_ast_parser.get_standalone_uses_code_paths(function_code)
        except Exception as e:
            logger.error(
                "Failed to get standalone uses code paths for function %s", function.name
            )
            return (VerifyResult.COMPILE_ERROR, str(e))

        # Run the tests
        test_error = self._embed_test_rust(
            function,
            combined_code,
            function_dependency_signatures,
            has_prefix,
            function_dependency_uses=function_dependency_uses
        )

        if test_error[0] != VerifyResult.SUCCESS:
            logger.error("Failed to run tests for function %s", function.name)
            return test_error

        return (VerifyResult.SUCCESS, None)

    @override
    def try_compile_rust_code(
        self,
        rust_code,
        executable=False,
        function_dependency_signatures=None,
        function_dependency_uses=None,
    ) -> tuple[VerifyResult, Optional[str]]:
        _rust_code = RustCode(rust_code)
        all_uses = _rust_code.used_code_list
        if function_dependency_signatures:
            joint_function_depedency_signatures = '\n'.join(
                function_dependency_signatures)
            joint_function_dependency_uses = ""
            remained_code = _rust_code.remained_code

            if function_dependency_uses:
                all_uses += function_dependency_uses
            all_uses_tuples = set(tuple(x) for x in all_uses)
            all_uses = [list(x) for x in all_uses_tuples]
            all_dependency_uses = merge_uses(all_uses)
            joint_function_dependency_uses = '\n'.join(all_dependency_uses)
            rust_code = f'''
#![allow(unused_imports)]
{joint_function_dependency_uses}

extern "C" {{
{joint_function_depedency_signatures}
}}

/* __START_TRANSLATION__ */
{remained_code}
'''
        return self._try_compile_rust_code_impl(rust_code, executable)
