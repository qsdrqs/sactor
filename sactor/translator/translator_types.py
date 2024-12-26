from enum import Enum, auto


class TranslateResult(Enum):
    SUCCESS = auto()
    MAX_ATTEMPTS_EXCEEDED = auto()
