import json
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
        self.max_attempts = config['general']['max_translation_attempts']
        self.c_parser = c_parser
        self.failure_info = {}

        if result_path:
            self.result_path = result_path
        else:
            self.result_path = os.path.join(
                utils.find_project_root(), 'result')

    def translate_struct(self, struct_union: StructInfo) -> TranslateResult:
        return self._translate_struct_impl(struct_union)

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
        return self._translate_function_impl(function)

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

    def append_failure_info(self, item, error_type, error_message):
        self.failure_info[item]["errors"].append({
            "type": error_type,
            "message": error_message
        })

    def init_failure_info(self, type, item):
        if item not in self.failure_info:
            self.failure_info[item] = {
                "type": type,
                "errors": []
            }

    def save_failure_info(self, path):
        if self.failure_info == {}:
            return
        # write into json format
        os.makedirs(os.path.dirname(path), exist_ok=True)
        utils.try_backup_file(path)
        with open(path, 'w') as f:
            json.dump(self.failure_info, f, indent=4)
