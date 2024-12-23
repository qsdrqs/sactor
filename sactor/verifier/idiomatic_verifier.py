import os
from typing import override

import rust_ast_parser
from sactor import utils
from sactor.c_parser import FunctionInfo
from sactor.llm import LLM

from .verifier_types import VerifyResult
from .verifier import Verifier


class IdiomaticVerifier(Verifier):
    def __init__(self, test_cmd, llm: LLM, build_path=None):
        super().__init__(test_cmd, build_path)
        self.function_test_harness_dir = os.path.join(
            self.build_path, "function_test_harness")
        self.llm = llm

    # generate test harness for the function
    def _function_generate_test_harness(
        self,
        function_name,
        idiomatic_impl,
        original_signature,
        idiomatic_signature,
        verify_result: tuple[VerifyResult, str | None] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
    ):
        # FIXME: add attempt counter

        idiomatic_signature = idiomatic_signature.replace(
            function_name, f"{function_name}_idiomatic")  # FIXME: dirty code
        prompt = f'''
Generate the harness for the function {function_name}_idiomatic with the following code pattern:
```rust
{original_signature} {{
    // TODO: Add code here to Convert the input to the idiomatic format
    let result = {idiomatic_signature}; // Call the idiomatic function
    // TODO: Add code here to Convert the result back to the original format
}}
'''
        prompt += '''
Output the translated function into this format (wrap with the following tags):
----FUNCTION----
```rust
// Your translated function here
```
----END FUNCTION----
'''
        if verify_result[0] == VerifyResult.COMPILE_ERROR:
            prompt += f'''
Lastly, the function is translated as:
```rust
{error_translation}
```
It failed to compile with the following error message, try to avoid this error:
{verify_result[1]}
'''
        elif verify_result[0] == VerifyResult.TEST_ERROR:
            prompt += f'''
Lastly, the function is translated as:
```rust
{error_translation}
```
It failed the following tests:
```
{verify_result[1]}
```
Try to avoid this error by passing the tests.
'''

        result = self.llm.query(prompt)

        llm_result = utils.parse_llm_result(result, "function")
        try:
            function_result = llm_result["function"]
        except KeyError:
            result = (VerifyResult.COMPILE_ERROR,
                      "Output does not wrapped in the correct format!")
            return self._function_generate_test_harness(
                function_name,
                idiomatic_impl,
                original_signature,
                idiomatic_signature,
                result,
                llm_result
            )

        compile_code = '\n'.join([
            idiomatic_impl.replace(function_name, f"{function_name}_idiomatic"), # FIXME: dirty code
            function_result
        ])

        result = self._try_compile_rust_code(
            compile_code, [])

        if result[0] != VerifyResult.SUCCESS:
            return self._function_generate_test_harness(
                function_name,
                idiomatic_impl,
                original_signature,
                idiomatic_signature,
                result,
                function_result
            )

        utils.save_code(
            f"{self.function_test_harness_dir}/{function_name}.rs", function_result)

        return (VerifyResult.SUCCESS, None)

    def _struct_generate_test_harness(self, struct_name, original_struct, idiomatic_struct):
        # TODO:
        pass

    @override
    def verify_function(self, function: FunctionInfo, idiomatic_impl, unidiomatic_signature, function_dependency_signatures, prefix=False) -> tuple[VerifyResult, str | None]:
        # Try to compile the Rust code
        function_name = function.name
        compile_result = self._try_compile_rust_code(
            idiomatic_impl, function_dependency_signatures)
        if compile_result[0] != VerifyResult.SUCCESS:
            return compile_result

        idiomatic_signature = rust_ast_parser.get_func_signatures(idiomatic_impl)[function_name]

        result = self._function_generate_test_harness(
            function_name,
            idiomatic_impl,
            unidiomatic_signature,
            idiomatic_signature
        )
        if result[0] != VerifyResult.SUCCESS:
            return result

        # We have had the test harness generated, now we need to run the tests
        test_error = self._embed_test_rust(
            function, idiomatic_impl, function_dependency_signatures, prefix)

        if test_error[0] != VerifyResult.SUCCESS:
            print(f"Error: Failed to run tests for function {function_name}")
            return test_error

        return (VerifyResult.SUCCESS, None)
