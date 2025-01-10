import os
import shutil
import subprocess
from typing import override

from sactor import utils

from .thirdparty import ThirdParty


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

    def get_c2rust_translation(self):
        # check c2rust executable
        if not shutil.which("c2rust"):
            raise OSError("c2rust executable not found")

        tmpdir = os.path.join(utils.get_temp_dir(), "c2rust")
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
               '--', *search_include_paths]
        print(cmd)
        # add C_INCLUDE_PATH to the environment if needed
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        if result.returncode != 0:
            print("c2rust failed")
            os.remove(tmp_filename_rs)
            raise RuntimeError("c2rust transpile command failed")

        # this is the translated Rust code
        assert os.path.exists(tmp_filename_rs)

        with open(tmp_filename_rs) as f:
            c2rust_content = f.read()

        return c2rust_content
