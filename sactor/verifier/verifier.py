#!/usr/bin/env python3

import json
import os
import subprocess
from abc import ABC, abstractmethod
from typing import Optional

from sactor import rust_ast_parser, utils
from sactor.c_parser import FunctionInfo, StructInfo, c_parser_utils
from sactor.combiner.combiner import RustCode, merge_uses
from sactor.combiner.partial_combiner import CombineResult, PartialCombiner

from .verifier_types import VerifyResult

class Verifier(ABC):
    def __init__(
        self,
        test_cmd_path: str,
        config: dict,
        build_path=None,
        no_feedback=False,
        extra_compile_command=None,
        executable_object=None,
    ):
        self.config = config
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
        self.test_cmd_path = test_cmd_path
        self.no_feedback = no_feedback
        self.extra_compile_command = extra_compile_command
        self.executable_object = executable_object

    @staticmethod
    def verify_test_cmd(test_cmd_path: str) -> bool:
        try:
            with open(test_cmd_path, "r") as f:
                test_cmd = f.read()
            test_cmd = test_cmd.strip()
            test_cmd = json.loads(test_cmd)
            if not isinstance(test_cmd, list):
                print(
                    "Error: Invalid test command file, expected a list of dicts, can't find the list")
                return False
            for cmd in test_cmd:
                if not isinstance(cmd, dict):
                    print(
                        "Error: Invalid test command file, expected a list of dicts, found a non-dict element in list")
                    return False
                if 'command' not in cmd:
                    print(
                        "Error: Invalid test command file, expected a list of dicts, found a dict without 'command' key")
                    return False
                command = cmd['command']
                if not isinstance(command, str) and not isinstance(command, list):
                    print(
                        "Error: Invalid test command file, expected list or string for 'command'")
                    return False
            return True

        except Exception as e:
            print(f"Error: Invalid test command file {test_cmd_path}: {e}")
            return False

    @abstractmethod
    def verify_function(
        self,
        function: FunctionInfo,
        function_code: str,
        data_type_code: dict[str, str],
        *args,
        **kwargs,
    ) -> tuple[VerifyResult, Optional[str]]:
        pass

    def verify_struct(
        self,
        struct: StructInfo,
        struct_code: str,
        struct_dependencies_code: dict[str, str],
    ) -> tuple[VerifyResult, Optional[str]]:
        structs = {struct.name: struct_code}
        structs.update(struct_dependencies_code)

        combiner = PartialCombiner({}, structs)
        result, combined_code = combiner.combine()
        if result != CombineResult.SUCCESS or combined_code is None:
            raise ValueError(f"Failed to combine the struct {struct.name}")

        compile_result = self.try_compile_rust_code(combined_code)
        if compile_result[0] != VerifyResult.SUCCESS:
            return compile_result

        return (VerifyResult.SUCCESS, None)

    def _try_compile_rust_code_impl(self, rust_code, executable=False) -> tuple[VerifyResult, Optional[str]]:
        utils.create_rust_proj(rust_code, "build_attempt",
                               self.build_attempt_path, is_lib=(not executable))

        # Try format the Rust code
        cmd = ["cargo", "fmt", "--manifest-path",
               f"{self.build_attempt_path}/Cargo.toml"]
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            # Rust code failed to format, unable to compile
            print("Rust code failed to format")
            return (VerifyResult.COMPILE_ERROR, result.stderr.decode())

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

    def try_compile_rust_code(self, rust_code, executable=False) -> tuple[VerifyResult, Optional[str]]:
        return self._try_compile_rust_code_impl(rust_code, executable)

    def _load_test_cmd(self, target) -> list[list[str]]:
        with open(self.test_cmd_path, "r") as f:
            test_cmd_str = f.read()
        test_cmd_str = test_cmd_str.strip()
        test_cmd_json = json.loads(test_cmd_str)
        test_cmd = []
        for item in test_cmd_json:
            cmd = item['command']
            if type(cmd) is str:
                cmd = cmd.split()
            for i, arg in enumerate(cmd):
                if arg == "%t":
                    cmd[i] = os.path.abspath(target)
            test_cmd.append(cmd)

        return test_cmd

    def _collect_feedback(self, output) -> str:
        lines = output.split('\n')
        feedback = ""
        in_feedback = False
        for line in lines:
            if line.find("--------Entering function: ") != -1:
                in_feedback = True
            if in_feedback:
                feedback += line + '\n'

        return feedback

    def _run_tests(self, target, env=None, test_number=None, valgrind=False) -> tuple[VerifyResult, Optional[str], Optional[int]]:
        if env is None:
            env = os.environ.copy()
        test_cmds = self._load_test_cmd(target)
        valgrind_cmd = [
            'valgrind',
            '--error-exitcode=1',
            '--leak-check=no',
            '--trace-children=yes',
            '--',
        ]

        timeout = self.config['general']['timeout_seconds']

        for i, cmd in enumerate(test_cmds):
            if test_number is not None and i != test_number:
                continue
            print(cmd)
            if valgrind:
                cmd = valgrind_cmd + cmd
            try:
                res = subprocess.run(
                    cmd,
                    env=env,
                    cwd=os.path.dirname(os.path.abspath(self.test_cmd_path)),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as e:
                return (VerifyResult.TEST_TIMEOUT, f'Failed to run test due to timeout: {e}', i)
            print(res.stdout.decode())
            print(res.stderr.decode())
            if res.returncode != 0:
                stdout = res.stdout.decode()
                stderr = res.stderr.decode()
                feedback = self._collect_feedback(stdout + stderr)
                if feedback != "":
                    return (VerifyResult.FEEDBACK, feedback, i)
                if stderr == "":
                    if stdout != "":
                        return (VerifyResult.TEST_ERROR, stdout, i)
                    else:
                        return (VerifyResult.TEST_ERROR, "No output", i)
                return (VerifyResult.TEST_ERROR, stderr, i)

        return (VerifyResult.SUCCESS, None, None)

    def _run_tests_with_rust(self, target, test_number=None, valgrind=False) -> tuple[VerifyResult, Optional[str], Optional[int]]:
        # get absolute path of the target
        target = os.path.abspath(target)
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = os.path.abspath(
            f"{self.embed_test_rust_dir}/target/debug")
        return self._run_tests(target, env, test_number, valgrind)

    def _mutate_c_code(self, c_function: FunctionInfo, filename, prefix=False) -> str:
        # remove the c code of the function, but keep the function signature
        node = c_function.node
        with open(filename, "r") as f:
            lines = f.readlines()

        # remove `static` from the function signature in function dependencies
        source_code = "".join(lines)
        for function_dependency in c_function.function_dependencies:
            file = function_dependency.node.location.file.name
            if file != filename:
                continue

            source_code = c_parser_utils.remove_function_static_decorator(
                function_dependency.name, source_code)

        lines = source_code.split("\n")

        # remove the function body
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
        # TODO: move this to c_parser.utils
        used_global_token_spellings = []
        used_global_vars = c_function.global_vars_dependencies
        for var in used_global_vars:
            if var.is_const:
                continue  # skip const global variables as it will be included
            var_node = var.node
            start_line = var_node.extent.start.line - 1
            end_line = var_node.extent.end.line
            tokens = utils.cursor_get_tokens(var_node)
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

        # add fflush(stdout);fflush(stderr); to the end of the printf stmt # TODO: dirty hack
        for i in range(len(lines)):
            if '#include' in lines[i] and ('stdio.h' in lines[i] or 'cstdio' in lines[i]):
                lines[i] = lines[i] + '\n' \
                    + '#define printf(fmt, ...) (printf(fmt, ##__VA_ARGS__), fflush(stdout), fflush(stderr))'

        return "\n".join(lines)

    def _embed_test_rust(
        self,
        c_function: FunctionInfo,
        rust_code,
        function_dependency_signatures: list[str] | None = None,
        prefix=False,
        idiomatic=False,
        function_dependency_uses=None
    ) -> tuple[VerifyResult, Optional[str]]:
        name = c_function.name
        filename = c_function.node.location.file.name

        rust_code = rust_ast_parser.expose_function_to_c(rust_code, name)

        parsed_rust_code = RustCode(rust_code)
        all_uses = RustCode(rust_code).used_code_list
        if function_dependency_signatures:
            joint_function_depedency_signatures = '\n'.join(
                function_dependency_signatures)
            joint_function_dependency_uses = ""
            remained_code = parsed_rust_code.remained_code

            if function_dependency_uses:
                all_uses += function_dependency_uses
            all_uses_tuples = set(tuple(x) for x in all_uses)
            all_uses = [list(x) for x in all_uses_tuples]
            all_dependency_uses = merge_uses(all_uses)
            joint_function_dependency_uses = '\n'.join(all_dependency_uses)
            rust_code = f'''
#![allow(unused_imports)]
{joint_function_dependency_uses}

extern "C" {{
{joint_function_depedency_signatures}
}}

/* __START_TRANSLATION__ */
{remained_code}
'''
        utils.create_rust_proj(
            rust_code, name, self.embed_test_rust_dir, is_lib=True)

        # compile
        # should succeed, omit output
        rust_compile_cmd = ["cargo", "build", "--manifest-path",
                            f"{self.embed_test_rust_dir}/Cargo.toml"]
        print(" ".join(rust_compile_cmd))
        res = subprocess.run(rust_compile_cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        if res.returncode != 0:
            raise RuntimeError(
                f"Failed to compile Rust code for function {name}")

        c_code_removed = self._mutate_c_code(c_function, filename, prefix)

        os.makedirs(self.embed_test_c_dir, exist_ok=True)

        with open(f"{self.embed_test_c_dir}/{name}.c", "w") as f:
            f.write(c_code_removed)

        compiler = utils.get_compiler()
        output_path = os.path.join(self.embed_test_c_dir, name)
        source_path = os.path.join(self.embed_test_c_dir, f'{name}.c')

        executable_objects = self.executable_object.split() if self.executable_object else []
        extra_compile_command = self.extra_compile_command.split() if self.extra_compile_command else []
        link_flags = [
            f'-L{self.embed_test_rust_dir}/target/debug',
            '-lm',
            f'-l{name}',
        ]

        c_compile_cmd = [
            compiler,
            '-o', output_path,
            source_path,
            *executable_objects,
            *link_flags,
            *extra_compile_command,
        ]

        # compile C code
        print(c_compile_cmd)
        res = subprocess.run(c_compile_cmd)
        if res.returncode != 0:
            raise RuntimeError(
                f"Error: Failed to compile C code for function {name}")
        # run tests
        result = self._run_tests_with_rust(f'{self.embed_test_c_dir}/{name}')
        if result[0] != VerifyResult.SUCCESS:
            failed_test_number = result[2]
            assert failed_test_number is not None
            if self.no_feedback:
                return (result[0], result[1])
            # rerun with feedback from `trace_fn`
            print(
                f"Error: Failed to run tests for function {name}, rerun with feedback")
            if idiomatic:
                rust_code = rust_ast_parser.add_attr_to_function(
                    rust_code, f'{name}_idiomatic', "#[sactor_proc_macros::trace_fn]")
            else:
                rust_code = rust_ast_parser.add_attr_to_function(
                    rust_code, name, "#[sactor_proc_macros::trace_fn]")
            utils.create_rust_proj(
                rust_code, name, self.embed_test_rust_dir, is_lib=True, proc_macro=True)
            res = subprocess.run(rust_compile_cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
            if res.returncode != 0:
                print(f"Error: Failed to compile Rust code for function {name}")
                print(res.stderr.decode())
                raise RuntimeError(
                    f"Failed to compile Rust code for function {name}")

            previous_result = result

            # TODO: improve feedback: 1. pointers not printable 2. main function doesn't have valid feedback
            result = self._run_tests_with_rust(
                f'{self.embed_test_c_dir}/{name}', failed_test_number, valgrind=True)

            if result[0] == VerifyResult.FEEDBACK:
                feedback = f'''
--------Begin Original Output--------
{previous_result[1]}
--------End Original Output--------
--------Begin Feedback--------
{result[1]}
--------End Feedback--------'''
                return (result[0], feedback)
            else:
                # No feedback, return the original error message
                return (result[0], previous_result[1])

        return (VerifyResult.SUCCESS, None)

