from enum import Enum, auto


class TranslationOutcome(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    BLOCKED_FAILED = "blocked_by_failed_dependency"
    FALLBACK_C2RUST = "fallback_c2rust"

class TranslateResult(Enum):
    SUCCESS = auto()
    MAX_ATTEMPTS_EXCEEDED = auto()
    NO_UNIDIOMATIC_CODE = auto()
