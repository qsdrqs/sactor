import os
import pytest
import shutil
import subprocess
import tempfile

from sactor.utils import load_default_config

def c_file_executable(file_path):
    with tempfile.TemporaryDirectory() as tmpdirname:
        compiler = None
        if shutil.which("clang"):
            compiler = "clang"
        elif shutil.which("gcc"):
            compiler = "gcc"

        assert compiler is not None
        os.makedirs(tmpdirname, exist_ok=True)
        subprocess.run([
            compiler,
            file_path,
            "-o",
            f"{tmpdirname}/a.out",
            '-ftrapv',
        ], check=True)

        executable = f"{tmpdirname}/a.out"
        yield (executable, file_path)

def can_compile(code: str) -> bool:
    with tempfile.TemporaryDirectory() as tmpdirname:
        with open(f"{tmpdirname}/a.c", "w") as f:
            f.write(code)
        compiler = None
        if shutil.which("clang"):
            compiler = "clang"
        elif shutil.which("gcc"):
            compiler = "gcc"

        assert compiler is not None
        result = subprocess.run([
            compiler,
            f"{tmpdirname}/a.c",
            "-o",
            f"{tmpdirname}/a.out",
            '-ftrapv',
        ])
        if result.returncode != 0:
            return False

        return True

@pytest.fixture
def config():
    return load_default_config()
