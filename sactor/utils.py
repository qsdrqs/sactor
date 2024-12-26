import os
import tempfile

import tomli as toml


def create_rust_lib(rust_code, lib_name, path):
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "src"), exist_ok=True)

    with open(f"{path}/Cargo.toml", "w") as f:
        f.write(f'''
[package]
name = "{lib_name}"
version = "0.1.0"
edition = "2021"

[dependencies]
libc = "0.2.159"

[lib]
name = "{lib_name}"
crate-type = ["cdylib"]
''')

    with open(f"{path}/src/lib.rs", "w") as f:
        f.write(rust_code)


def find_project_root():
    path = os.path.dirname(os.path.realpath(__file__))
    while path != "/":
        if os.path.exists(os.path.join(path, "pyproject.toml")):
            return path
        path = os.path.dirname(path)
    raise RuntimeError("Could not find project root")


def get_temp_dir():
    return '/tmp/sactor'
    # return tempfile.mkdtemp(prefix='sactor_')


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
            if line == f"----{arg.upper()}----":
                in_arg = True
                continue
            if line == f"----END {arg.upper()}----":
                in_arg = False
                continue
            if in_arg and '```' not in line:
                arg_result += line + "\n"
        print(f"Translated {arg}:")
        print(arg_result)
        res[arg] = arg_result
    return res


def save_code(path, code):
    path_dir = os.path.dirname(path)
    os.makedirs(path_dir, exist_ok=True)
    with open(path, "w") as f:
        f.write(code)


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

def try_load_config(config_file=None):
    proj_root = find_project_root()
    # load default config
    if not os.path.exists(os.path.join(proj_root, "sactor.default.toml")):
        raise FileNotFoundError("Could not find sactor.default.toml")
    with open(os.path.join(proj_root, "sactor.default.toml"), 'rb') as f:
        default_config = toml.load(f)

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
