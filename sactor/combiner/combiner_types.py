from enum import Enum, auto


class CombineResult(Enum):
    SUCCESS = auto()
    RUSTFMT_FAILED = auto()
    RUSTFIX_FAILED = auto()
    COMPILE_FAILED = auto()
    TEST_FAILED = auto()
