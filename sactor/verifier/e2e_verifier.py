import os
import subprocess
from typing import override

from sactor import utils

from .verifier import Verifier
from .verifier_types import VerifyResult


class E2EVerifier(Verifier):
    def __init__(
        self,
        test_cmd_path: str,
        config: dict,
        build_path=None,
        no_feedback=False,
        extra_compile_command=None,
        is_executable=False,
        executable_object=None,
    ):
        super().__init__(
            test_cmd_path,
            config=config,
            build_path=build_path,
            no_feedback=no_feedback,
            extra_compile_command=extra_compile_command,
            executable_object=executable_object,
        )
        self.is_executable = is_executable

    @override
    def verify_function(self):
        raise NotImplementedError("Can not verify function in E2EVerifier")

    def e2e_verify(self, code: str) -> tuple[VerifyResult, str | None]:
        # try compile the code
        compile_result = self._try_compile_rust_code(code, self.is_executable)

        if compile_result[0] != VerifyResult.SUCCESS:
            return compile_result

        # Run the tests
        if self.is_executable:
            test_error = self._run_tests(
                os.path.join(self.build_attempt_path, "target", "debug", "build_attempt"))
        else:
            if self.executable_object is None:
                raise ValueError(
                    "executable_object must be provided for library code")

            executable_objects = self.executable_object.split()

            program_combiner_path = os.path.join(
                self.build_path, "program_combiner")
            os.makedirs(program_combiner_path, exist_ok=True)
            compiler = utils.get_compiler()
            c_compile_cmd = [
                compiler,
                '-o',
                os.path.join(program_combiner_path, "combined"),
                f'-L{self.build_attempt_path}/target/debug',
                f'-lbuild_attempt',
            ]
            c_compile_cmd.extend(executable_objects)
            if self.extra_compile_command:
                c_compile_cmd.extend(self.extra_compile_command.split())
            print(c_compile_cmd)
            res = subprocess.run(c_compile_cmd)
            if res.returncode != 0:
                raise RuntimeError(
                    f"Error: Failed to compile C code for testing the combined code")

            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = os.path.abspath(
                f"{self.build_attempt_path}/target/debug")
            test_error = self._run_tests(
                os.path.join(program_combiner_path, "combined"), env=env)


        if test_error[0] != VerifyResult.SUCCESS:
            print("Error: Failed to run tests for the combined code")
            return test_error[:2]

        return (VerifyResult.SUCCESS, None)
