import os

from clang.cindex import Cursor

from sactor.utils import get_temp_dir

from .c_parser import CParser


def _remove_static_decorator_impl(node: Cursor, source_code: str) -> str:
    start_line = node.extent.start.line - 1
    end_line = node.extent.end.line
    tokens = node.get_tokens()
    token_spellings = [token.spelling for token in tokens]
    if token_spellings[0] == "static":
        token_spellings = token_spellings[1:]

    code_lines = source_code.split("\n")

    # Remove the static keyword from the source code
    for i in range(start_line, end_line):
        code_lines[i] = ""

    code_lines[start_line] = " ".join(token_spellings) + ';'

    return "\n".join(code_lines)


def remove_function_static_decorator(function_name: str, source_code: str) -> str:
    """
    Removes `static` decorator from the ident in the source code.
    """
    tmpdir = get_temp_dir()
    with open(os.path.join(tmpdir, "tmp.c"), "w") as f:
        f.write(source_code)

    c_parser = CParser(os.path.join(tmpdir, "tmp.c"))

    function = c_parser.get_function_info(function_name)
    node = function.node

    # handle declaration node
    decl_node = function.get_declaration_node()
    if decl_node is not None:
        source_code = _remove_static_decorator_impl(decl_node, source_code)
        # Need to parse the source code again to get the updated node
        with open(os.path.join(tmpdir, "tmp.c"), "w") as f:
            f.write(source_code)

        c_parser = CParser(os.path.join(tmpdir, "tmp.c"))
        node = c_parser.get_function_info(function_name).node

    if node is None:
        raise ValueError("Node is None")

    removed_code = _remove_static_decorator_impl(node, source_code)

    # remove the tmp.c
    os.remove(os.path.join(tmpdir, "tmp.c"))

    return removed_code
