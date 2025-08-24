import os
import re
import shutil, shlex
import subprocess

from clang import cindex
from clang.cindex import Cursor

from sactor import utils
from sactor.utils import get_temp_dir

from .c_parser import CParser


def _remove_static_decorator_impl(node: Cursor, source_code: str) -> str:
    code_lines = source_code.split("\n")
    tokens = utils.cursor_get_tokens(node)
    first_token = next(tokens)
    if first_token.spelling == "static":
        # delete the static keyword
        start_line = first_token.extent.start.line - 1
        start_column = first_token.extent.start.column
        end_column = first_token.extent.end.column
        code_lines[start_line] = code_lines[start_line][:start_column -
                                                        1] + code_lines[start_line][end_column:]

    return "\n".join(code_lines)


def _is_empty(node: Cursor) -> bool:
    tokens = utils.cursor_get_tokens(node)
    token_spellings = [token.spelling for token in tokens]
    return len(token_spellings) == 0


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
    if decl_node is not None and not _is_empty(decl_node):
        source_code = _remove_static_decorator_impl(decl_node, source_code)
        # Need to parse the source code again to get the updated node
        with open(os.path.join(tmpdir, "tmp.c"), "w") as f:
            f.write(source_code)

        c_parser = CParser(os.path.join(tmpdir, "tmp.c"), omit_error=True)
        node = c_parser.get_function_info(function_name).node

    if node is None:
        raise ValueError("Node is None")

    removed_code = _remove_static_decorator_impl(node, source_code)

    # remove the tmp.c
    os.remove(os.path.join(tmpdir, "tmp.c"))

    return removed_code


def expand_all_macros(input_file, commands: str=""):
    filename = os.path.basename(input_file)
    with open(input_file, 'r') as f:
        content = f.read()
    # Find the last #include line and insert the marker
    lines = content.splitlines()

    # remove #ifdef __cplusplus
    start = -1
    for i, line in enumerate(lines):
        if line.strip().startswith('#ifdef __cplusplus'):
            start = i
        if line.strip().startswith('#endif'):
            if start != -1:
                lines = lines[:start] + lines[i+1:]
                start = -1

    removed_includes = []
    for i, line in enumerate(lines):
        if line.strip().startswith('#include'):
            # remove the include line, to prevent expand macros in the header
            removed_includes.append(line)
            lines[i] = ''

    tmpdir = utils.get_temp_dir()
    os.makedirs(tmpdir, exist_ok=True)

    def get_expanded_code(tmpdir: str, filename: str, flags: list[str], output_filename_prefix: str="expanded") -> str:
        result = subprocess.run(
            ['cpp', '-C', '-P', os.path.join(tmpdir, filename), *flags],
            capture_output=True,
            text=True,
            check=True
        )
                # Combine with expanded part
        expanded = '\n'.join(removed_includes) + '\n' + result.stdout
        out_path = os.path.join(tmpdir, f"{output_filename_prefix}_{filename}")

        with open(out_path, 'w') as f:
            f.write(expanded)

        # check if it can compile, if not, will raise an error
        # assume it is a library, compatible with the executable
        utils.compile_c_code(out_path, commands=commands, is_library=True)
        return out_path

    # Write to a temporary file
    with open(os.path.join(tmpdir, filename), 'w') as f:
        f.write('\n'.join(lines))

    if commands:
        flags_with_tests, flags_without_tests = utils.get_compile_flags_from_commands(commands, filename)
        with_test_output_filepath = get_expanded_code(tmpdir, filename, flags_with_tests, "has_test_expanded")
        no_test_output_filepath = get_expanded_code(tmpdir, filename, flags_without_tests, "no_test_expanded")

    else:    
        # use `cpp -C -P` to expand all macros
        # note, if commands is "", with_test_output is the same as no_test_output
        with_test_output_filepath = get_expanded_code(tmpdir, filename, [], "has_test_expanded")
        no_test_output_filepath = get_expanded_code(tmpdir, filename, [], "no_test_expanded")

    return no_test_output_filepath, with_test_output_filepath


def preprocess_source_code(input_file, commands: str=""):
    # Expand all macros in the input file
    no_test_expanded_file, with_test_expanded_file = expand_all_macros(input_file, commands)
    # Unfold all typedefs in the expanded file
    compile_flags, _ = utils.get_compile_flags_from_commands(commands, input_file)
    include_flags = list(filter(lambda s: s.startswith("-I"), compile_flags))
    no_test_unfolded_file = unfold_typedefs(no_test_expanded_file, include_flags)
    with_test_unfolded_file = unfold_typedefs(with_test_expanded_file, include_flags)
    return no_test_unfolded_file, with_test_unfolded_file


def unfold_typedefs(input_file, compile_flags: list[str]=[]):
    c_parser = CParser(input_file, omit_error=True, extra_args=compile_flags)
    type_aliases = c_parser._type_alias

    with open(input_file, 'r') as f:
        content = f.read()

    # Remove/replace typedef declarations using libclang
    typedef_nodes = c_parser.get_typedef_nodes()

    # Sort nodes by position in reverse order to avoid offset issues when removing
    typedef_nodes.sort(key=lambda n: n.extent.start.offset, reverse=True)

    for node in typedef_nodes:
        struct_child = None
        enum_child = None
        for child in node.get_children():
            if child.kind == cindex.CursorKind.STRUCT_DECL or child.kind == cindex.CursorKind.UNION_DECL:
                struct_child = child
                break
            elif child.kind == cindex.CursorKind.ENUM_DECL:
                enum_child = child
                break

        start_offset = node.extent.start.offset
        end_offset = node.extent.end.offset
        # Extend end_offset to include any trailing semicolon and whitespace
        while end_offset < len(content) and content[end_offset] in ' \t\n':
            end_offset += 1
        if end_offset < len(content) and content[end_offset] == ';':
            end_offset += 1

        if struct_child:
            # This typedef defines a struct - keep only the struct part with semicolon
            struct_start = struct_child.extent.start.offset
            struct_end = struct_child.extent.end.offset
            struct_text = content[struct_start:struct_end] + ";"
            content = content[:start_offset] + \
                struct_text + content[end_offset:]
        elif enum_child:
            enum_start = enum_child.extent.start.offset
            enum_end = enum_child.extent.end.offset

            # Get the typedef name from the typedef declaration node itself
            typedef_name = node.spelling

            if typedef_name:
                enum_body = content[enum_start:enum_end]
                # Replace "enum" with "enum typedef_name"
                if enum_body.startswith("enum"):
                    enum_text = f"enum {typedef_name}" + enum_body[4:] + ";"
                else:
                    enum_text = f"enum {typedef_name} {enum_body};"
            else:
                # Fallback: just keep the enum part with semicolon
                enum_text = content[enum_start:enum_end] + ";"

            content = content[:start_offset] + enum_text + content[end_offset:]
        else:
            # Simple typedef - remove entirely including trailing semicolon
            content = content[:start_offset] + content[end_offset:]

    # Replace type aliases using libclang analysis of the modified content
    if type_aliases:
        # Write modified content to a temporary file for re-parsing
        tmp_dir = utils.get_temp_dir()
        tmp_file_path = os.path.join(tmp_dir, 'temp_unfolded.c')
        with open(tmp_file_path, 'w') as tmp_file:
            tmp_file.write(content)

        try:
            # Re-parse the modified content
            temp_parser = CParser(tmp_file_path, omit_error=True)

            # Get all identifier tokens that match our type aliases
            source_range = temp_parser.translation_unit.cursor.extent
            tokens = list(temp_parser.translation_unit.get_tokens(
                extent=source_range))

            # Filter tokens to only those in the main file
            main_file_tokens = []
            for token in tokens:
                token_file = str(
                    token.location.file) if token.location.file else ""
                if tmp_file_path in token_file or token_file.endswith(tmp_file_path.split('/')[-1]):
                    main_file_tokens.append(token)

            # Collect replacements
            replacements = []
            for i, token in enumerate(main_file_tokens):
                if (token.kind == cindex.TokenKind.IDENTIFIER and
                        token.spelling in type_aliases):

                    start_offset = token.extent.start.offset
                    end_offset = token.extent.end.offset

                    # Make sure the token text actually matches
                    if (start_offset < len(content) and
                        end_offset <= len(content) and
                            content[start_offset:end_offset] == token.spelling):

                        replacement = type_aliases[token.spelling]

                        # Check if we need to handle "struct alias" vs "alias" carefully
                        if replacement.startswith('struct '):
                            # Look at the previous token to see if it's already "struct"
                            prev_token = None
                            if i > 0:
                                prev_token = main_file_tokens[i - 1]

                            if (prev_token and prev_token.kind == cindex.TokenKind.KEYWORD
                                    and prev_token.spelling == "struct"):
                                # Remove "struct " prefix (handling any amount of whitespace)
                                struct_name = re.sub(
                                    r'^struct\s+', '', replacement)
                                replacements.append(
                                    (start_offset, end_offset, struct_name))
                            else:
                                # Replace with full "struct name"
                                replacements.append(
                                    (start_offset, end_offset, replacement))
                        elif replacement.startswith('enum '):
                            # Look at the previous token to see if it's already "enum"
                            prev_token = None
                            if i > 0:
                                prev_token = main_file_tokens[i - 1]

                            if (prev_token and prev_token.kind == cindex.TokenKind.KEYWORD
                                    and prev_token.spelling == "enum"):
                                # Remove "enum " prefix (handling any amount of whitespace)
                                enum_name = re.sub(
                                    r'^enum\s+', '', replacement)
                                replacements.append(
                                    (start_offset, end_offset, enum_name))
                            else:
                                # Replace with full "enum name"
                                replacements.append(
                                    (start_offset, end_offset, replacement))
                        else:
                            # Simple replacement
                            replacements.append(
                                (start_offset, end_offset, replacement))

            # Sort replacements by position in reverse order to avoid offset issues
            replacements.sort(key=lambda x: x[0], reverse=True)

            # Apply replacements
            for start_offset, end_offset, replacement in replacements:
                content = content[:start_offset] + \
                    replacement + content[end_offset:]

        finally:
            # Clean up temporary file
            shutil.rmtree(tmp_dir, ignore_errors=True)

    tmp_dir = utils.get_temp_dir()
    output_file = os.path.join(tmp_dir, 'unfolded_typedefs.c')
    with open(output_file, 'w') as f:
        f.write(content)

    return output_file
