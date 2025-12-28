import os, json
from ctypes import c_buffer
from typing import Any, Optional, override

import sactor.translator as translator
import sactor.verifier as verifier
from sactor import logging as sactor_logging, rust_ast_parser, utils
from sactor.utils import read_file
from sactor.c_parser import (CParser, EnumInfo, EnumValueInfo, FunctionInfo,
                             GlobalVarInfo, StructInfo)
from sactor.combiner import RustCode
from sactor.data_types import DataType
from sactor.llm import LLM
from sactor.verifier import VerifyResult

from .translator import Translator
from .translator_types import TranslateResult, TranslationOutcome
from ..combiner.rust_code import RustCode

logger = sactor_logging.get_logger(__name__)

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
        link_args: list[str] | None = None,
        compile_commands_file: str | None = None,
        entry_tu_file: str | None = None,
        link_closure: list[str] | None = None,
        project_usr_to_result_dir: dict[str, str] | None = None,
        project_struct_usr_to_result_dir: dict[str, str] | None = None,
        project_enum_usr_to_result_dir: dict[str, str] | None = None,
        project_global_usr_to_result_dir: dict[str, str] | None = None,
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
        self._failure_info_backup_prepared = False

        self.c2rust_translation = c2rust_translation
        base_name = "translated_code_unidiomatic"
        self.base_name = base_name
        self.translated_struct_path = os.path.join(
            self.result_path, base_name, "structs")
        self.translated_global_var_path = os.path.join(
            self.result_path, base_name, "global_vars")
        self.translated_enum_path = os.path.join(
            self.result_path, base_name, "enums")
        self.translated_function_path = os.path.join(
            self.result_path, base_name, "functions")
        self.fallback_c2rust = config['general']['unidiomatic_fallback_c2rust']
        self.fallback_c2rust_fix_attempts = config['general']['unidiomatic_fallback_c2rust_fix_attempts']
        self.verifier = verifier.UnidiomaticVerifier(
            test_cmd_path,
            config=config,
            build_path=build_path,
            extra_compile_command=extra_compile_command,
            executable_object=executable_object,
            processed_compile_commands=processed_compile_commands,
            link_args=link_args or [],
            compile_commands_file=compile_commands_file or "",
            entry_tu_file=entry_tu_file,
            link_closure=link_closure or [],
        )
        # Project-wide artifact index for precise dependency checks
        self.project_usr_to_result_dir = project_usr_to_result_dir or {}
        self.project_struct_usr_to_result_dir = project_struct_usr_to_result_dir or {}
        self.project_enum_usr_to_result_dir = project_enum_usr_to_result_dir or {}
        self.project_global_usr_to_result_dir = project_global_usr_to_result_dir or {}

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
        # Always initialize failure_info, even if already translated
        self.init_failure_info("enum", enum.name)
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
            if not self.fallback_c2rust:
                return TranslateResult.MAX_ATTEMPTS_EXCEEDED

            # fallback to c2rust
            logger.warning("Falling back to c2rust implementation for enum %s", enum.name)
            try:
                enum_result = rust_ast_parser.get_enum_definition(
                    self.c2rust_translation, enum.name)
            except Exception as e:
                error_message = (
                    f"Failed to extract enum {enum.name} from c2rust output: {e}")
                logger.error("%s", error_message)
                self.append_failure_info(
                    enum.name, "FALLBACK_ERROR", error_message, "")
                return TranslateResult.MAX_ATTEMPTS_EXCEEDED

            enum_result = rust_ast_parser.unidiomatic_types_cleanup(enum_result)
            result = self.verifier.try_compile_rust_code(enum_result)
            count = 0
            last_error_message = ""
            last_error_translation = ""
            while result[0] != VerifyResult.SUCCESS:
                count += 1
                if count > self.fallback_c2rust_fix_attempts:
                    self.append_failure_info(
                        enum.name, "FALLBACK_ERROR", "Failed to fix the enum using LLM", enum_result)
                    return TranslateResult.MAX_ATTEMPTS_EXCEEDED
                fix_prompt = f'''
The enum is translated as:
```rust
{enum_result}
```
It failed to compile with the following error message:
```
{result[1]}
```
Try to fix the error and provide a new version of the enum. Remember to keep the equivalence as much as possible.
Output the fixed enum into this format (wrap with the following tags):

----ENUM----
```rust
// Your translated enum here
```
----END ENUM----
'''
                if last_error_translation:
                    fix_prompt += f'''
The last time, the enum is fixed as:
```rust
{last_error_translation}
```
It failed to compile with the following error message:
```
{last_error_message}
```
Try to fix again.
'''

                logger.info("Fixing enum %s using LLM (attempt %d)", enum.name, count)
                fix_result = self.llm.query(fix_prompt)
                try:
                    llm_result = utils.parse_llm_result(fix_result, "enum")
                    enum_result = llm_result["enum"]
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
                    last_error_message = error_message
                    last_error_translation = fix_result
                    continue
                result = self.verifier.try_compile_rust_code(enum_result)
                if result[0] != VerifyResult.SUCCESS:
                    if result[0] == VerifyResult.COMPILE_ERROR:
                        last_error_message = result[1]
                        last_error_translation = enum_result
                    continue
                else:
                    break

            self._record_outcome("enum", enum.name, TranslationOutcome.FALLBACK_C2RUST)
            utils.save_code(enum_save_path, enum_result)
            return TranslateResult.SUCCESS

        logger.info("Translating enum: %s (attempts: %d)", enum.name, attempts)
        self.failure_info_set_attempts(enum.name, attempts + 1)

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
                error_translation=result,
                attempts=attempts+1
            )

        logger.debug("Translated enum for %s:", enum.name)
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

        enum_result = rust_ast_parser.unidiomatic_types_cleanup(
            enum_result)
        self.mark_translation_success("enum", enum.name)
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
        enum_dependency_code = ""
        enum_prompt_text = ""

        def return_result(global_var_result, verification=True):
            #remove mut from the binding pattern. Sometimes c2rust translates C `const` variables into Rust `static mut` variables, which is wrong
            if global_var.is_const:
                global_var_result = rust_ast_parser.remove_mut_from_type_specifiers(global_var_result, global_var.name)
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
            logger.debug("Translated global variable %s:", global_var.name)
            logger.debug("%s", global_var_result)
            if verification:
                # TODO: may add verification here
                compile_code = global_var_result
                if enum_dependency_code:
                    compile_code = f"{enum_dependency_code}\n{global_var_result}"
                try:
                    result = self.verifier.try_compile_rust_code(compile_code)
                except Exception as e:
                    error_message = f"Error: Syntax error in the translated code: {e}"
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
            self.mark_translation_success("global_var", global_var.name)
            utils.save_code(global_var_save_path, global_var_result)
            return TranslateResult.SUCCESS

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
            enum_names: list[str] = []
            for enum_val in used_enum_values:
                enum_names.append(enum_val.name)
                enum_defs_map[enum_val.definition.name] = enum_val.definition
            for enum_def in used_enum_defs:
                enum_names.append(enum_def.name)
                enum_defs_map[enum_def.name] = enum_def

            enum_defs_in_order = [enum_defs_map[name]
                                  for name in sorted(enum_defs_map.keys())]
            rust_enum_codes: list[str] = []
            c_enum_codes: list[str] = []
            for enum_def in enum_defs_in_order:
                enum_translation_res = self._translate_enum_impl(enum_def)
                if enum_translation_res != TranslateResult.SUCCESS:
                    return enum_translation_res
                enum_code_path = os.path.join(
                    self.translated_enum_path, enum_def.name + ".rs")
                rust_enum_codes.append(read_file(enum_code_path))
                c_enum_codes.append(
                    self.c_parser.extract_enum_definition_code(enum_def.name))

            enum_dependency_code = "\n\n".join(rust_enum_codes)
            unique_enum_names = list(dict.fromkeys(enum_names))
            enums_in_prompt = "\n".join(unique_enum_names)
            enums_c_code = "\n".join(c_enum_codes)
            enum_prompt_text = f'''
The global variable uses the following enums:
```c
{enums_in_prompt}
```
In C, they are defined as:
```c
{enums_c_code}
```
These enums are already translated to Rust as:
```rust
{enum_dependency_code}
```
Directly use these enums in your translation and do **NOT** redefine them.
'''

        if attempts > self.max_attempts - 1:
            # fallback
            logger.warning(
                "Failed to translate global variable %s after %d attempts using LLM; falling back to c2rust",
                global_var.name,
                self.max_attempts,
            )
            result = rust_ast_parser.get_static_item_definition(self.c2rust_translation, global_var.name)
            return return_result(result, verification=False)

        logger.info(
            "Translating global variable: %s (attempts: %d)",
            global_var.name,
            attempts,
        )
        self.failure_info_set_attempts(global_var.name, attempts + 1)
        # Prefer translating a definition when present (even if not const),
        # otherwise fall back to an extern declaration.
        # We detect a definition heuristically by checking if the extracted
        # code snippet contains an initializer ('='). This covers patterns like
        # `T GLOBAL = { ... };` which must be defined on the Rust side
        # since the original C definition moves into Rust.
        code_of_global_var_def = None
        try:
            code_of_global_var_def = self.c_parser.extract_global_var_definition_code(
                global_var.name)
        except Exception:
            code_of_global_var_def = None

        has_initializer = False
        if code_of_global_var_def is not None:
            # crude but effective: check for '=' in the definition span
            has_initializer = '=' in code_of_global_var_def

        if global_var.is_const or has_initializer:
            code_of_global_var = code_of_global_var_def or self.c_parser.extract_global_var_definition_code(
                global_var.name)
            if len(code_of_global_var) >= self.const_global_max_translation_len:
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
The global variable is an array with size {global_var.array_size}. Use `static` as the specifier in Rust.
'''
        else:
            code_of_global_var = global_var.get_decl()
            prompt = f'''
Use `extern "C"` wrap the following C global variable without defining the value, keep the upper/lower case of the global variable name.
```c
{code_of_global_var}
```
'''

        if enum_prompt_text:
            prompt += f"\n{enum_prompt_text}\n"

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
        # If already translated on disk, mark success and skip re-generation
        struct_path = os.path.join(self.translated_struct_path, struct_union.name + ".rs")
        if os.path.exists(struct_path):
            logger.info("Struct/Union %s already translated", struct_union.name)
            self.mark_translation_success("struct", struct_union.name)
            return TranslateResult.SUCCESS
        for struct in struct_union_dependencies:
            self.translate_struct(struct)
        self.failure_info_set_attempts(struct_union.name, attempts + 1)

        enum_dependencies = {}
        for enum_val in getattr(struct_union, "enum_value_dependencies", []):
            enum_dependencies[enum_val.definition.name] = enum_val.definition
        for enum_def in getattr(struct_union, "enum_dependencies", []):
            enum_dependencies[enum_def.name] = enum_def
        for enum_def in enum_dependencies.values():
            self._translate_enum_impl(enum_def)

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
        rust_s_u = rust_ast_parser.unidiomatic_types_cleanup(rust_s_u)

        self.mark_translation_success("struct", struct_union.name)
        # Save the translated struct/union
        utils.save_code(
            f'{self.translated_struct_path}/{struct_union.name}.rs', rust_s_u)

        return TranslateResult.SUCCESS

    def _prepare_function_context(
        self, function: FunctionInfo
    ) -> tuple[TranslateResult, Optional[dict[str, Any]]]:
        macro_definitions = self.c_parser.get_macro_definitions_for_function(function.name)
        function_dependencies = function.function_dependencies
        function_name_dependencies = [f.name for f in function_dependencies]

        function_depedency_signatures: list[str] = []
        all_uses: list[str] = []

        for dep in function_dependencies:
            dep_name = dep.name
            if dep_name == function.name:
                continue
            # Prefer local TU output
            translated_path = os.path.join(self.translated_function_path, f"{dep_name}.rs")
            if not os.path.exists(translated_path):
                # Cross-TU: resolve via project index (usr -> result_dir)
                owner_dir = None
                try:
                    usr = getattr(dep, 'usr', None)
                except Exception:
                    usr = None
                if usr and getattr(self, 'project_usr_to_result_dir', None):
                    owner_dir = self.project_usr_to_result_dir.get(usr)
                if owner_dir:
                    candidate = os.path.join(owner_dir, self.base_name, 'functions', f'{dep_name}.rs')
                    if os.path.exists(candidate):
                        translated_path = candidate
            if not os.path.exists(translated_path):
                raise RuntimeError(
                    f"Error: Dependency {dep_name} of function {function.name} is not translated yet")

            code = utils.read_file(translated_path)
            function_signatures = rust_ast_parser.get_func_signatures(code)
            function_use = RustCode(code).used_code_list
            all_uses += function_use

            lookup_name = dep_name
            if dep_name in translator.RESERVED_KEYWORDS:
                lookup_name = dep_name + "_"
            function_depedency_signatures.append(function_signatures[lookup_name] + ';')

        # Deduplicate dependency signatures and uses
        if function_depedency_signatures:
            seen_sigs = set()
            unique_sigs = []
            for sig in function_depedency_signatures:
                if sig not in seen_sigs:
                    seen_sigs.add(sig)
                    unique_sigs.append(sig)
            function_depedency_signatures = unique_sigs
        function_dependency_uses = all_uses

        structs_in_function = list(function.struct_dependencies)
        for func_dep in function_dependencies:
            structs_in_function.extend(func_dep.struct_dependencies)

        code_of_structs_full: dict[str, str] = {}
        code_of_structs_prompt: dict[str, str] = {}
        visited_structs: set[str] = set()
        code_of_enum: dict[Any, str] = {}
        used_enum_names: list[str] = []
        for struct in structs_in_function:
            all_structs = self.c_parser.retrieve_all_struct_dependencies(struct)
            for struct_name in all_structs:
                if struct_name in visited_structs:
                    continue
                struct_path = os.path.join(
                    self.translated_struct_path, f"{struct_name}.rs")
                if not os.path.exists(struct_path):
                    result = self.translate_struct(
                        self.c_parser.get_struct_info(struct_name)
                    )
                    if result != TranslateResult.SUCCESS:
                        return result, None
                if not os.path.exists(struct_path):
                    raise RuntimeError(
                        f"Error: Struct {struct_name} translation failed.")
                code_of_struct = utils.read_file(struct_path)
                try:
                    code_of_struct = rust_ast_parser.unidiomatic_types_cleanup(
                        code_of_struct
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to normalize struct %s code: %s",
                        struct_name,
                        exc,
                    )
                code_of_structs_full[struct_name] = code_of_struct
                try:
                    prompt_snippet = rust_ast_parser.strip_to_struct_items(
                        code_of_struct
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to strip struct prompt for %s: %s",
                        struct_name,
                        exc,
                    )
                    prompt_snippet = code_of_struct
                code_of_structs_prompt[struct_name] = prompt_snippet
                visited_structs.add(struct_name)

                struct_info = self.c_parser.get_struct_info(struct_name)
                collected_enum_defs = list(getattr(struct_info, "enum_dependencies", []))
                for enum_val in getattr(struct_info, "enum_value_dependencies", []):
                    collected_enum_defs.append(enum_val.definition)

                for enum_def in collected_enum_defs:
                    if enum_def not in code_of_enum:
                        self._translate_enum_impl(enum_def)
                        code_path = os.path.join(
                            self.translated_enum_path, enum_def.name + ".rs")
                        code_of_enum[enum_def] = read_file(code_path)
                    if enum_def.name not in used_enum_names:
                        used_enum_names.append(enum_def.name)

        used_global_vars: dict[str, str] = {}
        used_global_vars_only_type_and_names: dict[str, str] = {}
        used_global_var_nodes = function.global_vars_dependencies
        for global_var in used_global_var_nodes:
            if (
                global_var.node.location is not None
                and global_var.node.location.file.name
                != function.node.location.file.name
            ):
                continue
            global_var_res = self._translate_global_vars_impl(global_var)
            if global_var_res != TranslateResult.SUCCESS:
                return global_var_res, None
            code_path = os.path.join(
                self.translated_global_var_path, f"{global_var.name}.rs")
            code_of_global_var = read_file(code_path)
            try:
                type_and_name = rust_ast_parser.get_value_type_name(
                    code_of_global_var, global_var.name)
            except Exception as e:
                logger.warning(
                    "Failed to parse global variable %s with Rust parser: %s. Using fallback method.",
                    global_var.name,
                    e,
                )
                type_and_name = f"{code_of_global_var.rsplit('=')[0]};"
            used_global_vars[global_var.name] = code_of_global_var
            used_global_vars_only_type_and_names[global_var.name] = type_and_name

        used_stdio = function.stdio_list
        used_stdio_code = ""
        if len(used_stdio) > 0:
            used_stdio_code = 'extern "C" {\n'
            for stdio in used_stdio:
                used_stdio_code += f"    static mut {stdio}: *mut libc::FILE;\n"
            used_stdio_code += "}\n"

        used_enum_values: list[EnumValueInfo] = function.enum_values_dependencies
        used_enum_definitions = function.enum_dependencies
        if len(used_enum_values) > 0 or len(used_enum_definitions) > 0:
            enum_definitions = set()
            for enum in used_enum_values:
                if enum.name not in used_enum_names:
                    used_enum_names.append(enum.name)
                enum_definitions.add(enum.definition)

            for enum_def in used_enum_definitions:
                if enum_def.name not in used_enum_names:
                    used_enum_names.append(enum_def.name)
                enum_definitions.add(enum_def)

            for enum_def in enum_definitions:
                if enum_def not in code_of_enum:
                    self._translate_enum_impl(enum_def)
                    code_path = os.path.join(
                        self.translated_enum_path, enum_def.name + ".rs")
                    code_of_enum[enum_def] = read_file(code_path)

        context: dict[str, Any] = {
            "function_dependencies": function_dependencies,
            "macro_definitions": macro_definitions,
            "function_dependency_signatures": function_depedency_signatures,
            "function_dependency_uses": function_dependency_uses,
            "code_of_structs_full": code_of_structs_full,
            "code_of_structs_prompt": code_of_structs_prompt,
            "used_global_vars": used_global_vars,
            "used_global_vars_only_type_and_names": used_global_vars_only_type_and_names,
            "used_stdio": used_stdio,
            "used_stdio_code": used_stdio_code,
            "code_of_enum": code_of_enum,
            "used_enum_names": used_enum_names,
        }

        return TranslateResult.SUCCESS, context

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
            logger.info("Function %s already translated", function.name)
            # Mark as success for this run so the new failure_info.json is populated
            self.mark_translation_success("function", function.name)
            return TranslateResult.SUCCESS

        prepare_status, func_ctx = self._prepare_function_context(function)
        if prepare_status != TranslateResult.SUCCESS or func_ctx is None:
            return prepare_status

        function_dependencies = func_ctx["function_dependencies"]
        macro_definitions: list[str] = func_ctx["macro_definitions"]
        function_depedency_signatures: list[str] = func_ctx["function_dependency_signatures"]
        function_dependency_uses: list[str] = func_ctx["function_dependency_uses"]
        code_of_structs_full: dict[str, str] = func_ctx["code_of_structs_full"]
        code_of_structs_prompt: dict[str, str] = func_ctx["code_of_structs_prompt"]
        used_global_vars: dict[str, str] = func_ctx["used_global_vars"]
        used_global_vars_only_type_and_names: dict[str, str] = func_ctx["used_global_vars_only_type_and_names"]
        used_stdio: list[str] = func_ctx["used_stdio"]
        used_stdio_code: str = func_ctx["used_stdio_code"]
        code_of_enum: dict[Any, str] = func_ctx["code_of_enum"]
        used_enum_names: list[str] = func_ctx["used_enum_names"]

        if attempts > self.max_attempts - 1:
            logger.error(
                "Failed to translate function %s after %d attempts",
                function.name,
                self.max_attempts,
            )
            if not self.fallback_c2rust:
                return TranslateResult.MAX_ATTEMPTS_EXCEEDED

            # fallback to c2rust
            logger.warning("Falling back to c2rust implementation for function %s", function.name)
            try:
                function_result = rust_ast_parser.get_function_definition(
                    self.c2rust_translation, function.name)
            except Exception as e:
                error_message = (
                    f"Failed to extract function {function.name} from c2rust output: {e}")
                logger.error("%s", error_message)
                self.append_failure_info(
                    function.name, "FALLBACK_ERROR", error_message, "")
                return TranslateResult.MAX_ATTEMPTS_EXCEEDED

            function_result = rust_ast_parser.unidiomatic_function_cleanup(
                function_result)

            def verify_candidate(candidate_code: str) -> tuple[tuple[VerifyResult, Optional[str]], str]:
                processed_code = candidate_code
                try:
                    processed_code = rust_ast_parser.expand_use_aliases(processed_code)
                except Exception as e:
                    error_message = (
                        f"Error: Syntax error in the translated code when processing use statements: {e}")
                    logger.error("%s", error_message)
                    return (VerifyResult.COMPILE_ERROR, error_message), processed_code

                try:
                    function_result_sigs = rust_ast_parser.get_func_signatures(
                        processed_code)
                except Exception as e:
                    error_message = f"Error: Syntax error in the translated code: {e}"
                    logger.error("%s", error_message)
                    return (VerifyResult.COMPILE_ERROR, error_message), processed_code

                prefix = False
                if function.name not in function_result_sigs:
                    if function.name in translator.RESERVED_KEYWORDS:
                        name_prefix = function.name + "_"
                        if name_prefix in function_result_sigs:
                            prefix = True
                        else:
                            error_message = f"Function {name_prefix} not found in the translated code"
                            return (VerifyResult.COMPILE_ERROR, error_message), processed_code
                    else:
                        error_message = (
                            f"Error: Function signature not found in the translated code for function `{function.name}`. Got functions: {list(function_result_sigs.keys())}, check if you have the correct function name., you should **NOT** change the camel case to snake case and vice versa.")
                        return (VerifyResult.COMPILE_ERROR, error_message), processed_code

                data_type_code = code_of_structs_full | used_global_vars | code_of_enum | {
                    "stdio": used_stdio_code}
                verification = self.verifier.verify_function(
                    function,
                    function_code=processed_code,
                    data_type_code=data_type_code,
                    function_dependency_signatures=function_depedency_signatures,
                    function_dependency_uses=function_dependency_uses,
                    has_prefix=prefix,
                )
                return verification, processed_code

            verification, function_result = verify_candidate(function_result)
            count = 0
            last_error_message = ""
            last_error_translation = ""
            while verification[0] != VerifyResult.SUCCESS:
                count += 1
                if count > self.fallback_c2rust_fix_attempts:
                    self.append_failure_info(
                        function.name,
                        "FALLBACK_ERROR",
                        "Failed to fix the function using LLM",
                        function_result,
                    )
                    return TranslateResult.MAX_ATTEMPTS_EXCEEDED
                fix_prompt = f'''
The function is translated as:
```rust
{function_result}
```
It failed to compile with the following error message:
```
{verification[1]}
```
Try to fix the error and provide a new version of the function. Remember to keep the equivalence as much as possible.
Usually this is caused by missing proper `use` statements.
**DO NOT** add any extra function/struct dependencies or change the code structure, only fix the code to make it compile.

Output the fixed function into this format (wrap with the following tags):
----FUNCTION----
```rust
// Your translated function here
```
----END FUNCTION----
'''
                if last_error_translation:
                    fix_prompt += f'''
The last time, the function is fixed as:
```rust
{last_error_translation}
```
It failed to compile with the following error message:
```
{last_error_message}
```
Try to fix again.
'''
                logger.info(
                    "Fixing function %s using LLM (attempt %d)", function.name, count)
                fix_result = self.llm.query(fix_prompt)
                try:
                    llm_result = utils.parse_llm_result(fix_result, "function")
                    function_result_candidate = llm_result["function"]
                except Exception as e:
                    error_message = f'''
Error: Failed to parse the result from LLM, result is not wrapped by the tags as instructed. Remember the tag:
----FUNCTION----
```rust
// Your translated function here
```
----END FUNCTION----
'''
                    logger.error("%s", error_message)
                    last_error_message = error_message
                    last_error_translation = fix_result
                    continue

                function_result_candidate = rust_ast_parser.unidiomatic_function_cleanup(
                    function_result_candidate)
                verification, processed_code = verify_candidate(
                    function_result_candidate)
                function_result = processed_code
                if verification[0] != VerifyResult.SUCCESS:
                    last_error_message = verification[1]
                    last_error_translation = function_result
                    continue
                else:
                    break

            self._record_outcome("function", function.name, TranslationOutcome.FALLBACK_C2RUST)
            utils.save_code(function_save_path, function_result)
            return TranslateResult.SUCCESS

        logger.info("Translating function: %s (attempts: %d)", function.name, attempts)
        self.failure_info_set_attempts(function.name, attempts + 1)
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

        if len(macro_definitions) > 0:
            joined_macro_defs = '\n'.join(macro_definitions)
            prompt += f'''
The function body above may reference the following macros. Use these definitions to understand the semantics; do **NOT** redefine them in Rust—expand or replicate their behavior as needed in the translation.
```c
{joined_macro_defs}
```
'''

        if len(code_of_structs_prompt) > 0:
            joint_code_of_structs = '\n'.join(code_of_structs_prompt.values())
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

        if len(used_global_vars) > 0:
            joint_used_global_vars_only_type_and_names = '\n'.join(used_global_vars_only_type_and_names.values())
            prompt += f'''
The function uses the following const global variables, which are already translated. The global variables' types and names are provided below, but the values are omitted.
You should **NOT** define or declare the following global variables in your translation, as the system will automatically define them. But you can access the variables in your translation.
The translated const global variables are:
:
```rust
{joint_used_global_vars_only_type_and_names}
```
'''

        # handle stdio
        if len(used_stdio) > 0:
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
        if len(code_of_enum) > 0:
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
            logger.error("%s", error_message)
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
            logger.error("%s", error_message)
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
                logger.error("%s", error_message)
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
        try:
        # process the function result
        # there may be an Error, so put it in a try block
            function_result = rust_ast_parser.expand_use_aliases(function_result) # remove potentail 'as' in use statements
        except SyntaxError as e:
            error_message = f"Error: Syntax error in the translated code when processing use statements: {e}"
            logger.error("%s", error_message)
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

        logger.debug("Translated function %s:", function.name)
        logger.debug("%s", function_result)

        data_type_code = code_of_structs_full | used_global_vars | code_of_enum | {
            "stdio": used_stdio_code}
        # add error handling because here can raise exceptions
        result = self.verifier.verify_function(
            function,
            function_code=function_result,
            data_type_code=data_type_code,
            function_dependency_signatures=function_depedency_signatures,
            function_dependency_uses=function_dependency_uses,
            has_prefix=prefix
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
        self.mark_translation_success("function", function.name)
        utils.save_code(function_save_path, function_result)
        return TranslateResult.SUCCESS
