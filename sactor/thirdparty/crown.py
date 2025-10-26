import json
import os
import shutil
from enum import Enum, auto
from typing import override

from sactor import logging as sactor_logging
from sactor import utils

from .thirdparty import ThirdParty

CROWN_RUST_VERSION = "nightly-2023-01-26"

logger = sactor_logging.get_logger(__name__)

class CrownType(Enum):
    FUNCTION = auto()
    STRUCT = auto()


class Crown(ThirdParty):
    def __init__(self, build_path=None):
        # check executables
        if not shutil.which("crown"):
            raise OSError("crown executable not found")
        if not shutil.which("rustup"):
            raise OSError("rustup executable not found")

        if build_path:
            self.build_path = build_path
        else:
            tmpdir = utils.get_temp_dir()
            self.build_path = os.path.join(tmpdir, 'build')
        self.analysis_build_path = os.path.join(
            self.build_path, "crown_analysis")
        self.analysis_results_path = os.path.join(
            self.build_path, "crown_analysis_results")

        # Set up environment variables
        result = utils.run_command(
            ['rustc', f'+{CROWN_RUST_VERSION}', '--print', 'sysroot']
        )
        rust_sysroot = result.stdout.strip()
        env = utils.patched_env("LD_LIBRARY_PATH", f'{rust_sysroot}/lib')
        self.env = env

    @staticmethod
    @override
    def check_requirements() -> list[str]:
        result = []
        if not shutil.which("crown"):
            result.append("crown")
        if not shutil.which("rustup"):
            result.append("rustup")
        return result

    def _try_compile_rust(self, path):
        cmd = ['rustup', 'run', f'{CROWN_RUST_VERSION}-x86_64-unknown-linux-gnu',
               'cargo', 'build', '--manifest-path', path]
        result = utils.run_command(cmd, env=self.env)
        return result.returncode == 0

    def analyze(self, target_c2rust_code):
        crown_analysis_lib = "crown_analysis"
        lib_wrapper_code = f'''
extern crate libc;
extern crate core;
pub mod {crown_analysis_lib};
'''
        utils.create_rust_proj(
            lib_wrapper_code, crown_analysis_lib, self.analysis_build_path, is_lib=True)
        with open(os.path.join(self.analysis_build_path, f"src/{crown_analysis_lib}.rs"), "w") as f:
            f.write(target_c2rust_code)

        cmd_prefix = ['rustup', 'run',
                      # Version that works with crown
                      f'{CROWN_RUST_VERSION}-x86_64-unknown-linux-gnu', 'crown']
        # run crown preprocess
        cmd = [*cmd_prefix, os.path.join(
            self.analysis_build_path, "src/lib.rs"), 'preprocess', 'in-place']
        logger.debug("Executing crown command: %s", " ".join(cmd))
        result = utils.run_command(
            cmd, env=self.env, cwd=self.analysis_build_path
        )
        if result.returncode != 0:
            logger.error("Crown preprocess stderr: %s", result.stderr)
            raise RuntimeError("crown preprocess failed")
        if not self._try_compile_rust(self.analysis_build_path):
            # preoprocess messes up the code, recover it
            logger.warning("crown preprocess messed up code; restoring original translation")
            with open(os.path.join(self.analysis_build_path, f"src/{crown_analysis_lib}.rs"), "w") as f:
                f.write(target_c2rust_code)

        cmd = [*cmd_prefix, os.path.join(
            self.analysis_build_path, "src/lib.rs"), 'explicit-addr', 'in-place']
        result = utils.run_command(
            cmd, env=self.env, cwd=self.analysis_build_path
        )
        if result.returncode != 0:
            raise RuntimeError("crown explicit-addr failed")
        if not self._try_compile_rust(self.analysis_build_path):
            # explicit-addr messes up the code, recover it
            logger.warning("crown explicit-addr messed up code; restoring original translation")
            with open(os.path.join(self.analysis_build_path, f"src/{crown_analysis_lib}.rs"), "w") as f:
                f.write(target_c2rust_code)

        # run crown
        os.makedirs(self.analysis_results_path, exist_ok=True)
        cmd = [*cmd_prefix, os.path.join(
            self.analysis_build_path, "src/lib.rs"), 'analyse', self.analysis_results_path]
        result = utils.run_command(
            cmd, env=self.env, cwd=self.analysis_build_path
        )
        if result.returncode != 0:
            raise RuntimeError("crown analyse failed")
        self._read_analyze_result()

    def _read_analyze_result(self):
        if not os.path.exists(self.analysis_results_path):
            raise RuntimeError("crown analysis results not found")
        if not os.path.exists(os.path.join(self.analysis_results_path, "fatness.json")):
            self.fatness = {}
        else:
            with open(os.path.join(self.analysis_results_path, "fatness.json")) as f:
                self.fatness = json.load(f)
        if not os.path.exists(os.path.join(self.analysis_results_path, "mutability.json")):
            self.mutability = {}
        else:
            with open(os.path.join(self.analysis_results_path, "mutability.json")) as f:
                self.mutability = json.load(f)
        if not os.path.exists(os.path.join(self.analysis_results_path, "ownership.json")):
            self.ownership = {}
        else:
            with open(os.path.join(self.analysis_results_path, "ownership.json")) as f:
                self.ownership = json.load(f)

    def query(self, query, type: CrownType):
        results = {}
        match type:
            case CrownType.FUNCTION:
                fatness = self.fatness.get('fn_data', {})
                mutability = self.mutability.get('fn_data', {})
                ownership = self.ownership.get('fn_data', {})
            case CrownType.STRUCT:
                fatness = self.fatness.get('struct_data', {})
                mutability = self.mutability.get('struct_data', {})
                ownership = self.ownership.get('struct_data', {})
            case _:
                raise ValueError("Invalid CrownType")

        for k, v in fatness.items():
            k_path = k.split("::")
            if k_path[-1] == query:
                for k1, v1 in v.items():
                    if len(v1) == 0 and len(mutability[k][k1]) == 0 and len(ownership[k][k1]) == 0:
                        # skip empty results
                        continue
                    results[k1] = {
                        "fatness": v1,
                        "mutability": mutability[k][k1],
                        "ownership": ownership[k][k1]
                    }
        return results
