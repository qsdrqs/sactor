import json
import os
import re
import subprocess
from typing import override, Optional

from sactor import rust_ast_parser, utils
from sactor.c_parser import FunctionInfo, StructInfo, GlobalVarInfo
from sactor.thirdparty.rustfmt import RustFmt
from sactor.verifier import E2EVerifier, VerifyResult

from .combiner import Combiner
from .combiner_types import CombineResult
from .rust_code import RustCode


class ProgramCombiner(Combiner):
    def __init__(
        self,
        config: dict,
        functions: list[FunctionInfo],
        structs: list[StructInfo],
        global_vars: list[GlobalVarInfo],
        test_cmd_path,
        build_path,
        is_executable: bool,
        extra_compile_command=None,
        executable_object=None,
    ):
        self.config = config
        self.functions = functions
        self.structs = structs
        self.global_vars = global_vars

        self.verifier = E2EVerifier(
            test_cmd_path,
            config,
            build_path=build_path,
            extra_compile_command=extra_compile_command,
            executable_object=executable_object,
            is_executable=is_executable,
        )
        self.is_executable = is_executable
        self.build_path = build_path
        self.clippy_stat = {}
        if is_executable:
            self.source_name = "main.rs"
        else:
            self.source_name = "lib.rs"

    @override
    def combine(self, result_dir_with_type: str, is_idiomatic=False) -> tuple[CombineResult, Optional[str]]:
        file_path = os.path.join(result_dir_with_type, 'combined.rs')
        if os.path.exists(file_path):
            print("Skip combining: combined.rs already exists")
            return CombineResult.SUCCESS, None

        function_code: dict[str, RustCode] = {}
        data_type_code: dict[str, RustCode] = {}
        for function in self.functions:
            function_name = function.name
            with open(os.path.join(result_dir_with_type, 'functions', f'{function_name}.rs'), "r") as f:
                f_code = f.read()
                function_code[function_name] = RustCode(f_code)

        for struct in self.structs:
            struct_name = struct.name
            with open(os.path.join(result_dir_with_type, 'structs', f'{struct_name}.rs'), "r") as f:
                s_code = f.read()
                data_type_code[struct_name] = RustCode(s_code)

        for global_var in self.global_vars:
            global_var_name = global_var.name
            with open(os.path.join(result_dir_with_type, 'global_vars', f'{global_var_name}.rs'), "r") as f:
                g_code = f.read()
                data_type_code[global_var_name] = RustCode(g_code)

        output_code = self._combine_code(function_code, data_type_code)

        # verify the combined code
        skip_test = False
        if not self.is_executable:
            if not is_idiomatic:
                # expose functions to C for all the functions
                e2e_code = output_code
                for function in self.functions:
                    e2e_code = rust_ast_parser.expose_function_to_c(
                        e2e_code, function.name)
            else:
                # idiomatic code does not need to expose functions to C
                e2e_code = output_code
                skip_test = True # e2e test can not be run on idiomatic code, because of the api mismatch to C
        else:
            e2e_code = output_code

        if not skip_test:
            result = self.verifier.e2e_verify(
                e2e_code)
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
            is_lib=not self.is_executable
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
            # Can have both warnings and errors, but this is not compile error
            cmd, capture_output=True)

        has_error = False
        if result.returncode != 0:
            has_error = True

        # collect warnings count
        self._stat_warnings_errors(
            build_program, result.stderr.decode("utf-8"), has_error)

        # copy the combined code to the result directory
        cmd = ["cp", "-f",
               os.path.join(build_program, "src", self.source_name), file_path]
        result = subprocess.run(cmd, check=True, capture_output=True)

        # save the warning stat
        with open(os.path.join(result_dir_with_type, "clippy_stat.json"), "w") as f:
            json.dump(self.clippy_stat, f, indent=4)

        return CombineResult.SUCCESS, output_code

    def _get_warning_error_count(self, compiler_output: str, has_error: bool) -> tuple[int, int]:
        warnings_count = 0
        compiler_output_lines = compiler_output.split("\n")
        for output in compiler_output_lines:
            total_pattern = re.compile(
                    r'.*`program` \((?:bin "program"|lib)\) generated (\d+) warnings.*')
            total_match = total_pattern.match(output)
            if total_match:
                warnings_count = int(total_match.group(1))
                break

        errors_count = 0
        if has_error:
            for output in compiler_output_lines:
                error_pattern = re.compile(
                    r'.*could not compile `program` \((?:bin "program"|lib)\) due to (\d+) previous errors.*')
                error_match = error_pattern.match(output)
                if error_match:
                    errors_count = int(error_match.group(1))
                    break

        return warnings_count, errors_count

    def _stat_warnings_errors(self, build_dir, compiler_output: str, has_errror: bool):
        compiler_output_lines = compiler_output.split("\n")
        total_warnings, total_errors = self._get_warning_error_count(
            compiler_output, has_errror)
        warning_types = []
        error_types = []

        print(
            f"Found {total_warnings} warnings in the combined code")
        print(
            f"Found {total_errors} errors in the combined code")
        for output in compiler_output_lines:
            note_warning_pattern = re.compile(
                r'.*= note: `#\[warn\((.*)\)\]` on by default.*')
            warning_match = note_warning_pattern.match(output)
            note_error_pattern = re.compile(
                r'.*= note: `#\[deny\((.*)\)\]` on by default.*')
            error_match = note_error_pattern.match(output)
            if warning_match:
                warning_type = warning_match.group(1)
                warning_types.append(warning_type)
            elif error_match:
                error_type = error_match.group(1)
                error_types.append(error_type)

        self.clippy_stat["total_warnings"] = total_warnings
        self.clippy_stat["total_errors"] = total_errors
        self.clippy_stat["warnings"] = {}
        self.clippy_stat["errors"] = {}

        # remove errors
        current_count = total_errors
        suppress_lines = 0
        for error_type in error_types:
            # write #![allow(error_type)] to the top of the file to suppress the error
            with open(os.path.join(build_dir, "src", self.source_name), "r") as f:
                code = f.read()

            code = f"#![allow({error_type})]\n{code}"
            with open(os.path.join(build_dir, "src", self.source_name), "w") as f:
                f.write(code)
            suppress_lines += 1

            # re-run cargo clippy
            cmd = ["cargo", "clippy", "--manifest-path",
                   os.path.join(build_dir, "Cargo.toml")]
            result = subprocess.run(
                cmd, capture_output=True, check=True)

            _, new_error_count = self._get_warning_error_count(
                result.stderr.decode("utf-8"), has_errror)
            diff = current_count - new_error_count
            self.clippy_stat["errors"][error_type] = diff
            current_count = new_error_count

        if current_count != 0:
            self.clippy_stat["errors"]["unknown"] = current_count

        current_count = total_warnings
        for warning_type in warning_types:
            # write #![allow(warning_type)] to the top of the file to suppress the warning
            with open(os.path.join(build_dir, "src", self.source_name), "r") as f:
                code = f.read()

            code = f"#![allow({warning_type})]\n{code}"
            with open(os.path.join(build_dir, "src", self.source_name), "w") as f:
                f.write(code)
            suppress_lines += 1

            # re-run cargo clippy
            cmd = ["cargo", "clippy", "--manifest-path",
                   os.path.join(build_dir, "Cargo.toml")]
            result = subprocess.run(
                cmd, capture_output=True, check=True)

            new_warning_cout, _ = self._get_warning_error_count(
                result.stderr.decode("utf-8"), has_errror)
            diff = current_count - new_warning_cout
            self.clippy_stat["warnings"][warning_type] = diff
            current_count = new_warning_cout

        if current_count != 0:
            self.clippy_stat["warnings"]["unknown"] = current_count

        # remove the suppress lines
        with open(os.path.join(build_dir, "src", self.source_name), "r") as f:
            code = f.read()

        code_lines = code.split("\n")
        code_lines = code_lines[suppress_lines:]
        code = "\n".join(code_lines)
        with open(os.path.join(build_dir, "src", self.source_name), "w") as f:
            f.write(code)
