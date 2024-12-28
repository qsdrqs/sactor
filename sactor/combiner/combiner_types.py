from enum import Enum, auto


class CombineResult(Enum):
    SUCCESS = auto()
    RUSTFMT_FAILED = auto()
