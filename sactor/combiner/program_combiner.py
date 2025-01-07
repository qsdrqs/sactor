import os
import re
import json
import subprocess
from typing import override

from sactor import utils
from sactor.c_parser import FunctionInfo, StructInfo
from sactor.thirdparty.rustfmt import RustFmt
from sactor.verifier import E2EVerifier, VerifyResult

from .combiner import Combiner
from .combiner_types import CombineResult
from .rust_code import RustCode


class ProgramCombiner(Combiner):
    def __init__(self, functions: list[FunctionInfo], structs: list[StructInfo], test_cmd_path, build_path):
        self.functions = functions
        self.structs = structs

        self.verifier = E2EVerifier(test_cmd_path, build_path)
        self.build_path = build_path
        self.warning_stat = {}

    @override
    def combine(self, result_dir_with_type: str) -> tuple[CombineResult, str | None]:
        file_path = os.path.join(result_dir_with_type, 'combined.rs')
        if os.path.exists(file_path):
            print("Skip combining: combined.rs already exists")
            return CombineResult.SUCCESS, None

        function_code: dict[str, RustCode] = {}
        struct_code: dict[str, RustCode] = {}
        for function in self.functions:
            function_name = function.name
            with open(os.path.join(result_dir_with_type, 'functions', f'{function_name}.rs'), "r") as f:
                f_code = f.read()
                function_code[function_name] = RustCode(f_code)

        for struct in self.structs:
            struct_name = struct.name
            with open(os.path.join(result_dir_with_type, 'structs', f'{struct_name}.rs'), "r") as f:
                s_code = f.read()
                struct_code[struct_name] = RustCode(s_code)

        output_code = self._combine_code(function_code, struct_code)

        # verify the combined code
        result = self.verifier.e2e_verify(output_code, executable=True)
        if result[0] != VerifyResult.SUCCESS:
            print(f"Error: Failed to verify the combined code: {result[1]}")
            match result[0]:
                case VerifyResult.COMPILE_ERROR:
                    return CombineResult.COMPILE_FAILED, None
                case VerifyResult.TEST_ERROR:
                    return CombineResult.TEST_FAILED, None
                case _:
                    raise ValueError(
                        f"Unexpected error during verification: {result[0]}")

        # create a rust project
        build_program = os.path.join(self.build_path, "program")
        utils.create_rust_proj(
            rust_code=output_code,
            proj_name="program",
            path=build_program,
            is_lib=False
        )

        # format the code
        cmd = ["cargo", "fmt", "--manifest-path",
               os.path.join(build_program, "Cargo.toml")]
        result = subprocess.run(
            cmd, capture_output=True)

        if result.returncode != 0:
            print(f"Error: Failed to format the code: {result.stderr}")
            return CombineResult.RUSTFMT_FAILED, None

        # fix the code
        cmd = ["cargo", "clippy", "--fix", "--allow-no-vcs", "--manifest-path",
               os.path.join(build_program, "Cargo.toml")]
        print(cmd)
        result = subprocess.run(
            cmd, capture_output=True)

        if result.returncode != 0:
            print(f"Error: Failed to fix the code: {result.stderr}")
            return CombineResult.RUSTFIX_FAILED, None

        # cargo clippy
        cmd = ["cargo", "clippy", "--manifest-path",
               os.path.join(build_program, "Cargo.toml")]

        result = subprocess.run(
            cmd, capture_output=True)
        if result.returncode != 0:
            print(f"Error: Failed to run cargo clippy: {result.stderr}")
            return CombineResult.RUSTFIX_FAILED, None

        # collect warnings count
        self._stat_warnings(build_program, result.stderr.decode("utf-8"))

        # copy the combined code to the result directory
        cmd = ["cp", "-f",
               os.path.join(build_program, "src", "main.rs"), file_path]
        result = subprocess.run(cmd, check=True, capture_output=True)

        # save the warning stat
        with open(os.path.join(result_dir_with_type, "warning_stat.json"), "w") as f:
            json.dump(self.warning_stat, f, indent=4)

        return CombineResult.SUCCESS, output_code

    def _get_warning_count(self, compiler_output: str) -> int:
        warnings_count = 0
        compiler_output_lines = compiler_output.split("\n")
        for output in compiler_output_lines:
            total_pattern = re.compile(
                r'.*`program` \(bin "program"\) generated (\d+) warnings.*')
            total_match = total_pattern.match(output)
            if total_match:
                warnings_count = int(total_match.group(1))
                break

        return warnings_count


    def _stat_warnings(self, build_dir, compiler_output: str):
        compiler_output_lines = compiler_output.split("\n")
        total_warnings = self._get_warning_count(compiler_output)
        warning_types = []

        print(
            f"Found {total_warnings} warnings in the combined code")
        for output in compiler_output_lines:
            note_pattern = re.compile(
                r'.*= note: `#\[warn\((.*)\)\]` on by default.*')
            note_match = note_pattern.match(output)
            if note_match:
                warning_type = note_match.group(1)
                warning_types.append(warning_type)

        self.warning_stat["total_warnings"] = total_warnings

        current_count = total_warnings
        suppress_lines = 0
        for warning_type in warning_types:
            # write #![allow(warning_type)] to the top of the file to suppress the warning
            with open(os.path.join(build_dir, "src", "main.rs"), "r") as f:
                code = f.read()

            code = f"#![allow({warning_type})]\n{code}"
            with open(os.path.join(build_dir, "src", "main.rs"), "w") as f:
                f.write(code)
            suppress_lines += 1

            # re-run cargo clippy
            cmd = ["cargo", "clippy", "--manifest-path",
                   os.path.join(build_dir, "Cargo.toml")]
            result = subprocess.run(
                cmd, capture_output=True, check=True)

            new_count = self._get_warning_count(result.stderr.decode("utf-8"))
            diff = current_count - new_count
            self.warning_stat[warning_type] = diff
            current_count = new_count

        assert current_count == 0

        # remove the suppress lines
        with open(os.path.join(build_dir, "src", "main.rs"), "r") as f:
            code = f.read()

        code_lines = code.split("\n")
        code_lines = code_lines[suppress_lines:]
        code = "\n".join(code_lines)
        with open(os.path.join(build_dir, "src", "main.rs"), "w") as f:
            f.write(code)
