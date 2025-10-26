import json
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from sactor import logging as sactor_logging
from sactor import utils
from sactor.c_parser import (CParser, EnumInfo, FunctionInfo, GlobalVarInfo,
                             StructInfo)
from sactor.llm import LLM
from sactor.verifier import VerifyResult

from .translator_types import TranslateResult


logger = sactor_logging.get_logger(__name__)


class Translator(ABC):
    def __init__(self, llm: LLM, c_parser: CParser, config, result_path=None):
        self.llm = llm
        self.config = config
        self.max_attempts = config['general']['max_translation_attempts']
        self.const_global_max_translation_len = int(
            config['general'].get('const_global_max_translation_len', 2048)
        )
        self.c_parser = c_parser
        self.failure_info = {}
        if result_path:
            self.result_path = result_path
        else:
            self.result_path = os.path.join(
                utils.find_project_root(), 'result')
        self.failure_info_path = os.path.join(
            self.result_path, "general_failure_info.json")
        self._failure_info_backup_prepared = False
        self.translation_status: Dict[str, Dict[str, str]] = defaultdict(dict)
        self._dependency_cache: Dict[Tuple[str, str], str] = {}

    def translate_struct(self, struct_union: StructInfo) -> TranslateResult:
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
        item_type = self.failure_info[item].get("type")
        if item_type:
            self._set_translation_status(item_type, item, "failure")
        self.save_failure_info(self.failure_info_path)

    def init_failure_info(self, type, item):
        if item not in self.failure_info:
            # TODO: fix failure_info keys to be unique
            # Currently we use item name as key,
            # but a function and a struct can have the same name
            # and overwrite each other.

            # TODO: in the future, we may want to reuse previous failure info
            # if the failure_info file already exists.
            self.failure_info[item] = {
                "type": type,
                "errors": [],
                "status": "untranslated",
                # per-run attempt counts; initialise with the current run's slot
                "attempts": [0]
            }
            self.save_failure_info(self.failure_info_path)
        if type and item not in self.translation_status[type]:
            self.translation_status[type][item] = "pending"

    def failure_info_set_attempts(self, item, attempts):
        info = self.failure_info.get(item)
        if info is None:
            raise KeyError(f"Attempting to update attempts for unknown item: {item}")
        if not info['attempts']:
            raise RuntimeError(f"No attempt slot recorded for {item}; ensure init_failure_info was called before failures are recorded.")
        info['attempts'][-1] = attempts
        self.save_failure_info(self.failure_info_path)

    def save_failure_info(self, path):
        if self.failure_info == {}:
            return
        # write into json format
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self.failure_info, f, indent=4)

    def prepare_failure_info_backup(self):
        if self._failure_info_backup_prepared:
            return
        dir_path = os.path.dirname(self.failure_info_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        if os.path.exists(self.failure_info_path):
            utils.try_backup_file(self.failure_info_path)
            # Start fresh for the new run; previous state lives in the backup.
            self.failure_info = {}
        self._failure_info_backup_prepared = True

    def has_dependencies_all_translated(self, cursor, dependencies_mapping):
        ready, _ = self.check_dependencies(cursor, dependencies_mapping)
        return ready

    def check_dependencies(self, cursor, dependencies_mapping) -> tuple[bool, list[dict]]:
        blockers: List[dict] = []
        deps = dependencies_mapping(cursor)
        for dep in deps:
            dep_name = getattr(dep, "name", None)
            if not dep_name:
                continue
            dep_type = self._resolve_dependency_type(dep)
            status = self._get_translation_status(dep_type, dep_name)
            if status == "success":
                continue
            if status in {"failure", "blocked"}:
                blockers.append({
                    "type": dep_type,
                    "name": dep_name,
                    "status": status,
                })
                continue
            if self._dependency_artifact_exists(dep_type, dep_name):
                self._set_translation_status(dep_type, dep_name, "success")
                continue
            blockers.append({
                "type": dep_type,
                "name": dep_name,
                "status": status or "missing",
            })
        return len(blockers) == 0, blockers

    def mark_dependency_block(self, item_type: str, item_name: str, blockers: Sequence[dict]):
        if not blockers:
            return
        self.init_failure_info(item_type, item_name)
        any_failed = any(
            blocker.get("status") in {"failure", "blocked"}
            for blocker in blockers
        )
        status_label = "blocked_by_failed_dependency" if any_failed else "waiting_for_dependency"
        self.failure_info[item_name]['status'] = status_label
        formatted = [{
            "type": blocker.get("type"),
            "name": blocker.get("name"),
            "status": blocker.get("status"),
        } for blocker in blockers]
        self.failure_info[item_name]['blockers'] = formatted
        self._set_translation_status(item_type, item_name, "blocked")

    def mark_translation_success(self, item_type: str, item_name: str):
        self._set_translation_status(item_type, item_name, "success")
        if item_name in self.failure_info:
            self.failure_info[item_name]['status'] = "success"

    def _resolve_dependency_type(self, dep) -> str:
        if isinstance(dep, StructInfo):
            return "struct"
        if isinstance(dep, FunctionInfo):
            return "function"
        if isinstance(dep, GlobalVarInfo):
            return "global_var"
        if isinstance(dep, EnumInfo):
            return "enum"
        return "unknown"

    def _set_translation_status(self, item_type: str, item_name: str, status: str):
        if not item_type:
            return
        self.translation_status[item_type][item_name] = status

    def _get_translation_status(self, item_type: str, item_name: str) -> Optional[str]:
        if not item_type:
            return None
        return self.translation_status.get(item_type, {}).get(item_name)

    def _dependency_artifact_exists(self, item_type: str, item_name: str) -> bool:
        if not item_name:
            return False
        candidate_paths: List[str] = []
        path_attr_map = {
            "struct": "translated_struct_path",
            "function": "translated_function_path",
            "enum": "translated_enum_path",
            "global_var": "translated_global_var_path",
        }
        attr = path_attr_map.get(item_type)
        if attr and hasattr(self, attr):
            base_path = getattr(self, attr)
            if base_path:
                candidate_paths.append(os.path.join(base_path, f"{item_name}.rs"))
        for candidate in candidate_paths:
            if os.path.exists(candidate):
                return True
        cache_key = (item_type, item_name)
        cached = self._dependency_cache.get(cache_key)
        if cached == "exists":
            return True
        if cached == "missing":
            return False
        result = utils.run_command(
            ["find", self.result_path, "-name", f"{item_name}.rs"]
        )
        found = len(result.stdout.strip()) > 0
        self._dependency_cache[cache_key] = "exists" if found else "missing"
        return found

    def print_result_summary(self, title: str):
        def count_success(ctype: str) -> int:
            v = sum([1 if v['type'] == ctype and v['status'] == 'success' else 0 for v in self.failure_info.values() ])
            return v

        logger.info("%s translation result summary:", title)
        logger.info(
            "Functions: successfully translated %d out of %d in total",
            count_success("function"),
            len(self.c_parser.get_functions()),
        )
        logger.info(
            "Structs or Unions: successfully translated %d out of %d in total",
            count_success("struct"),
            len(self.c_parser.get_structs()),
        )
