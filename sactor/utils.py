import os


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

