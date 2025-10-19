import os, json, glob
import shutil
import subprocess
from typing import override, List

from sactor import logging as sactor_logging
from sactor import utils

from .thirdparty import ThirdParty

logger = sactor_logging.get_logger(__name__)

class C2Rust(ThirdParty):
    def __init__(self, filename):
        self.filename = filename

    @staticmethod
    @override
    def check_requirements() -> list[str]:
        result = []
        if not shutil.which("c2rust"):
            result.append("c2rust")
        if not shutil.which("gcc") and not shutil.which("clang"):
            result.append("C compiler(gcc or clang)")

        return result

    def get_c2rust_translation(self, compile_flags: list[str] =[]):
        # check c2rust executable
        if not shutil.which("c2rust"):
            raise OSError("c2rust executable not found")

        tmpdir = os.path.join(utils.get_temp_dir(), "c2rust")
        shutil.rmtree(tmpdir, ignore_errors=True) # remove old files if any
        os.makedirs(tmpdir, exist_ok=True)
        filename_noext = os.path.splitext(self.filename)[0]
        tmp_filename = os.path.join(
            tmpdir, os.path.basename(self.filename))
        tmp_filename_rs = os.path.join(
            tmpdir, os.path.basename(filename_noext + ".rs"))
        shutil.copy(self.filename, tmp_filename)

        # run c2rust
        search_include_paths = utils.get_compiler_include_paths()
        search_include_paths = [
            f'-I{path}' for path in search_include_paths]
        cmd = ['c2rust', 'transpile', tmp_filename,
            '--', *search_include_paths, *compile_flags]
        logger.debug("Running c2rust command: %s", cmd)
        # add C_INCLUDE_PATH to the environment if needed
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        if result.returncode != 0:
            logger.error("c2rust failed: %s", result.stderr.decode())
            if os.path.exists(tmp_filename_rs):
                os.remove(tmp_filename_rs)
            raise RuntimeError("c2rust transpile command failed")
        # this is the translated Rust code
        assert os.path.exists(tmp_filename_rs)

        with open(tmp_filename_rs) as f:
            c2rust_content = f.read()

        return c2rust_content
