import json
import os
import shutil
from typing import Optional, override

import sactor.translator as translator
import sactor.verifier as verifier
from sactor import rust_ast_parser, utils
from sactor.c_parser import (CParser, EnumInfo, EnumValueInfo, FunctionInfo,
                             GlobalVarInfo, StructInfo)
from sactor.llm import LLM
from sactor.thirdparty import Crown, CrownType
from sactor.utils import read_file
from sactor.verifier import VerifyResult
from sactor.verifier.spec.spec_types import (extract_spec_block, save_spec,
                                             validate_basic_function_spec,
                                             validate_basic_struct_spec)

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
        executable_object=None,
        processed_compile_commands: list[list[str]] = [],
    ):
        super().__init__(
            llm=llm,
            c_parser=c_parser,
            config=config,
            result_path=result_path,
        )
        self.failure_info_path = os.path.join(
            self.result_path, "idiomatic_failure_info.json")
        if os.path.isfile(self.failure_info_path):
            content = read_file(self.failure_info_path)
            self.failure_info = json.loads(content)
        self._failure_info_backup_prepared = False

        self.c2rust_translation = c2rust_translation
        base_name = "translated_code_idiomatic"
        self.base_name = base_name

        self.translated_struct_path = os.path.join(
            self.result_path, base_name, "structs")
        self.translated_function_path = os.path.join(
            self.result_path, base_name, "functions")
        self.translated_global_var_path = os.path.join(
            self.result_path, base_name, "global_vars")
        self.translated_enum_path = os.path.join(
            self.result_path, base_name, "enums")
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
            executable_object=executable_object,
            processed_compile_commands=processed_compile_commands,
        )
        self.crown_result = crown_result

        self.specs_base_path = os.path.join(
            self.result_path, base_name, "specs")
        self.function_specs_path = os.path.join(
            self.specs_base_path, "functions")
        self._function_name_map_path = os.path.join(
            self.specs_base_path, "function_name_map.json"
        )
        self._function_name_map_cache: Optional[dict[str, str]] = None
        self._spec_schema_text: Optional[str] = None

    def _get_spec_schema_text(self) -> str:
        """Return the cached JSON schema text for SPEC generation."""
        if self._spec_schema_text is None:
            project_root = utils.find_project_root()
            schema_path = os.path.join(
                project_root, "sactor", "verifier", "spec", "schema.json"
            )
            self._spec_schema_text = read_file(schema_path)
        return self._spec_schema_text

    def _load_function_name_map(self) -> dict[str, str]:
        if self._function_name_map_cache is None:
            mapping: dict[str, str] = {}
            if os.path.exists(self._function_name_map_path):
                try:
                    with open(self._function_name_map_path, "r") as _mf:
                        mapping = json.load(_mf)
                    if not isinstance(mapping, dict):
                        mapping = {}
                except Exception:
                    mapping = {}
            self._function_name_map_cache = mapping
        return self._function_name_map_cache

    def _get_spec_idiomatic_name(self, function_name: str) -> Optional[str]:
        spec_path = os.path.join(
            self.function_specs_path, f"{function_name}.json"
        )
        if not os.path.exists(spec_path):
            return None
        try:
            with open(spec_path, "r") as _sf:
                spec_obj = json.load(_sf)
            candidate = spec_obj.get("idiomatic_name")
            if isinstance(candidate, str):
                candidate = candidate.strip()
                if candidate:
                    return candidate
        except Exception:
            return None
        return None

    def _resolve_dependency_decl_name(
        self,
        original_name: str,
        function_signatures: dict[str, str],
    ) -> Optional[str]:
        candidates: list[str] = []
        spec_candidate = self._get_spec_idiomatic_name(original_name)
        if spec_candidate:
            candidates.append(spec_candidate)
        mapping_candidate = self._load_function_name_map().get(original_name)
        if isinstance(mapping_candidate, str):
            mapping_candidate = mapping_candidate.strip()
            if mapping_candidate:
                candidates.append(mapping_candidate)
        if original_name in translator.RESERVED_KEYWORDS:
            candidates.append(original_name + "_")
        candidates.append(original_name)

        seen: set[str] = set()
        ordered_candidates: list[str] = []
        for cand in candidates:
            if cand and cand not in seen:
                ordered_candidates.append(cand)
                seen.add(cand)

        for cand in ordered_candidates:
            if cand in function_signatures:
                return cand

        if len(function_signatures) == 1:
            return next(iter(function_signatures.keys()))

        return None

    @override
    def _translate_enum_impl(
        self,
        enum: EnumInfo,
        verify_result: tuple[VerifyResult, Optional[str]] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslateResult:
        # Always initialize failure_info, even if already translated
        self.init_failure_info("enum", enum.name)

        enum_save_path = os.path.join(
            self.translated_enum_path, enum.name + ".rs")
        if os.path.exists(enum_save_path):
            print(f"Enum {enum.name} already translated")
            # Mark as success for this run so the new failure_info.json is populated
            self.failure_info[enum.name]['status'] = "success"
            return TranslateResult.SUCCESS
        if attempts > self.max_attempts - 1:
            print(
                f"Error: Failed to translate enum {enum.name} after {self.max_attempts} attempts")
            return TranslateResult.MAX_ATTEMPTS_EXCEEDED
        print(f"Translating enum: {enum.name} (attempts: {attempts})")

        if not os.path.exists(f"{self.unidiomatic_result_path}/translated_code_unidiomatic/enums/{enum.name}.rs"):
            raise RuntimeError(
                f"Error: Enum {enum.name} is not translated into unidiomatic Rust yet")
        code_of_enum = read_file(
            f"{self.unidiomatic_result_path}/translated_code_unidiomatic/enums/{enum.name}.rs")
        prompt = f'''
Translate the following unidiomatic Rust enum to idiomatic Rust. Try to avoid using raw pointers in the translation of the enum.
The enum is:
```rust
{code_of_enum}
```
If you think the enum is already idiomatic, you can directly copy the code to the output format.
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
Lastly, the enum is translated as:
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
                f'erorr type {verify_result[0]} not implemented')

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
                error_translation=enum_result,
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
        # Always initialize failure_info, even if already translated
        self.init_failure_info("global_var", global_var.name)
        if os.path.exists(global_var_save_path):
            print(f"Global variable {global_var.name} already translated")
            # Mark as success for this run so the new failure_info.json is populated
            self.failure_info[global_var.name]['status'] = "success"
            return TranslateResult.SUCCESS

        if attempts > self.max_attempts - 1:
            print(
                f"Error: Failed to translate global variable {global_var.name} after {self.max_attempts} attempts")
            return TranslateResult.MAX_ATTEMPTS_EXCEEDED
        print(
            f"Translating global variable: {global_var.name} (attempts: {attempts})")
        if global_var.is_const:
            global_var_name = global_var.name
            if not os.path.exists(f"{self.unidiomatic_result_path}/translated_code_unidiomatic/global_vars/{global_var_name}.rs"):
                raise RuntimeError(
                    f"Error: Global variable {global_var_name} is not translated into unidiomatic Rust yet")
            code_of_global_var = read_file(
                f"{self.unidiomatic_result_path}/translated_code_unidiomatic/global_vars/{global_var_name}.rs")
            prompt = f'''
Translate the following unidiomatic Rust const global variable to idiomatic Rust. Try to avoid using raw pointers in the translation of the global variable.
The global variable is:
```rust
{code_of_global_var}
```
If you think the global variable is already idiomatic, you can directly copy the code to the output format.
'''
        else:
            raise NotImplementedError(
                "Error: Only support translating const global variables for idiomatic Rust")

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
Lastly, the global variable is translated as:
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
                f'erorr type {verify_result[0]} not implemented')

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
        self.failure_info[global_var.name]['status'] = "success"
        utils.save_code(global_var_save_path, global_var_result)
        return TranslateResult.SUCCESS

    @override
    def _translate_struct_impl(
        self,
        struct_union: StructInfo,
        verify_result: tuple[VerifyResult, Optional[str]] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslateResult:
        # Translate the struct/union
        struct_save_path = os.path.join(
            self.translated_struct_path, struct_union.name + ".rs")
        # Always initialize failure_info, even if already translated
        self.init_failure_info("struct", struct_union.name)
        if os.path.exists(struct_save_path):
            print(f"Struct {struct_union.name} already translated")
            # Mark as success for this run so the new failure_info.json is populated
            self.failure_info[struct_union.name]['status'] = "success"
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

        unidiomatic_struct_code = read_file(struct_path)

        # Get results from crown
        crown_output = self.crown_result.query(
            struct_union.name, CrownType.STRUCT)

        # Get previous translation results as dependencies
        # Unlike the function, we only need to retrieve one level of dependencies
        dependencies_code = {}
        dependency_names = [d.name for d in struct_union.dependencies]
        for dependency_name in dependency_names:
            struct_path = os.path.join(
                self.translated_struct_path, dependency_name + ".rs")
            if not os.path.exists(struct_path):
                raise RuntimeError(
                    f"Error: Dependency {dependency_name} of struct {struct_union.name} is not translated yet")
            dependencies_code[dependency_name] = read_file(struct_path)
        joined_dependencies_code = '\n'.join(dependencies_code.values())

        # Translate the struct
        prompt = f'''
Translate the following Rust struct to idiomatic Rust. Try to avoid using raw pointers in the translation of the struct.
If the struct is designed as a cloneable struct, try to add/implement the `Clone` trait for the struct.
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
        # Attach JSON Schema for SPEC reference
        _schema_text = self._get_spec_schema_text()

        # define output format with SPEC
        prompt += f'''
Output the translated struct into this format (wrap with the following tags):
----STRUCT----
```rust
// Your translated struct here
```
----END STRUCT----

Also output a minimal JSON spec that maps the unidiomatic Rust layout to the idiomatic Rust struct.
Full JSON Schema for the SPEC (do not output the schema; output only an instance that conforms to it):
```json
{_schema_text}
```
Format:
----SPEC----
```json
{{
  "struct_name": "{struct_union.name}",
  "fields": [
    {{
      "u_field": {{
        "name": "...",
        "type": "...",
        "shape": "scalar" | {{"ptr": {{"kind": "slice|cstring|ref", "len_from": "?", "len_const": 1}}}}
      }},
      "i_field": {{
        "name": "...",
        "type": "..."
      }}
    }}
  ]
}}
```
----END SPEC----
Few-shot examples (each includes unidiomatic Rust, idiomatic Rust, and the SPEC):
Example S1 (scalar + cstring + slice):
Unidiomatic Rust:
```rust
#[repr(C)]
pub struct A {{
    pub num: u32,
    pub name: *const libc::c_char,
    pub data: *const u8,
    pub data_len: usize,
}}
```
Idiomatic Rust:
```rust
pub struct A {{
    pub num: u32,
    pub name: String,
    pub data: Vec<u8>,
}}
```
----SPEC----
```json
{{
  "struct_name": "A",
  "fields": [
    {{ "u_field": {{"name": "num",  "type": "u32",             "shape": "scalar" }},
       "i_field": {{"name": "num",  "type": "u32"}} }},
    {{ "u_field": {{"name": "name", "type": "*const c_char",    "shape": {{ "ptr": {{ "kind": "cstring" }} }} }},
       "i_field": {{"name": "name", "type": "String"}} }},
    {{ "u_field": {{"name": "data", "type": "*const u8",       "shape": {{ "ptr": {{ "kind": "slice", "len_from": "data_len" }} }} }},
       "i_field": {{"name": "data", "type": "Vec<u8>"}} }},
    {{ "u_field": {{"name": "data_len", "type": "usize",       "shape": "scalar" }},
       "i_field": {{"name": "data.len", "type": "usize"}} }}
  ]
}}
```
----END SPEC----

Example S2 (nested dot-path + ref):
Unidiomatic Rust:
```rust
#[repr(C)]
pub struct Inner {{ pub x: i32, pub name: *const libc::c_char }}
#[repr(C)]
pub struct Outer {{ pub id: u32, pub inn: Inner, pub pval: *const u32 }}
```
Idiomatic Rust:
```rust
pub struct Inner {{ pub x: i32, pub name: String }}
pub struct Outer {{ pub id: u32, pub inner: Inner, pub val: u32 }}
```
----SPEC----
```json
{{
  "struct_name": "Outer",
  "fields": [
    {{ "u_field": {{"name": "id",       "type": "u32",            "shape": "scalar" }},
       "i_field": {{"name": "id",       "type": "u32" }} }},
    {{ "u_field": {{"name": "inn.x",     "type": "i32",            "shape": "scalar" }},
       "i_field": {{"name": "inner.x",  "type": "i32" }} }},
    {{ "u_field": {{"name": "inn.name",  "type": "*const c_char",   "shape": {{ "ptr": {{ "kind": "cstring" }} }} }},
       "i_field": {{"name": "inner.name","type": "String" }} }},
    {{ "u_field": {{"name": "pval",     "type": "*const u32",      "shape": {{ "ptr": {{ "kind": "ref" }} }} }},
       "i_field": {{"name": "val",      "type": "u32" }} }}
  ]
}}
```
----END SPEC----

Example S3 (nullable cstring maps to Option):
Unidiomatic Rust:
```rust
#[repr(C)]
pub struct S {{ pub name: *const libc::c_char }}
```
Idiomatic Rust:
```rust
pub struct S {{ pub name: Option<String> }}
```
----SPEC----
```json
{{
  "struct_name": "S",
  "fields": [
    {{ "u_field": {{"name": "name", "type": "*const c_char", "shape": {{ "ptr": {{ "kind": "cstring", "null": "nullable" }} }} }},
       "i_field": {{"name": "name", "type": "Option<String>" }} }}
  ]
}}
```
----END SPEC----
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
        elif verify_result[0] != VerifyResult.SUCCESS:
            raise NotImplementedError(
                f'error type {verify_result[0]} not implemented')

        # Query LLM and keep the raw output for SPEC extraction later
        llm_raw = self.llm.query(prompt)
        try:
            llm_result = utils.parse_llm_result(llm_raw, "struct")
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
                struct_union.name, "COMPILE_ERROR", error_message, llm_raw
            )
            return self._translate_struct_impl(
                struct_union,
                verify_result=(VerifyResult.COMPILE_ERROR, error_message),
                error_translation=llm_raw,
                attempts=attempts+1
            )
        struct_result = llm_result["struct"]

        # add Debug trait for struct/union
        try:
            struct_result = rust_ast_parser.add_derive_to_struct_union(
                struct_result, struct_union.name, "Debug")
        except Exception as e:
            error_message = f"Error: Failed to add Debug trait to the struct: {e}, please check if the struct has a correct syntax"
            print(error_message)
            self.append_failure_info(
                struct_union.name, "COMPILE_ERROR", error_message, llm_raw
            )
            return self._translate_struct_impl(
                struct_union,
                verify_result=(VerifyResult.COMPILE_ERROR, error_message),
                error_translation=llm_raw,
                attempts=attempts+1
            )

        # Stage SPEC output before verification so harness generation can pick it up after success
        spec_tmp_dir: Optional[str] = None
        spec_tmp_path: Optional[str] = None
        raw_struct_spec: Optional[str] = None
        final_spec_base = os.path.join(self.result_path, self.base_name)
        final_spec_path = os.path.join(
            final_spec_base, "specs", "structs", f"{struct_union.name}.json"
        )
        spec_pre_saved = False
        spec_valid = False
        try:
            raw_struct_spec = extract_spec_block(llm_raw)
            if raw_struct_spec:
                spec_obj = json.loads(raw_struct_spec)
                ok, msg = validate_basic_struct_spec(
                    spec_obj, struct_union.name)
                if ok:
                    spec_tmp_dir = utils.get_temp_dir()
                    tmp_stage_base = os.path.join(spec_tmp_dir, "spec_stage")
                    save_spec(tmp_stage_base, "struct",
                              struct_union.name, raw_struct_spec)
                    spec_tmp_path = os.path.join(
                        tmp_stage_base,
                        "specs",
                        "structs",
                        f"{struct_union.name}.json",
                    )
                    try:
                        save_spec(
                            final_spec_base,
                            "struct",
                            struct_union.name,
                            raw_struct_spec,
                        )
                        spec_pre_saved = True
                        spec_valid = True
                    except Exception as e:
                        print(f"Struct spec pre-save failed: {e}")
                else:
                    print(f"Struct spec validation failed: {msg}")
                    spec_valid = False
            else:
                print(
                    f"Struct {struct_union.name}: SPEC block not found in LLM output")
                spec_valid = False
        except Exception as e:
            print(f"Struct spec staging skipped: {e}")

        if not spec_valid:
            if spec_tmp_dir:
                shutil.rmtree(spec_tmp_dir, ignore_errors=True)
            error_message = "Struct SPEC missing or invalid; retrying translation"
            print(error_message)
            self.append_failure_info(
                struct_union.name,
                "COMPILE_ERROR",
                error_message,
                llm_raw,
            )
            return self._translate_struct_impl(
                struct_union,
                verify_result=(VerifyResult.COMPILE_ERROR, error_message),
                error_translation=llm_raw,
                attempts=attempts + 1,
            )

        result = self.verifier.verify_struct(
            struct_union,
            struct_result,
            dependencies_code
        )
        if result[0] == VerifyResult.COMPILE_ERROR:
            if spec_tmp_dir:
                shutil.rmtree(spec_tmp_dir, ignore_errors=True)
            if spec_pre_saved and os.path.exists(final_spec_path):
                try:
                    os.remove(final_spec_path)
                except OSError:
                    pass
            self.append_failure_info(
                struct_union.name, "COMPILE_ERROR", result[1], struct_result)
            return self._translate_struct_impl(
                struct_union,
                verify_result=result,
                error_translation=struct_result,
                attempts=attempts + 1
            )
        elif result[0] == VerifyResult.TEST_ERROR:
            if spec_tmp_dir:
                shutil.rmtree(spec_tmp_dir, ignore_errors=True)
            if spec_pre_saved and os.path.exists(final_spec_path):
                try:
                    os.remove(final_spec_path)
                except OSError:
                    pass
            self.append_failure_info(
                struct_union.name, "TEST_ERROR", result[1], struct_result)
            return self._translate_struct_impl(
                struct_union,
                verify_result=result,
                error_translation=struct_result,
                attempts=attempts + 1
            )
        elif result[0] == VerifyResult.TEST_HARNESS_MAX_ATTEMPTS_EXCEEDED:
            if spec_tmp_dir:
                shutil.rmtree(spec_tmp_dir, ignore_errors=True)
            if spec_pre_saved and os.path.exists(final_spec_path):
                try:
                    os.remove(final_spec_path)
                except OSError:
                    pass
            self.append_failure_info(
                struct_union.name, "TEST_ERROR", result[1], struct_result)
            return TranslateResult.MAX_ATTEMPTS_EXCEEDED

        elif result[0] != VerifyResult.SUCCESS:
            raise NotImplementedError(
                f'error type {result[0]} not implemented')

        if not spec_pre_saved and spec_tmp_path and raw_struct_spec:
            try:
                save_spec(final_spec_base, "struct",
                          struct_union.name, raw_struct_spec)
                spec_pre_saved = True
            except Exception as e:
                print(f"Struct spec final save failed: {e}")
        if not spec_pre_saved and os.path.exists(final_spec_path):
            try:
                os.remove(final_spec_path)
            except OSError:
                pass
        if spec_tmp_dir:
            shutil.rmtree(spec_tmp_dir, ignore_errors=True)

        # Save the results
        utils.save_code(struct_save_path, struct_result)

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
        # Always initialize failure_info, even if already translated
        self.init_failure_info("function", function.name)
        if os.path.exists(function_save_path):
            print(f"Function {function.name} already translated")
            # Mark as success for this run so the new failure_info.json is populated
            self.failure_info[function.name]['status'] = "success"
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
        for f in function.function_dependencies:
            structs_in_function.extend(f.struct_dependencies)
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
                code_of_structs[struct_name] = read_file(struct_path)
                visited_structs.add(struct_name)

        # Get used global variables
        used_global_var_nodes = function.global_vars_dependencies
        used_global_vars = {}
        for global_var in used_global_var_nodes:
            if global_var.node.location is not None and global_var.node.location.file.name != function.node.location.file.name:
                continue
            global_var_res = self._translate_global_vars_impl(global_var)
            if global_var_res != TranslateResult.SUCCESS:
                return global_var_res
            with open(os.path.join(self.translated_global_var_path, global_var.name + ".rs"), "r") as file:
                code_of_global_var = file.read()
                used_global_vars[global_var.name] = code_of_global_var

        used_enum_values: list[EnumValueInfo] = function.enum_values_dependencies
        used_enum_defs = function.enum_dependencies
        code_of_enum = {}

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
            code = read_file(f"{self.translated_function_path}/{f}.rs")
            function_signatures = rust_ast_parser.get_func_signatures(code)
            resolved_name = self._resolve_dependency_decl_name(
                f, function_signatures
            )
            if resolved_name is None:
                available = ', '.join(function_signatures.keys())
                raise RuntimeError(
                    f"Error: Unable to determine idiomatic name for dependency {f} when translating {function.name}. Available declarations: [{available}]"
                )
            function_depedency_signatures.append(
                # add a semicolon to the end
                function_signatures[resolved_name] + ';')

        # Translate the function
        # Get the unidiomatic translation code
        unidiomatic_function_path = os.path.join(
            self.unidiomatic_result_path, "translated_code_unidiomatic/functions", function.name + ".rs")
        if not os.path.exists(unidiomatic_function_path):
            raise RuntimeError(
                f"Error: Function {function.name} is not translated into unidiomatic Rust yet")

        unidiomatic_function_code = read_file(unidiomatic_function_path)

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
Your solution should only have **one** function, if you need to create help function, define the help function inside the function you translate.
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

        if len(used_global_vars) > 0:
            joint_used_global_vars = '\n'.join(used_global_vars.values())
            prompt += f'''
The function uses the following const global variables, which are already translated as (you should **NOT** include them in your translation, as the system will automatically include them):
```rust
{joint_used_global_vars}
```
'''
        if len(used_enum_values) > 0 or len(used_enum_defs) > 0:
            enum_definitions = set()
            used_enum_names = []
            for enum in used_enum_values:
                used_enum_names.append(enum.name)
                enum_definitions.add(enum.definition)
            for enum_def in used_enum_defs:
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
Directly use the translated enums in your translation. You should **NOT** include them in your translation, as the system will automatically include them.
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

        allow_spec = function.name != "main"

        prompt += '''
Output the translated function into this format (wrap with the following tags):
----FUNCTION----
```rust
// Your translated function here
```
----END FUNCTION----
'''

        if allow_spec:
            _schema_text = self._get_spec_schema_text()

            prompt += f'''

Also output a minimal JSON spec that maps the unidiomatic Rust layout to the idiomatic Rust for the function arguments and return value.
Full JSON Schema for the SPEC (do not output the schema; output only an instance that conforms to it):
```json
{_schema_text}
```
----SPEC----
```json
{{
  "function_name": "{function.name}",
  "fields": [
    {{
      "u_field": {{
        "name": "...",
        "type": "...",
        "shape": "scalar" | {{"ptr": {{"kind": "slice|cstring|ref", "len_from": "?", "len_const": 1}}}}
      }},
      "i_field": {{
        "name": "...",
        "type": "..."
      }}
    }}
  ]
}}
```
----END SPEC----
Few-shot examples (each with unidiomatic Rust signature, idiomatic Rust signature, and the SPEC):
Example F1 (slice arg):
Unidiomatic Rust:
```rust
pub unsafe extern "C" fn sum(xs: *const i32, n: usize) -> i32;
```
Idiomatic Rust:
```rust
pub fn sum(xs: &[i32]) -> i32;
```
----SPEC----
```json
{{
  "function_name": "sum",
  "fields": [
    {{ "u_field": {{"name": "xs", "type": "*const i32", "shape": {{ "ptr": {{ "kind": "slice", "len_from": "n" }} }} }},
       "i_field": {{"name": "xs", "type": "&[i32]" }} }},
    {{ "u_field": {{"name": "n",  "type": "usize",      "shape": "scalar" }},
       "i_field": {{"name": "xs.len", "type": "usize" }} }}
  ]
}}
```
----END SPEC----

Example F2 (ref out):
Unidiomatic Rust:
```rust
pub unsafe extern "C" fn get_value(out_value: *mut i32);
```
Idiomatic Rust:
```rust
pub fn get_value() -> i32;
```
----SPEC----
```json
{{
  "function_name": "get_value",
  "fields": [
    {{ "u_field": {{"name": "out_value", "type": "*mut i32", "shape": {{ "ptr": {{ "kind": "ref" }} }} }},
       "i_field": {{"name": "ret", "type": "i32" }} }}
  ]
}}
```
----END SPEC----

Example F3 (nullable cstring maps to Option):
Unidiomatic Rust:
```rust
pub unsafe extern "C" fn set_name(name: *const libc::c_char);
```
Idiomatic Rust:
```rust
pub fn set_name(name: Option<&str>);
```
----SPEC----
```json
{{
  "function_name": "set_name",
  "fields": [
    {{ "u_field": {{"name": "name", "type": "*const c_char", "shape": {{ "ptr": {{ "kind": "cstring", "null": "nullable" }} }} }},
       "i_field": {{"name": "name", "type": "Option<&str>" }} }}
  ]
}}
```
----END SPEC----
'''

        feed_to_verify = (VerifyResult.SUCCESS, None)
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

        elif verify_result[0] == VerifyResult.TEST_ERROR or verify_result[0] == VerifyResult.TEST_TIMEOUT:
            feed_to_verify = verify_result
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
                f'error type {verify_result[0]} not implemented')

        # Query LLM and keep the raw output for SPEC extraction later
        llm_raw = self.llm.query(prompt)
        try:
            llm_result = utils.parse_llm_result(llm_raw, "function")
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
                function.name, "COMPILE_ERROR", error_message, llm_raw
            )
            return self._translate_function_impl(
                function,
                verify_result=(VerifyResult.COMPILE_ERROR, error_message),
                error_translation=llm_raw,
                attempts=attempts+1
            )
        try:
            function_result = llm_result["function"]
        except KeyError:
            error_message = f"Error: Output does not wrapped in the correct format!"
            self.append_failure_info(
                function.name, "COMPILE_ERROR", error_message, llm_raw
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
            error_message = f"Error: Syntax error in the translated code: {e}"
            print(error_message)
            self.append_failure_info(
                function.name, "COMPILE_ERROR", error_message, llm_raw
            )
            # retry the translation
            return self._translate_function_impl(
                function,
                verify_result=(VerifyResult.COMPILE_ERROR,
                               error_message),
                error_translation=function_result,
                attempts=attempts+1
            )

        # detect whether there are too many functions which may cause multi-definition problems after combining
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

        # Determine idiomatic function name; prefer SPEC if provided
        idiomatic_func_name = None
        if allow_spec:
            try:
                raw_spec_try = extract_spec_block(llm_raw)
                if raw_spec_try:
                    spec_obj_try = json.loads(raw_spec_try)
                    name_from_spec = spec_obj_try.get("function_name")
                    if isinstance(name_from_spec, str) and name_from_spec.strip():
                        idiomatic_func_name = name_from_spec.strip()
            except Exception:
                pass
        # Fallback: only function present in result
        if idiomatic_func_name is None and len(function_result_sigs) == 1:
            try:
                idiomatic_func_name = next(iter(function_result_sigs.keys()))
            except Exception:
                idiomatic_func_name = None

        # If still unknown, require original name to be present
        if idiomatic_func_name is None:
            if function.name not in function_result_sigs:
                if function.name in translator.RESERVED_KEYWORDS:
                    # TODO: handle this case
                    pass
                else:
                    error_message = f"Error: Function signature not found in the translated code for function `{function.name}`. Got functions: {list(function_result_sigs.keys())}. If you renamed the function, include a SPEC with `function_name`."
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
        else:
            # SPEC provided a new name; ensure it exists in the output
            if idiomatic_func_name not in function_result_sigs:
                error_message = f"Error: SPEC declares function_name `{idiomatic_func_name}`, but translated code defines: {list(function_result_sigs.keys())}"
                print(error_message)
                return self._translate_function_impl(
                    function,
                    verify_result=(VerifyResult.COMPILE_ERROR, error_message),
                    error_translation=function_result,
                    attempts=attempts+1
                )

        # fetch all struct dependencies
        all_structs = set()
        all_global_vars = set()
        all_dependency_functions = set()

        def get_all_dependencies(function: FunctionInfo):
            for struct in function.struct_dependencies:
                all_structs.add(struct.name)
            for g_var in function.global_vars_dependencies:
                all_global_vars.add(g_var.name)

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

        all_dt_code = {}
        for struct in all_structs:
            all_dt_code[struct] = read_file(
                f"{self.translated_struct_path}/{struct}.rs")

        for g_var in all_global_vars:
            all_dt_code[g_var] = read_file(
                f"{self.translated_global_var_path}/{g_var}.rs")

        all_dependency_functions_code = {}
        for f in all_dependency_functions:
            all_dependency_functions_code[f] = read_file(
                f"{self.translated_function_path}/{f}.rs")

        data_type_code = all_dt_code | used_global_vars | code_of_enum

        # process the function result
        function_result = rust_ast_parser.expand_use_aliases(
            function_result)  # remove potentail 'as' in use statements

        # Verify the translation
        # Stage SPEC (with idiomatic name) before verification so harness generation can see it
        spec_tmp_dir: Optional[str] = None
        spec_tmp_path: Optional[str] = None
        spec_pre_saved = False
        spec_json_to_save: Optional[str] = None
        final_spec_base = os.path.join(self.result_path, self.base_name)
        final_spec_path = os.path.join(
            final_spec_base, "specs", "functions", f"{function.name}.json"
        )
        if allow_spec:
            try:
                raw_spec_candidate = extract_spec_block(llm_raw)
                if raw_spec_candidate:
                    spec_obj = json.loads(raw_spec_candidate)
                    # Force canonical function name and attach idiomatic name hint
                    spec_obj["function_name"] = function.name
                    if idiomatic_func_name:
                        spec_obj["idiomatic_name"] = idiomatic_func_name
                    ok, msg = validate_basic_function_spec(
                        spec_obj, function.name)
                    if ok:
                        spec_json_to_save = json.dumps(spec_obj, indent=2)
                        spec_tmp_dir = utils.get_temp_dir()
                        tmp_stage_base = os.path.join(
                            spec_tmp_dir, "spec_stage")
                        save_spec(
                            tmp_stage_base,
                            "function",
                            function.name,
                            spec_json_to_save,
                        )
                        spec_tmp_path = os.path.join(
                            tmp_stage_base,
                            "specs",
                            "functions",
                            f"{function.name}.json",
                        )
                        save_spec(
                            final_spec_base,
                            "function",
                            function.name,
                            spec_json_to_save,
                        )
                        spec_pre_saved = True
                    else:
                        print(f"Function spec validation failed: {msg}")
                else:
                    print(
                        f"Function {function.name}: SPEC block not found in LLM output")
            except Exception as e:
                print(f"Function spec staging skipped: {e}")

        result = self.verifier.verify_function(
            function,
            function_code=function_result,
            data_type_code=data_type_code,
            function_dependencies_code=all_dependency_functions_code,
            unidiomatic_signature=undiomantic_function_signature,
            prefix=False,  # TODO: check here
        )

        if result[0] != VerifyResult.SUCCESS:
            # Clean up staged SPEC and mapping if verification failed
            if spec_pre_saved and os.path.exists(final_spec_path):
                try:
                    os.remove(final_spec_path)
                except OSError:
                    pass
            if spec_tmp_dir:
                shutil.rmtree(spec_tmp_dir, ignore_errors=True)
            if result[0] == VerifyResult.COMPILE_ERROR:
                self.append_failure_info(
                    function.name, "COMPILE_ERROR", result[1], function_result)

            elif result[0] == VerifyResult.TEST_ERROR or result[0] == VerifyResult.FEEDBACK or result[0] == VerifyResult.TEST_TIMEOUT:
                self.append_failure_info(
                    function.name, "TEST_ERROR", result[1], function_result)
            elif result[0] == VerifyResult.TEST_HARNESS_MAX_ATTEMPTS_EXCEEDED:
                self.append_failure_info(
                    function.name, "TEST_ERROR", result[1], function_result)
                return TranslateResult.MAX_ATTEMPTS_EXCEEDED
            else:
                raise NotImplementedError(
                    f'error type {result[0]} not implemented')

            return self._translate_function_impl(
                function,
                verify_result=result,
                error_translation=function_result,
                attempts=attempts + 1
            )

        # Persist SPEC (if staged) and update mapping after successful verification
        if spec_json_to_save and not spec_pre_saved:
            try:
                save_spec(final_spec_base, "function",
                          function.name, spec_json_to_save)
                spec_pre_saved = True
            except Exception as e:
                print(f"Function spec final save failed: {e}")
        if spec_tmp_dir:
            shutil.rmtree(spec_tmp_dir, ignore_errors=True)

        # Update idiomatic name mapping (best-effort)
        if idiomatic_func_name:
            try:
                mapping_dir = os.path.join(final_spec_base, "specs")
                os.makedirs(mapping_dir, exist_ok=True)
                mapping_path = os.path.join(
                    mapping_dir, "function_name_map.json")
                mapping_data = {}
                if os.path.exists(mapping_path):
                    with open(mapping_path, "r") as _mf:
                        try:
                            mapping_data = json.load(_mf)
                        except Exception:
                            mapping_data = {}
                mapping_data[function.name] = idiomatic_func_name
                with open(mapping_path, "w") as _mf:
                    json.dump(mapping_data, _mf, indent=2)
                self._function_name_map_cache = mapping_data
            except Exception as e:
                print(f"Function name mapping update skipped: {e}")

        # save code
        utils.save_code(
            f"{self.translated_function_path}/{function.name}.rs", function_result)

        return TranslateResult.SUCCESS
