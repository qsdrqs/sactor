import json, subprocess
import os
from abc import ABC, abstractmethod
from typing import Optional

from sactor import utils
from sactor.c_parser import CParser, FunctionInfo, StructInfo, GlobalVarInfo, EnumInfo
from sactor.llm import LLM
from sactor.verifier import VerifyResult

from .translator_types import TranslateResult


class Translator(ABC):
    def __init__(self, llm: LLM, c_parser: CParser, config, result_path=None):
        self.llm = llm
        self.config = config
        self.max_attempts = config['general']['max_translation_attempts']
        self.c_parser = c_parser
        self.failure_info = {}
        if result_path:
            self.result_path = result_path
        else:
            self.result_path = os.path.join(
                utils.find_project_root(), 'result')
        self.failure_info_path = os.path.join(
            self.result_path, "general_failure_info.json")

    def translate_struct(self, struct_union: StructInfo) -> TranslateResult:
        self.failure_info_add_attempts_element(struct_union.name, "struct")
        res = self._translate_struct_impl(struct_union)
        self.save_failure_info(self.failure_info_path)
        return res

    @abstractmethod
    def _translate_enum_impl(
        self,
        enum: EnumInfo,
        verify_result: tuple[VerifyResult, Optional[str]] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslateResult:
        pass

    @abstractmethod
    def _translate_global_vars_impl(
        self,
        global_var: GlobalVarInfo,
        verify_result: tuple[VerifyResult, Optional[str]] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslateResult:
        pass

    @abstractmethod
    def _translate_struct_impl(
        self,
        struct_union: StructInfo,
        verify_result: tuple[VerifyResult, Optional[str]] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslateResult:
        pass

    def translate_function(self, function: FunctionInfo) -> TranslateResult:
        self.failure_info_add_attempts_element(function.name, "function")
        res = self._translate_function_impl(function)
        self.save_failure_info(self.failure_info_path)
        return res

    @abstractmethod
    def _translate_function_impl(
        self,
        function: FunctionInfo,
        verify_result: tuple[VerifyResult, Optional[str]] = (
            VerifyResult.SUCCESS, None),
        error_translation=None,
        attempts=0,
    ) -> TranslateResult:
        pass

    def append_failure_info(self, item, error_type, error_message, error_translation):
        self.failure_info[item]["errors"].append({
            "type": error_type,
            "message": error_message,
            "translation": error_translation
        })
        self.failure_info[item]['status'] = "failure"
        self.save_failure_info(self.failure_info_path)

    def init_failure_info(self, type, item):
        if item not in self.failure_info:
            # TODO: fix failure_info keys to be unique
            # Currently we use item name as key,
            # but a function and a struct can have the same name
            # and overwrite each other.
            self.failure_info[item] = {
                "type": type,
                "errors": [],
                "status": "untranslated",
                # number of attempts
                # each element is the total attempts in each run (when running sactor many times)
                "attempts": [] 
            }
            self.save_failure_info(self.failure_info_path)

    def failure_info_add_attempts_element(self, item: str, ty: str):
        self.init_failure_info(ty, item)
        self.failure_info[item]['attempts'].append(0)
        self.save_failure_info(self.failure_info_path)

    def failure_info_set_attempts(self, item, attempts):
        self.failure_info[item]['attempts'][-1] = attempts
        self.save_failure_info(self.failure_info_path)

    def save_failure_info(self, path):
        if self.failure_info == {}:
            return
        # write into json format
        os.makedirs(os.path.dirname(path), exist_ok=True)
        utils.try_backup_file(path)
        with open(path, 'w') as f:
            json.dump(self.failure_info, f, indent=4)

    def has_dependencies_all_translated(self, cursor, dependencies_mapping, ty="function"):
        ty_dir = ty + "s"
        result_path = os.path.join(self.result_path, self.base_name, ty_dir, f'{dep.name}.rs')
        for dep in dependencies_mapping(cursor):
            if not os.path.isfile(result_path):
                return False
        return True

    def print_result_summary(self, title: str):
        def count_success(ctype: str) -> int:
            v = sum([1 if v['type'] == ctype and v['status'] == 'success' else 0 for v in self.failure_info.values() ])
            return v

        print(f"{title} translation result summary:")
        print(f"Functions: successfully translated {count_success("function")} out of {len(self.c_parser.get_functions())} in total")
        print(f"Structs or Unions: successfully translated {count_success("struct")} out of {len(self.c_parser.get_structs())} in total")
