import os, shlex
import subprocess
from typing import override, Optional

from sactor import logging as sactor_logging
from sactor import utils

from .verifier import Verifier
from .verifier_types import VerifyResult


logger = sactor_logging.get_logger(__name__)


class E2EVerifier(Verifier):
    def __init__(
        self,
        test_cmd_path: str,
        config: dict,
        build_path=None,
        no_feedback=False,
        extra_compile_command=None,
        is_executable=True,
        executable_object=None,
        processed_compile_commands: list[list[str]] = [],

    ):
        super().__init__(
            test_cmd_path,
            config=config,
            build_path=build_path,
            no_feedback=no_feedback,
            extra_compile_command=extra_compile_command,
            executable_object=executable_object,
            processed_compile_commands=processed_compile_commands,
        )
        self.is_executable = is_executable

    @override
    def verify_function(self):
        raise NotImplementedError("Can not verify function in E2EVerifier")

    def e2e_verify(self, code: str) -> tuple[VerifyResult, Optional[str]]:
        # try compile the code
        compile_result = self.try_compile_rust_code(code, self.is_executable)

        if compile_result[0] != VerifyResult.SUCCESS:
            return compile_result

        # Run the tests
        if self.is_executable:
            test_error = self._run_tests(
                os.path.join(self.build_attempt_path, "target", "debug", "build_attempt"))
        else:
            # Library case: we must link provided object files against the built Rust lib
            executable_variants = self._iter_executable_variants()
            if not executable_variants:
                raise ValueError(
                    "executable_object must be provided for library code")

            link_flags = [
                f'-L{self.build_attempt_path}/target/debug',
                '-lbuild_attempt',
                '-lm',
            ]
            program_combiner_path = os.path.join(self.build_path, "program_combiner")
            os.makedirs(program_combiner_path, exist_ok=True)
            compiler = utils.get_compiler()
            env = utils.patched_env("LD_LIBRARY_PATH", f"{self.build_attempt_path}/target/debug")

            extra_compile_args = shlex.split(self.extra_compile_command) if self.extra_compile_command else []

            last_result: tuple[VerifyResult, Optional[str]] = (VerifyResult.SUCCESS, None)
            for index, executable_objects in enumerate(executable_variants):
                # Always use the same output path; variants are run serially
                output_path = os.path.join(program_combiner_path, "combined")

                # Build a combined binary with the variant-specific objects first, then our lib flags
                c_link_cmd = [
                    compiler,
                    '-o', output_path,
                    *executable_objects,
                    *link_flags,
                    *extra_compile_args,
                ]
                logger.debug("Compiling combined program (variant %s): %s", index, c_link_cmd)
                res = utils.run_command(c_link_cmd, capture_output=False)
                if res.returncode != 0:
                    raise RuntimeError("Error: Failed to compile combined program for variant %s" % index)

                logger.debug("Running E2E tests for variant %s", index)
                last_result = self._run_tests(output_path, env=env)
                if last_result[0] != VerifyResult.SUCCESS:
                    logger.error("E2E tests failed for variant %s", index)
                    return last_result[:2]

            # All variants passed
            test_error = last_result

        if test_error[0] != VerifyResult.SUCCESS:
            logger.error("Failed to run tests for the combined code")
            return test_error[:2]

        return (VerifyResult.SUCCESS, None)
