import os, copy
import shutil
import tempfile
import subprocess
from typing import List, Tuple
import re, shlex
import tomli as toml
from clang.cindex import Cursor, SourceLocation, SourceRange

from sactor import rust_ast_parser
from sactor.data_types import DataType
from sactor.thirdparty.rustfmt import RustFmt

TO_TRANSLATE_C_FILE_MARKER = "_sactor_to_translate_.c"

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
        proj_root = find_project_root()
        sactor_proc_macros_path = os.path.join(proj_root, "sactor_proc_macros")
        # Copy sactor_proc_macros to the project
        shutil.copytree(sactor_proc_macros_path,
                        os.path.join(path, "sactor_proc_macros"))


def find_project_root():
    path = os.path.dirname(os.path.realpath(__file__))
    while path != "/":
        if os.path.exists(os.path.join(path, "pyproject.toml")):
            return path
        path = os.path.dirname(path)
    raise RuntimeError("Could not find project root")


def get_temp_dir():
    tmpdir = tempfile.gettempdir()
    os.makedirs(os.path.join(tmpdir, "sactor"), exist_ok=True)
    new_tmp_dir = tempfile.mkdtemp(dir=os.path.join(tmpdir, "sactor"))
    # tmpdir = '/tmp/sactor'
    return new_tmp_dir


def parse_llm_result(llm_result, *args):
    '''
    Parse the result from LLM

    Need to be formatted as:
    ----ARG----
    content
    ----END ARG----
    '''
    res = {}
    for arg in args:
        in_arg = False
        arg_result = ""
        for line in llm_result.split("\n"):
            # prevent hallucination to different length of dashes
            if line.find(f"-{arg.upper()}-") != -1 and not in_arg:
                in_arg = True
                continue
            if line.find(f"-END {arg.upper()}-") != -1 and in_arg:
                in_arg = False
                continue
            if in_arg and '```' not in line:
                arg_result += line + "\n"
        if arg_result == "":
            raise ValueError(f"Could not find {arg}")
        if in_arg:
            raise ValueError(f"Could not find end of {arg}")
        print(f"Generated {arg}:")
        print(arg_result)
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
        print("Cannot format the code")  # allow to continue


def print_red(s):
    print("\033[91m {}\033[00m".format(s))


def print_green(s):
    print("\033[92m {}\033[00m".format(s))


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
    proj_root = find_project_root()
    # load default config
    if not os.path.exists(os.path.join(proj_root, "sactor.default.toml")):
        raise FileNotFoundError("Could not find sactor.default.toml")
    with open(os.path.join(proj_root, "sactor.default.toml"), 'rb') as f:
        default_config = toml.load(f)

    return default_config


def try_load_config(config_file=None):
    proj_root = find_project_root()
    default_config = load_default_config()

    if config_file is None:
        config_file = os.path.join(proj_root, "sactor.toml")
        if not os.path.exists(config_file):
            raise FileNotFoundError("Could not find sactor.toml")
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Could not find config file {config_file}")

    with open(config_file, 'rb') as f:
        config = toml.load(f)

     # Merge default config with user config
    config = _merge_configs(config, default_config)

    return config


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
    e.g., 
commands : `gcc -DHAVE_CONFIG_H -I. -I..  -I../include -I../include  -D_V_SELFTEST -O2 -Wall -Wextra -ffast-math -fsigned-char -g -O2 -MT test_bitwise-bitwise.o -MD -MP -MF .deps/test_bitwise-bitwise.Tpo -c -o test_bitwise-bitwise.o `test -f 'bitwise.c' || echo './'`bitwise.c
mv -f .deps/test_bitwise-bitwise.Tpo .deps/test_bitwise-bitwise.Po
/bin/bash ../libtool  --tag=CC   --mode=link gcc -D_V_SELFTEST -O2 -Wall -Wextra -ffast-math -fsigned-char -g -O2   -o test_bitwise test_bitwise-bitwise.o  ` 
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

def get_compile_flags_from_commands(processed_compile_commands: List[List[str]]) -> Tuple[list[str], list[str]]:
        processed_commands = copy.deepcopy(processed_compile_commands)
        cmd = []
        for cmd in processed_commands:
            if TO_TRANSLATE_C_FILE_MARKER in cmd:
                break

        processed_commands = cmd
        flags =  list(filter(lambda s: s.startswith("-"), processed_commands))
        # generate C source code with code for tests, for validation
        del_index = []
        for i, flag in enumerate(flags):
            if flag == "-o" or flag == '-c' or flag.startswith("-M"):
                del_index.append(i)
        for i in del_index[::-1]:
            del flags[i]
        flags_with_tests = copy.deepcopy(flags)
        # C source code without code for tests, for translation
        del_index = []
        for i, flag in enumerate(flags):
            if re.search(r"-D[\w\d_]*?TEST", flag) :
                del_index.append(i)
        for i in del_index[::-1]:
            del flags[i]
        flags_without_tests = flags
        return flags_with_tests, flags_without_tests

