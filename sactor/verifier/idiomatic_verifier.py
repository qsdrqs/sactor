import os
from typing import override

from sactor import rust_ast_parser, utils
from sactor.c_parser import FunctionInfo
from sactor.llm import LLM

from .verifier import Verifier
from .verifier_types import VerifyResult


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

        uses = rust_ast_parser.get_uses_code(idiomatic_impl)
        joint_uses = '\n'.join(uses)
        idiomatic_signature = idiomatic_signature.replace(
            function_name, f"{function_name}_idiomatic")
        prompt = f'''
This is the idiomatic translation of Rust code from C, the function signature is
```rust
{idiomatic_signature};
```
This is the unidiomatic translation of Rust code from C, the function signature is
```rust
{original_signature};
```
Generate the harness for the function {function_name}_idiomatic with the following code pattern so that it can be tested:
Finish all the TODOs.
You should **NOT** add any dummy implementation of the function or structs, as it will be provided by the verifier:
```rust
{original_signature} {{
    // TODO: Add code here to Convert the input to the idiomatic format
    let result = {idiomatic_signature}; // Call the idiomatic function
    // TODO: Add code here to Convert the result back to the original format
}}
'''
        if len(uses) > 0:
            prompt += f'''
Following uses will be provied by the verifier, you should **ONLY** add uses that are not in the following list:
```rust
{joint_uses}
```
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
Analyze the error messages, think about the possible reasons, and try to avoid this error.
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
            rust_ast_parser.rename_function(
                idiomatic_impl,
                function_name,
                f"{function_name}_idiomatic"
            ),
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
            f"{self.function_test_harness_dir}/{function_name}.rs", compile_code)

        return (VerifyResult.SUCCESS, None)

    def _struct_generate_test_harness(self, struct_name, original_struct, idiomatic_struct):
        # TODO:
        pass

    @override
    def verify_function(self, function: FunctionInfo, function_code, struct_code, function_dependency_signatures, unidiomatic_signature, prefix=False) -> tuple[VerifyResult, str | None]:
        combined_code = rust_ast_parser.combine_struct_function(
            struct_code, function_code)

        unsafe_count = rust_ast_parser.count_unsafe_blocks(combined_code)
        if unsafe_count > 0:
            return (VerifyResult.COMPILE_ERROR, "Unsafe blocks are not allowed in the idiomatic code")

        # Try to compile the Rust code
        function_name = function.name
        compile_result = self._try_compile_rust_code(
            combined_code, function_dependency_signatures)
        if compile_result[0] != VerifyResult.SUCCESS:
            return compile_result

        idiomatic_signature = rust_ast_parser.get_func_signatures(function_code)[
            function_name]

        result = self._function_generate_test_harness(
            function_name,
            combined_code,
            unidiomatic_signature,
            idiomatic_signature
        )
        if result[0] != VerifyResult.SUCCESS:
            return result

        # We have had the test harness generated, now we need to run the tests
        with open(f"{self.function_test_harness_dir}/{function_name}.rs") as f:
            harness_code = f.read()

        test_error = self._embed_test_rust(
            function, harness_code, function_dependency_signatures, prefix)

        if test_error[0] != VerifyResult.SUCCESS:
            print(f"Error: Failed to run tests for function {function_name}")
            return test_error

        return (VerifyResult.SUCCESS, None)
