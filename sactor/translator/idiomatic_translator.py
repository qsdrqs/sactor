import os
from typing import override

import sactor.translator as translator
import sactor.verifier as verifier
from sactor import rust_ast_parser, utils
from sactor.c_parser import CParser, FunctionInfo, StructInfo
from sactor.llm import LLM
from sactor.thirdparty import Crown, CrownType
from sactor.verifier import VerifyResult

from .translator import Translator
from .translator_types import TranslateResult


class IdiomaticTranslator(Translator):
    def __init__(
        self,
        llm: LLM,
        c2rust_translation,
        crown_result: Crown,
        c_parser: CParser,
        test_cmd_path,
        config,
        build_path=None,
        unidiomatic_result_path=None,
        result_path=None,
        extra_compile_command=None,
    ):
        super().__init__(
            llm=llm,
            c_parser=c_parser,
            config=config,
            result_path=result_path,
        )
        self.c2rust_translation = c2rust_translation

        self.translated_struct_path = os.path.join(
            self.result_path, "translated_code_idiomatic/structs")
        self.translated_function_path = os.path.join(
            self.result_path, "translated_code_idiomatic/functions")
        if unidiomatic_result_path:
            self.unidiomatic_result_path = unidiomatic_result_path
        else:
            self.unidiomatic_result_path = self.result_path

        self.verifier = verifier.IdiomaticVerifier(
            test_cmd_path,
            llm=llm,
            config=config,
            build_path=build_path,
            result_path=result_path,
            unidiomatic_result_path=self.unidiomatic_result_path,
            extra_compile_command=extra_compile_command,
        )
        self.crown_result = crown_result

    @override
    def _translate_struct_impl(
        self,
        struct_union: StructInfo,
        verify_result: tuple[VerifyResult, str | None] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslateResult:
        # Translate the struct/union
        self.init_failure_info("struct", struct_union.name)
        struct_save_path = os.path.join(
            self.translated_struct_path, struct_union.name + ".rs")
        if os.path.exists(struct_save_path):
            print(f"Struct {struct_union.name} already translated")
            return TranslateResult.SUCCESS

        if attempts > self.max_attempts - 1:
            print(
                f"Error: Failed to translate struct {struct_union.name} after {self.max_attempts} attempts")
            return TranslateResult.MAX_ATTEMPTS_EXCEEDED

        print(
            f"Translating struct: {struct_union.name} (attempts: {attempts})")

        # Get unidiomatic translation code
        struct_path = os.path.join(
            self.unidiomatic_result_path, "translated_code_unidiomatic/structs", struct_union.name + ".rs")
        if not os.path.exists(struct_path):
            raise RuntimeError(
                f"Error: Struct {struct_union.name} is not translated into unidiomatic Rust yet")

        with open(struct_path, "r") as file:
            unidiomatic_struct_code = file.read()

        # Get results from crown
        crown_output = self.crown_result.query(
            struct_union.name, CrownType.STRUCT)

        # Get previous translation results as dependencies
        # Unlike the function, we only need to retrieve one level of dependencies
        dependencies_code = []
        dependency_names = [d.name for d in struct_union.dependencies]
        for dependency_name in dependency_names:
            struct_path = os.path.join(
                self.translated_struct_path, dependency_name + ".rs")
            if not os.path.exists(struct_path):
                raise RuntimeError(
                    f"Error: Dependency {dependency_name} of struct {struct_union.name} is not translated yet")
            with open(struct_path, "r") as file:
                dependencies_code.append(file.read())
        joined_dependencies_code = '\n'.join(dependencies_code)

        # Translate the struct
        prompt = f'''
Translate the following Rust struct to idiomatic Rust. Try to avoid using raw pointers in the translation of the struct.
```rust
{unidiomatic_struct_code}
```
'''
        if len(crown_output) > 0:
            prompt += f'''
"Crown" is a pointer analysis tool that can help to identify the ownership, mutability and fatness of pointers. Following are the possible annotations for pointers:
```
fatness:
    - `Ptr`: Single pointer
    - `Arr`: Pointer is an array
mutability:
    - `Mut`: Mutable pointer
    - `Imm`: Immutable pointer
ownership:
    - `Owning`: Owns the pointer
    - `Transient`: Not owns the pointer
````

The following is the output of Crown for this struct:
```
{crown_output}
```
Analyze the Crown output firstly, then translate the struct with the help of the Crown output.
'''

        if len(dependencies_code) > 0:
            prompt += f'''
The struct uses the following structs/unions, which are already translated as (you don't need to include them in your translation, and **you can not modify them**):
```rust
{joined_dependencies_code}
```
'''
        used_type_aliases = struct_union.type_aliases
        if len(used_type_aliases) > 0:
            used_type_aliases_kv_pairs = [
                f'{alias} = {used_type}' for alias, used_type in used_type_aliases.items()]
            joint_used_type_aliases = '\n'.join(used_type_aliases_kv_pairs)
            prompt += f'''
The struct uses the following type aliases, which are defined as:
```rust
{joint_used_type_aliases}
```
'''
        # define output format
        prompt += f'''
Output the translated struct into this format (wrap with the following tags):
----STRUCT----
```rust
// Your translated struct here
```
----END STRUCT----
'''

        if verify_result[0] == VerifyResult.COMPILE_ERROR:
            prompt += f'''
Lastly, the struct is translated as:
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
The error message may be cause your translation includes other structs (maybe the dependencies).
Remember, you should only provide the translation for the struct and necessary `use` statements. The system will automatically include the dependencies in the final translation.
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
        try:
            llm_result = utils.parse_llm_result(result, "struct")
        except:
            error_message = f'''
Error: Failed to parse the result from LLM, result is not wrapped by the tags as instructed. Remember the tag:
----STRUCT----
```rust
// Your translated struct here
```
----END STRUCT----
'''
            print(error_message)
            self.append_failure_info(
                struct_union.name, "COMPILE_ERROR", error_message
            )
            return self._translate_struct_impl(
                struct_union,
                verify_result=(VerifyResult.COMPILE_ERROR, error_message),
                error_translation=result,
                attempts=attempts+1
            )
        struct_result = llm_result["struct"]

        # TODO: Verify the translation

        # add Debug trait for struct/union
        try:
            struct_result = rust_ast_parser.add_derive_to_struct_union(
                struct_result, struct_union.name, "Debug")
        except Exception as e:
            error_message = f"Error: Failed to add Debug trait to the struct: {e}, please check if the struct has a correct syntax"
            print(error_message)
            self.append_failure_info(
                struct_union.name, "COMPILE_ERROR", error_message
            )
            return self._translate_struct_impl(
                struct_union,
                verify_result=(VerifyResult.COMPILE_ERROR, error_message),
                error_translation=result,
                attempts=attempts+1
            )

        # Save the results
        utils.save_code(struct_save_path, struct_result)

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

        # Get used struct, unions
        structs_in_function = function.struct_dependencies
        code_of_structs = {}
        visited_structs = set()
        for struct in structs_in_function:
            all_structs = self.c_parser.retrieve_all_struct_dependencies(
                struct)
            for struct_name in all_structs:
                if struct_name in visited_structs:
                    continue
                struct_path = os.path.join(
                    self.translated_struct_path, struct_name + ".rs")
                if not os.path.exists(struct_path):
                    raise RuntimeError(
                        f"Error: Struct {struct_name} is not translated yet")
                with open(struct_path, "r") as file:
                    code_of_structs[struct_name] = file.read()
                    visited_structs.add(struct_name)

        # Get used global variables
        # TODO: add this

        # Get used functions
        function_dependencies = function.function_dependencies
        function_name_dependencies = [f.name for f in function_dependencies]
        function_depedency_signatures = []
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
                function_depedency_signatures.append(
                    function_signatures[f] + ';')  # add a semicolon to the end

        # Translate the function
        # Get the unidiomatic translation code
        unidiomatic_function_path = os.path.join(
            self.unidiomatic_result_path, "translated_code_unidiomatic/functions", function.name + ".rs")
        if not os.path.exists(unidiomatic_function_path):
            raise RuntimeError(
                f"Error: Function {function.name} is not translated into unidiomatic Rust yet")

        with open(unidiomatic_function_path, "r") as file:
            unidiomatic_function_code = file.read()

        undiomantic_function_signatures = rust_ast_parser.get_func_signatures(
            unidiomatic_function_code)
        undiomantic_function_signature = undiomantic_function_signatures[function.name]

        # Get results from crown
        crown_output = self.crown_result.query(
            function.name, CrownType.FUNCTION)

        # Translate the function
        prompt = f'''
Translate the following unidiomatic Rust function into idiomatic Rust. Try to remove all the `unsafe` blocks and only use the safe Rust code or use the `unsafe` blocks only when necessary.
Before translating, analyze the unsafe blocks one by one and how to convert them into safe Rust code.
**libc may not be provided in the idiomatic code, so try to avoid using libc functions and types, and avoid using `std::ffi` module.**
```rust
{unidiomatic_function_code}
```
'''
        if len(crown_output) > 0:
            prompt += f'''
"Crown" is a pointer analysis tool that can help to identify the ownership, mutability and fatness of pointers. Following are the possible annotations for pointers:
```
fatness:
    - `Ptr`: Single pointer
    - `Arr`: Pointer is an array
mutability:
    - `Mut`: Mutable pointer
    - `Imm`: Immutable pointer
ownership:
    - `Owning`: Owns the pointer
    - `Transient`: Not owns the pointer
````

The following is the output of Crown for this function:
```
{crown_output}
```
Analyze the Crown output firstly, then translate the pointers in function arguments and return values with the help of the Crown output.
Try to avoid using pointers in the function arguments and return values if possible.
'''

        if len(code_of_structs) > 0:
            joint_struct_code = '\n'.join(code_of_structs.values())
            prompt += f'''
This function uses the following structs/unions, which are already translated as (you don't need to include them in your translation, and **you can not modify them**):
```rust
{joint_struct_code}
```
'''
        used_type_aliases = function.type_alias_dependencies
        if len(used_type_aliases) > 0:
            used_type_aliases_kv_pairs = [
                f'{alias} = {used_type}' for alias, used_type in used_type_aliases.items()]
            joint_used_type_aliases = '\n'.join(used_type_aliases_kv_pairs)
            prompt += f'''
The function uses the following type aliases, which are defined as:
```rust
{joint_used_type_aliases}
```
'''
        if len(function_depedency_signatures) > 0:
            joint_signatures = '\n'.join(function_depedency_signatures)
            prompt += f'''
This function uses the following functions, which are already translated as (you don't need to include them in your translation, and **you can not modify them**):
```rust
{joint_signatures}
```
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
It failed the following tests:
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
        try:
            function_result = llm_result["function"]
        except KeyError:
            error_message = f"Error: Output does not wrapped in the correct format!"
            self.append_failure_info(
                function.name, "COMPILE_ERROR", error_message
            )
            return self._translate_function_impl(
                function,
                verify_result=(VerifyResult.COMPILE_ERROR, error_message),
                error_translation=llm_result,
                attempts=attempts + 1
            )

        try:
            function_result_sigs = rust_ast_parser.get_func_signatures(
                function_result)
        except Exception as e:
            error_message = f"Error: Failed to parse the function: {e}"
            print(error_message)
            self.append_failure_info(
                function.name, "COMPILE_ERROR", error_message
            )
            # retry the translation
            return self._translate_function_impl(
                function,
                verify_result=(VerifyResult.COMPILE_ERROR,
                               error_message),
                error_translation=function_result,
                attempts=attempts+1
            )

        if function.name not in function_result_sigs:
            if function.name in translator.RESERVED_KEYWORDS:
                # TODO: handle this case
                pass
            else:
                error_message = f"Error: Function signature not found in the translated code for function `{function.name}`. Got functions: {list(
                    function_result_sigs.keys()
                )}, check if you have the correct function name., you should **NOT** change the camel case to snake case and vice versa."
                print(error_message)
                return self._translate_function_impl(
                    function,
                    verify_result=(
                        VerifyResult.COMPILE_ERROR,
                        error_message,
                    ),
                    error_translation=function_result,
                    attempts=attempts+1
                )

        all_structs = set()
        all_dependency_functions = set()

        def get_all_dependencies(function: FunctionInfo):
            for struct in function.struct_dependencies:
                all_structs.add(struct.name)
            for f in function.function_dependencies:
                all_dependency_functions.add(f.name)
                get_all_dependencies(f)

        get_all_dependencies(function)

        def get_all_struct_dependencies(struct: StructInfo):
            for s in struct.dependencies:
                all_structs.add(s.name)
                get_all_struct_dependencies(s)

        for struct in structs_in_function:
            get_all_struct_dependencies(struct)

        all_structs_code = {}
        for struct in all_structs:
            with open(f"{self.translated_struct_path}/{struct}.rs", "r") as file:
                all_structs_code[struct] = file.read()

        all_dependency_functions_code = {}
        for f in all_dependency_functions:
            with open(f"{self.translated_function_path}/{f}.rs", "r") as file:
                all_dependency_functions_code[f] = file.read()

        # Verify the translation
        result = self.verifier.verify_function(
            function,
            function_code=function_result,
            struct_code=all_structs_code,
            function_dependencies_code=all_dependency_functions_code,
            unidiomatic_signature=undiomantic_function_signature,
            prefix=False,  # TODO: check here
        )

        if result[0] != VerifyResult.SUCCESS:
            if result[0] == VerifyResult.COMPILE_ERROR:
                self.append_failure_info(
                    function.name, "COMPILE_ERROR", result[1])

            elif result[0] == VerifyResult.TEST_ERROR or result[0] == VerifyResult.FEEDBACK:
                self.append_failure_info(
                    function.name, "TEST_ERROR", result[1])
            else:
                raise NotImplementedError(
                    f'erorr type {result[0]} not implemented')

            return self._translate_function_impl(
                function,
                verify_result=result,
                error_translation=function_result,
                attempts=attempts + 1
            )

        # save code
        utils.save_code(
            f"{self.translated_function_path}/{function.name}.rs", function_result)

        return TranslateResult.SUCCESS
