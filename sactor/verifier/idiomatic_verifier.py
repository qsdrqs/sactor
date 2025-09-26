import os
import json as json
from typing import Optional, override

from sactor import rust_ast_parser, utils
from sactor.c_parser import FunctionInfo, StructInfo
from sactor.combiner.partial_combiner import CombineResult, PartialCombiner
from sactor.data_types import DataType
from sactor.llm import LLM
from .verifier import Verifier
from .verifier_types import VerifyResult
from .selftest.struct_roundtrip import StructRoundTripTester
from sactor.verifier.spec.harness_codegen import generate_struct_harness_from_spec_file, generate_function_harness_from_spec_file


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
        self.saved_test_harness_path = os.path.join(
            self.result_path, "test_harness")
        if unidiomatic_result_path is not None:
            self.unidiomatic_result_path = unidiomatic_result_path
        else:
            self.unidiomatic_result_path = self.result_path

    def _ensure_struct_harness_available(
        self,
        struct_info: StructInfo,
        visited: Optional[set[str]] = None,
        idiomatic_override: Optional[str] = None,
    ) -> tuple[VerifyResult, Optional[str]]:
        """Make sure the given struct's harness exists on disk.

        Returns the result of harness generation when work was required, or
        ``(VerifyResult.SUCCESS, None)`` if the harness was already present or
        successfully restored from cache.
        """
        if visited is None:
            visited = set()
        if struct_info.name in visited:
            return (VerifyResult.SUCCESS, None)
        visited.add(struct_info.name)

        harness_path = os.path.join(
            self.struct_test_harness_dir, f"{struct_info.name}.rs"
        )
        if os.path.exists(harness_path) or self._hydrate_struct_harness(struct_info.name):
            return (VerifyResult.SUCCESS, None)

        # Ensure dependencies have their harness materialized first.
        for dependency in struct_info.dependencies:
            # Skip self references to avoid infinite recursion.
            if dependency.name == struct_info.name:
                continue
            result = self._ensure_struct_harness_available(dependency, visited)
            if result[0] != VerifyResult.SUCCESS:
                return result

        unidiomatic_path = os.path.join(
            self.unidiomatic_result_path,
            "translated_code_unidiomatic",
            "structs",
            f"{struct_info.name}.rs",
        )
        if not os.path.exists(unidiomatic_path):
            raise ValueError(
                f"Struct {struct_info.name} is not translated into unidiomatic Rust yet"
            )

        with open(unidiomatic_path) as f:
            unidiomatic_code = f.read()
        if idiomatic_override is not None:
            idiomatic_code = idiomatic_override
        else:
            idiomatic_path = os.path.join(
                self.result_path,
                "translated_code_idiomatic",
                "structs",
                f"{struct_info.name}.rs",
            )
            if not os.path.exists(idiomatic_path):
                raise ValueError(
                    f"Struct {struct_info.name} is not translated into idiomatic Rust yet"
                )
            with open(idiomatic_path) as f:
                idiomatic_code = f.read()

        return self._struct_generate_test_harness(
            struct_info.name,
            unidiomatic_code,
            idiomatic_code,
            struct_info.dependencies,
        )

    def _hydrate_struct_harness(self, struct_name: str) -> bool:
        """Ensure the given struct harness exists in the working dir.

        If it is missing, try to restore it from the persisted results cache.
        Returns True when the harness is now available.
        """
        harness_path = os.path.join(
            self.struct_test_harness_dir, f"{struct_name}.rs")
        if os.path.exists(harness_path):
            return True
        cached_path = os.path.join(
            self.saved_test_harness_path, "structs", f"{struct_name}.rs")
        if not os.path.exists(cached_path):
            return False
        with open(cached_path) as f:
            cached_code = f.read()
        utils.save_code(harness_path, cached_code)
        return True

    def _persist_struct_harness(self, struct_name: str) -> None:
        """Copy the freshly generated struct harness into the cached results."""
        harness_path = os.path.join(
            self.struct_test_harness_dir, f"{struct_name}.rs")
        if not os.path.exists(harness_path):
            return
        with open(harness_path) as f:
            harness_code = f.read()
        utils.save_code(
            os.path.join(
                self.saved_test_harness_path, "structs", f"{struct_name}.rs"
            ),
            harness_code,
        )

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
            last_status, last_log = verify_result
            detail = ""
            if last_status != VerifyResult.SUCCESS and last_log:
                detail = f"\nLast error ({last_status.name}):\n{last_log}"
            message = (
                f"Spec-driven harness exhausted {self.max_attempts} attempts for function {function_name}."
            )
            message += detail
            return (VerifyResult.TEST_HARNESS_MAX_ATTEMPTS_EXCEEDED, message)
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
        # Rename idiomatic signature function name to `{function_name}_idiomatic` even if the
        # idiomatic translation changed the name. Use Rust AST parser to get function names.
        try:
            sig_map = rust_ast_parser.get_func_signatures(idiomatic_signature)
            if len(sig_map) >= 1:
                idiom_decl_name = next(iter(sig_map.keys()))
            else:
                impl_map = rust_ast_parser.get_func_signatures(idiomatic_impl)
                idiom_decl_name = next(iter(impl_map.keys())) if len(impl_map) >= 1 else function_name
        except Exception:
            idiom_decl_name = function_name
        idiomatic_signature_replaced = utils.rename_rust_function_signature(
            idiomatic_signature,
            idiom_decl_name,
            f"{function_name}_idiomatic",
            DataType.FUNCTION
        )
        convert_back_prompt = ""
        if struct_signature_dependency_names:
            convert_back_prompt = "You need to covert mutable reference back and **COPY** the content of C structs to the input mutable pointers, as all convertion functions are at **DIFFERENT** memory locations"
        prompt = f'''
This is the idiomatic Rust implementation (translated from the unidiomatic Rust), the function signature is
```rust
{idiomatic_signature_replaced};
```
This is the unidiomatic Rust implementation (FFI layout-compatible), the function signature is
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
                f'error type {verify_result[0]} not implemented')

        # Try spec-driven function harness generation first
        func_spec_path = os.path.join(
            self.result_path,
            "translated_code_idiomatic",
            "specs",
            "functions",
            f"{function_name}.json",
        )
        # Collect optional LLM notes from spec to guide fallback prompts
        spec_hints_text = None
        if os.path.exists(func_spec_path):
            try:
                with open(func_spec_path, 'r') as _sf:
                    _spec_obj = json.load(_sf)
                _notes = []
                for _f in _spec_obj.get('fields', []):
                    if not isinstance(_f, dict):
                        continue
                    note = _f.get('llm_note')
                    if isinstance(note, str) and note.strip():
                        u = (_f.get('u_field') or {}).get('name', '')
                        i = (_f.get('i_field') or {}).get('name', '')
                        _notes.append(f"- {u} -> {i}: {note.strip()}")
                if _notes:
                    hints = "\n".join(_notes)
                    prompt += f"\nSpec hints (from SPEC.llm_note):\n{hints}\n"
                    spec_hints_text = hints
            except Exception:
                pass
        function_result = None
        try:
            function_result = generate_function_harness_from_spec_file(
                function_name,
                idiomatic_signature_replaced,
                original_signature_renamed,
                list(struct_signature_dependency_names),
                func_spec_path,
            )
        except Exception as e:
            print(f"Spec-driven function harness failed: {e}")

        # If spec-driven produced TODOs or failed previously, ask LLM to finish/fix
        if function_result is not None and 'TODO:' in function_result:
            helper_blocks: list[str] = []
            for dep_name in struct_signature_dependency_names:
                helper_path = os.path.join(
                    self.struct_test_harness_dir,
                    f"{dep_name}.rs",
                )
                if os.path.exists(helper_path):
                    try:
                        with open(helper_path, 'r') as _hf:
                            helper_blocks.append(_hf.read().strip())
                    except Exception:
                        pass

            llm_prompt = f'''
We have an initial spec-driven harness with TODOs. Finish all TODOs and ensure it compiles.
Idiomatic signature:
```rust
{idiomatic_signature_replaced};
```
Unidiomatic signature:
```rust
{original_signature_renamed};
```
{('Spec hints (from SPEC.llm_note):\n' + spec_hints_text + '\n') if spec_hints_text else ''}
Current harness:
```rust
{function_result}
```
'''
            if helper_blocks:
                helpers_joined = "\n\n".join(helper_blocks)
                llm_prompt += f"The following struct converters are available and must be reused:\n```rust\n{helpers_joined}\n```\n"

            llm_prompt += """Output only the final function in this format:
----FUNCTION----
```rust
// Your translated function here
```
----END FUNCTION----
"""
            result = self.llm.query(llm_prompt)
            try:
                llm_result = utils.parse_llm_result(result, "function")
                function_result = llm_result["function"]
            except Exception as e:
                print(f"Failed to parse LLM completion for TODO-fix: {e}")

        if function_result is None:
            # TZ: when this will be called?
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
                    if not self._hydrate_struct_harness(struct_name):
                        raise ValueError(
                            f"Struct {struct_name} test harness is not generated")
                with open(f"{self.struct_test_harness_dir}/{struct_name}.rs") as f:
                    struct_code[struct_name] = f.read()

        # Rename the actual idiomatic implementation to `{function_name}_idiomatic` using the
        # detected idiomatic name from its signature
        function_code[function_name] = rust_ast_parser.rename_function(
            idiomatic_impl,
            idiom_decl_name,
            f"{function_name}_idiomatic"
        )
        function_code[f"{function_name}_harness"] = function_result

        combiner = PartialCombiner(function_code, struct_code)
        try:
            result, compile_code = combiner.combine()
        except Exception as e:
            return (VerifyResult.COMPILE_ERROR, f"Failed to combine code for function {function_name}: {e}")
        if result != CombineResult.SUCCESS or compile_code is None:
            return (VerifyResult.COMPILE_ERROR, f"Failed to combine the function {function_name}")

        result = self.try_compile_rust_code(
            compile_code)

        if result[0] != VerifyResult.SUCCESS:
            # If we compiled a spec-driven harness and it failed, try LLM to fix the compile errors in-place
            if function_result is not None:
                fix_prompt = f'''
The following test harness failed to compile. Fix compile errors and provide a working version. Do not add unrelated code; rely on provided signatures.
Idiomatic signature:
```rust
{idiomatic_signature_replaced};
```
Unidiomatic signature:
```rust
{original_signature_renamed};
```
{('Spec hints (from SPEC.llm_note):\n' + spec_hints_text + '\n') if spec_hints_text else ''}
Harness (with possible TODOs):
```rust
{function_result}
```
Compiler errors:
```
{result[1]}
```
Output only the final function in this format:
----FUNCTION----
```rust
// Your translated function here
```
----END FUNCTION----
'''
                res2 = self.llm.query(fix_prompt)
                try:
                    llm_fixed = utils.parse_llm_result(res2, "function")["function"]
                    function_code[f"{function_name}_harness"] = llm_fixed
                    combiner = PartialCombiner(function_code, struct_code)
                    result2, compile_code2 = combiner.combine()
                    if result2 == CombineResult.SUCCESS and compile_code2 is not None:
                        result3 = self.try_compile_rust_code(compile_code2)
                        if result3[0] == VerifyResult.SUCCESS:
                            utils.save_code(
                                f"{self.function_test_harness_dir}/{function_name}.rs", compile_code2)
                            return (VerifyResult.SUCCESS, None)
                except Exception as e:
                    print(f"LLM fix attempt failed: {e}")

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
            last_status, last_log = verify_result
            detail = ""
            if last_status != VerifyResult.SUCCESS and last_log:
                detail = f"\nLast error ({last_status.name}):\n{last_log}"
            message = (
                f"Spec-driven harness exhausted {self.max_attempts} attempts for struct {struct_name}."
            )
            message += detail
            return (VerifyResult.TEST_HARNESS_MAX_ATTEMPTS_EXCEEDED, message)

        # rename the unidiomatic struct to C struct
        unidiomatic_struct_code_renamed = rust_ast_parser.rename_struct_union(
            unidiomatic_struct_code, struct_name, f"C{struct_name}")

        # rename all the dependencies
        for dependency in struct_dependencies:
            dependency_name = dependency.name
            unidiomatic_struct_code_renamed = rust_ast_parser.rename_struct_union(
                unidiomatic_struct_code_renamed, dependency_name, f"C{dependency_name}")

        # Try spec-driven harness first (if spec exists and supported)
        spec_path = os.path.join(
            self.result_path,
            "translated_code_idiomatic",
            "specs",
            "structs",
            f"{struct_name}.json",
        )
        function_result = None
        struct_spec_hints = None
        try:
            # TZ: why named as `function_result`?
            function_result = generate_struct_harness_from_spec_file(
                struct_name,
                idiomatic_struct_code,
                unidiomatic_struct_code_renamed,
                spec_path,
            )
            if os.path.exists(spec_path):
                try:
                    with open(spec_path, 'r') as _sf:
                        _spec_obj = json.load(_sf)
                    _notes = []
                    for _f in _spec_obj.get('fields', []):
                        if not isinstance(_f, dict):
                            continue
                        note = _f.get('llm_note')
                        if isinstance(note, str) and note.strip():
                            u = (_f.get('u_field') or {}).get('name', '')
                            i = (_f.get('i_field') or {}).get('name', '')
                            _notes.append(f"- {u} -> {i}: {note.strip()}")
                    if _notes:
                        struct_spec_hints = "\n".join(_notes)
                except Exception:
                    pass
        except Exception as e:
            print(f"Spec-driven harness generation failed (struct {struct_name}): {e}")

        if function_result is None:
            error_message = (
                "Error: Spec-driven struct harness generation failed; "
                "no fallback template is allowed."
            )
            print(error_message)
            return (
                VerifyResult.COMPILE_ERROR,
                error_message,
            )

        if 'TODO:' in function_result:
            prompt = f'''
We have an initial spec-driven struct converters with TODOs. Finish all TODOs and ensure it compiles.
Idiomatic struct:
```rust
{idiomatic_struct_code}
```
Unidiomatic (repr C) struct:
```rust
{unidiomatic_struct_code_renamed}
```
{('Spec hints (from SPEC.llm_note):\n' + struct_spec_hints + '\n') if struct_spec_hints else ''}
Current converters:
```rust
{function_result}
```
Output only the two functions in this format:
----FUNCTION----
```rust
// Your translated function here
```
----END FUNCTION----
'''
            if len(struct_dependencies) > 0:
                for dependency in struct_dependencies:
                    dependency_name = dependency.name
                    if not os.path.exists(f"{self.struct_test_harness_dir}/{dependency_name}.rs"):
                        if self._hydrate_struct_harness(dependency_name):
                            continue
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

            result = self.llm.query(prompt)

            try:
                llm_result = utils.parse_llm_result(result, "function")
                function_result = llm_result["function"]
            except Exception:
                error_message = (
                    "Error: Failed to parse the result from LLM, result is not "
                    "wrapped by the tags as instructed. Remember the tag:\n"
                    "----FUNCTION----\n```rust\n// Your translated function here\n```\n"
                    "----END FUNCTION----"
                )
                print(error_message)
                return self._struct_generate_test_harness(
                    struct_name,
                    unidiomatic_struct_code,
                    idiomatic_struct_code,
                    struct_dependencies,
                    (VerifyResult.COMPILE_ERROR, error_message),
                    error_translation=result,
                    attempts=attempts+1,
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
            harness_path = os.path.join(
                self.struct_test_harness_dir, f"{dependency_name}.rs"
            )
            if not os.path.exists(harness_path):
                if not self._hydrate_struct_harness(dependency_name):
                    raise FileNotFoundError(
                        f"Struct harness for {dependency_name} is missing in both build and cache "
                        "directories; expected generate_struct_harness_from_spec_file to persist it."
                    )
            with open(harness_path) as f:
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
            # Try LLM fix in-place if we have an initial spec-driven/LLM harness
            if function_result is not None:
                fix_prompt = f'''
The following struct converters failed to compile. Fix compile errors and provide a working version. Do not add unrelated code.
Idiomatic struct:
```rust
{idiomatic_struct_code}
```
Unidiomatic (repr C) struct:
```rust
{unidiomatic_struct_code_renamed}
```
Converters:
```rust
{function_result}
```
Compiler errors:
```
{result[1]}
```
Output only the two functions in this format:
----FUNCTION----
```rust
// Your translated function here
```
----END FUNCTION----
'''
                res2 = self.llm.query(fix_prompt)
                try:
                    llm_fixed = utils.parse_llm_result(res2, "function")["function"]
                    save_code_try = '\n'.join([
                        idiomatic_struct_code,
                        unidiomatic_struct_code_renamed,
                        llm_fixed,
                    ])
                    result2 = self.try_compile_rust_code(save_code_try)
                    if result2[0] == VerifyResult.SUCCESS:
                        utils.save_code(
                            f"{self.struct_test_harness_dir}/{struct_name}.rs", save_code_try)
                        self._persist_struct_harness(struct_name)
                        return (VerifyResult.SUCCESS, None)
                except Exception as e:
                    print(f"LLM struct fix attempt failed: {e}")

            return self._struct_generate_test_harness(
                struct_name,
                unidiomatic_struct_code,
                idiomatic_struct_code,
                struct_dependencies,
                result,
                function_result,
                attempts=attempts+1
            )

        # Selftest gate: run minimal roundtrip before saving the harness
        try:
            tester = StructRoundTripTester(
                llm=self.llm,
                spec_root=os.path.join(
                    self.result_path,
                    "translated_code_idiomatic",
                    "specs",
                    "structs",
                ),
            )
            ok, snippet = tester.run_minimal(combined_code, struct_name)
        except Exception as e:
            ok = False
            snippet = f"selftest runtime error: {e}"
        if not ok:
            # TZ: should not return, should retry with error feedback
            return (
                VerifyResult.COMPILE_ERROR,
                f"SELFTEST(struct {struct_name}) FAILED:\n{snippet}",
            )

        utils.save_code(
            f"{self.struct_test_harness_dir}/{struct_name}.rs", save_code)
        self._persist_struct_harness(struct_name)

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

        try:
            rust_ast_parser.get_standalone_uses_code_paths(function_code)
        except Exception as e:
            print(f"Error: Failed to get standalone uses code paths for function {function.name}")
            return (VerifyResult.COMPILE_ERROR, str(e))

        # Determine the idiomatic function's declared name in `function_code`.
        # Prefer mapping/spec-provided idiomatic name when available.
        idiom_sigs = rust_ast_parser.get_func_signatures(function_code)
        idiomatic_decl_name = None

        spec_path = os.path.join(
            self.result_path,
            "translated_code_idiomatic",
            "specs",
            "functions",
            f"{function_name}.json",
        )
        spec_idiom = None
        try:
            if os.path.exists(spec_path):
                with open(spec_path, 'r') as _sf:
                    spec_obj = json.load(_sf)
                candidate = spec_obj.get('idiomatic_name')
                if isinstance(candidate, str) and candidate.strip():
                    spec_idiom = candidate.strip()
                else:
                    fallback_name = spec_obj.get('function_name')
                    if isinstance(fallback_name, str) and fallback_name.strip():
                        spec_idiom = fallback_name.strip()
        except Exception:
            spec_idiom = None

        mapping_idiom = None
        try:
            mapping_path = os.path.join(
                self.result_path,
                "translated_code_idiomatic",
                "specs",
                "function_name_map.json",
            )
            if os.path.exists(mapping_path):
                with open(mapping_path, 'r') as _mf:
                    mapping_data = json.load(_mf)
                candidate = mapping_data.get(function_name)
                if isinstance(candidate, str) and candidate.strip():
                    mapping_idiom = candidate.strip()
        except Exception:
            mapping_idiom = None

        if spec_idiom and spec_idiom in idiom_sigs:
            idiomatic_decl_name = spec_idiom
        elif mapping_idiom and mapping_idiom in idiom_sigs:
            idiomatic_decl_name = mapping_idiom
        elif function_name in idiom_sigs:
            idiomatic_decl_name = function_name
        elif len(idiom_sigs) == 1:
            idiomatic_decl_name = next(iter(idiom_sigs.keys()))
        else:
            if spec_idiom and spec_idiom not in idiom_sigs:
                return (VerifyResult.COMPILE_ERROR, f"SPEC declares idiomatic_name `{spec_idiom}`, but translated code defines: {list(idiom_sigs.keys())}")
            if mapping_idiom and mapping_idiom not in idiom_sigs:
                return (VerifyResult.COMPILE_ERROR, f"Name mapping expects `{mapping_idiom}`, but translated code defines: {list(idiom_sigs.keys())}")
            return (VerifyResult.COMPILE_ERROR, f"Unable to determine idiomatic function name for `{function_name}`; available: {list(idiom_sigs.keys())}")

        idiomatic_signature = idiom_sigs[idiomatic_decl_name]

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

                    # Ensure the struct harness exists (regenerate if cache missing).
                    result = self._ensure_struct_harness_available(
                        struct,
                        idiomatic_override=data_type_code[struct_name],
                    )
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
                list(struct_signature_dependency_names),
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

    @override
    def verify_struct(
        self,
        struct: StructInfo,
        struct_code: str,
        struct_dependencies_code: dict[str, str],
    ) -> tuple[VerifyResult, Optional[str]]:
        result = super().verify_struct(struct, struct_code, struct_dependencies_code)
        if result[0] != VerifyResult.SUCCESS:
            return result

        harness_result = self._ensure_struct_harness_available(
            struct,
            idiomatic_override=struct_code,
        )
        if harness_result[0] != VerifyResult.SUCCESS:
            return harness_result

        return result
