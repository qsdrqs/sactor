#!/usr/bin/env python3

import json, tempfile
import os, shlex
import subprocess
from abc import ABC, abstractmethod
from typing import Optional

from sactor import logging as sactor_logging
from sactor import rust_ast_parser, utils
from sactor.utils import is_compile_command, process_commands_to_compile, read_file, read_file_lines

from sactor.c_parser import FunctionInfo, StructInfo, c_parser_utils, CParser
from sactor.combiner.combiner import RustCode, merge_uses
from sactor.combiner.partial_combiner import CombineResult, PartialCombiner

from .verifier_types import VerifyResult

logger = sactor_logging.get_logger(__name__)

class Verifier(ABC):
    def __init__(
        self,
        test_cmd_path: str,
        config: dict,
        build_path=None,
        no_feedback=False,
        extra_compile_command: str | None=None,
        executable_object: str | None=None,
        processed_compile_commands: list[list[str]] = [],
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
        self.processed_compile_commands = processed_compile_commands

    @staticmethod
    def verify_test_cmd(test_cmd_path: str) -> bool:
        try:
            test_cmd = read_file(test_cmd_path)
            test_cmd = test_cmd.strip()
            test_cmd = json.loads(test_cmd)
            if not isinstance(test_cmd, list):
                logger.error(
                    "Invalid test command file %s: expected a list of dicts",
                    test_cmd_path,
                )
                return False
            for cmd in test_cmd:
                if not isinstance(cmd, dict):
                    logger.error(
                        "Invalid test command file %s: non-dict element in list",
                        test_cmd_path,
                    )
                    return False
                if 'command' not in cmd:
                    logger.error(
                        "Invalid test command file %s: dict without 'command' key",
                        test_cmd_path,
                    )
                    return False
                command = cmd['command']
                if not isinstance(command, str) and not isinstance(command, list):
                    logger.error(
                        "Invalid test command file %s: 'command' must be list or string",
                        test_cmd_path,
                    )
                    return False
            return True

        except Exception as e:
            logger.error("Invalid test command file %s: %s", test_cmd_path, e)
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
            logger.error("Rust code failed to format")
            return (VerifyResult.COMPILE_ERROR, result.stderr.decode())

        # Try to compile the Rust code
        cmd = ["cargo", "build", "--manifest-path",
               f"{self.build_attempt_path}/Cargo.toml"]
        logger.debug("Compiling Rust project: %s", ' '.join(cmd))
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            # Rust code failed to compile
            logger.error("Rust code failed to compile")
            return (VerifyResult.COMPILE_ERROR, result.stderr.decode())
        else:
            # Rust code compiled successfully
            logger.info("Rust code compiled successfully")
            return (VerifyResult.SUCCESS, None)

    def try_compile_rust_code(self, rust_code, executable=False) -> tuple[VerifyResult, Optional[str]]:
        return self._try_compile_rust_code_impl(rust_code, executable)

    def _load_test_cmd(self, target) -> list[list[str]]:
        test_cmd_str = read_file(self.test_cmd_path)
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
            logger.debug("Running test command: %s", cmd)
            if valgrind:
                cmd = valgrind_cmd + cmd
            try:
                res = utils.run_command_with_limit(
                        cmd=cmd,
                        time_limit_sec=timeout,
                        cwd=os.path.dirname(os.path.abspath(self.test_cmd_path)),
                        env=env
                    )
            except subprocess.TimeoutExpired as e:
                return (VerifyResult.TEST_TIMEOUT, f'Failed to run test due to timeout: {e}', i)
            stdout = res.stdout
            stderr = res.stderr
            if stdout:
                logger.debug("Test stdout: %s", stdout)
            if stderr:
                logger.debug("Test stderr: %s", stderr)
            if res.returncode != 0:

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
        env = utils.patched_env("LD_LIBRARY_PATH", f"{self.embed_test_rust_dir}/target/debug")
        return self._run_tests(target, env, test_number, valgrind)

    def _mutate_c_code(self, c_function: FunctionInfo, filename, prefix=False) -> str:
        # remove the c code of the function, but keep the function signature
        node = c_function.node
        lines = read_file_lines(filename)

        # remove `static` from the function signature in function dependencies
        source_code = "".join(lines)
        for function_dependency in c_function.function_dependencies:
            file = function_dependency.node.location.file.name
            if file != filename:
                continue

            source_code = c_parser_utils.remove_function_static_decorator(
                function_dependency.name, source_code)
        # If the to-be-translated function is static, then it cannot be linked to the Rust definition.
        # So we remove the static attribute.
        # This solution may trigger bugs if other linked object files have functions with the same name.
        # The above code removing static in function dependencies may also trigger this bug.
        # TODO: rename the to-be-translated function to a unique name using the current `prefix` argument & mechanism;
        #       after translation, name the Rust translated function with the original name, and remove its `pub` attribute.
        source_code = c_parser_utils.remove_function_static_decorator(c_function.name, source_code)
        lines = source_code.split("\n")
        tmpdir = utils.get_temp_dir()
        with open(os.path.join(tmpdir, "tmp.c"), "w") as f:
            f.write(source_code)

        c_parser = CParser(os.path.join(tmpdir, "tmp.c"), omit_error=True)
        c_function = c_parser.get_function_info(c_function.name)
        node = c_function.node
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
                logger.error('Global variable is not declared: %s', var_node.spelling)
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
        logger.debug("Compiling embedded Rust crate: %s", " ".join(rust_compile_cmd))
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

        executable_objects = shlex.split(self.executable_object) if self.executable_object else []
        extra_compile_command = shlex.split(extra_compile_command) if self.extra_compile_command else []
        link_flags = [
            f'-L{self.embed_test_rust_dir}/target/debug',
            '-lm',
            f'-l{name}',
        ]

        if self.processed_compile_commands:
            commands = process_commands_to_compile(self.processed_compile_commands, output_path, source_path)
            # assuming the last command is the linking command
            # TODO: check if it is a linking command?
            commands[-1].extend(executable_objects)
            commands[-1].extend(link_flags)
            for command in commands:
                to_check = False
                if is_compile_command(command):
                    to_check = True
                logger.debug("Running compile command: %s", command)
                res = subprocess.run(command)
                if to_check and res.returncode != 0:
                    raise RuntimeError(
                        f"Error: Failed to compile C code for function {name}")

        else:
            c_compile_cmd = [
                compiler,
                '-o', output_path,
                source_path,
                *executable_objects,
                *link_flags,
                *extra_compile_command,
            ]

            # compile C code
            logger.debug("Compiling C harness: %s", c_compile_cmd)
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
            logger.error(
                "Failed to run tests for function %s, rerunning with feedback",
                name,
            )
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
                logger.error(
                    "Failed to compile Rust code for function %s during feedback rerun",
                    name,
                )
                logger.error("%s", res.stderr.decode())
                raise RuntimeError(
                    f"Failed to compile Rust code for function {name}. Error messages from the Rust compiler:\n{res.stderr.decode()}")

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
