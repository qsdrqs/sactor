import os, json, glob
import shutil
import subprocess
from typing import override, List

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

    def get_c2rust_translation(self, compile_commands_file: str=""):
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

        # def process_compile_commands_file(compile_commands_file: str) -> str:
        #     tmp_commands_file = os.path.join(
        #         tmpdir, os.path.basename(compile_commands_file))
        #     with open(compile_commands_file) as f:
        #         commands = json.load(f)
        #     new_commands = []
        #     c_source_basename = os.path.basename(self.filename)

        #     def has_test(command: dict) -> bool:
        #         args = command['arguments']
        #         for arg in args:
        #             if arg.startswith("-D") and "TEST" in arg:
        #                 return True
        #         return False
            
        #     def find_output_path_index(command: dict) -> int:
        #         index = -1
        #         for i, arg in enumerate(command["arguments"][:-1]):
        #             if arg == "-o":
        #                 index = i + 1
        #                 break
        #         return index
            
        #     def find_source_path_index(command: dict) -> int:
        #         for i, arg in enumerate(command["arguments"]):
        #             if arg.endswith(".c"):
        #                 return i
        #         return -1
            
        #     for command in commands:
        #         if command["file"].endswith(c_source_basename) and \
        #             not has_test(command):
        #             new_commands.append(command)
        #     new_commands.sort(key=lambda c: len(c['arguments']))
        #     if not new_commands:
        #         raise Exception("No valid command in compile_commands.json")
        #     command = new_commands[0]
        #     if "output" in command:
        #         del command["output"]
        #     i = find_output_path_index(command)
        #     if i == -1:
        #         command["arguments"].extend(("-o", tmp_filename[:-2] + ".o"))
        #     else:
        #         command["arguments"][i] = tmp_filename[:-2] + ".o"
            
        #     i = find_source_path_index(command)
        #     if i == -1:
        #         command["arguments"].append(tmp_filename)
        #     else:
        #         command["arguments"][i] = tmp_filename
        #     command["file"] = tmp_filename
        #     with open(tmp_commands_file, "w") as f:
        #         json.dump([command], f)
        #     return tmp_commands_file

        if compile_commands_file:
            cmd = ["c2rust", "transpile", compile_commands_file]
            shutil.move(filename_noext + ".rs", tmp_filename_rs)
            for path in glob.glob(os.path.join( os.path.dirname(self.filename), "*.rs")):
                os.remove(path)
        else:            
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
            print(f"c2rust failed: {result.stderr.decode()}")
            if os.path.exists(tmp_filename_rs):
                os.remove(tmp_filename_rs)
            raise RuntimeError("c2rust transpile command failed")

        # this is the translated Rust code
        assert os.path.exists(tmp_filename_rs)

        with open(tmp_filename_rs) as f:
            c2rust_content = f.read()

        return c2rust_content
