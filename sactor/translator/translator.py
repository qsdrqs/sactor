import json
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from sactor import logging as sactor_logging
from sactor import utils
from sactor.c_parser import (CParser, EnumInfo, FunctionInfo, GlobalVarInfo,
                             StructInfo)
from sactor.c_parser.refs import FunctionDependencyRef
from sactor.llm import LLM
from sactor.verifier import VerifyResult

from .translator_types import TranslateResult, TranslationOutcome


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
                os.getcwd(), 'sactor_result')
        self.failure_info_path = os.path.join(
            self.result_path, "general_failure_info.json")
        self._failure_info_backup_prepared = False
        self.translation_status: Dict[str, Dict[str, TranslationOutcome]] = defaultdict(dict)
        self._dependency_cache: Dict[Tuple[str, str], bool] = {}

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
        item_type = self.failure_info[item].get("type")
        if item_type:
            self._record_outcome(item_type, item, TranslationOutcome.FAILURE)
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
        # Status is recorded only when we reach a terminal outcome.

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
            # Fast-path: resolve by USR -> TU result dir (project index) for function deps
            if dep_type == "function":
                try:
                    usr = getattr(dep, 'usr', None)
                except Exception:
                    usr = None
                if usr and getattr(self, 'project_usr_to_result_dir', None):
                    owner_dir = self.project_usr_to_result_dir.get(usr)
                    if owner_dir:
                        candidate = os.path.join(owner_dir, 'translated_code_unidiomatic', 'functions', f'{dep_name}.rs')
                        if os.path.exists(candidate):
                            # mark success and continue
                            self._set_translation_status(dep_type, dep_name, TranslationOutcome.SUCCESS)
                            continue
            status = self._get_translation_status(dep_type, dep_name)
            if status in {
                TranslationOutcome.SUCCESS,
                TranslationOutcome.FALLBACK_C2RUST,
            }:
                continue
            if status in {TranslationOutcome.FAILURE, TranslationOutcome.BLOCKED_FAILED}:
                blockers.append({
                    "type": dep_type,
                    "name": dep_name,
                    "status": status.value,
                })
                continue
            if self._dependency_artifact_exists(dep_type, dep_name):
                self._set_translation_status(dep_type, dep_name, TranslationOutcome.SUCCESS)
                continue
            if status is None:
                raise RuntimeError(
                    f"Dependency '{dep_name}' of type '{dep_type}' should have been translated before use."
                )
            blockers.append({
                "type": dep_type,
                "name": dep_name,
                "status": status.value,
            })
        return len(blockers) == 0, blockers

    def mark_dependency_block(self, item_type: str, item_name: str, blockers: Sequence[dict]):
        if not blockers:
            return
        self.init_failure_info(item_type, item_name)
        any_failed = any(
            blocker.get("status") in {
                TranslationOutcome.FAILURE.value,
                TranslationOutcome.BLOCKED_FAILED.value,
            }
            for blocker in blockers
        )
        if any_failed:
            self.failure_info[item_name]['status'] = TranslationOutcome.BLOCKED_FAILED.value
            outcome = TranslationOutcome.BLOCKED_FAILED
        else:
            raise RuntimeError(
                f"mark_dependency_block called without failed dependencies for '{item_name}'."
            )
        formatted = [{
            "type": blocker.get("type"),
            "name": blocker.get("name"),
            "status": blocker.get("status"),
        } for blocker in blockers]
        self.failure_info[item_name]['blockers'] = formatted
        self._set_translation_status(item_type, item_name, outcome)

    def mark_translation_success(self, item_type: str, item_name: str):
        self._record_outcome(item_type, item_name, TranslationOutcome.SUCCESS)
        key = (item_type, item_name)
        self._dependency_cache[key] = True

    def _resolve_dependency_type(self, dep) -> str:
        if isinstance(dep, StructInfo):
            return "struct"
        if isinstance(dep, FunctionInfo):
            return "function"
        # Treat unified function dependency refs as function deps
        try:
            if isinstance(dep, FunctionDependencyRef):
                return "function"
        except Exception:
            pass
        if isinstance(dep, GlobalVarInfo):
            return "global_var"
        if isinstance(dep, EnumInfo):
            return "enum"
        return "unknown"

    def _record_outcome(self, item_type: str, item_name: str, outcome: TranslationOutcome):
        self._set_translation_status(item_type, item_name, outcome)
        if item_name in self.failure_info:
            self.failure_info[item_name]['status'] = outcome.value

    def _set_translation_status(self, item_type: str, item_name: str, status: TranslationOutcome):
        if not item_type:
            return
        self.translation_status[item_type][item_name] = status

    def _get_translation_status(self, item_type: str, item_name: str) -> Optional[TranslationOutcome]:
        if not item_type:
            return None
        return self.translation_status.get(item_type, {}).get(item_name)

    def _dependency_artifact_exists(self, item_type: str, item_name: str) -> bool:
        if not item_name:
            return False

        cache_key = (item_type, item_name)
        cached = self._dependency_cache.get(cache_key)
        if cached is not None:
            return cached

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
                candidate = os.path.join(base_path, f"{item_name}.rs")
                if os.path.exists(candidate):
                    self._dependency_cache[cache_key] = True
                    return True

        # No heuristics: design requires dependency artifacts to exist at precise locations.
        # If not found above, return False and let the caller raise.
        self._dependency_cache[cache_key] = False
        return False

    def _scan_for_artifact(self, item_name: str) -> bool:
        if not os.path.isdir(self.result_path):
            return False
        for root, _, files in os.walk(self.result_path):
            for filename in files:
                if not filename.endswith(".rs"):
                    continue
                stem, _ = os.path.splitext(filename)
                if stem == item_name:
                    return True
        return False

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
