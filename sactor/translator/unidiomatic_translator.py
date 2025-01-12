import os
from typing import override

import sactor.translator as translator
import sactor.verifier as verifier
from sactor import rust_ast_parser, utils
from sactor.data_types import DataType
from sactor.c_parser import CParser, FunctionInfo, StructInfo
from sactor.llm import LLM
from sactor.verifier import VerifyResult

from .translator import Translator
from .translator_types import TranslateResult


class UnidiomaticTranslator(Translator):
    def __init__(
        self,
        llm: LLM,
        c2rust_translation,
        c_parser: CParser,
        test_cmd_path,
        max_attempts,
        build_path=None,
        result_path=None,
        extra_compile_command=None,
    ) -> None:
        super().__init__(
            llm=llm,
            c_parser=c_parser,
            max_attempts=max_attempts,
            result_path=result_path,
        )
        self.c2rust_translation = c2rust_translation

        self.translated_struct_path = os.path.join(
            self.result_path, "translated_code_unidiomatic/structs")
        self.translated_function_path = os.path.join(
            self.result_path, "translated_code_unidiomatic/functions")
        self.verifier = verifier.UnidiomaticVerifier(
            test_cmd_path,
            build_path=build_path,
            extra_compile_command=extra_compile_command
        )

    @override
    def _translate_struct_impl(
        self,
        struct_union: StructInfo,
        verify_result: tuple[VerifyResult, str | None] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslateResult:
        # Translate all the dependencies of the struct/union
        struct_union_dependencies = struct_union.dependencies
        for struct in struct_union_dependencies:
            self.translate_struct(struct)

        match struct_union.data_type:
            case DataType.STRUCT:
                rust_s_u = rust_ast_parser.get_struct_definition(
                    self.c2rust_translation, struct_union.name)
            case DataType.UNION:
                rust_s_u = rust_ast_parser.get_union_definition(
                    self.c2rust_translation, struct_union.name)
            case _:
                raise ValueError(
                    f"Error: Invalid data type {struct_union.data_type}")

        # add Debug trait for struct/union
        rust_s_u = rust_ast_parser.add_derive_to_struct_union(
            rust_s_u, struct_union.name, "Debug")

        # Save the translated struct/union
        utils.save_code(
            f'{self.translated_struct_path}/{struct_union.name}.rs', rust_s_u)

        return TranslateResult.SUCCESS

    @override
    def _translate_function_impl(
        self,
        function: FunctionInfo,
        verify_result: tuple[VerifyResult, str | None] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslateResult:
        self.init_failure_info("function", function.name)

        function_save_path = os.path.join(
            self.translated_function_path, function.name + ".rs")
        if os.path.exists(function_save_path):
            print(f"Function {function.name} already translated")
            return TranslateResult.SUCCESS

        if attempts > self.max_attempts - 1:
            print(
                f"Error: Failed to translate function {function.name} after {self.max_attempts} attempts")
            return TranslateResult.MAX_ATTEMPTS_EXCEEDED
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
        code_of_structs = {}
        visited_structs = set()
        for struct in structs_in_function:
            all_structs = self.c_parser.retrieve_all_struct_dependencies(
                struct)
            for struct_name in all_structs:
                if struct_name in visited_structs:
                    continue
                if not os.path.exists(f"{self.translated_struct_path}/{struct_name}.rs"):
                    raise RuntimeError(
                        f"Error: Struct {struct_name} is not translated yet")
                with open(f"{self.translated_struct_path}/{struct_name}.rs", "r") as file:
                    code_of_struct = file.read()
                    code_of_structs[struct_name] = code_of_struct
                    visited_structs.add(struct_name)

        code_of_function = self.c_parser.extract_function_code(function.name)
        prompt = f'''
Translate the following C function to Rust. Try to keep the **equivalence** as much as possible.
`libc` will be included as the **only** dependency you can use. To keep the equivalence, you can use `unsafe` if you want.
The function is:
```c
{code_of_function}
```
'''

        if function.name == 'main':
            prompt += '''
The function is the `main` function, which is the entry point of the program. The return type should be `()`, and the arguments should be `()`.
For `return 0;`, you can directly `return;` in Rust or ignore it if it's the last statement.
For other return values, you can use `std::process::exit()` to return the value.
For `argc` and `argv`, you can use `std::env::args()` to get the arguments.
'''

        if len(code_of_structs) > 0:
            joint_code_of_structs = '\n'.join(code_of_structs.values())
            prompt += f'''
The function uses the following structs/unions, which are already translated as (you should **NOT** include them in your translation, as the system will automatically include them):
```rust
{joint_code_of_structs}
```
'''
        used_type_aliases = function.type_alias_dependencies
        if len(used_type_aliases) > 0:
            used_type_aliases_kv_pairs = [
                f'{alias} = {used_type}' for alias, used_type in used_type_aliases.items()]
            joint_used_type_aliases = '\n'.join(used_type_aliases_kv_pairs)
            prompt += f'''
The function uses the following type aliases, which are defined as:
```c
{joint_used_type_aliases}
```
'''

        used_global_var_nodes = function.global_vars_dependencies
        used_global_vars = []
        for node in used_global_var_nodes:
            if node.location is not None and node.location.file.name != function.node.location.file.name:
                continue
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
The function uses the following functions, which are already translated as (you should **NOT** include them in your translation, as the system will automatically include them):
```rust
{joint_function_depedency_signatures}
```
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
It failed to compile with the following error message:
```
{verify_result[1]}
```
Analyzing the error messages, think about the possible reasons, and try to avoid this error.
'''
            # for redefine error
            assert verify_result[1] is not None
            if verify_result[1].find("is defined multiple times") != -1:
                prompt += f'''
The error message may be cause your translation includes other functions or structs (maybe the dependencies).
Remember, you should only provide the translation for the function and necessary `use` statements. The system will automatically include the dependencies in the final translation.
'''

        elif verify_result[0] == VerifyResult.TEST_ERROR:
            prompt += f'''
Lastly, the function is translated as:
```rust
{error_translation}
```
When running the test, it failed with the following error message:
```
{verify_result[1]}
```
Analyze the error messages, think about the possible reasons, and try to avoid this error.
'''
        elif verify_result[0] == VerifyResult.FEEDBACK:
            prompt += f'''
Lastly, the function is translated as:
```rust
{error_translation}
```
When running the test, it failed with the following error message:
```
{verify_result[1]}
```
In this error message, the 'original output' is the actual output from the program error message. The 'Feedback' is information of function calls collected during the test.

Analyze the error messages, think about the possible reasons, and try to avoid this error.
'''
        elif verify_result[0] != VerifyResult.SUCCESS:
            raise NotImplementedError(
                f'erorr type {verify_result[0]} not implemented')

        # result = query_llm(prompt, False, f"test.rs")
        result = self.llm.query(prompt)
        try:
            llm_result = utils.parse_llm_result(result, "function")
        except:
            error_message = f'''
Error: Failed to parse the result from LLM, result is not wrapped by the tags as instructed. Remember the tag:
----FUNCTION----
```rust
// Your translated function here
```
----END FUNCTION----
'''
            print(error_message)
            self.append_failure_info(
                function.name, "COMPILE_ERROR", error_message
            )
            return self._translate_function_impl(
                function,
                verify_result=(VerifyResult.COMPILE_ERROR, error_message),
                error_translation=result,
                attempts=attempts+1
            )
        function_result = llm_result["function"]

        # TODO: check function signature, must use pointers, not Box, etc.
        try:
            function_result_sigs = rust_ast_parser.get_func_signatures(
                function_result)
        except Exception as e:
            error_message = f"Error: Failed to parse the function: {e}"
            print(error_message)
            # retry the translation
            self.append_failure_info(
                function.name, "COMPILE_ERROR", error_message
            )
            return self._translate_function_impl(
                function,
                verify_result=(VerifyResult.COMPILE_ERROR,
                               error_message),
                error_translation=function_result,
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
                    error_message = f"Function {name_prefix} not found in the translated code"
                    self.append_failure_info(
                        function.name, "COMPILE_ERROR", error_message
                    )
                    return self._translate_function_impl(
                        function,
                        verify_result=(
                            VerifyResult.COMPILE_ERROR, error_message),
                        error_translation=function_result,
                        attempts=attempts+1
                    )
            else:
                error_message = f"Error: Function signature not found in the translated code for function `{function.name}`. Got functions: {list(
                    function_result_sigs.keys()
                )}, check if you have the correct function name., you should **NOT** change the camel case to snake case and vice versa."
                print(error_message)
                self.append_failure_info(
                    function.name, "COMPILE_ERROR", error_message
                )
                return self._translate_function_impl(
                    function,
                    verify_result=(
                        VerifyResult.COMPILE_ERROR, error_message),
                    error_translation=function_result,
                    attempts=attempts+1
                )
        else:
            function_result_sig = function_result_sigs[function.name]
        pointers_count = function_result_sig.count('*')
        # if pointers_count != function.get_pointer_count_in_signature():
        #     print(f"Error: Function signature doesn't match the original function signature. Expected {function.get_pointer_count_in_signature()} pointers, got {pointers_count}")
        #     self.translate_function(function, error_message="Function signature doesn't match the original function signature", error_translation=structs_result+function_result, attempts=attempts+1)
        #     return

        if len(function_result.strip()) == 0:
            error_message = "Translated code doesn't wrap by the tags as instructed"
            self.append_failure_info(
                function.name, "COMPILE_ERROR", error_message
            )
            return self._translate_function_impl(
                function,
                verify_result=(
                    VerifyResult.COMPILE_ERROR, error_message),
                error_translation=function_result,
                attempts=attempts+1
            )

        print("Translated function:")
        print(function_result)

        result = self.verifier.verify_function(
            function,
            function_result,
            code_of_structs,
            function_depedency_signatures,
            prefix
        )
        if result[0] != VerifyResult.SUCCESS:
            if result[0] == VerifyResult.COMPILE_ERROR:
                compile_error = result[1]
                self.append_failure_info(
                    function.name, "COMPILE_ERROR", compile_error)
                # Try to translate the function again, with the error message

            elif result[0] == VerifyResult.TEST_ERROR or result[0] == VerifyResult.FEEDBACK:
                # TODO: maybe simply retry the translation here
                test_error = result[1]
                self.append_failure_info(
                    function.name, "TEST_ERROR", test_error)

            else:
                raise NotImplementedError(
                    f'erorr type {result[0]} not implemented')
            return self._translate_function_impl(
                function,
                result,
                error_translation=function_result,
                attempts=attempts+1
            )
        function_result = rust_ast_parser.unidiomatic_function_cleanup(function_result)

        utils.save_code(function_save_path, function_result)
        return TranslateResult.SUCCESS
