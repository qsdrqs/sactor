from enum import Enum, auto


class VerifyResult(Enum):
    SUCCESS = auto()
    COMPILE_ERROR = auto()
    TEST_ERROR = auto()
