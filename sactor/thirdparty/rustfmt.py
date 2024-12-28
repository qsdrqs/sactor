import shutil
import subprocess
from typing import override

from .thirdparty import ThirdParty


class RustFmt(ThirdParty):
    def __init__(self, file_path):
        self.file_path = file_path

    @staticmethod
    @override
    def check_requirements() -> list[str]:
        if not shutil.which("rustfmt"):
            return ["rustfmt"]
        return []

    def format(self):
        cmd = ["rustfmt", self.file_path]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise OSError(f"Failed to format the file: {self.file_path}")
