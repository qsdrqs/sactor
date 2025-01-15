from enum import Enum, auto


class VerifyResult(Enum):
    SUCCESS = auto()
    COMPILE_ERROR = auto()
    TEST_ERROR = auto()
    TEST_TIMEOUT = auto()
    TEST_HARNESS_MAX_ATTEMPTS_EXCEEDED = auto()
    FEEDBACK = auto()
