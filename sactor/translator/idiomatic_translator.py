import os
from typing import override

import rust_ast_parser
import sactor.translator as translator
import sactor.verifier as verifier
from sactor import utils
from sactor.c_parser import CParser, FunctionInfo, StructInfo
from sactor.llm import LLM
from sactor.thirdparty import Crown, CrownType
from sactor.verifier import VerifyResult

from .translator_types import TranslationResult
from .translator import Translator


class IdiomaticTranslator(Translator):
    def __init__(self, llm: LLM, c2rust_translation, crown_result: Crown, c_parser: CParser, test_cmd, unidiomatic_result_path=None, result_path=None, max_attempts=6):
        super().__init__(
            llm,
            c_parser,
            result_path,
            max_attempts,
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

        self.verifier = verifier.IdiomaticVerifier(test_cmd, llm)
        self.crown_result = crown_result

    @override
    def translate_struct(self, struct_union: StructInfo, error_message=None, error_translation=None, error_tests=None, attempts=0) -> TranslationResult:
        self.init_failure_info("struct", struct_union.name)
        struct_save_path = os.path.join(
            self.translated_struct_path, struct_union.name + ".rs")
        if os.path.exists(struct_save_path):
            print(f"Struct {struct_union.name} already translated")
            return TranslationResult.SUCCESS

        if attempts > self.max_attempts - 1:
            print(
                f"Error: Failed to translate struct {struct_union.name} after {self.max_attempts} attempts")
            return TranslationResult.MAX_ATTEMPTS_EXCEEDED

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
        crown_output = self.crown_result.query(struct_union.name, CrownType.STRUCT)

        # Get previous translation results
        dependencies_code = []
        for dependency in struct_union.dependencies:
            struct_path = os.path.join(
                self.translated_struct_path, dependency + ".rs")
            if not os.path.exists(struct_path):
                raise RuntimeError(
                    f"Error: Dependency {dependency} of struct {struct_union.name} is not translated yet")
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
Translate the struct with the help of the Crown output.
'''

        if len(dependencies_code) > 0:
            prompt += f'''
The struct uses the following structs/unions, which are already translated as (you don't need to include them in your translation, and **you can not modify them**):
```rust
{joined_dependencies_code}
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

        if error_message:
            prompt += f'''
Lastly, the struct is translated as:
```rust
{error_translation}
```
It failed to compile with the following error message, try to avoid this error:
```
{error_message}
```
'''
        # TODO: add error_tests here

        result = self.llm.query(prompt)
        llm_result = utils.parse_llm_result(result, "struct")
        struct_result = llm_result["struct"]

        # TODO: Verify the translation

        # Save the results
        utils.save_code(struct_save_path, struct_result)

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

        # Get used struct, unions
        structs_in_target = function.struct_dependencies
        code_of_translated_structs = []
        print(structs_in_target)
        struct_names_in_target = [struct.name for struct in structs_in_target]
        for struct in struct_names_in_target:
            # FIXME: add struct dependencies
            struct_path = os.path.join(
                self.translated_struct_path, struct + ".rs")
            if not os.path.exists(struct_path):
                raise RuntimeError(
                    f"Error: Struct {struct} is not translated yet")
            with open(struct_path, "r") as file:
                code_of_translated_structs.append(file.read())

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
Translate the function with the help of the Crown output.
'''

        if len(code_of_translated_structs) > 0:
            joint_structs = '\n'.join(code_of_translated_structs)
            prompt += f'''
This function uses the following structs/unions, which are already translated as (you don't need to include them in your translation, and **you can not modify them**):
```rust
{joint_structs}
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
            return self.translate_function(
                function,
                verify_result=(VerifyResult.COMPILE_ERROR,
                               "Output does not wrapped in the correct format!"),
                error_translation=llm_result,
                attempts=attempts + 1
            )

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
                return self.translate_function(
                    function,
                    verify_result=(
                        VerifyResult.COMPILE_ERROR, error_message),
                    error_translation=function_result,
                    attempts=attempts+1
                )

        # Verify the translation
        result = self.verifier.verify_function(
            function,
            function_result,
            undiomantic_function_signature,
            function_depedency_signatures,
            False  # TODO: check here
        )

        if result[0] != VerifyResult.SUCCESS:
            if result[0] == VerifyResult.COMPILE_ERROR:
                self.append_failure_info(
                    function.name, "COMPILE_ERROR", result[1])

            elif result[0] == VerifyResult.TEST_ERROR:
                self.append_failure_info(
                    function.name, "TEST_ERROR", result[1])
            else:
                raise NotImplementedError(
                    f'erorr type {result[0]} not implemented')

            return self.translate_function(
                function,
                verify_result=result,
                error_translation=function_result,
                attempts=attempts + 1
            )

        # save code
        utils.save_code(
            f"{self.translated_function_path}/{function.name}.rs", function_result)

        return TranslationResult.SUCCESS

    def combine(self, functions, structs, global_vars):
        pass
