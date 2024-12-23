from enum import Enum, auto


class TranslationResult(Enum):
    SUCCESS = auto()
    MAX_ATTEMPTS_EXCEEDED = auto()
