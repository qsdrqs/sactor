import os
from typing import override

from .verifier import Verifier
from .verifier_types import VerifyResult


class E2EVerifier(Verifier):
    def __init__(self, test_cmd, build_path=None):
        super().__init__(test_cmd, build_path)

    @override
    def verify_function(self):
        raise NotImplementedError("Can not verify function in E2EVerifier")

    def e2e_verify(self, code: str, executable) -> tuple[VerifyResult, str | None]:
        # try compile the code
        compile_result = self._try_compile_rust_code(code, [], executable)

        if compile_result[0] != VerifyResult.SUCCESS:
            return compile_result

        # Run the tests
        test_error = self._run_tests(
            os.path.join(self.build_attempt_path, "target", "debug", "build_attempt"))

        if test_error[0] != VerifyResult.SUCCESS:
            print("Error: Failed to run tests for the combined code")
            return test_error

        return (VerifyResult.SUCCESS, None)
