import os
from typing import override

import rust_ast_parser
import sactor.translator as translator
import sactor.verifier as verifier
from sactor import utils
from sactor.c_parser import CParser, FunctionInfo, StructInfo
from sactor.llm import LLM
from sactor.verifier import VerifyResult

from .translator_types import TranslationResult
from .translator import Translator


class UnidiomaticTranslator(Translator):
    def __init__(self, llm: LLM, c2rust_translation, c_parser: CParser, test_cmd, result_path=None, max_attempts=6) -> None:
        super().__init__(
            llm,
            c_parser,
            result_path,
            max_attempts,
        )
        self.c2rust_translation = c2rust_translation

        self.translated_struct_path = os.path.join(
            self.result_path, "translated_code_unidiomatic/structs")
        self.translated_function_path = os.path.join(
            self.result_path, "translated_code_unidiomatic/functions")
        self.verifier = verifier.UnidiomaticVerifier(test_cmd)

    @override
    def translate_struct(self, struct_union: StructInfo) -> TranslationResult:
        # FIXME: add dependencies translation
        if struct_union.is_struct:
            rust_s_u = rust_ast_parser.get_struct_definition(
                self.c2rust_translation, struct_union.name)
        else:
            rust_s_u = rust_ast_parser.get_union_definition(
                self.c2rust_translation, struct_union.name)
        os.makedirs(self.translated_struct_path, exist_ok=True)
        with open(f'{self.translated_struct_path}/{struct_union.name}.rs', 'w') as f:
            f.write(rust_s_u)

        return TranslationResult.SUCCESS

    @override
    def translate_function(
        self,
        function: FunctionInfo,
        verify_result: tuple[VerifyResult, str | None] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslationResult:
        self.init_failure_info("function", function.name)

        function_save_path = os.path.join(
            self.translated_function_path, function.name + ".rs")
        if os.path.exists(function_save_path):
            print(f"Function {function.name} already translated")
            return TranslationResult.SUCCESS

        if attempts > self.max_attempts - 1:
            print(
                f"Error: Failed to translate function {function.name} after {self.max_attempts} attempts")
            return TranslationResult.MAX_ATTEMPTS_EXCEEDED
        print(f"Translating function: {function.name} (attempts: {attempts})")

        function_dependencies = function.function_dependencies
        function_name_dependencies = [f.name for f in function_dependencies]
        # check the presence of the dependencies
        function_depedency_signatures = []
        prefix_ref = False
        for f in function_name_dependencies:
            if f == function.name:
                # Skip self dependencies
                continue
            if not os.path.exists(f"{self.translated_function_path}/{f}.rs"):
                raise RuntimeError(
                    f"Error: Dependency {f} of function {function.name} is not translated yet")
            # get the translated function signatures
            with open(f"{self.translated_function_path}/{f}.rs", "r") as file:
                code = file.read()
                function_signatures = rust_ast_parser.get_func_signatures(code)
                if f in translator.RESERVED_KEYWORDS:
                    f = f + "_"
                    prefix_ref = True
                function_depedency_signatures.append(
                    function_signatures[f] + ';')  # add a semicolon to the end

        # Translate the function using LLM
        structs_in_function = function.struct_dependencies
        code_of_function = self.c_parser.get_code_of_function(function.name)
        code_of_structs = []
        added_structs = set()
        for struct in structs_in_function:
            all_structs = self.c_parser.get_all_dependent_structs(struct)
            for struct_name in all_structs:
                if struct_name in added_structs:
                    continue
                if not os.path.exists(f"{self.translated_struct_path}/{struct_name}.rs"):
                    raise RuntimeError(
                        f"Error: Struct {struct_name} is not translated yet")
                with open(f"{self.translated_struct_path}/{struct_name}.rs", "r") as file:
                    code_of_struct = file.read()
                    code_of_structs.append(code_of_struct)
                    added_structs.add(struct_name)
        prompt = f'''
Translate the following C function to Rust. Try to keep the **equivalence** as much as possible.
`libc` will be included as the **only** dependency you can use. To keep the equivalence, you can use `unsafe` if you want.
The function is:
```c
{code_of_function}
```
'''

        if len(code_of_structs) > 0:
            joint_code_of_structs = '\n'.join(code_of_structs)
            prompt += f'''
The function uses the following structs/unions, which are already translated as (you don't need to include them in your translation):
```rust
{joint_code_of_structs}
```
'''

        used_global_var_nodes = function.global_vars_dependencies
        used_global_vars = []
        for node in used_global_var_nodes:
            tokens = node.get_tokens()
            used_global_vars.append(
                ' '.join([token.spelling for token in tokens]))
        if len(used_global_vars) > 0:
            joint_used_global_vars = '\n'.join(used_global_vars)
            prompt += f'''
The function uses the following static/global variables. Directly translate them and keep the upper/lower case as original, use the 'extern "C"' to wrap the result.
```c
{joint_used_global_vars}
```
'''
        # TODO: check upper/lower case of the global variables
        # TODO: check extern "C" for global variables
        used_enums = function.enum_dependencies
        if len(used_enums) > 0:
            used_enums_kv_pairs = [
                f'{enum.name} = {enum.value}' for enum in used_enums]
            joint_used_enums = '\n'.join(used_enums_kv_pairs)
            prompt += f'''
The function uses the following enums, which defined as:
```c
{joint_used_enums}
```
'''

        if len(function_depedency_signatures) > 0:
            joint_function_depedency_signatures = '\n'.join(
                function_depedency_signatures)
            prompt += f'''
The function uses the following functions, which are already translated as (you don't need to include them in your translation):
```rust
{joint_function_depedency_signatures}
```
'''
        # TODO: check if the translation includes the dependencies
        if len(code_of_structs) > 0:
            prompt += f'''
Translate the structs/unions firstly. Then output the translated struct/unions into this format (wrap with the following tags):
----STRUCTS----
```rust
// Your translated structs/unions here
```
----END STRUCTS----
'''

        if function.name in translator.RESERVED_KEYWORDS:
            prompt += f'''
As the function name `{function.name}` is a reserved keyword in Rust, you need to add a '_' at the end of the function name.
'''

        prompt += f'''
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
```
{verify_result[1]}
```
'''
        elif verify_result[0] == VerifyResult.TEST_ERROR:
            prompt += f'''
Lastly, the function is translated as:
```rust
{error_translation}
```
When running the test, it failed with the following error message, try to avoid this error:
```
{verify_result[1]}
```
'''

        # result = query_llm(prompt, False, f"test.rs")
        result = self.llm.query(prompt)
        llm_result = utils.parse_llm_result(result, "structs", "function")
        function_result = llm_result["function"]

        # TODO: check function signature, must use pointers, not Box, etc.
        try:
            function_result_sigs = rust_ast_parser.get_func_signatures(
                function_result)
        except ValueError as e:
            error_message = f"Error: Failed to parse the function: {e}"
            print(error_message)
            # retry the translation
            return self.translate_function(
                function,
                verify_result=(VerifyResult.COMPILE_ERROR,
                               error_message),
                error_translation=structs_result+function_result,
                attempts=attempts+1
            )
        prefix = False
        if function.name not in function_result_sigs:
            if function.name in translator.RESERVED_KEYWORDS:
                name_prefix = function.name + "_"
                if name_prefix in function_result_sigs:
                    function_result_sig = function_result_sigs[name_prefix]
                    prefix = True
                else:
                    return self.translate_function(
                        function,
                        verify_result=(
                            VerifyResult.COMPILE_ERROR, f"Function {name_prefix} not found in the translated code"),
                        error_translation=structs_result+function_result,
                        attempts=attempts+1
                    )
            else:
                error_message = f"Error: Function signature not found in the translated code for function `{function.name}`. Got functions: {list(
                    function_result_sigs.keys()
                )}, check if you have the correct function name., you should **NOT** change the camel case to snake case and vice versa."
                print(error_message)
                return self.translate_function(
                    function,
                    verify_result=(
                        VerifyResult.COMPILE_ERROR, error_message),
                    error_translation=structs_result+function_result,
                    attempts=attempts+1
                )
                # exit(f"Error: Function signature not found in the translated code for function {function.name}: {function_result_sigs}") FIXME: check here
        else:
            function_result_sig = function_result_sigs[function.name]
        pointers_count = function_result_sig.count('*')
        # if pointers_count != function.get_pointer_count_in_signature():
        #     print(f"Error: Function signature doesn't match the original function signature. Expected {function.get_pointer_count_in_signature()} pointers, got {pointers_count}")
        #     self.translate_function(function, error_message="Function signature doesn't match the original function signature", error_translation=structs_result+function_result, attempts=attempts+1)
        #     return

        if len(function_result.strip()) == 0:
            print("Error: Empty translation")
            return self.translate_function(
                function,
                verify_result=(
                    VerifyResult.COMPILE_ERROR, "Translated code doesn't wrap by the tags as instructed"),
                error_translation=structs_result,
                attempts=attempts+1
            )

        print("Translated structs/unions:")
        print(structs_result)
        print("Translated function:")
        print(function_result)

        result = self.verifier.verify_function(
            function,
            function_result,
            function_depedency_signatures,
            prefix
        )
        if result[0] != VerifyResult.SUCCESS:
            if result[0] == VerifyResult.COMPILE_ERROR:
                compile_error = result[1]
                self.append_failure_info(
                    function.name, "COMPILE_ERROR", compile_error)
                # Try to translate the function again, with the error message

            elif result[0] == VerifyResult.TEST_ERROR:
                # TODO: maybe simply retry the translation here
                test_error = result[1]
                self.append_failure_info(
                    function.name, "TEST_ERROR", test_error)

            else:
                raise NotImplementedError(
                    f'erorr type {result[0]} not implemented')
            return self.translate_function(
                function,
                result,
                error_translation=structs_result+function_result,
                attempts=attempts+1
            )

        utils.save_code(function_save_path, structs_result + function_result)
        return TranslationResult.SUCCESS

    def combine(self, functions, structs, global_vars):
        pass
