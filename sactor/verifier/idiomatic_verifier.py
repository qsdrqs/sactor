import os
from typing import override, Optional

from sactor import rust_ast_parser, utils
from sactor.c_parser import FunctionInfo, StructInfo
from sactor.combiner.partial_combiner import CombineResult, PartialCombiner
from sactor.data_types import DataType
from sactor.llm import LLM

from .verifier import Verifier
from .verifier_types import VerifyResult


class IdiomaticVerifier(Verifier):
    def __init__(
        self,
        test_cmd_path,
        llm: LLM,
        config: dict,
        build_path=None,
        no_feedback=False,
        extra_compile_command=None,
        result_path=None,
        unidiomatic_result_path=None,
        executable_object=None,
    ):
        super().__init__(
            test_cmd_path,
            config=config,
            build_path=build_path,
            no_feedback=no_feedback,
            extra_compile_command=extra_compile_command,
            executable_object=executable_object,
        )
        self.function_test_harness_dir = os.path.join(
            self.build_path, "function_test_harness")
        self.struct_test_harness_dir = os.path.join(
            self.build_path, "struct_test_harness")
        self.llm = llm
        self.max_attempts = self.config['general']['max_verifier_harness_attempts']
        if result_path is not None:
            self.result_path = result_path
        else:
            self.result_path = os.path.join(
                utils.find_project_root(), 'result')
        self.saved_test_harness_path = os.path.join(self.result_path, "test_harness")
        if unidiomatic_result_path is not None:
            self.unidiomatic_result_path = unidiomatic_result_path
        else:
            self.unidiomatic_result_path = self.result_path


    # generate test harness for the function
    def _function_generate_test_harness(
        self,
        function_name,
        idiomatic_impl,
        original_signature,
        idiomatic_signature,
        struct_signature_dependency_names: list[str] = [],
        verify_result: tuple[VerifyResult, Optional[str]] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ):
        if attempts > self.max_attempts - 1:
            print(
                f"Error: Failed to get compilable test harness for function {function_name} after {self.max_attempts} attempts")
            return VerifyResult.TEST_HARNESS_MAX_ATTEMPTS_EXCEEDED, None
        print(
            f"Tries: {attempts} to generate test harness for function {function_name}")

        original_signature_renamed = original_signature
        if len(struct_signature_dependency_names) > 0:
            # rename oringal signature to use unidiomatic struct
            for struct_name in struct_signature_dependency_names:
                original_signature_renamed = utils.rename_rust_function_signature(
                    original_signature_renamed,
                    struct_name,
                    f"C{struct_name}",
                    DataType.STRUCT
                )

        uses = rust_ast_parser.get_uses_code(idiomatic_impl)
        joint_uses = '\n'.join(uses)
        idiomatic_signature_replaced = utils.rename_rust_function_signature(
            idiomatic_signature,
            function_name,
            f"{function_name}_idiomatic",
            DataType.FUNCTION
        )
        convert_back_prompt = ""
        if struct_signature_dependency_names:
            convert_back_prompt = "You need to covert mutable reference back and **COPY** the content of C structs to the input mutable pointers, as all convertion functions are at **DIFFERENT** memory locations"
        prompt = f'''
This is the idiomatic translation of Rust code from C, the function signature is
```rust
{idiomatic_signature_replaced};
```
This is the unidiomatic translation of Rust code from C, the function signature is
```rust
{original_signature_renamed};
```
Generate the harness for the function {function_name}_idiomatic with the following code pattern so that it can be tested:
Finish all the TODOs.
You should **NOT** add any dummy implementation of the function or structs, as it will be provided by the verifier:
```rust
// TODO: add necessary `use`s here
// Don't add the definitions of any other functions and structs, they will be provided by the system

{original_signature_renamed} {{
    // TODO: Add code here to Convert the input to the idiomatic format
    let result = {idiomatic_signature_replaced}; // Call the idiomatic function
    // TODO: Add code here to Convert the result back to the original format
    // {convert_back_prompt}
}}
```
remove all the TODOs and replace them with the necessary code.
'''
        if len(struct_signature_dependency_names) > 0:
            prompt += f'''
Some structs are used in the function invoking, in {function_name}, they are invoked C structs, and in the {function_name}_idiomatic, they are idiomatic structs, you should call the following functions to convert between the two structs
They will be provided by the verifier, **DO NOT** implement or add template code for them:
```rust
'''
            for struct_name in struct_signature_dependency_names:
                prompt += f'''
// {struct_name} <-> C{struct_name}
unsafe fn {struct_name}_to_C{struct_name}_mut(input: &mut {struct_name}) -> *mut C{struct_name}; // Convert the idiomatic struct to the C struct at a **DIFFERENT** memory location
unsafe fn C{struct_name}_to_{struct_name}_mut(input: *mut C{struct_name}) -> &'static mut {struct_name}; // Convert the C struct to the idiomatic struct at a **DIFFERENT** memory location
'''
            prompt += "```\n"

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
It failed to compile with the following error message:
```
{verify_result[1]}
```
Analyzing the error messages, think about the possible reasons, and try to avoid this error.
'''
        elif verify_result[0] == VerifyResult.TEST_ERROR or verify_result[0] == VerifyResult.TEST_TIMEOUT:
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
        elif verify_result[0] != VerifyResult.SUCCESS:
            raise NotImplementedError(
                f'erorr type {verify_result[0]} not implemented')

        result = self.llm.query(prompt)

        try:
            llm_result = utils.parse_llm_result(result, "function")
            function_result = llm_result["function"]
        except:
            error_message = f'''
Error: Failed to parse the result from LLM, result is not wrapped by the tags as instructed. Remember the tag:
----FUNCTION----
```rust
// Your translated function here
```
----END FUNCTION----
'''
            return self._function_generate_test_harness(
                function_name,
                idiomatic_impl,
                original_signature,
                idiomatic_signature,
                struct_signature_dependency_names,
                verify_result=(VerifyResult.COMPILE_ERROR, error_message),
                error_translation=result,
                attempts=attempts+1
            )

        struct_code = {}
        function_code = {}
        if len(struct_signature_dependency_names) > 0:
            # combine the struct code
            for struct_name in struct_signature_dependency_names:
                if not os.path.exists(f"{self.struct_test_harness_dir}/{struct_name}.rs"):
                    raise ValueError(
                        f"Struct {struct_name} test harness is not generated")
                with open(f"{self.struct_test_harness_dir}/{struct_name}.rs") as f:
                    struct_code[struct_name] = f.read()

        function_code[function_name] = rust_ast_parser.rename_function(
            idiomatic_impl,
            function_name,
            f"{function_name}_idiomatic"
        )
        function_code[f"{function_name}_harness"] = function_result

        combiner = PartialCombiner(function_code, struct_code)
        result, compile_code = combiner.combine()
        if result != CombineResult.SUCCESS or compile_code is None:
            raise ValueError(
                f"Failed to combine the function {function_name}")

        result = self.try_compile_rust_code(
            compile_code)

        if result[0] != VerifyResult.SUCCESS:
            return self._function_generate_test_harness(
                function_name,
                idiomatic_impl,
                original_signature,
                idiomatic_signature,
                struct_signature_dependency_names,
                result,
                function_result,
                attempts=attempts+1
            )

        utils.save_code(
            f"{self.function_test_harness_dir}/{function_name}.rs", compile_code)

        return (VerifyResult.SUCCESS, None)

    def _struct_generate_test_harness(
        self,
        struct_name: str,
        unidiomatic_struct_code: str,
        idiomatic_struct_code: str,
        struct_dependencies: list[StructInfo],
        verify_result: tuple[VerifyResult, Optional[str]] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> tuple[VerifyResult, Optional[str]]:
        if attempts > self.max_attempts - 1:
            print(
                f"Error: Failed to get compilable test harness for function {struct_name} after {self.max_attempts} attempts")
            return VerifyResult.TEST_HARNESS_MAX_ATTEMPTS_EXCEEDED, None

        # rename the unidiomatic struct to C struct
        unidiomatic_struct_code_renamed = rust_ast_parser.rename_struct_union(
            unidiomatic_struct_code, struct_name, f"C{struct_name}")

        # rename all the dependencies
        for dependency in struct_dependencies:
            dependency_name = dependency.name
            unidiomatic_struct_code_renamed = rust_ast_parser.rename_struct_union(
                unidiomatic_struct_code_renamed, dependency_name, f"C{dependency_name}")

        # generate the test harness for the struct
        prompt = f'''
There are two structs: {struct_name} and C{struct_name}, the {struct_name} is the idiomatic translation of Rust code from C, the struct is
```rust
{idiomatic_struct_code}
```
The C{struct_name} is the unidiomatic translation of Rust code from C, the struct is
```rust
{unidiomatic_struct_code_renamed}
```
Generate two transformations functions to convert between the two structs:
Finish all the TODOs.
You should **NOT** add any dummy implementation of the function or structs, as it will be provided by the verifier:
```rust
unsafe fn {struct_name}_to_C{struct_name}_mut(input: &mut {struct_name}) -> *mut C{struct_name} {{
// TODO: Add code here to Convert the input to the C{struct_name} format
// Use `Box::into_raw()` to convert the reference to a pointer
// Create a new memory space for the C{struct_name} and return the pointer
}}

unsafe fn C{struct_name}_to_{struct_name}_mut(input: *mut C{struct_name}) -> &'static mut {struct_name} {{
// TODO: Add code here to Convert the input to the {struct_name} format
// Use `Box::leak()` to convert the pointer to a static reference
// Note that all pointers in the C{struct_name} can be null, check the null pointer before using it
// Create a new memory space for the {struct_name} and return the reference
}}
'''

        if len(struct_dependencies) > 0:
            # check if the dependencies harness have been generated
            for dependency in struct_dependencies:
                dependency_name = dependency.name
                if not os.path.exists(f"{self.struct_test_harness_dir}/{dependency_name}.rs"):
                    # generate the test harness for the dependency
                    unidiomatic_dependency_code_path = os.path.join(
                        self.unidiomatic_result_path,
                        "translated_code_unidiomatic",
                        "structs",
                        f"{dependency_name}.rs"
                    )
                    idiomatic_dependency_code_path = os.path.join(
                        self.result_path,
                        "translated_code_idiomatic",
                        "structs",
                        f"{dependency_name}.rs"
                    )
                    if not os.path.exists(unidiomatic_dependency_code_path):
                        raise ValueError(
                            f"Struct {dependency_name} is not translated into unidiomatic code")
                    if not os.path.exists(idiomatic_dependency_code_path):
                        raise ValueError(
                            f"Struct {dependency_name} is not translated into idiomatic code")

                    with open(unidiomatic_dependency_code_path) as f:
                        unidiomatic_dependency_code = f.read()
                    with open(idiomatic_dependency_code_path) as f:
                        idiomatic_dependency_code = f.read()
                    result = self._struct_generate_test_harness(
                        dependency_name,
                        unidiomatic_dependency_code,
                        idiomatic_dependency_code,
                        dependency.dependencies,
                    )
                    if result[0] != VerifyResult.SUCCESS:
                        return result

            prompt += f'''
The following coverting functions of the dependencies have been generated, you can directly invoke them (DO NOT include them again) as they will be provided by the system:
```rust
'''
            for dependency in struct_dependencies:
                dependency_name = dependency.name
                prompt += f'''
// {dependency_name} <-> C{dependency_name}
fn {dependency_name}_to_C{dependency_name}_mut(input: &mut {dependency_name}) -> *mut C{dependency_name}; // Convert the idiomatic struct to the C struct at a **DIFFERENT** memory location
fn C{dependency_name}_to_{dependency_name}_mut(input: *mut C{dependency_name}) -> &'static mut {dependency_name}; // Convert the C struct to the idiomatic struct at a **DIFFERENT** memory location
'''
            prompt += "```\n"

        prompt += '''
Output the two transformation functions into this format (wrap with the following tags):
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
        elif verify_result[0] == VerifyResult.TEST_ERROR or verify_result[0] == VerifyResult.TEST_TIMEOUT:
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
        elif verify_result[0] != VerifyResult.SUCCESS:
            raise NotImplementedError(
                f'erorr type {verify_result[0]} not implemented')

        result = self.llm.query(prompt)

        try:
            llm_result = utils.parse_llm_result(result, "function")
            function_result = llm_result["function"]
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
            return self._struct_generate_test_harness(
                struct_name,
                unidiomatic_struct_code,
                idiomatic_struct_code,
                struct_dependencies,
                (VerifyResult.COMPILE_ERROR, error_message),
                error_translation=result,
                attempts=attempts+1
            )

        # check if the functions all available
        try:
            rust_ast_parser.get_func_signatures(function_result)[
                f"{struct_name}_to_C{struct_name}_mut"]
            rust_ast_parser.get_func_signatures(function_result)[
                f"C{struct_name}_to_{struct_name}_mut"]
        except:
            error_message = "Error: The transformation functions are not complete"
            print(error_message)
            return self._struct_generate_test_harness(
                struct_name,
                unidiomatic_struct_code,
                idiomatic_struct_code,
                struct_dependencies,
                (VerifyResult.COMPILE_ERROR, error_message),
                attempts=attempts+1
            )

        combine_structs = {}
        for dependency in struct_dependencies:
            dependency_name = dependency.name
            # TODO: may need dependencies of the dependencies
            with open(f"{self.struct_test_harness_dir}/{dependency_name}.rs") as f:
                combine_structs[dependency_name] = f.read()

        save_code = '\n'.join([
            idiomatic_struct_code,
            unidiomatic_struct_code_renamed,
            function_result
        ])
        combine_structs[struct_name] = save_code
        combiner = PartialCombiner({}, combine_structs)
        result, combined_code = combiner.combine()
        if result != CombineResult.SUCCESS or combined_code is None:
            raise ValueError(
                f"Failed to combine the struct {struct_name}")

        result = self.try_compile_rust_code(combined_code)

        if result[0] != VerifyResult.SUCCESS:
            return self._struct_generate_test_harness(
                struct_name,
                unidiomatic_struct_code,
                idiomatic_struct_code,
                struct_dependencies,
                result,
                function_result,
                attempts=attempts+1
            )

        # TODO: may use fuzzing to check the correctness of the transformation functions

        utils.save_code(
            f"{self.struct_test_harness_dir}/{struct_name}.rs", save_code)

        return (VerifyResult.SUCCESS, None)

    @override
    def verify_function(
        self,
        function: FunctionInfo,
        function_code: str,
        data_type_code: dict[str, str],
        function_dependencies_code: dict[str, str],
        unidiomatic_signature,
        prefix=False,
    ) -> tuple[VerifyResult, Optional[str]]:
        functions = function_dependencies_code.copy()
        functions[function.name] = function_code

        combiner = PartialCombiner(functions, data_type_code)
        result, combined_code = combiner.combine()
        if result != CombineResult.SUCCESS or combined_code is None:
            raise ValueError(f"Failed to combine the function {function.name}")

        total, unsafe = rust_ast_parser.count_unsafe_tokens(combined_code)
        if unsafe > 0:
            # TODO: may allow unsafe blocks in the future
            return (VerifyResult.COMPILE_ERROR, "Unsafe blocks are not allowed in the idiomatic code")

        # Try to compile the Rust code
        function_name = function.name
        compile_result = self.try_compile_rust_code(
            combined_code)
        if compile_result[0] != VerifyResult.SUCCESS:
            return compile_result

        idiomatic_signature = rust_ast_parser.get_func_signatures(function_code)[
            function_name]

        if function_name == "main":
            # main function doesn't have test harness
            harness_code = combined_code
        else:
            # Generate the test harness for the function
            struct_signature_dependencies = function.get_structs_in_signature()
            if len(struct_signature_dependencies) > 0:
                # generate struct test harness first
                for struct in struct_signature_dependencies:
                    struct_name = struct.name
                    if struct_name not in data_type_code:
                        print(
                            f"Error: Struct {struct_name} is not provided in the struct code")
                        return (VerifyResult.COMPILE_ERROR, None)

                    unidiomatic_struct_code_path = os.path.join(
                        self.unidiomatic_result_path,
                        "translated_code_unidiomatic",
                        "structs",
                        f"{struct_name}.rs"
                    )
                    if not os.path.exists(unidiomatic_struct_code_path):
                        raise ValueError(
                            f"Struct {struct_name} is not translated into unidiomatic code")
                    with open(unidiomatic_struct_code_path) as f:
                        unidiomatic_struct_code = f.read()

                    result = self._struct_generate_test_harness(
                        struct_name,
                        unidiomatic_struct_code,
                        data_type_code[struct_name],
                        struct.dependencies
                    )
                    # TODO: harness feedback may not be useful
                    if result[0] != VerifyResult.SUCCESS:
                        return result

            struct_signature_dependency_names = set()
            for struct in struct_signature_dependencies:
                struct_signature_dependency_names.add(struct.name)
                for dependency in struct.dependencies:
                    # TODO: may need to check the dependencies of the dependencies
                    struct_signature_dependency_names.add(dependency.name)

            # remove duplicate structs in the dependencies
            combiner_struct_pop_list = []
            for struct_name in combiner.data_types.keys():
                if struct_name in struct_signature_dependency_names:
                    combiner_struct_pop_list.append(struct_name)
            for struct_name in combiner_struct_pop_list:
                combiner.data_types.pop(struct_name)

            # regenerate the combined code
            result, combined_code_harness = combiner.combine()
            if result != CombineResult.SUCCESS or combined_code_harness is None:
                raise ValueError(
                    f"Failed to combine the harness code for function {function_name}")

            result = self._function_generate_test_harness(
                function_name,
                combined_code_harness,
                unidiomatic_signature,
                idiomatic_signature,
                list(struct_signature_dependency_names)
            )
            if result[0] != VerifyResult.SUCCESS:
                # TODO: harness feedback may not be useful
                return result

            # We have had the test harness generated, now we need to run the tests
            with open(f"{self.function_test_harness_dir}/{function_name}.rs") as f:
                harness_code = f.read()

        test_error = self._embed_test_rust(
            function,
            harness_code,
            prefix=prefix,
            idiomatic=True
        )

        if test_error[0] != VerifyResult.SUCCESS:
            print(f"Error: Failed to run tests for function {function_name}")
            return test_error

        # save harness code
        path = os.path.join(self.saved_test_harness_path,
                            "functions", f"{function_name}.rs")
        utils.save_code(path, harness_code)

        return (VerifyResult.SUCCESS, None)
