import json
import os
import shutil
from typing import Optional, override

import sactor.translator as translator
import sactor.verifier as verifier
from sactor import logging as sactor_logging, rust_ast_parser, utils
from sactor.c_parser import (CParser, EnumInfo, EnumValueInfo, FunctionInfo,
                             GlobalVarInfo, StructInfo)
from sactor.llm import LLM
from sactor.thirdparty import Crown, CrownType
from sactor.translator.idiomatic_fewshots import FUNCTION_FEWSHOTS, STRUCT_FEWSHOTS
from sactor.utils import read_file
from sactor.verifier import VerifyResult
from sactor.verifier.spec.spec_types import (extract_spec_block, save_spec,
                                             validate_basic_function_spec,
                                             validate_basic_struct_spec)

from .translator import Translator
from .translator_types import TranslateResult


logger = sactor_logging.get_logger(__name__)


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
        link_args: list[str] | None = None,
        continue_run_when_incomplete=False
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
        
        self.continue_run_when_incomplete = continue_run_when_incomplete

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
            link_args=link_args or [],
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
        self._struct_name_map_path = os.path.join(
            self.specs_base_path, "struct_name_map.json"
        )
        self._struct_name_map_cache: Optional[dict[str, str]] = None
        self._spec_schema_text: Optional[str] = None

    def _get_spec_schema_text(self) -> str:
        """Return the cached JSON schema text for SPEC generation."""
        if self._spec_schema_text is None:
            self._spec_schema_text = utils.load_spec_schema_text()
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

    def _load_struct_name_map(self) -> dict[str, str]:
        if self._struct_name_map_cache is None:
            mapping: dict[str, str] = {}
            if os.path.exists(self._struct_name_map_path):
                try:
                    with open(self._struct_name_map_path, "r") as _mf:
                        mapping = json.load(_mf)
                    if not isinstance(mapping, dict):
                        mapping = {}
                except Exception:
                    mapping = {}
            self._struct_name_map_cache = mapping
        return self._struct_name_map_cache

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
            logger.info("Enum %s already translated", enum.name)
            # Mark as success for this run so the new failure_info.json is populated
            self.mark_translation_success("enum", enum.name)
            return TranslateResult.SUCCESS
        if attempts > self.max_attempts - 1:
            logger.error(
                "Failed to translate enum %s after %d attempts",
                enum.name,
                self.max_attempts,
            )
            return TranslateResult.MAX_ATTEMPTS_EXCEEDED
        logger.info("Translating enum: %s (attempts: %d)", enum.name, attempts)
        self.failure_info_set_attempts(enum.name, attempts + 1)

        if not os.path.exists(f"{self.unidiomatic_result_path}/translated_code_unidiomatic/enums/{enum.name}.rs"):
            msg = f"Error: Enum {enum.name} is not translated into unidiomatic Rust yet"
            if self.continue_run_when_incomplete:
                self.append_failure_info(enum.name, "NO_UNIDIOMATIC_CODE_ERROR", msg, "")
                logger.warning(msg)
                return TranslateResult.NO_UNIDIOMATIC_CODE
            else:
                raise RuntimeError(msg)
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
            logger.error("%s", error_message)
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

        logger.debug("Translated enum %s:", enum.name)
        logger.debug("%s", enum_result)

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
        
        def return_result(global_var_result, verification=True):
            # check the global variable name, allow const global variable to have different name
            if global_var.name not in global_var_result and not global_var.is_const:
                if global_var_result.lower().find(global_var.name.lower()) != -1:
                    error_message = f"Error: Global variable name {global_var.name} not found in the translated code, keep the upper/lower case of the global variable name."
                else:
                    error_message = f"Error: Global variable name {global_var.name} not found in the translated code"
                    logger.error("%s", error_message)
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

            logger.debug("Translated global variable %s:\n%s", global_var.name, global_var_result)

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
            self.mark_translation_success("global_var", global_var.name)
            utils.save_code(global_var_save_path, global_var_result)
            return TranslateResult.SUCCESS

        enum_dependency_code = ""
        # Always initialize failure_info, even if already translated
        self.init_failure_info("global_var", global_var.name)
        if os.path.exists(global_var_save_path):
            logger.info("Global variable %s already translated", global_var.name)
            # Mark as success for this run so the new failure_info.json is populated
            self.mark_translation_success("global_var", global_var.name)
            return TranslateResult.SUCCESS

        used_enum_values = getattr(global_var, "enum_value_dependencies", [])
        used_enum_defs = getattr(global_var, "enum_dependencies", [])
        if used_enum_values or used_enum_defs:
            enum_defs_map: dict[str, EnumInfo] = {}
            for enum_val in used_enum_values:
                enum_defs_map[enum_val.definition.name] = enum_val.definition
            for enum_def in used_enum_defs:
                enum_defs_map[enum_def.name] = enum_def

            rust_enum_codes: list[str] = []
            for enum_def in [enum_defs_map[name] for name in sorted(enum_defs_map.keys())]:
                enum_translation_res = self._translate_enum_impl(enum_def)
                if enum_translation_res != TranslateResult.SUCCESS:
                    return enum_translation_res
                enum_code_path = os.path.join(
                    self.translated_enum_path, enum_def.name + ".rs")
                rust_enum_codes.append(read_file(enum_code_path))

            enum_dependency_code = "\n\n".join(rust_enum_codes)

        if attempts > self.max_attempts - 1:
            logger.error(
                "Failed to translate global variable %s after %d attempts",
                global_var.name,
                self.max_attempts,
            )
            return TranslateResult.MAX_ATTEMPTS_EXCEEDED
        logger.info(
            "Translating global variable: %s (attempts: %d)",
            global_var.name,
            attempts,
        )
        self.failure_info_set_attempts(global_var.name, attempts + 1)

        if global_var.is_const:
            global_var_name = global_var.name
            if not os.path.exists(f"{self.unidiomatic_result_path}/translated_code_unidiomatic/global_vars/{global_var_name}.rs"):
                msg = f"Error: Global variable {global_var_name} is not translated into unidiomatic Rust yet"
                if self.continue_run_when_incomplete:
                    self.append_failure_info(
                        global_var_name,
                        "NO_UNIDIOMATIC_CODE_ERROR",
                        msg,
                        ""
                        )
                    logger.warning(msg)
                    return TranslateResult.NO_UNIDIOMATIC_CODE
                else:
                    raise RuntimeError(msg)
            code_of_global_var = read_file(
                f"{self.unidiomatic_result_path}/translated_code_unidiomatic/global_vars/{global_var_name}.rs")
            if len(code_of_global_var) >= self.const_global_max_translation_len:
                # use ast parser to change libc numeric types to Rust primitive types
                result = rust_ast_parser.replace_libc_numeric_types_to_rust_primitive_types(code_of_global_var)
                return return_result(result, verification=False)
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
            logger.error("%s", error_message)
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
                logger.error("%s", error_message)
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
        # TODO: may add verification here
        compile_code = global_var_result
        if enum_dependency_code:
            compile_code = f"{enum_dependency_code}\n{global_var_result}"
        result = self.verifier.try_compile_rust_code(compile_code)
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
        self.mark_translation_success("global_var", global_var.name)
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
        error_spec=None,
    ) -> TranslateResult:
        # Translate the struct/union
        struct_save_path = os.path.join(
            self.translated_struct_path, struct_union.name + ".rs")
        # Always initialize failure_info, even if already translated
        self.init_failure_info("struct", struct_union.name)
        if os.path.exists(struct_save_path):
            logger.info("Struct %s already translated", struct_union.name)
            # Mark as success for this run so the new failure_info.json is populated
            self.mark_translation_success("struct", struct_union.name)
            return TranslateResult.SUCCESS

        if attempts > self.max_attempts - 1:
            logger.error(
                "Failed to translate struct %s after %d attempts",
                struct_union.name,
                self.max_attempts,
            )
            return TranslateResult.MAX_ATTEMPTS_EXCEEDED

        logger.info(
            "Translating struct: %s (attempts: %d)",
            struct_union.name,
            attempts,
        )
        self.failure_info_set_attempts(struct_union.name, attempts + 1)

        # Get unidiomatic translation code
        struct_path = os.path.join(
            self.unidiomatic_result_path, "translated_code_unidiomatic/structs", struct_union.name + ".rs")
        if not os.path.exists(struct_path):
            msg = f"Error: Struct {struct_union.name} is not translated into unidiomatic Rust yet"
            if self.continue_run_when_incomplete:
                self.append_failure_info(
                    struct_union.name,
                    "NO_UNIDIOMATIC_CODE_ERROR",
                    msg,
                    ""
                )
                logger.warning(msg)
                return TranslateResult.NO_UNIDIOMATIC_CODE
            else:
                raise RuntimeError(msg)

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

        enum_dependency_defs: dict[str, EnumInfo] = {}
        for enum_val in getattr(struct_union, "enum_value_dependencies", []):
            enum_dependency_defs[enum_val.definition.name] = enum_val.definition
        for enum_def in getattr(struct_union, "enum_dependencies", []):
            enum_dependency_defs[enum_def.name] = enum_def

        enum_dependency_code: dict[str, str] = {}
        if enum_dependency_defs:
            for enum_def in enum_dependency_defs.values():
                self._translate_enum_impl(enum_def)
                enum_path = os.path.join(
                    self.translated_enum_path, enum_def.name + ".rs")
                enum_dependency_code[enum_def.name] = read_file(enum_path)
            logger.debug(
                "Struct %s includes enum dependencies: %s",
                struct_union.name,
                list(enum_dependency_code.keys()),
            )

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
        if len(enum_dependency_code) > 0:
            joined_enum_names = '\n'.join(enum_dependency_code.keys())
            joined_enum_code = '\n'.join(enum_dependency_code.values())
            prompt += f'''
The struct uses the following enums or type aliases. They are already translated and will be provided automatically; you should **NOT** redefine them:
```c
{joined_enum_names}
```
In Rust they are available as:
```rust
{joined_enum_code}
```
Refer to these definitions directly in your translation.
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
If you rename the idiomatic type, set the `i_type` field accordingly (still set it even if unchanged).

Naming guardrails (do not skip):
- The repr(C) type must stay exactly `C{struct_union.name}` (same casing as the original C identifier). Never CamelCase or otherwise rename the C-side type.
- Do not re-declare the repr(C) struct; assume `pub struct C{struct_union.name}` already exists in the compiled crate and only reference it.
- Do not emit conversion functions nor reference the repr(C) alias (e.g. `C{struct_union.name}`) directly; keep the output strictly to the idiomatic Rust type and any pure-Rust helper methods. The verifier will synthesize the bridging code.
- If you rename the idiomatic type, the converters must be emitted exactly as `unsafe fn C{struct_union.name}_to_<idiomatic_name>_mut(...)` and `unsafe fn <idiomatic_name>_to_C{struct_union.name}_mut(...)`.
- When the C layout uses typedefs such as `uint32_t` or `uint8_t`, either import them from `libc` or map them to the corresponding Rust primitives (e.g. `u32`, `u8`). The generated code must compile without missing typedefs.
Full JSON Schema for the SPEC (do not output the schema; output only an instance that conforms to it):
```json
{_schema_text}
```
Format:
----SPEC----
```json
{{
  "struct_name": "{struct_union.name}",
  "i_kind": "struct",
  "i_type": "<Idiomatic type name (use the same as struct_name if unchanged)>",
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
'''
        prompt += "\nFew-shot examples (each includes unidiomatic Rust, idiomatic Rust, and the SPEC):"
        for example in STRUCT_FEWSHOTS:
            prompt += f"""

{example.label}:
{example.description}
Unidiomatic Rust:
```rust
{example.unidiomatic}
```
Idiomatic Rust:
```rust
{example.idiomatic}
```
----SPEC----
```json
{example.spec}
```
----END SPEC----
"""

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

            # Detect naming / typedef regressions and steer the retry aggressively.
            lowered_error = verify_result[1].lower()
            if "cannot find function" in lowered_error and "_to_c" in lowered_error:
                prompt += f"""
The compiler could not find one or more conversion helpers (e.g. `C{struct_union.name}_to_<idiomatic>_mut`).
Double-check that you:
- Kept the repr(C) struct named exactly `C{struct_union.name}`;
- Emitted both converters with that exact casing: `unsafe fn C{struct_union.name}_to_<Idiomatic>_mut(...)` and `unsafe fn <Idiomatic>_to_C{struct_union.name}_mut(...)`;
- Called those helpers when handling nested structs or optional pointers.
Never CamelCase `C{struct_union.name}`.
"""
            if "cannot find type `uint" in lowered_error or "consider importing this type alias" in lowered_error:
                prompt += """
One of the C typedefs such as `uint32_t`/`uint8_t` was left dangling. Either `use libc::<the typedef>` or map it to the canonical Rust primitive (`u32`, `u8`, etc.). Do not leave bare typedef names that Rust does not know about.
"""

        elif verify_result[0] == VerifyResult.TEST_ERROR:
            prompt += f'''
Lastly, the struct is translated as:
```rust
{error_translation}
```
It failed the following tests:
```
{verify_result[1]}
```
Analyze the error messages, think about the possible reasons, and try to avoid this error.
'''
        elif verify_result[0] == VerifyResult.TEST_HARNESS_MAX_ATTEMPTS_EXCEEDED:
            harness_log = verify_result[1] if verify_result[1] else "(harness generator produced no log)"
            prompt += f'''
Lastly, the struct is translated as:
```rust
{error_translation}
```
'''
            if error_spec:
                prompt += f'''
The SPEC generated for the struct was:
```json
{error_spec}
```
'''
            prompt += f'''
Test harness generation failed repeatedly with the following log:
```
{harness_log}
```
Please inspect the SPEC and conversion logic to ensure both transformation functions are emitted and consistent with the struct layout. Try to fix the issues this time.
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
            logger.error("%s", error_message)
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
        spec_obj_parsed: Optional[dict] = None
        spec_validation_error: Optional[str] = None
        try:
            raw_struct_spec = extract_spec_block(llm_raw)
            if raw_struct_spec:
                spec_obj = json.loads(raw_struct_spec)
                normalized_struct_spec = json.dumps(
                    spec_obj, indent=2) + "\n"
                ok, msg = validate_basic_struct_spec(
                    spec_obj, struct_union.name)
                if ok:
                    spec_obj_parsed = spec_obj
                    raw_struct_spec = normalized_struct_spec
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
                        logger.error("Struct spec pre-save failed: %s", e)
                else:
                    logger.error("Struct spec validation failed: %s", msg)
                    spec_validation_error = msg
                    spec_valid = False
            else:
                logger.warning(
                    "Struct %s: SPEC block not found in LLM output",
                    struct_union.name,
                )
                spec_validation_error = "SPEC block missing in LLM output"
                spec_valid = False
        except Exception as e:
            logger.warning("Struct spec staging skipped: %s", e)
            spec_validation_error = str(e)

        if not spec_valid:
            if spec_tmp_dir:
                shutil.rmtree(spec_tmp_dir, ignore_errors=True)
            error_detail = spec_validation_error or "Struct SPEC missing or invalid"
            error_message = f"Struct SPEC invalid: {error_detail}"
            logger.error("%s", error_message)
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
                error_spec=raw_struct_spec,
            )

        # Determine idiomatic type name and ensure Debug derive for struct-like outputs
        idiomatic_struct_name = struct_union.name
        idiomatic_kind = "struct"
        if spec_obj_parsed:
            candidate = spec_obj_parsed.get("i_type")
            if isinstance(candidate, str) and candidate.strip():
                idiomatic_struct_name = candidate.strip()
            kind_candidate = spec_obj_parsed.get("i_kind")
            if isinstance(kind_candidate, str) and kind_candidate.strip():
                idiomatic_kind = kind_candidate.strip().lower()
        else:
            cached = self._load_struct_name_map().get(struct_union.name)
            if isinstance(cached, str) and cached.strip():
                idiomatic_struct_name = cached.strip()

        if idiomatic_struct_name == "":
            idiomatic_struct_name = struct_union.name

        if idiomatic_kind != "enum":
            derive_applied = False
            candidate_order = []
            for cand in (idiomatic_struct_name, struct_union.name):
                if cand not in candidate_order:
                    candidate_order.append(cand)
            for candidate in candidate_order:
                try:
                    struct_result = rust_ast_parser.add_derive_to_struct_union(
                        struct_result, candidate, "Debug")
                    derive_applied = True
                    idiomatic_struct_name = candidate
                    break
                except Exception:
                    continue
            if not derive_applied:
                error_message = (
                    "Error: Failed to add Debug trait to the struct; please check if the struct has a valid definition"
                )
                logger.error("%s", error_message)
                self.append_failure_info(
                    struct_union.name, "COMPILE_ERROR", error_message, llm_raw
                )
                return self._translate_struct_impl(
                    struct_union,
                    verify_result=(VerifyResult.COMPILE_ERROR, error_message),
                    error_translation=llm_raw,
                    attempts=attempts+1
                )

        all_dependency_code: dict[str, str] = {}
        all_dependency_code.update(dependencies_code)
        all_dependency_code.update(enum_dependency_code)

        result = self.verifier.verify_struct(
            struct_union,
            struct_result,
            all_dependency_code,
            idiomatic_name=idiomatic_struct_name,
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
                attempts=attempts + 1,
                error_spec=raw_struct_spec,
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
                attempts=attempts + 1,
                error_spec=raw_struct_spec,
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
            return self._translate_struct_impl(
                struct_union,
                verify_result=result,
                error_translation=struct_result,
                attempts=attempts + 1,
                error_spec=raw_struct_spec,
            )
        elif result[0] != VerifyResult.SUCCESS:
            raise NotImplementedError(
                f'error type {result[0]} not implemented')
        
        if not spec_pre_saved and spec_tmp_path and raw_struct_spec:
            try:
                save_spec(final_spec_base, "struct",
                          struct_union.name, raw_struct_spec)
                spec_pre_saved = True
            except Exception as e:
                logger.error("Struct spec final save failed: %s", e)
        if not spec_pre_saved and os.path.exists(final_spec_path):
            try:
                os.remove(final_spec_path)
            except OSError:
                pass
        if spec_tmp_dir:
            shutil.rmtree(spec_tmp_dir, ignore_errors=True)

        # Update idiomatic name mapping
        if idiomatic_struct_name:
            try:
                mapping_dir = os.path.join(final_spec_base, "specs")
                os.makedirs(mapping_dir, exist_ok=True)
                mapping_path = self._struct_name_map_path
                mapping_data = {}
                if os.path.exists(mapping_path):
                    with open(mapping_path, "r") as _mf:
                        try:
                            mapping_data = json.load(_mf)
                        except Exception:
                            mapping_data = {}
                mapping_data[struct_union.name] = idiomatic_struct_name
                with open(mapping_path, "w") as _mf:
                    json.dump(mapping_data, _mf, indent=2)
                self._struct_name_map_cache = mapping_data
            except Exception as e:
                logger.warning("Struct name mapping update skipped: %s", e)

        # Save the results
        self.mark_translation_success("struct", struct_union.name)
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
        error_spec=None,
    ) -> TranslateResult:

        function_save_path = os.path.join(
            self.translated_function_path, function.name + ".rs")
        # Always initialize failure_info, even if already translated
        self.init_failure_info("function", function.name)
        if os.path.exists(function_save_path):
            logger.info("Function %s already translated", function.name)
            # Mark as success for this run so the new failure_info.json is populated
            self.mark_translation_success("function", function.name)
            return TranslateResult.SUCCESS

        if attempts > self.max_attempts - 1:
            logger.error(
                "Failed to translate function %s after %d attempts",
                function.name,
                self.max_attempts,
            )
            return TranslateResult.MAX_ATTEMPTS_EXCEEDED
        logger.info("Translating function: %s (attempts: %d)", function.name, attempts)
        self.failure_info_set_attempts(function.name, attempts + 1)

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
                # Use Rust parser to properly extract type and name, avoiding issues with values containing special characters
                try:
                    type_and_name = rust_ast_parser.get_value_type_name(code_of_global_var, global_var.name)
                except Exception as e:
                    # Fallback to old method if parsing fails
                    logger.warning(
                        "Failed to parse global variable %s with Rust parser: %s. Using fallback method.",
                        global_var.name,
                        e,
                    )
                    type_and_name = f"{code_of_global_var.rsplit('=')[0]};"
                used_global_vars[global_var.name] = code_of_global_var
                used_global_vars_only_type_and_names[global_var.name] = type_and_name

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
            msg = f"Error: Function {function.name} is not translated into unidiomatic Rust yet"
            if self.continue_run_when_incomplete:
                self.append_failure_info(
                    function.name,
                    "NO_UNIDIOMATIC_CODE_ERROR",
                    msg,
                    ""
                )
                logger.warning(msg)
                return TranslateResult.NO_UNIDIOMATIC_CODE
            else:
                raise RuntimeError(msg)

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
            joint_used_global_vars_only_type_and_names = '\n'.join(used_global_vars_only_type_and_names.values())
            prompt += f'''
The function uses the following const global variables, whose types and names are (you should **NOT** define or declare them in your translation, as the system will automatically define them. But you can access these global variables):
```rust
{joint_used_global_vars_only_type_and_names}
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
'''
        prompt += "\nFew-shot examples (each with unidiomatic Rust signature, idiomatic Rust signature, and the SPEC):"
        for example in FUNCTION_FEWSHOTS:
            prompt += f"""

{example.label}:
{example.description}
Unidiomatic Rust:
```rust
{example.unidiomatic}
```
Idiomatic Rust:
```rust
{example.idiomatic}
```
----SPEC----
```json
{example.spec}
```
----END SPEC----
"""

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

        elif verify_result[0] == VerifyResult.TEST_HARNESS_MAX_ATTEMPTS_EXCEEDED:
            harness_log = verify_result[1] if verify_result[1] else "(harness generator produced no log)"
            prompt += f'''
Lastly, the function is translated as:
```rust
{error_translation}
```
The SPEC is translated as:
```json
{error_spec}
```

Test harness failed to generate after repeated attempts.
Harness generator output:
```
{harness_log}
```
This may indicate the SPEC is inconsistent with the function implementation,
please analyze the possible reasons, try to fix it this time.
'''

        elif verify_result[0] in (
            VerifyResult.TEST_ERROR,
            VerifyResult.TEST_TIMEOUT,
        ):
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
            logger.error("%s", error_message)
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
            logger.error("%s", error_message)
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
                    logger.error("%s", error_message)
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
                logger.error("%s", error_message)
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

        # Stage SPEC (with idiomatic name) before verification so harness generation can see it
        spec_tmp_dir: Optional[str] = None
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
                        save_spec(
                            final_spec_base,
                            "function",
                            function.name,
                            spec_json_to_save,
                        )
                        spec_pre_saved = True
                    else:
                        logger.error("Function spec validation failed: %s", msg)
                else:
                    logger.warning(
                        "Function %s: SPEC block not found in LLM output",
                        function.name,
                    )
            except Exception as e:
                logger.warning("Function spec staging skipped: %s", e)
        
        try:
            result = self.verifier.verify_function(
                function,
                function_code=function_result,
                data_type_code=data_type_code,
                function_dependencies_code=all_dependency_functions_code,
                unidiomatic_signature=undiomantic_function_signature,
                prefix=False,  # TODO: check here
            )
        except Exception as e:
            self.append_failure_info(
                function.name, "COMPILE_ERROR", str(e), function_result
            )
            # TODO: assign a new error code instead of compile_error?
            result2 = (VerifyResult.COMPILE_ERROR, str(e))
            return self._translate_function_impl(
                function,
                result2,
                error_translation=function_result,
                attempts=attempts+1
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
                return self._translate_function_impl(
                    function,
                    verify_result=result,
                    error_translation=function_result,
                    attempts=attempts + 1,
                    error_spec=spec_json_to_save
                )
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
                logger.error("Function spec final save failed: %s", e)
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
                logger.warning("Function name mapping update skipped: %s", e)

        # save code
        self.mark_translation_success("function", function.name)
        utils.save_code(
            f"{self.translated_function_path}/{function.name}.rs", function_result)

        return TranslateResult.SUCCESS
