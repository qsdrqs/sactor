import os, copy
import shutil
import tempfile
import subprocess
from typing import List, Tuple, Optional
from pathlib import Path
from importlib import resources
import re, shlex
import tomli as toml
from clang.cindex import Cursor, SourceLocation, SourceRange
import sys
import time
import select
from sactor import logging as sactor_logging
from sactor import rust_ast_parser
from sactor.data_types import DataType
from sactor.thirdparty.rustfmt import RustFmt
from collections import namedtuple


logger = sactor_logging.get_logger(__name__)

TO_TRANSLATE_C_FILE_MARKER = "_sactor_to_translate_.c"
_PROJECT_ROOT_CACHE: Optional[str] = None


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
            proj_root = Path(find_project_root())
            fallback_macros = proj_root / "sactor_proc_macros"
            if fallback_macros.is_dir():
                shutil.copytree(fallback_macros, macros_destination)
                copied = True

        if not copied:
            raise FileNotFoundError("Could not locate sactor_proc_macros resources")


def find_project_root() -> str:
    global _PROJECT_ROOT_CACHE
    if _PROJECT_ROOT_CACHE:
        return _PROJECT_ROOT_CACHE

    env_root = os.environ.get("SACTOR_ROOT")
    if env_root:
        env_path = Path(env_root).expanduser()
        if env_path.is_dir():
            _PROJECT_ROOT_CACHE = str(env_path.resolve())
            return _PROJECT_ROOT_CACHE
        logger.warning("SACTOR_ROOT=%s does not point to a directory", env_root)

    current = Path(__file__).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            _PROJECT_ROOT_CACHE = str(candidate)
            return _PROJECT_ROOT_CACHE

    package_root = current.parent
    _PROJECT_ROOT_CACHE = str(package_root)
    logger.debug("Falling back to package directory for project root: %s", package_root)
    return _PROJECT_ROOT_CACHE


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
    """Load the bundled default configuration, falling back to repo checkout."""
    project_default = Path(find_project_root()) / "sactor.default.toml"
    candidates = [project_default]
    try:
        candidates.append(resources.files("sactor._resources").joinpath("sactor.default.toml"))
    except Exception:
        logger.debug("Packaged default config not found via importlib.resources", exc_info=True)

    for candidate in candidates:
        try:
            if hasattr(candidate, "open"):
                with candidate.open("rb") as f:
                    return toml.load(f)
            candidate_path = Path(candidate)
            if candidate_path.is_file():
                with open(candidate_path, "rb") as f:
                    return toml.load(f)
        except FileNotFoundError:
            continue
        except Exception:
            logger.debug("Failed to load default config from %s", candidate, exc_info=True)

    raise FileNotFoundError("Could not load sactor.default.toml")


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

    project_candidate = Path(find_project_root()) / "sactor.toml"
    if project_candidate.is_file():
        user_config = _load_user_config(project_candidate)
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
    result = subprocess.run(cmd, stderr=subprocess.PIPE,
                            stdout=subprocess.DEVNULL)
    compile_output = result.stderr.decode()
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

def is_compile_command(l: List[str]) -> bool:
    """Return True if it is a compile or link command. Otherwise, False"""
    if "gcc" in l or "clang" in l:
        return True
    return False

def process_commands_to_list(commands: str, to_translate_file: str) -> List[List[str]]:
    # parse into list of list of str
    commands = list(map(lambda s: shlex.split(s), filter(lambda s: len(s) > 0, commands.splitlines())))
    # add -Og -g flags to all compiler commands
    for command in commands:
        if is_compile_command(command):
            for i, item in enumerate(command[:]):
                if item.endswith(".c") and os.path.samefile(item, to_translate_file):
                    command[i] = TO_TRANSLATE_C_FILE_MARKER
            # The last -O flag overrides all previous -O flags, so don't need to care previous ones
            command.extend(("-Og", "-g"))

    return commands


def process_commands_to_compile(commands: List[List[str]], executable_path: str, source_path: str | list[str]) -> List[List[str]]:
    commands = copy.deepcopy(commands)
    for i, command in enumerate(commands[:]):
        if is_compile_command(command):
            for j, item in enumerate(command[:]):
                if item == TO_TRANSLATE_C_FILE_MARKER:
                        command[j] = source_path
            if isinstance(source_path, list):
                flatten_command = []
                for item in command:
                    if isinstance(item, list):
                        flatten_command.extend(item)
                    else:
                        flatten_command.append(item)
                commands[i] = flatten_command

    # The last command if it contains (`gcc` or `clang`) and `-o [path]`, [path] will be replaced by `executable_path` as defined in the function.
    if commands and is_compile_command(commands[-1]):
        try:
            i = commands[-1].index("-o")
        except ValueError:
            commands[-1].extend(("-o", executable_path))
        else:
            commands[-1][i + 1] = executable_path
    return commands


def compile_c_code(file_path: str, commands: list[list[str]], is_library=False) -> str:
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

    commands = process_commands_to_compile(commands, executable_path, file_path)
    if commands:
        for command in commands:
            to_check = False
            if is_compile_command(command):
                to_check = True
                command.append("-ftrapv")
                if is_library:
                    command.append("-c")
            _result = subprocess.run(command, check=to_check)
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
        subprocess.run(cmd, check=True)  # raise exception if failed

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

def remove_keys_from_collection(src: dict | list, blacklist: set[str] | None = None) -> dict | list:
    blacklist = set() if not blacklist else blacklist
    blacklist.add("key")
    if type(src) == dict:
        result = {}
        for key, value in src.items():
            keep = True
            for banned in blacklist:
                if banned in key:
                    keep = False
                    break
            if keep:
                ty_value = type(value)
                if ty_value == dict or ty_value == list:
                    value = remove_keys_from_collection(value, blacklist)
                result[key] = value
    elif type(src) == list:
        result = []
        for item in src:
            ty = type(item)
            if ty == dict or ty == list:
                item = remove_keys_from_collection(item, blacklist)
            result.append(item)
    else:
        raise TypeError("Type must be dict or list")
    return result

ProcessResult = namedtuple("ProcessResult", ["stdout", "stderr", "returncode"])

def run_command_with_limit(cmd, limit_bytes=40000, time_limit_sec=300, **kwargs) -> ProcessResult:
    """
    Run a command and capture its stdout in real-time.
    Stop when limit_bytes bytes are read or time_limit_sec have elapsed.
    This is useful when a command returns too much output, causing out-of-memory errors.
    """
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=4096,
        text=False,
        **kwargs
    )
    captured_out, captured_err = bytearray(), bytearray()
    start_time = time.monotonic()
    returncode = 0
    is_timeout = False
    def read_available() -> Tuple[None | bytes, None | bytes, None | int]:
        rlist, _, _ = select.select([process.stdout, process.stderr], [], [], 0.5)
        out, err = None, None
        for r in rlist:
            if r is process.stdout:
                out = r.read(4096)
            elif r is process.stderr:
                err = r.read(4096)
            else:
                raise TypeError("Unexpected elements in rlist")
        return out, err
    try:
        forced_terminate = False
        while True:
            # --- time check ---
            elapsed = time.monotonic() - start_time
            if elapsed >= time_limit_sec:
                print("\n--- Time limit reached, terminating process ---", file=sys.stderr)
                process.terminate()
                forced_terminate = True
                is_timeout = True
                break
            out, err = read_available()
            if out is None and err is None:
                continue  # no data yet; check time again
            if out == b"" and err == b"":  # EOF
                break
            if out:
                captured_out.extend(out)
            if err:
                captured_err.extend(err)
            if len(captured_out) >= limit_bytes:
                print("\n--- Stdout byte limit reached, terminating process ---", file=sys.stderr)
                process.terminate()
                forced_terminate = True
                break
            if len(captured_err) >= limit_bytes:
                print("\n--- Stderr byte limit reached, terminating process ---", file=sys.stderr)
                process.terminate()
                forced_terminate = True
                break
        # wait briefly for exit
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            forced_terminate = True
        finally:
            if not forced_terminate:
                returncode = process.returncode

    finally:
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
    if is_timeout:
        raise TimeoutError(f"Time limit ({time_limit_sec} s) reached")
    out_text = bytes(captured_out[:limit_bytes]).decode(errors="ignore")
    err_text = bytes(captured_err[:limit_bytes]).decode(errors="ignore")
    return ProcessResult(out_text, err_text, returncode)
