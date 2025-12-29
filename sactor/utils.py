import os, copy
import hashlib
import shutil
import tempfile
import subprocess
from typing import List, Tuple, Optional, Sequence
from pathlib import Path
from importlib import resources
import re, shlex
import tomli as toml
import sys
import time
import select
from sactor import logging as sactor_logging
from sactor import rust_ast_parser
from sactor.data_types import DataType
from sactor.thirdparty.rustfmt import RustFmt
from collections import namedtuple
from dataclasses import dataclass

from clang.cindex import (
    Cursor,
    SourceLocation,
    SourceRange,
    CompilationDatabase,
    CompilationDatabaseError,
)

logger = sactor_logging.get_logger(__name__)

TO_TRANSLATE_C_FILE_MARKER = "_sactor_to_translate_.c"

_CONFIG_SENSITIVE_SUBSTRINGS = (
    "token",
    "secret",
    "password",
)

_CONFIG_SENSITIVE_EXACT = (
    "api_key",
    "access_key",
    "secret_key",
    "client_secret",
    "refresh_token",
)

_CONFIG_SENSITIVE_ALLOW = (
    "capabilities",
)
_SANITIZE_REDACTION_TOKEN = "***REDACTED***"


@dataclass(frozen=True)
class ConfigRedactionPolicy:
    deny_exact: tuple[str, ...] = _CONFIG_SENSITIVE_EXACT
    deny_substrings: tuple[str, ...] = _CONFIG_SENSITIVE_SUBSTRINGS
    allow_exact: tuple[str, ...] = _CONFIG_SENSITIVE_ALLOW

    def __post_init__(self) -> None:
        object.__setattr__(self, "_deny_exact_lower", {entry.lower() for entry in self.deny_exact})
        object.__setattr__(self, "_allow_exact_lower", {entry.lower() for entry in self.allow_exact})


        object.__setattr__(self, "_deny_substrings_lower", tuple(fragment.lower() for fragment in self.deny_substrings))

    def should_remove(self, key: str) -> bool:
        lowered = key.lower()
        if lowered in self._allow_exact_lower:
            return False
        if lowered in self._deny_exact_lower:
            return True
        for fragment in self._deny_substrings_lower:
            if fragment in lowered:
                return True
        return False


######## CLI / Path / LLM Stat Helpers ########
def _normalize_executable_object_arg(executable_object):
    if isinstance(executable_object, list):
        executable_object = [item for item in executable_object if item]
        if len(executable_object) == 1:
            return executable_object[0]
        if len(executable_object) == 0:
            return None
        return executable_object
    return executable_object


def _slug_for_path(path: str) -> str:
    rel_path = os.path.relpath(path, os.getcwd())
    sanitized = rel_path.replace(os.sep, "__")
    if os.altsep:
        sanitized = sanitized.replace(os.altsep, "__")
    sanitized = sanitized.replace("..", "__")
    digest = hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:8]
    return f"{sanitized}__{digest}"


def _derive_llm_stat_path(
    base_path: str,
    *,
    slug: str | None = None,
    stage: str | None = None,
) -> str:
    suffix_parts = []
    if slug:
        suffix_parts.append(slug)
    if stage:
        suffix_parts.append(stage)

    if os.path.isdir(base_path):
        filename = "llm_stat"
        if suffix_parts:
            filename = f"{filename}_{'_'.join(suffix_parts)}"
        filename = f"{filename}.json"
        return os.path.join(base_path, filename)

    if not suffix_parts:
        return base_path

    root, ext = os.path.splitext(base_path)
    suffix = "_".join(suffix_parts)
    if ext:
        return f"{root}_{suffix}{ext}"
    return f"{base_path}_{suffix}"

def _copy_resource_tree(resource_root, destination: Path) -> None:
    """Recursively copy a Traversable resource tree into the destination path."""
    def _copy(node, target: Path) -> None:
        if node.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            for child in node.iterdir():
                _copy(child, target / child.name)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with node.open("rb") as src, open(target, "wb") as dst:
                dst.write(src.read())

    destination_path = Path(destination)
    if destination_path.exists():
        shutil.rmtree(destination_path)
    destination_path.mkdir(parents=True, exist_ok=True)
    for child in resource_root.iterdir():
        _copy(child, destination_path / child.name)

def create_rust_proj(rust_code, proj_name, path, is_lib: bool, proc_macro=False):
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(os.path.join(path, "src"), exist_ok=True)

    manifest = f'''
[package]
name = "{proj_name}"
version = "0.1.0"
edition = "2021"

[dependencies]
libc = "0.2.159"'''
    if proc_macro:
        manifest += '''
sactor_proc_macros = { path = "./sactor_proc_macros" }'''

    if is_lib:
        manifest += f'''
[lib]
name = "{proj_name}"
crate-type = ["cdylib"]'''

    with open(f"{path}/Cargo.toml", "w") as f:
        f.write(manifest)

    if is_lib:
        with open(f"{path}/src/lib.rs", "w") as f:
            f.write(rust_code)
    else:
        with open(f"{path}/src/main.rs", "w") as f:
            f.write(rust_code)

    if proc_macro:
        macros_destination = Path(path) / "sactor_proc_macros"
        copied = False
        try:
            macros_resource = resources.files("sactor._resources").joinpath("sactor_proc_macros")
            if macros_resource.is_dir():
                _copy_resource_tree(macros_resource, macros_destination)
                copied = True
        except Exception:
            logger.debug("Unable to copy proc macros from packaged resources", exc_info=True)

        if not copied:
            raise FileNotFoundError("Could not locate sactor_proc_macros resources")


def get_temp_dir():
    tmpdir = tempfile.gettempdir()
    os.makedirs(os.path.join(tmpdir, "sactor"), exist_ok=True)
    new_tmp_dir = tempfile.mkdtemp(dir=os.path.join(tmpdir, "sactor"))
    # tmpdir = '/tmp/sactor'
    return new_tmp_dir


def parse_llm_result(llm_result, *args):
    '''
    Parse the result from LLM.

    Expected format (case-insensitive, dashes/underscores/spaces optional):
    ----ARG----
    content
    ----END ARG----
    '''

    def _canonical_tag(s: str) -> Optional[str]:
        trimmed = s.strip()
        if not trimmed:
            return None
        trimmed = trimmed.rstrip(":.")
        if not trimmed:
            return None
        if not re.fullmatch(r"[A-Za-z0-9\s\-_`]+", trimmed):
            return None
        canonical = re.sub(r"[\s\-_`]+", "", trimmed)
        return canonical.upper() or None

    res = {}
    lines = llm_result.split("\n")
    for arg in args:
        start_token = re.sub(r"[\s\-_`]+", "", arg.upper())
        end_token = f"END{start_token}"
        in_arg = False
        start_found = False
        arg_result = ""

        for line in lines:
            tag = _canonical_tag(line)
            if not in_arg:
                if tag == start_token:
                    in_arg = True
                    start_found = True
                continue

            if tag == end_token:
                in_arg = False
                break

            stripped_line = line.strip()
            if stripped_line.startswith("```") or stripped_line.startswith("~~~"):
                continue
            arg_result += line + "\n"

        if not start_found:
            raise ValueError(f"Could not find {arg}")
        if in_arg:
            raise ValueError(f"Could not find end of {arg}")
        if arg_result == "":
            raise ValueError(f"Empty result for {arg}")
        logger.debug("Generated %s:", arg)
        logger.debug("%s", arg_result)
        res[arg] = arg_result
    return res


def save_code(path, code):
    path_dir = os.path.dirname(path)
    os.makedirs(path_dir, exist_ok=True)
    with open(path, "w") as f:
        f.write(code)
    rustfmt = RustFmt(path)
    try:
        rustfmt.format()
    except Exception:
        logger.warning("Cannot format the code")  # allow to continue


def format_rust_snippet(code: str) -> str:
    """Return the rustfmt-formatted version of `code` when possible."""

    try:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "snippet.rs")
            save_code(path, code)
            with open(path, "r") as f:
                return f.read().rstrip()
    except Exception:
        pass
    return code


def _merge_configs(config, default_config):
    config_out = {}

    for key, default_value in default_config.items():
        if key in config:
            if isinstance(config[key], dict) and isinstance(default_value, dict):
                config_out[key] = _merge_configs(config[key], default_value)
            elif isinstance(config[key], dict) or isinstance(default_value, dict):
                raise TypeError(f"Type mismatch for key '{key}': "
                                f"config has {type(config[key])}, default_config has {type(default_value)}")
            # Otherwise, config[key] takes precedence
            else:
                config_out[key] = config[key]
        else:
            config_out[key] = default_value

    # Add keys that are only in config
    for key, value in config.items():
        if key not in default_config:
            config_out[key] = value

    return config_out


def load_default_config():
    """Load the bundled default configuration from packaged resources."""
    resource_dir = Path(__file__).resolve().parent / "_resources"
    candidate = resource_dir / "sactor.default.toml"
    if candidate.is_file():
        with open(candidate, "rb") as f:
            return toml.load(f)

    raise FileNotFoundError("Could not load _resources/sactor.default.toml")


def load_spec_schema_text() -> str:
    """Return the spec schema JSON text from packaged resources.

    Raises FileNotFoundError if the schema cannot be located.
    """
    try:
        schema_resource = resources.files("sactor.verifier.spec").joinpath("schema.json")
        with schema_resource.open("r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        pass

    fallback = Path(__file__).resolve().parent / "verifier" / "spec" / "schema.json"
    if fallback.is_file():
        return fallback.read_text(encoding="utf-8")

    raise FileNotFoundError("Could not locate verifier/spec/schema.json")


def try_load_config(config_file=None):
    """Load user configuration merged with defaults.

    Resolution order:
    1. Explicit `config_file` argument.
    2. `SACTOR_CONFIG` environment variable.
    3. `./sactor.toml` relative to current working directory.
    4. `sactor.toml` inside the repository checkout (development mode).
    If none are found, return the default config alone.
    """
    default_config = load_default_config()

    def _load_user_config(path: Path) -> dict:
        with open(path, "rb") as f:
            return toml.load(f)

    if config_file:
        candidate = Path(config_file).expanduser()
        if not candidate.is_file():
            raise FileNotFoundError(f"Could not find config file {candidate}")
        user_config = _load_user_config(candidate)
        return _merge_configs(user_config, default_config)

    env_candidate = os.environ.get("SACTOR_CONFIG")
    if env_candidate:
        env_path = Path(env_candidate).expanduser()
        if not env_path.is_file():
            raise FileNotFoundError(f"SACTOR_CONFIG={env_candidate} does not point to a readable file")
        user_config = _load_user_config(env_path)
        return _merge_configs(user_config, default_config)

    cwd_candidate = Path.cwd() / "sactor.toml"
    if cwd_candidate.is_file():
        user_config = _load_user_config(cwd_candidate)
        return _merge_configs(user_config, default_config)

    # Load from repository root if in development mode
    package_dir = Path(__file__).resolve().parent
    repo_candidate = package_dir.parent / "sactor.toml"
    if repo_candidate.is_file():
        user_config = _load_user_config(repo_candidate)
        return _merge_configs(user_config, default_config)

    logger.info("No user config found; falling back to default configuration only")
    return default_config


def normalize_string(output: str) -> str:
    lines = output.splitlines()
    for i, line in enumerate(lines):
        lines[i] = line.strip()
    return '\n'.join(lines)


def rename_rust_function_signature(signature: str, old_name: str, new_name: str, data_type: DataType) -> str:
    has_tail_comma = False
    if signature.strip().endswith(";"):
        signature = signature.replace(";", "")
        has_tail_comma = True

    signature = signature + "{}"
    match data_type:
        case DataType.FUNCTION:
            signature = rust_ast_parser.rename_function(
                signature, old_name, new_name)
        case DataType.UNION:
            signature = rust_ast_parser.rename_struct_union(
                signature, old_name, new_name)
        case DataType.STRUCT:
            signature = rust_ast_parser.rename_struct_union(
                signature, old_name, new_name)
        case _:
            raise ValueError(f"Unknown data type {data_type}")

    # remove {}
    signature = signature.replace("{}", "").strip()

    if has_tail_comma:
        signature = signature + ";"

    return signature


def get_compiler() -> str:
    if shutil.which("clang"):
        compiler = "clang"
    elif shutil.which("gcc"):
        compiler = "gcc"
    else:
        raise OSError("No C compiler found")

    return compiler


def get_compiler_include_paths() -> list[str]:
    compiler = get_compiler()
    cmd = [compiler, '-v', '-E', '-x', 'c', '/dev/null']
    result = run_command(cmd)
    compile_output = result.stderr
    search_include_paths = []

    add_include_path = False
    for line in compile_output.split('\n'):
        if line.startswith('#include <...> search starts here:'):
            add_include_path = True
            continue
        if line.startswith('End of search list.'):
            break

        if add_include_path:
            search_include_paths.append(line.strip())

    return search_include_paths

def is_compile_command(command: List[str]) -> bool:
    """Return True if the command invokes a C compiler (gcc/clang/cc variants)."""
    if not command:
        return False
    compilers = ("gcc", "clang", "cc")
    for token in command:
        if not isinstance(token, str):
            continue
        name = os.path.basename(token)
        lower = name.lower()
        if any(comp in lower for comp in compilers):
            return True
    return False

def load_compile_commands_from_file(path: str, to_translate_file: str) -> List[List[str]]:
    """Load compile commands for the target C file using libclang's compilation database."""
    if not path:
        return []
    if not os.path.exists(path):
        raise FileNotFoundError(f"compile commands file not found: {path}")

    compile_commands_dir = os.path.realpath(os.path.dirname(path))
    target_abs = os.path.realpath(to_translate_file)
    if not os.path.exists(target_abs):
        raise FileNotFoundError(f"Target source file not found: {to_translate_file}")

    try:
        database = CompilationDatabase.fromDirectory(compile_commands_dir)
    except CompilationDatabaseError as exc:
        raise ValueError(
            f"Failed to load compilation database from {compile_commands_dir}: {exc}"
        ) from exc

    try:
        entries_iter = database.getCompileCommands(target_abs)
    except CompilationDatabaseError as exc:
        raise ValueError(
            f"Failed to retrieve compile commands for {target_abs}: {exc}"
        ) from exc

    entries = list(entries_iter or [])
    if not entries:
        raise ValueError(
            f"No compile commands for {to_translate_file} found in {path}"
        )

    command_lines: list[str] = []
    for entry in entries:
        working_dir = entry.directory or compile_commands_dir
        args = [str(arg) for arg in entry.arguments]
        if "--" in args:
            continue
        filename_abs = entry.filename
        if filename_abs and not os.path.isabs(filename_abs):
            filename_abs = os.path.realpath(os.path.join(working_dir, filename_abs))
        else:
            filename_abs = os.path.realpath(filename_abs) if filename_abs else filename_abs
        if filename_abs:
            try:
                if not os.path.samefile(filename_abs, target_abs):
                    continue
            except FileNotFoundError:
                continue
        normalized: list[str] = []
        for token in args:
            if token == entry.filename:
                normalized.append(filename_abs if filename_abs else token)
                continue
            if token.endswith(".c") and not os.path.isabs(token):
                normalized.append(os.path.realpath(os.path.join(working_dir, token)))
                continue
            normalized.append(token)
        command_lines.append(shlex.join(normalized))

    deduped_lines = list(dict.fromkeys(command_lines))
    if not deduped_lines:
        raise ValueError(
            f"No compile commands for {to_translate_file} found in {path}"
        )
    return process_commands_to_list("\n".join(deduped_lines), target_abs)


def list_c_files_from_compile_commands(path: str) -> list[str]:
    """Return all distinct .c translation units described by compile_commands.json."""
    if not path:
        return []
    if not os.path.exists(path):
        raise FileNotFoundError(f"compile commands file not found: {path}")

    compile_commands_dir = os.path.realpath(os.path.dirname(path))
    try:
        database = CompilationDatabase.fromDirectory(compile_commands_dir)
    except CompilationDatabaseError as exc:
        raise ValueError(
            f"Failed to load compilation database from {compile_commands_dir}: {exc}"
        ) from exc

    try:
        entries = database.getAllCompileCommands()
    except CompilationDatabaseError as exc:
        raise ValueError(
            f"Failed to enumerate compile commands from {compile_commands_dir}: {exc}"
        ) from exc

    files: list[str] = []
    seen: set[str] = set()
    for entry in entries or []:
        args = [str(arg) for arg in entry.arguments]
        if "--" in args:
            continue
        filename = entry.filename
        if not filename:
            continue
        directory = entry.directory or compile_commands_dir
        if not os.path.isabs(filename):
            filename_abs = os.path.realpath(os.path.join(directory, filename))
        else:
            filename_abs = os.path.realpath(filename)
        if not filename_abs.lower().endswith(".c"):
            continue
        if not os.path.exists(filename_abs):
            continue
        if filename_abs in seen:
            continue
        seen.add(filename_abs)
        files.append(filename_abs)
    return files

def process_commands_to_list(commands: str, to_translate_file: str) -> List[List[str]]:
    result: list[list[str]] = []
    target_abs = os.path.realpath(to_translate_file)
    for line in commands.splitlines():
        line = line.strip()
        if not line:
            continue
        command = shlex.split(line)
        replaced_target = False
        for i, item in enumerate(command[:]):
            if item.endswith(".c"):
                try:
                    if os.path.samefile(item, target_abs):
                        command[i] = TO_TRANSLATE_C_FILE_MARKER
                        replaced_target = True
                        continue
                except FileNotFoundError:
                    pass
        if replaced_target:
            command.extend(("-Og", "-g"))
        result.append(command)
    return result


def process_commands_to_compile(commands: List[List[str]], output_path: str, source_path: str | list[str]) -> List[List[str]]:
    commands = copy.deepcopy(commands)
    for i, command in enumerate(commands[:]):
        if is_compile_command(command):
            replaced_marker = False
            for j, item in enumerate(command[:]):
                if item == TO_TRANSLATE_C_FILE_MARKER:
                    command[j] = source_path
                    replaced_marker = True
            if replaced_marker:
                if isinstance(source_path, list):
                    flatten_command = []
                    for token in command:
                        if isinstance(token, list):
                            flatten_command.extend(token)
                        else:
                            flatten_command.append(token)
                    command = flatten_command
                if "-c" not in command:
                    command.append("-c")
                try:
                    out_idx = command.index("-o")
                except ValueError:
                    command.extend(["-o", output_path])
                else:
                    if out_idx + 1 < len(command):
                        command[out_idx + 1] = output_path
                    else:
                        command.append(output_path)
                commands[i] = command
    return commands


def compile_c_code(
    file_path: str,
    commands: list[list[str]],
    link_args: Optional[Sequence[str]] = None,
    is_library: bool = False,
) -> str:
    '''
    Compile a C file to a executable file, return the path to the executable

    commands: compilation command for a C file. If it requires multiple commands sequentially, separate the commands by newlines.
    The last command if it contains (`gcc` or `clang`) and `-o [path]`, [path] will be replaced by `executable_path` as defined in the function.
    All gcc or libtool will be added -Og -g flags.
    '''
    compiler = get_compiler()
    tmpdir = os.path.join(get_temp_dir(), "c_compile")
    os.makedirs(tmpdir, exist_ok=True)
    executable_path = os.path.join(
        tmpdir, os.path.basename(file_path) + ".out")
    object_path = executable_path + ".o"

    processed_commands = process_commands_to_compile(commands, object_path, file_path)
    if processed_commands:
        for command in processed_commands:
            to_check = False
            if is_compile_command(command):
                to_check = True
                if "-ftrapv" not in command:
                    command.append("-ftrapv")
            run_command(command, capture_output=False, check=to_check)
        if not is_library:
            link_cmd = [
                compiler,
                object_path,
                '-o',
                executable_path,
            ]
            if link_args:
                link_cmd.extend(link_args)
            run_command(link_cmd, capture_output=False, check=True)
        return object_path if is_library else executable_path
    else:
        cmd = [
            compiler,
            file_path,
            '-o',
            executable_path,
            '-ftrapv',  # enable overflow checking
        ]
        if is_library:
            cmd.append('-c')  # compile to object file instead of executable
        if link_args:
            cmd.extend(link_args)
        run_command(cmd, capture_output=False, check=True)  # raise exception if failed

    return executable_path


# Workaround for bug in clang.cindex: cursor.get_tokens() return empty list if macro is used
# https://github.com/llvm/llvm-project/issues/43451
# https://github.com/llvm/llvm-project/issues/68340
def cursor_get_tokens(cursor: Cursor):
    tu = cursor.translation_unit

    start = cursor.extent.start
    start = SourceLocation.from_position(
        tu, start.file, start.line, start.column)

    end = cursor.extent.end
    end = SourceLocation.from_position(tu, end.file, end.line, end.column)

    extent = SourceRange.from_locations(start, end)

    yield from tu.get_tokens(extent=extent)

def try_backup_file(file_path):
    if not os.path.exists(file_path):
        return
    backup_path = file_path + ".bak"
    number = 1
    while os.path.exists(backup_path):
        backup_path = file_path + f".bak.{number}"
        number += 1

    os.rename(file_path, backup_path)


################################
# Utils for c parser
################################
def load_text_with_mappings(path: str, encoding: str = 'utf-8'):
    """
    Read a text file as both bytes and string and build offset mappings.

    Returns a tuple (text_str, data_bytes, b2s, s2b) where:
    - text_str: the file decoded as a Python string using the given encoding
    - data_bytes: the raw file content in bytes
    - b2s: list mapping byte offset -> string index (codepoint index)
    - s2b: list mapping string index -> byte offset
    """
    with open(path, 'rb') as f:
        data_bytes = f.read()
    text_str = data_bytes.decode(encoding, errors='strict')
    b_len = len(data_bytes)
    s_len = len(text_str)
    b2s = [0] * (b_len + 1)
    s2b = [0] * (s_len + 1)
    byte_pos = 0
    for i, ch in enumerate(text_str):
        s2b[i] = byte_pos
        bl = len(ch.encode(encoding))
        for k in range(bl):
            if byte_pos + k <= b_len:
                b2s[byte_pos + k] = i
        byte_pos += bl
    s2b[s_len] = b_len
    b2s[b_len] = s_len
    return text_str, data_bytes, b2s, s2b


def byte_to_str_index(b2s: list[int], b_off: int) -> int:
    """
    Convert a byte offset (from libclang extents) to a Python string index
    using a precomputed byte->string mapping.
    """
    if b_off < 0:
        return 0
    if b_off >= len(b2s):
        return b2s[-1]
    return b2s[b_off]


def scan_ws_semicolon_bytes(data: bytes, pos: int) -> int:
    """
    From a byte position, skip ASCII whitespace and one optional semicolon.

    Returns the new byte position after skipping.
    """
    n = len(data)
    while pos < n and data[pos:pos+1] in (b' ', b'\t', b'\n', b'\r'):
        pos += 1
    if pos < n and data[pos:pos+1] == b';':
        pos += 1
    return pos

def get_compile_flags_from_commands(processed_compile_commands: List[List[str]]) -> list[str]:
    """To get only the compile flags, for the C source file. If they have specific linking flags, this function does not care."""
    processed_commands = copy.deepcopy(processed_compile_commands)
    cmd = []
    # assume the first command mentioning the to-be-translated C source is the command containing the flags.
    # TODO: This code assumes that the first such command is either a compile command or a compile-and-linking command. Add checks to test
    #       if it is.
    for cmd2 in processed_commands:
        if TO_TRANSLATE_C_FILE_MARKER in cmd2:
            cmd = cmd2
            break
    processed_commands = cmd
    flags =  list(filter(lambda s: s.startswith("-"), processed_commands))
    # flags for macro-expanding C source files with tests
    del_index = []
    for i, flag in enumerate(flags):
        if flag == "-o" or flag == '-c' or flag.startswith("-M"):
            del_index.append(i)
    for i in del_index[::-1]:
        del flags[i]
    # flags for macro-expanding C source files without tests. We remove test flags if they are wrongly included by the input.
    del_index = []
    for i, flag in enumerate(flags):
        if re.search(r"-D[\w\d_]*?TEST", flag) :
            del_index.append(i)
    for i in del_index[::-1]:
        del flags[i]
    flags_without_tests = flags
    return flags_without_tests

def read_file(path: str) -> str:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Could not find file {path}")
    with open(path, "r") as f:
        return f.read()

def read_file_lines(path: str) -> List[str]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Could not find file {path}")
    with open(path, "r") as f:
        return f.readlines()

def patched_env(key, value, env=None):
    if env is None:
        env = os.environ.copy()
    old_value = None
    if key in env:
        old_value = env[key]
    env[key] = value if old_value is None else f"{value}:{old_value}"
    return env


def sanitize_config(
    obj: dict | list | str | int | float | bool | None,
    *,
    redact: bool = False,
    policy: ConfigRedactionPolicy | None = None,
) -> dict | list | str | int | float | bool | None:
    """Recursively sanitize configuration structures.

    When ``redact`` is False (default), sensitive keys are removed entirely.
    When ``redact`` is True, sensitive keys are retained but their values are
    replaced with a redaction token.
    """

    active_policy = policy or ConfigRedactionPolicy()

    if isinstance(obj, dict):
        cleaned: dict = {}
        for key, value in obj.items():
            if active_policy.should_remove(key):
                if redact:
                    cleaned[key] = _SANITIZE_REDACTION_TOKEN
                continue
            cleaned[key] = sanitize_config(value, redact=redact, policy=active_policy)
        return cleaned

    if isinstance(obj, list):
        return [sanitize_config(item, redact=redact, policy=active_policy) for item in obj]

    return obj

ProcessResult = namedtuple("ProcessResult", ["stdout", "stderr", "returncode"])


def _extend_with_limit(buffer: bytearray, chunk: bytes, limit: int) -> bool:
    """Append ``chunk`` into ``buffer`` up to ``limit`` bytes.

    Returns ``True`` when the incoming chunk exceeded the remaining capacity.
    """

    if limit <= 0:
        return True
    remaining = limit - len(buffer)
    if remaining <= 0:
        return True
    buffer.extend(chunk[:remaining])
    return len(chunk) > remaining


def _run_command_streaming(
    cmd: Sequence[str | os.PathLike[str]],
    *,
    limit_bytes: int,
    time_limit_sec: float | None,
    env: dict[str, str] | None,
    cwd: str | os.PathLike[str] | None,
    text: bool,
) -> ProcessResult:
    if limit_bytes is None or limit_bytes <= 0:
        raise ValueError("limit_bytes must be a positive integer")

    configured_time_limit = time_limit_sec
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        env=env,
        cwd=cwd,
        text=False,
    )

    stdout_buf = bytearray()
    stderr_buf = bytearray()
    timed_out = False
    start_time = time.monotonic()
    streams = []
    if process.stdout is not None:
        streams.append(process.stdout)
    if process.stderr is not None:
        streams.append(process.stderr)

    while streams:
        now = time.monotonic()
        if time_limit_sec is not None and now - start_time >= time_limit_sec:
            timed_out = True
            logger.warning(
                "Time limit reached (%.2fs); terminating process",
                configured_time_limit,
            )
            process.terminate()
            time_limit_sec = None  # avoid repeated termination attempts

        timeout = None
        if time_limit_sec is not None:
            timeout = max(0.0, min(0.2, time_limit_sec - (now - start_time)))

        readable, _, _ = select.select(streams, [], [], timeout)
        if not readable:
            if process.poll() is not None:
                # Drain any remaining data after process exit.
                for stream in list(streams):
                    chunk = stream.read()
                    if chunk:
                        truncated = _extend_with_limit(
                            stdout_buf if stream is process.stdout else stderr_buf,
                            chunk,
                            limit_bytes,
                        )
                        if truncated:
                            logger.warning(
                                "%s byte limit reached (%d bytes); terminating process",
                                "Stdout" if stream is process.stdout else "Stderr",
                                limit_bytes,
                            )
                            if process.poll() is None:
                                process.terminate()
                    else:
                        streams.remove(stream)
            continue

        for stream in readable:
            chunk = stream.read(4096)
            if not chunk:
                streams.remove(stream)
                continue
            buffer = stdout_buf if stream is process.stdout else stderr_buf
            truncated = _extend_with_limit(buffer, chunk, limit_bytes)
            if truncated:
                logger.warning(
                    "%s byte limit reached (%d bytes); terminating process",
                    "Stdout" if stream is process.stdout else "Stderr",
                    limit_bytes,
                )
                if process.poll() is None:
                    process.terminate()

        if process.poll() is not None:
            # Allow loop to drain remaining buffered data on next iteration.
            continue

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    returncode = process.poll()
    if timed_out:
        raise TimeoutError(
            "Time limit exceeded while running command"
            if configured_time_limit is None
            else f"Time limit ({configured_time_limit:.2f}s) exceeded while running command"
        )

    stdout_bytes = bytes(stdout_buf[:limit_bytes])
    stderr_bytes = bytes(stderr_buf[:limit_bytes])
    if text:
        return ProcessResult(
            stdout_bytes.decode(errors="ignore"),
            stderr_bytes.decode(errors="ignore"),
            returncode if returncode is not None else 0,
        )
    return ProcessResult(stdout_bytes, stderr_bytes, returncode if returncode is not None else 0)

def run_command(
    cmd: Sequence[str | os.PathLike[str]],
    *,
    capture_output: bool = True,
    text: bool = True,
    timeout: float | None = None,
    limit_bytes: int | None = None,
    env: dict[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
    check: bool = False,
    input_data: str | bytes | None = None,
) -> ProcessResult:
    """
    Unified command execution helper.

    Streams output when ``limit_bytes`` is provided, enforcing byte/time limits.
    Otherwise delegates to ``subprocess.run`` with consistent return semantics.
    """
    if limit_bytes is not None:
        if not capture_output:
            raise ValueError("capture_output must be True when enforcing byte limits")
        if input_data is not None:
            raise ValueError("stdin input is not supported when limit_bytes is set")
        time_limit = timeout if timeout is not None else 300
        result = _run_command_streaming(
            cmd,
            limit_bytes=limit_bytes,
            time_limit_sec=time_limit,
            env=env,
            cwd=cwd,
            text=text,
        )
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        return result

    completed = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        env=env,
        cwd=cwd,
        text=text,
        timeout=timeout,
        check=False,
        input=input_data,
    )
    stdout = completed.stdout if capture_output and completed.stdout is not None else ""
    stderr = completed.stderr if capture_output and completed.stderr is not None else ""
    result = ProcessResult(stdout, stderr, completed.returncode)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, stdout, stderr)
    return result
