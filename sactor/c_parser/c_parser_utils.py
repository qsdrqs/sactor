import os
import re
import shutil
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


def expand_all_macros(input_file):
    filename = os.path.basename(input_file)
    with open(input_file, 'r') as f:
        content = f.read()
    # Find the last #include line and insert the marker
    lines = content.splitlines()

    # remove #ifdef __cplusplus
    # FIXME: wrong
    start = -1
    for i, line in enumerate(lines):
        if line.strip().startswith('#ifdef __cplusplus'):
            start = i
        if line.strip().startswith('#endif'):
            if start != -1:
                lines = lines[:start] + lines[i+1:]

    removed_includes = []
    for i, line in enumerate(lines):
        if line.strip().startswith('#include'):
            # remove the include line, to prevent expand macros in the header
            removed_includes.append(line)
            lines[i] = ''

    tmpdir = utils.get_temp_dir()
    os.makedirs(tmpdir, exist_ok=True)

    try:
        # Write to a temporary file
        with open(os.path.join(tmpdir, filename), 'w') as f:
            f.write('\n'.join(lines))

        # use `cpp -C -P` to expand all macros
        result = subprocess.run(
            ['cpp', '-C', '-P', os.path.join(tmpdir, filename)],
            capture_output=True,
            text=True,
            check=True
        )

        # Combine with expanded part
        expanded = '\n'.join(removed_includes) + '\n' + result.stdout
        out_path = os.path.join(tmpdir, f"expanded_{filename}")

        with open(out_path, 'w') as f:
            f.write(expanded)

        # check if it can compile, if not, will raise an error
        # assume it is a library, compatible with the executable
        utils.compile_c_code(out_path, is_library=True)
    finally:
        # Clean up temporary directory
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Return the path to the expanded file
    tmp_dir = utils.get_temp_dir()
    out_path = os.path.join(tmp_dir, f"expanded_{filename}")
    with open(out_path, 'w') as f:
        f.write(expanded)

    return out_path


def preprocess_source_code(input_file):
    # Expand all macros in the input file
    expanded_file = expand_all_macros(input_file)
    # Unfold all typedefs in the expanded file
    unfolded_file = unfold_typedefs(expanded_file)
    return unfolded_file


def unfold_typedefs(input_file):
    c_parser = CParser(input_file, omit_error=True)
    type_aliases = c_parser._type_alias

    text_str, data_bytes, b2s, s2b = utils.load_text_with_mappings(input_file)
    content = text_str

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

        _start_b = node.extent.start.offset
        _end_b = node.extent.end.offset
        _end_b = utils.scan_ws_semicolon_bytes(data_bytes, _end_b) # For removing trailing semicolon and whitespace
        start_offset = utils.byte_to_str_index(b2s, _start_b)
        end_offset = utils.byte_to_str_index(b2s, _end_b)

        if struct_child:
            _struct_start_b = struct_child.extent.start.offset
            _struct_end_b = struct_child.extent.end.offset
            struct_start = utils.byte_to_str_index(b2s, _struct_start_b)
            struct_end = utils.byte_to_str_index(b2s, _struct_end_b)
            typedef_name = node.spelling
            struct_body = content[struct_start:struct_end]

            is_union = (struct_child.kind == cindex.CursorKind.UNION_DECL)
            kw = "union" if is_union else "struct"

            brace_idx = struct_body.find("{")
            if brace_idx != -1:
                name_seg = struct_body[len(kw):brace_idx]
                anonymous = name_seg.strip() == ""
            else:
                anonymous = True

            if anonymous and typedef_name:
                if brace_idx != -1:
                    struct_text = f"{kw} {typedef_name} " + struct_body[brace_idx:] + ";"
                else:
                    struct_text = f"{kw} {typedef_name} {{}};"
            else:
                struct_text = struct_body + ";"

            content = content[:start_offset] + struct_text + content[end_offset:]
        elif enum_child:
            _enum_start_b = enum_child.extent.start.offset
            _enum_end_b = enum_child.extent.end.offset
            enum_start = utils.byte_to_str_index(b2s, _enum_start_b)
            enum_end = utils.byte_to_str_index(b2s, _enum_end_b)
            typedef_name = node.spelling

            # Handle anonymous enum typedef
            if typedef_name:
                enum_body = content[enum_start:enum_end]
                if enum_body.startswith("enum"):
                    enum_text = f"enum {typedef_name}" + enum_body[4:] + ";"
                else:
                    enum_text = f"enum {typedef_name} {enum_body};"
            else:
                enum_text = content[enum_start:enum_end] + ";"
            content = content[:start_offset] + enum_text + content[end_offset:]
        else:
            underlying = node.underlying_typedef_type.get_canonical()
            if not CParser.is_func_type(underlying):
                content = content[:start_offset] + content[end_offset:]

    # Replace type aliases using libclang analysis of the modified content
    if type_aliases:
        # Write modified content to a temporary file for re-parsing
        tmp_dir = utils.get_temp_dir()
        tmp_file_path = os.path.join(tmp_dir, 'temp_unfolded.c')
        with open(tmp_file_path, 'w') as tmp_file:
            tmp_file.write(content)
        txt2, b2, b2s2, s2b2 = utils.load_text_with_mappings(tmp_file_path)
        content = txt2

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

                    _tok_start_b = token.extent.start.offset
                    _tok_end_b = token.extent.end.offset
                    start_offset = utils.byte_to_str_index(b2s2, _tok_start_b)
                    end_offset = utils.byte_to_str_index(b2s2, _tok_end_b)

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
