import os, json
from ctypes import c_buffer
from typing import Optional, override

import sactor.translator as translator
import sactor.verifier as verifier
from sactor import rust_ast_parser, utils
from sactor.utils import read_file
from sactor.c_parser import (CParser, EnumInfo, EnumValueInfo, FunctionInfo,
                             GlobalVarInfo, StructInfo)
from sactor.combiner import RustCode
from sactor.data_types import DataType
from sactor.llm import LLM
from sactor.verifier import VerifyResult

from .translator import Translator
from .translator_types import TranslateResult
from ..combiner.rust_code import RustCode

CONST_VAR_MAX_TRANSLATION_LEN = 2048

class UnidiomaticTranslator(Translator):
    def __init__(
        self,
        llm: LLM,
        c2rust_translation,
        c_parser: CParser,
        test_cmd_path,
        config: dict,
        build_path=None,
        result_path=None,
        extra_compile_command=None,
        executable_object=None,
        processed_compile_commands: list[list[str]] = [],
    ) -> None:
        super().__init__(
            llm=llm,
            c_parser=c_parser,
            config=config,
            result_path=result_path,
        )
        self.failure_info_path = os.path.join(
            self.result_path, "unidiomatic_failure_info.json")
        if os.path.isfile(self.failure_info_path):
            content = read_file(self.failure_info_path)
            self.failure_info = json.loads(content)

        self.c2rust_translation = c2rust_translation
        base_name = "translated_code_unidiomatic"

        self.translated_struct_path = os.path.join(
            self.result_path, base_name, "structs")
        self.translated_global_var_path = os.path.join(
            self.result_path, base_name, "global_vars")
        self.translated_enum_path = os.path.join(
            self.result_path, base_name, "enums")
        self.translated_function_path = os.path.join(
            self.result_path, base_name, "functions")
        self.verifier = verifier.UnidiomaticVerifier(
            test_cmd_path,
            config=config,
            build_path=build_path,
            extra_compile_command=extra_compile_command,
            executable_object=executable_object,
            processed_compile_commands=processed_compile_commands,
        )

    @override
    def _translate_enum_impl(
        self,
        enum: EnumInfo,
        verify_result: tuple[VerifyResult, Optional[str]] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslateResult:
        enum_save_path = os.path.join(
            self.translated_enum_path, enum.name + ".rs")
        if os.path.exists(enum_save_path):
            print(f"Enum {enum.name} already translated")
            return TranslateResult.SUCCESS
        if attempts > self.max_attempts - 1:
            print(
                f"Error: Failed to translate enum {enum.name} after {self.max_attempts} attempts")
            return TranslateResult.MAX_ATTEMPTS_EXCEEDED
        print(f"Translating enum: {enum.name} (attempts: {attempts})")
        self.init_failure_info("enum", enum.name)

        code_of_enum = self.c_parser.extract_enum_definition_code(enum.name)
        prompt = f'''
Translate the following C enum to Rust. Try to keep the **equivalence** as much as possible.
`libc` will be included as the **only** dependency you can use. To keep the equivalence, you can use `unsafe` if you want.
The enum is:
```c
{code_of_enum}
```
'''
        prompt += f'''
Output the translated enum into this format (wrap with the following tags):
----ENUM----
```rust
// Your translated enum here
```
----END ENUM----
'''

        if verify_result[0] == VerifyResult.COMPILE_ERROR:
            prompt += f'''
The last time, the enum is translated as:
```rust
{error_translation}
```
It failed to compile with the following error message:
```
{verify_result[1]}
```
Analyzing the error messages, think about the possible reasons, and try to avoid this error.
'''
        elif verify_result[0] != VerifyResult.SUCCESS:
            raise NotImplementedError(
                f'error type {verify_result[0]} not implemented')

        result = self.llm.query(prompt)
        try:
            llm_result = utils.parse_llm_result(result, "enum")
        except:
            error_message = f'''
Error: Failed to parse the result from LLM, result is not wrapped by the tags as instructed. Remember the tag:
----ENUM----
```rust
// Your translated enum here
```
----END ENUM----
'''
            print(error_message)
            self.append_failure_info(
                enum.name, "COMPILE_ERROR", error_message, result
            )
            return self._translate_enum_impl(
                enum,
                verify_result=(VerifyResult.COMPILE_ERROR, error_message),
                error_translation=result,
                attempts=attempts+1
            )
        enum_result = llm_result["enum"]

        if len(enum_result.strip()) == 0:
            error_message = "Translated code doesn't wrap by the tags as instructed"
            self.append_failure_info(
                enum.name, "COMPILE_ERROR", error_message, result
            )
            return self._translate_enum_impl(
                enum,
                verify_result=(
                    VerifyResult.COMPILE_ERROR, error_message),
                error_translation=result,
                attempts=attempts+1
            )

        print("Translated enum:")
        print(enum_result)

        # TODO: temporary solution, may need to add verification here
        result = self.verifier.try_compile_rust_code(enum_result)
        if result[0] != VerifyResult.SUCCESS:
            if result[0] == VerifyResult.COMPILE_ERROR:
                self.append_failure_info(
                    enum.name, "COMPILE_ERROR", result[1], enum_result)
            return self._translate_enum_impl(
                enum,
                verify_result=result,
                error_translation=enum_result,
                attempts=attempts + 1
            )

        enum_result = rust_ast_parser.unidiomatic_types_cleanup(
            enum_result)
        utils.save_code(enum_save_path, enum_result)
        return TranslateResult.SUCCESS

    @override
    def _translate_global_vars_impl(
        self,
        global_var: GlobalVarInfo,
        verify_result: tuple[VerifyResult, Optional[str]] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslateResult:
        global_var_save_path = os.path.join(
            self.translated_global_var_path, global_var.name + ".rs")
        
        def return_result(global_var_result, verification=True):
            # check the global variable name, allow const global variable to have different name
            if global_var.name not in global_var_result and not global_var.is_const:
                if global_var_result.lower().find(global_var.name.lower()) != -1:
                    error_message = f"Error: Global variable name {global_var.name} not found in the translated code, keep the upper/lower case of the global variable name."
                else:
                    error_message = f"Error: Global variable name {global_var.name} not found in the translated code"
                    print(error_message)
                    self.append_failure_info(
                        global_var.name, "COMPILE_ERROR", error_message, global_var_result
                    )
                    return self._translate_global_vars_impl(
                        global_var,
                        verify_result=(
                            VerifyResult.COMPILE_ERROR, error_message),
                        error_translation=global_var_result,
                        attempts=attempts+1
                    )
            print("Translated global variable:")
            print(global_var_result)
            if verification:
                # TODO: may add verification here
                result = self.verifier.try_compile_rust_code(global_var_result)
                if result[0] != VerifyResult.SUCCESS:
                    if result[0] == VerifyResult.COMPILE_ERROR:
                        self.append_failure_info(
                            global_var.name, "COMPILE_ERROR", result[1], global_var_result)
                    return self._translate_global_vars_impl(
                        global_var,
                        verify_result=result,
                        error_translation=global_var_result,
                        attempts=attempts + 1
                    )
            global_var_result = rust_ast_parser.unidiomatic_types_cleanup(
                global_var_result)
            self.failure_info[global_var.name]['status'] = "success"
            utils.save_code(global_var_save_path, global_var_result)
            return TranslateResult.SUCCESS
           
        if os.path.exists(global_var_save_path):
            print(f"Global variable {global_var.name} already translated")
            return TranslateResult.SUCCESS

        if attempts > self.max_attempts - 1:
            # fallback
            print(
                f"Failed to translate global variable {global_var.name} after {self.max_attempts} attempts using LLM.",
                "Translated it using c2rust"
                )
            result = rust_ast_parser.get_static_item_definition(self.c2rust_translation, global_var.name)
            return return_result(result, verification=False)

        print(
            f"Translating global variable: {global_var.name} (attempts: {attempts})")

        self.init_failure_info("global_var", global_var.name)
        if global_var.is_const:
            code_of_global_var = self.c_parser.extract_global_var_definition_code(
                global_var.name)
            if len(code_of_global_var) >= CONST_VAR_MAX_TRANSLATION_LEN:
                result = rust_ast_parser.get_static_item_definition(self.c2rust_translation, global_var.name)
                return return_result(result, verification=False)

            prompt = f'''
Translate the following C global variable to Rust. Try to keep the **equivalence** as much as possible.
`libc` will be included as the **only** dependency you can use. To keep the equivalence, you can use `unsafe` if you want.
In the translation, keep the casing and spelling of the variable name **identical** to the source C code.
The global variable is:
```c
{code_of_global_var}
```
'''
            if global_var.is_array:
                prompt += f'''
The global variable is an array with size {global_var.array_size}. Use `static mut` to bypass the Rust's mutability rules if necessary.
'''
        else:
            code_of_global_var = global_var.get_decl()
            prompt = f'''
Use `extern "C"` wrap the following C global variable without defining the value, keep the upper/lower case of the global variable name.
```c
{code_of_global_var}
```
'''

        prompt += f'''
Output the translated global variable into this format (wrap with the following tags):
----GLOBAL VAR----
```rust
// Your translated global variable here
```
----END GLOBAL VAR----
'''
        if verify_result[0] == VerifyResult.COMPILE_ERROR:
            prompt += f'''
The last time, the global variable is translated as:
```rust
{error_translation}
```
It failed to compile with the following error message:
```
{verify_result[1]}
```
Analyzing the error messages, think about the possible reasons, and try to avoid this error.
'''

        elif verify_result[0] != VerifyResult.SUCCESS:
            raise NotImplementedError(
                f'error type {verify_result[0]} not implemented')

        result = self.llm.query(prompt)
        try:
            llm_result = utils.parse_llm_result(result, "global var")
        except:
            error_message = f'''
Error: Failed to parse the result from LLM, result is not wrapped by the tags as instructed. Remember the tag:
----GLOBAL VAR----
```rust
// Your translated global variable here
```
----END GLOBAL VAR----
'''
            print(error_message)
            self.append_failure_info(
                global_var.name, "COMPILE_ERROR", error_message, result
            )
            return self._translate_global_vars_impl(
                global_var,
                verify_result=(VerifyResult.COMPILE_ERROR, error_message),
                error_translation=result,
                attempts=attempts+1
            )
        global_var_result = llm_result["global var"]

        if len(global_var_result.strip()) == 0:
            error_message = "Translated code doesn't wrap by the tags as instructed"
            self.append_failure_info(
                global_var.name, "COMPILE_ERROR", error_message, result
            )
            return self._translate_global_vars_impl(
                global_var,
                verify_result=(
                    VerifyResult.COMPILE_ERROR, error_message),
                error_translation=result,
                attempts=attempts+1
            )
        return return_result(global_var_result)


    def _translate_struct_impl(
        self,
        struct_union: StructInfo,
        verify_result: tuple[VerifyResult, Optional[str]] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslateResult:
        # Translate all the dependencies of the struct/union
        struct_union_dependencies = struct_union.dependencies
        self.init_failure_info("struct", struct_union.name)
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
                self.append_failure_info(struct_union.name, "TYPE_TRANSLATION_ERROR", f"Error: Invalid data type {struct_union.data_type}", "")
                raise ValueError(
                    f"Error: Invalid data type {struct_union.data_type}")

        # add Debug trait for struct/union
        rust_s_u = rust_ast_parser.add_derive_to_struct_union(
            rust_s_u, struct_union.name, "Debug")

        self.failure_info[struct_union.name]['status'] = "success"
        # Save the translated struct/union
        utils.save_code(
            f'{self.translated_struct_path}/{struct_union.name}.rs', rust_s_u)

        return TranslateResult.SUCCESS

    @override
    def _translate_function_impl(
        self,
        function: FunctionInfo,
        verify_result: tuple[VerifyResult, Optional[str]] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslateResult:
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

        self.init_failure_info("function", function.name)

        function_dependencies = function.function_dependencies
        function_name_dependencies = [f.name for f in function_dependencies]
        # check the presence of the dependencies
        function_depedency_signatures = []
        function_dependency_uses = []
        all_uses = []
        prefix_ref = False
        for f in function_name_dependencies:
            if f == function.name:
                # Skip self dependencies
                continue
            if not os.path.exists(f"{self.translated_function_path}/{f}.rs"):
                raise RuntimeError(
                    f"Error: Dependency {f} of function {function.name} is not translated yet")
            # get the translated function signatures
            code = read_file(f"{self.translated_function_path}/{f}.rs")
            function_signatures = rust_ast_parser.get_func_signatures(code)
            function_use = RustCode(code).used_code_list
                all_uses += function_use
                if f in translator.RESERVED_KEYWORDS:
                    f = f + "_"
                    prefix_ref = True
                function_depedency_signatures.append(
                    function_signatures[f] + ';')  # add a semicolon to the end

        function_dependency_uses = all_uses

        # Translate the function using LLM
        structs_in_function = function.struct_dependencies
        code_of_structs = {}
        visited_structs = set()
        for f in function_dependencies:
            structs_in_function.extend(f.struct_dependencies)
        for struct in structs_in_function:
            all_structs = self.c_parser.retrieve_all_struct_dependencies(
                struct)
            for struct_name in all_structs:
                if struct_name in visited_structs:
                    continue
                if not os.path.exists(f"{self.translated_struct_path}/{struct_name}.rs"):
                    result = self.translate_struct(
                        self.c_parser.get_struct_info(struct_name)
                    )
                    if result != TranslateResult.SUCCESS:
                        raise RuntimeError(
                            f"Error: Struct {struct_name} translation failed.")
                if not os.path.exists(f"{self.translated_struct_path}/{struct_name}.rs"):
                    raise RuntimeError(
                            f"Error: Struct {struct_name} translation failed.")
                code_of_struct = read_file(f"{self.translated_struct_path}/{struct_name}.rs")
                code_of_structs[struct_name] = code_of_struct
                visited_structs.add(struct_name)

        code_of_function = self.c_parser.extract_function_code(function.name)
        prompt = f'''
Translate the following C function to Rust. Try to keep the **equivalence** as much as possible.
`libc` will be included as the **only** dependency you can use. To keep the equivalence, you can use `unsafe` if you want.
Your solution should only have **one** function, if you need to create help function, define the help function inside the function you translate.
The function is:
```c
{code_of_function}
```
'''

        if function.name == 'main':
            prompt += '''
The function is the `main` function, which is the entry point of the program. The function signature should be: `pub fn main() -> ()`.
For `return 0;`, you can directly `return;` in Rust or ignore it if it's the last statement.
For other return values, you can use `std::process::exit()` to return the value.
For `argc` and `argv`, you can use `std::env::args()` to get the arguments.
'''

        if len(code_of_structs) > 0:
            joint_code_of_structs = '\n'.join(code_of_structs.values())
            prompt += f'''
The function uses the following structs/unions, which are already translated as (you should **NOT** define them in your translation, as the system will automatically define them. But you can use these structs or unions):
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
        used_global_vars = {}
        used_global_vars_only_type_and_names = {}
        for global_var in used_global_var_nodes:
            if global_var.node.location is not None and global_var.node.location.file.name != function.node.location.file.name:
                continue
            global_var_res = self._translate_global_vars_impl(global_var)
            if global_var_res != TranslateResult.SUCCESS:
                return global_var_res
            with open(os.path.join(self.translated_global_var_path, global_var.name + ".rs"), "r") as file:
                code_of_global_var = file.read()
                # we only keep the type and name of the variable. e.g., for `static mut a: i32 = 5;`, we keep `static mut a: i32;`
                # because 1. values are not needed for function translation; 2. if it has a long value, for example a very long array,
                # including the value will break the LLM.
                # FIXME: It may trigger a bug, for example, `static a: &str = "=2"`;. Strictly speaking this need to be done through a Rust parser.
                type_and_name = f"{code_of_global_var.rsplit("=")[0]};"
                used_global_vars[global_var.name] = code_of_global_var
                used_global_vars_only_type_and_names[global_var.name] = type_and_name

        if len(used_global_vars) > 0:
            joint_used_global_vars_only_type_and_names = '\n'.join(used_global_vars_only_type_and_names.values())
            prompt += f'''
The function uses the following const global variables, which are already translated. The global variables' types and names are provided below, but the values are omitted.
You should **NOT** define the following global variables in your translation, as the system will automatically define them. But you can access the variables in your translation.
The translated const global variables are:
:
```rust
{joint_used_global_vars_only_type_and_names}
```
'''

        # handle stdio
        used_stdio = function.stdio_list
        used_stdio_code = ""
        if len(used_stdio) > 0:
            used_stdio_code = 'extern "C" {\n'
            for stdio in used_stdio:
                used_stdio_code += f"    static mut {stdio}: *mut libc::FILE;\n"
            used_stdio_code += "}\n"
            joint_stdio = ', '.join(used_stdio)
            prompt += f'''
The function uses some of the following stdio file descriptors: {joint_stdio}. Which will be included as
```rust
{used_stdio_code}
```
You should **NOT** declare or define them in your translation, as the system will automatically define them. But you can use them in your translation.
'''

        # TODO: check upper/lower case of the global variables
        # TODO: check extern "C" for global variables
        used_enum_values: list[EnumValueInfo] = function.enum_values_dependencies
        used_enum_definitions = function.enum_dependencies
        code_of_enum = {}
        if len(used_enum_values) > 0 or len(used_enum_definitions) > 0:
            enum_definitions = set()
            used_enum_names = []
            for enum in used_enum_values:
                used_enum_names.append(enum.name)
                enum_definitions.add(enum.definition)

            for enum_def in used_enum_definitions:
                used_enum_names.append(enum_def.name)
                enum_definitions.add(enum_def)

            for enum_def in enum_definitions:
                self._translate_enum_impl(enum_def)
                with open(os.path.join(self.translated_enum_path, enum_def.name + ".rs"), "r") as file:
                    code_of_enum[enum_def] = file.read()

            joint_used_enums = '\n'.join(used_enum_names)
            joint_code_of_enum = '\n'.join(code_of_enum.values())

            prompt += f'''
The function uses the following enums:
```c
{joint_used_enums}
```
Which are already translated as:
```rust
{joint_code_of_enum}
```
Directly access the translated enums in your translation. You should **NOT** define or declare them in your translation, as the system will automatically define them.
'''

        if len(function_depedency_signatures) > 0:
            joint_function_depedency_signatures = '\n'.join(
                function_depedency_signatures)
            prompt += f'''
The function calls the following functions, which are already translated and defined in Rust.
Do **NOT** include the definition or declaration of the following functions in your translation.
If you include them, the output will be considered **invalid**.
But you can call the following functions in your translation.
Only output the translation of the function I request.
The called functions' signatures in Rust are the following:
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
The last time, the function is translated as:
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

        elif verify_result[0] == VerifyResult.TEST_ERROR or verify_result[0] == VerifyResult.TEST_TIMEOUT:
            prompt += f'''
The last time, the function is translated as:
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
The last time, the function is translated as:
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
                f'error type {verify_result[0]} not implemented')

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
                function.name, "COMPILE_ERROR", error_message, result
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
            error_message = f"Error: Syntax error in the translated code: {e}"
            print(error_message)
            # retry the translation
            self.append_failure_info(
                function.name,
                "COMPILE_ERROR",
                error_message,
                function_result
            )
            return self._translate_function_impl(
                function,
                verify_result=(VerifyResult.COMPILE_ERROR,
                               error_message),
                error_translation=function_result,
                attempts=attempts+1
            )

        # detect whether there are too many functions which many causing multi-definition problem after combining
        if len(function_result_sigs) > 1:
            error_message = f"Error: {len(function_result_sigs)} functions are generated, expect **only one** function. If you need to define help function please generate it as a subfuncion in the translated function."
            self.append_failure_info(
                function.name,
                "COMPILE_ERROR",
                error_message,
                function_result
            )
            return self._translate_function_impl(
                function,
                verify_result=(
                    VerifyResult.COMPILE_ERROR, error_message),
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
                        function.name, "COMPILE_ERROR", error_message, function_result
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
                    function.name, "COMPILE_ERROR", error_message, function_result
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
                function.name, "COMPILE_ERROR", error_message, result
            )
            return self._translate_function_impl(
                function,
                verify_result=(
                    VerifyResult.COMPILE_ERROR, error_message),
                error_translation=result,
                attempts=attempts+1
            )

        # process the function result
        function_result = rust_ast_parser.expand_use_aliases(function_result) # remove potentail 'as' in use statements

        print("Translated function:")
        print(function_result)

        data_type_code = code_of_structs | used_global_vars | code_of_enum | {
            "stdio": used_stdio_code}
        # add error handling because here can raise exceptions
        try:
            result = self.verifier.verify_function(
                function,
                function_code=function_result,
                data_type_code=data_type_code,
                function_dependency_signatures=function_depedency_signatures,
                function_dependency_uses=function_dependency_uses,
                has_prefix=prefix
            )
        except Exception as e:
            # FIXME: What is the situation for this?
            self.append_failure_info(
                function.name, "COMPILE_ERROR", str(e), function_result
            )
            # TODO: assign a new error code instead of compile_error?
            result = (VerifyResult.COMPILE_ERROR, str(e))
            return self._translate_function_impl(
                function,
                result,
                error_translation=function_result,
                attempts=attempts+1
            )
        if result[0] != VerifyResult.SUCCESS:
            if result[0] == VerifyResult.COMPILE_ERROR:
                compile_error = result[1]
                self.append_failure_info(
                    function.name, "COMPILE_ERROR", compile_error, function_result)
                # Try to translate the function again, with the error message

            elif result[0] == VerifyResult.TEST_ERROR or result[0] == VerifyResult.FEEDBACK or result[0] == VerifyResult.TEST_TIMEOUT:
                # TODO: maybe simply retry the translation here
                test_error = result[1]
                self.append_failure_info(
                    function.name, "TEST_ERROR", test_error, function_result)

            else:
                raise NotImplementedError(
                    f'error type {result[0]} not implemented')
            return self._translate_function_impl(
                function,
                result,
                error_translation=function_result,
                attempts=attempts+1
            )
        function_result = rust_ast_parser.unidiomatic_function_cleanup(
            function_result)
        self.failure_info[function.name]["status"] = "success"
        utils.save_code(function_save_path, function_result)
        return TranslateResult.SUCCESS

