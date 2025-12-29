from dataclasses import dataclass
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


@dataclass
class TranslateBatchResult:
    entries: list[dict[str, object]]
    any_failed: bool
    base_result_dir: str
    combined_dir: str | None
