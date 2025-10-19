import datetime as _dt
import json
import logging as _logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

_LOGGER_NAMESPACE = "sactor"
_LLM_LOGGER_NAME = f"{_LOGGER_NAMESPACE}.llm"
_PROMPT_LEVEL = 15
_RESPONSE_LEVEL = 16

_logging.addLevelName(_PROMPT_LEVEL, "PROMPT")
_logging.addLevelName(_RESPONSE_LEVEL, "RESPONSE")

_DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

def _standard_attrs() -> set[str]:
    record = _logging.makeLogRecord({})
    attrs = set(record.__dict__.keys())
    attrs.update({"message", "asctime"})
    return attrs


_STANDARD_ATTRS = _standard_attrs()

_COLOR_MAP = {
    _logging.DEBUG: "\033[36m",      # Cyan
    _logging.INFO: "\033[37m",       # Light gray
    _logging.WARNING: "\033[33m",    # Yellow
    _logging.ERROR: "\033[31m",      # Red
    _logging.CRITICAL: "\033[41m",   # Red background
    _PROMPT_LEVEL: "\033[91m",        # Red for prompts
    _RESPONSE_LEVEL: "\033[92m",      # Bright green
}
_RESET = "\033[0m"


@dataclass
class LoggingState:
    log_dir: Optional[str]
    text_log_path: Optional[str]
    jsonl_log_path: Optional[str]
    prompt_log_path: Optional[str]
    console_level: int
    file_level: int
    jsonl_enabled: bool
    prompt_trace_enabled: bool


_state: Optional[LoggingState] = None


def _parse_level(value: Optional[str], default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    value = value.upper()
    if value.isdigit():
        return int(value)
    try:
        return _logging._nameToLevel[value]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unknown log level: {value}") from exc


class _ColorFormatter(_logging.Formatter):
    def __init__(self, fmt: str, datefmt: Optional[str], use_color: bool) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.use_color = use_color

    def format(self, record: _logging.LogRecord) -> str:
        if getattr(record, "plain", False):
            return record.getMessage()
        message = super().format(record)
        if self.use_color:
            color = _COLOR_MAP.get(record.levelno)
            if color:
                message = f"{color}{message}{_RESET}"
        return message


class _MaxLevelFilter(_logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: _logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


class _JsonLinesFormatter(_logging.Formatter):
    def format(self, record: _logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, _DEFAULT_DATEFMT),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "pathname": record.pathname,
            "lineno": record.lineno,
            "func": record.funcName,
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                try:
                    json.dumps({key: value})
                    payload[key] = value
                except TypeError:
                    payload[key] = repr(value)
        return json.dumps(payload, ensure_ascii=False)


def _timestamped_filename(pattern: str, timestamp_format: str) -> str:
    now = _dt.datetime.now().strftime(timestamp_format)
    try:
        return pattern.format(timestamp=now, pid=os.getpid())
    except KeyError:
        # Fallback if unsupported placeholder used
        return pattern.format(timestamp=now)


def _resolve_log_dir(logging_cfg: Dict[str, Any], result_dir: Optional[str], override: Optional[str]) -> Optional[str]:
    if override:
        return os.path.abspath(override)
    cfg_dir = logging_cfg.get("dir")
    subdir = logging_cfg.get("subdir", "logs")
    base: Optional[str]
    if cfg_dir:
        base = cfg_dir if os.path.isabs(cfg_dir) else os.path.abspath(cfg_dir)
    elif result_dir:
        base = os.path.join(os.path.abspath(result_dir), subdir)
    else:
        base = os.path.join(os.getcwd(), subdir)
    return base


def get_logger(name: Optional[str] = None) -> _logging.Logger:
    if name is None:
        return _logging.getLogger(_LOGGER_NAMESPACE)
    if name.startswith(_LOGGER_NAMESPACE):
        full_name = name
    else:
        full_name = f"{_LOGGER_NAMESPACE}.{name}"
    return _logging.getLogger(full_name)


def log_llm_prompt(prompt: str) -> None:
    logger = get_logger(_LLM_LOGGER_NAME)
    logger.log(_PROMPT_LEVEL, prompt, extra={"llm_event": "prompt"})


def log_llm_response(response: str) -> None:
    logger = get_logger(_LLM_LOGGER_NAME)
    logger.log(_RESPONSE_LEVEL, response, extra={"llm_event": "response"})


def configure_logging(
    config: Dict[str, Any],
    *,
    result_dir: Optional[str] = None,
    console_level_override: Optional[str] = None,
    file_level_override: Optional[str] = None,
    log_dir_override: Optional[str] = None,
    disable_color: bool = False,
    enable_jsonl_override: Optional[bool] = None,
    prompt_log_override: Optional[bool] = None,
    force_reconfigure: bool = False,
) -> LoggingState:
    global _state

    logging_cfg: Dict[str, Any] = config.get("logging", {}) if config else {}

    console_level = _parse_level(console_level_override, _parse_level(logging_cfg.get("console_level"), _logging.INFO))
    file_level = _parse_level(file_level_override, _parse_level(logging_cfg.get("file_level"), _logging.DEBUG))

    use_color = logging_cfg.get("color", True) and not disable_color
    timestamp_format = logging_cfg.get("timestamp_format", "%Y%m%dT%H%M%S")
    pattern = logging_cfg.get("filename_pattern", "sactor-{timestamp}.log")

    jsonl_enabled = enable_jsonl_override if enable_jsonl_override is not None else logging_cfg.get("jsonl", False)
    prompt_trace_enabled = prompt_log_override if prompt_log_override is not None else logging_cfg.get("prompt_trace", False)

    log_dir = _resolve_log_dir(logging_cfg, result_dir, log_dir_override)
    text_log_path = None
    jsonl_log_path = None
    prompt_log_path = None

    logger = get_logger()
    if logger.handlers and not force_reconfigure:
        return _state  # type: ignore[return-value]

    logger.handlers.clear()
    logger.setLevel(min(console_level, file_level))
    logger.propagate = False

    stdout_handler = _logging.StreamHandler(stream=sys.stdout)
    stdout_handler.setLevel(console_level)
    stdout_handler.addFilter(_MaxLevelFilter(_logging.ERROR - 1))
    stdout_handler.setFormatter(_ColorFormatter(_DEFAULT_FORMAT, _DEFAULT_DATEFMT, use_color and sys.stdout.isatty()))
    logger.addHandler(stdout_handler)

    stderr_handler = _logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setLevel(max(console_level, _logging.ERROR))
    stderr_handler.setFormatter(_ColorFormatter(_DEFAULT_FORMAT, _DEFAULT_DATEFMT, use_color and sys.stderr.isatty()))
    logger.addHandler(stderr_handler)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        text_log_path = os.path.join(log_dir, _timestamped_filename(pattern, timestamp_format))
        file_handler = _logging.FileHandler(text_log_path, encoding="utf-8")
        file_handler.setLevel(file_level)
        file_handler.setFormatter(_logging.Formatter(_DEFAULT_FORMAT, _DEFAULT_DATEFMT))
        logger.addHandler(file_handler)

        if jsonl_enabled:
            jsonl_log_path = os.path.join(log_dir, _timestamped_filename(pattern.replace(".log", ".jsonl"), timestamp_format))
            json_handler = _logging.FileHandler(jsonl_log_path, encoding="utf-8")
            json_handler.setLevel(file_level)
            json_handler.setFormatter(_JsonLinesFormatter())
            logger.addHandler(json_handler)

        if prompt_trace_enabled:
            prompt_log_path = os.path.join(log_dir, _timestamped_filename("prompts-{timestamp}.log", timestamp_format))
            prompt_handler = _logging.FileHandler(prompt_log_path, encoding="utf-8")
            prompt_handler.setLevel(_PROMPT_LEVEL)
            prompt_handler.setFormatter(_logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", _DEFAULT_DATEFMT))
            prompt_logger = get_logger(_LLM_LOGGER_NAME)
            prompt_logger.addHandler(prompt_handler)
            prompt_logger.setLevel(min(_PROMPT_LEVEL, logger.level))
            prompt_logger.propagate = True

    else:
        prompt_logger = get_logger(_LLM_LOGGER_NAME)
        prompt_logger.setLevel(min(_PROMPT_LEVEL, logger.level))

    _state = LoggingState(
        log_dir=log_dir,
        text_log_path=text_log_path,
        jsonl_log_path=jsonl_log_path,
        prompt_log_path=prompt_log_path,
        console_level=console_level,
        file_level=file_level,
        jsonl_enabled=jsonl_enabled,
        prompt_trace_enabled=prompt_trace_enabled,
    )

    return _state


def get_logging_state() -> Optional[LoggingState]:
    return _state


def is_configured() -> bool:
    logger = get_logger()
    return bool(logger.handlers)
