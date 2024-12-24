#!/usr/bin/env python3

import os
import subprocess
from abc import ABC, abstractmethod

from sactor import rust_ast_parser, utils
from sactor.c_parser import FunctionInfo

from .verifier_types import VerifyResult


class Verifier(ABC):
    def __init__(self, test_cmd: str | list[str], build_path=None):
        if build_path:
            self.build_path = build_path
        else:
            tmpdir = utils.get_temp_dir()
            self.build_path = os.path.join(tmpdir, 'build')
        self.build_attempt_path = os.path.join(
            self.build_path, "build_attempt")
        self.embed_test_rust_dir = os.path.join(
            self.build_path, "embed_test_rust")
        self.embed_test_c_dir = os.path.join(self.build_path, "embed_test_c")
        self.test_cmd = test_cmd

    @abstractmethod
    def verify_function(self, *args, **kwargs) -> tuple[VerifyResult, str | None]:
        pass

    def _try_compile_rust_code(self, rust_code, function_dependency_signatures) -> tuple[VerifyResult, str | None]:
        # Create a temporary Rust project
        os.makedirs(f"{self.build_attempt_path}/src", exist_ok=True)

        joint_function_depedency_signatures = '\n'.join(
            function_dependency_signatures)
        rust_code = f'''
extern "C" {{
{joint_function_depedency_signatures}
}}
{rust_code}
'''

        utils.create_rust_lib(rust_code, "build_attempt",
                              self.build_attempt_path)

        # Try to compile the Rust code
        cmd = ["cargo", "build", "--manifest-path",
               f"{self.build_attempt_path}/Cargo.toml"]
        print(' '.join(cmd))
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            # Rust code failed to compile
            print("Rust code failed to compile")
            return (VerifyResult.COMPILE_ERROR, result.stderr.decode())
        else:
            # Rust code compiled successfully
            print("Rust code compiled successfully")
            return (VerifyResult.SUCCESS, None)

    def _run_tests(self, name, target):
        # get absolute path of the target
        target = os.path.abspath(target)
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = os.path.abspath(
            f"{self.embed_test_rust_dir}/target/debug")
        if type(self.test_cmd) == str:
            cmd = [self.test_cmd, target]
        elif type(self.test_cmd) == list:
            cmd = self.test_cmd + [target]
        else:
            raise ValueError(f"Invalid test command type: {type(self.test_cmd)}, expected str or list[str]")
        res = subprocess.run(cmd, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(res.stdout.decode())
        print(res.stderr.decode())
        if res.returncode != 0:
            print(f"Error: Failed to run tests for function {name}")
            stdout = res.stdout.decode()
            stderr = res.stderr.decode()
            if stderr is None:
                if stdout is not None:
                    return (VerifyResult.TEST_ERROR, stdout)
                else:
                    return (VerifyResult.TEST_ERROR, "No output")
            return (VerifyResult.TEST_ERROR, stderr)
        return (VerifyResult.SUCCESS, None)

    def _remove_c_code(self, c_function: FunctionInfo, filename, prefix=False):
        def remove_prefix(set_of_strings):
            """
            Some items in the list may be the prefix of other items, remove the prefix items, only keep the longest items
            """
            longest_items = []

            for string, start, end in set_of_strings:
                is_prefix = False
                for other_string, _, _ in set_of_strings:
                    if string != other_string and other_string.startswith(string):
                        is_prefix = True
                        break
                if not is_prefix:
                    longest_items.append((string, start, end))

            return longest_items

        # remove the c code of the function, but keep the function signature
        node = c_function.node
        location = node.location
        with open(filename, "r") as f:
            lines = f.readlines()

        # get the function signature
        call_stmt = ""
        if prefix:
            signature = c_function.get_signature(c_function.name+"_") + ';'
            orig_signature = c_function.get_signature()
            call_original = f"{
                c_function.name+'_'}({', '.join([arg_name for arg_name, _ in c_function.arguments])});"
            call_stmt = f"{orig_signature} {{\n    {call_original}\n}}"
        else:
            signature = c_function.get_signature() + ';'

        start_line = node.extent.start.line - 1
        end_line = node.extent.end.line
        for i in range(start_line, end_line):
            lines[i] = ""
        if prefix:
            lines[start_line] = signature + "\n" + call_stmt + "\n"
        else:
            lines[start_line] = signature + "\n"

        # change global variables to extern
        used_global_token_spellings = []
        used_global_vars = c_function.global_vars_dependencies
        for var_node in used_global_vars:
            start_line = var_node.extent.start.line - 1
            end_line = var_node.extent.end.line
            tokens = var_node.get_tokens()
            token_spellings = [token.spelling for token in tokens]
            if len(token_spellings) == 0:
                print(
                    f'Error: Global variable is not declared: {var_node.spelling}')
            used_global_token_spellings.append(
                (token_spellings, start_line, end_line))
        for token_spellings, start_line, end_line in used_global_token_spellings:
            long_token_spellings = ' '.join(token_spellings)
            is_prefix = False
            for other_token_spellings, _, _ in used_global_token_spellings:
                if token_spellings != other_token_spellings and ' '.join(other_token_spellings).startswith(long_token_spellings):
                    is_prefix = True
                    break
            if is_prefix:
                used_global_token_spellings.remove(
                    (token_spellings, start_line, end_line))

        for token_spellings, start_line, end_line in used_global_token_spellings:
            if token_spellings[0] == "extern":
                continue
            elif token_spellings[0] == "static":
                token_spellings = token_spellings[1:]

            for i in range(start_line, end_line):
                lines[i] = ""
            lines[start_line] = ' '.join(token_spellings) + ';\n'

        return "".join(lines)

    def _embed_test_rust(self, c_function: FunctionInfo, rust_code, function_dependency_signatures, prefix=False):
        name = c_function.name
        filename = c_function.node.location.file.name

        rust_code = rust_ast_parser.expose_function_to_c(rust_code)
        if len(function_dependency_signatures) > 0:
            joint_function_depedency_signatures = '\n'.join(
                function_dependency_signatures)
            rust_code = f'''
extern "C" {{
{joint_function_depedency_signatures}
}}

{rust_code}
'''
        utils.create_rust_lib(rust_code, name, self.embed_test_rust_dir)

        # compile
        # should succeed, omit output
        cmd = ["cargo", "build", "--manifest-path",
               f"{self.embed_test_rust_dir}/Cargo.toml"]
        print(" ".join(cmd))
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        if res.returncode != 0:
            raise RuntimeError(
                "Failed to compile Rust code for function {name}")

        library_path = f"{self.embed_test_rust_dir}/target/debug/lib{name}.so"
        c_code_removed = self._remove_c_code(c_function, filename, prefix)

        os.makedirs(self.embed_test_c_dir, exist_ok=True)

        with open(f"{self.embed_test_c_dir}/{name}.c", "w") as f:
            f.write(c_code_removed)

        # compile the C code
        cmd = ['gcc', '-o', os.path.join(self.embed_test_c_dir, name), os.path.join(
            self.embed_test_c_dir, f'{name}.c'), f'-L{self.embed_test_rust_dir}/target/debug', f'-l{name}']
        print(cmd)
        res = subprocess.run(cmd)
        if res.returncode != 0:
            raise RuntimeError(
                f"Error: Failed to compile C code for function {name}")

        # run tests
        return self._run_tests(name, f'{self.embed_test_c_dir}/{name}')
