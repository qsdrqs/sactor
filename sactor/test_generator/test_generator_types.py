from enum import Enum, auto


class TestGeneratorResult(Enum):
    SUCCESS = auto()
    MAX_ATTEMPTS_EXCEEDED = auto()
