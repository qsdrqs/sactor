import os
import re
import shutil
import subprocess
from typing import NamedTuple, Optional

from clang import cindex
from clang.cindex import Cursor, Index, TranslationUnit

from sactor import logging as sactor_logging, utils
from sactor.utils import get_temp_dir, read_file, read_file_lines

from .c_parser import CParser


logger = sactor_logging.get_logger(__name__)


class _TypedefEdit(NamedTuple):
    start: int
    end: int
    text: str

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
    decl_nodes = function.get_declaration_nodes()
    for decl_node in decl_nodes:
        if decl_node is not None and not _is_empty(decl_node):
            source_code = _remove_static_decorator_impl(decl_node, source_code)
            # Need to parse the source code again to get the updated node
            with open(os.path.join(tmpdir, "tmp.c"), "w") as f:
                f.write(source_code)

            c_parser = CParser(os.path.join(tmpdir, "tmp.c"), omit_error=True)
            node = c_parser.get_function_info(function_name).node
            if node is None:
                raise ValueError("Node is None")

    source_code = _remove_static_decorator_impl(node, source_code)

    # remove the tmp.c
    os.remove(os.path.join(tmpdir, "tmp.c"))

    return source_code


def expand_all_macros(input_file, commands: list[list[str]] | None=None):
    """
    Return:
    - no_test_output_filepath: source file for the translator
    """
    if not commands:
        commands = []
    filename = os.path.basename(input_file)

    if commands:
        compile_flags = utils.get_compile_flags_from_commands(commands)
    else:
        compile_flags = []
    tmpdir = utils.get_temp_dir()
    os.makedirs(tmpdir, exist_ok=True)

    def expand_custom_headers(tmp_file_path: str, flags: list):
        """
        This will only expand the custom header non-recursively.
        """
        index = cindex.Index.create()
        compiler_include_paths = utils.get_compiler_include_paths()
        args = ['-x', 'c', '-std=c99'] + (flags or [])
        args.extend([f"-I{path}" for path in compiler_include_paths])
        translation_unit = index.parse(
                tmp_file_path, args=args, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)

        #map: line number -> include file path (if non-system)
        non_system_includes = {}
        for include in translation_unit.get_includes():
            loc = include.location
            header = include.include
            if not header or not loc:
                continue
            if not os.path.samefile(loc.file.name, tmp_file_path):
                continue
            header_location = cindex.SourceLocation.from_position(
                translation_unit,
                header,
                1,
                1
            )
            if not bool(cindex.conf.lib.clang_Location_isInSystemHeader(header_location)):
                # print(header.name , "include source location:", loc.file.name)
                non_system_includes[loc.line] = header.name

        new_lines = []
        # exclude system includes (includes in compiler include paths)
        for path in compiler_include_paths:
            non_system_includes = {k: v for k, v in non_system_includes.items() if not v.startswith(path)}
        if non_system_includes:
            lines = read_file_lines(tmp_file_path)
            for i, line in enumerate(lines, start=1):
                if i in non_system_includes:
                    header_file = non_system_includes[i]
                    try:
                        header_content = read_file(header_file)
                        # Paste raw contents, but don't recursively expand
                        new_lines.append(f"/* Begin expanded {header_file} */\n")
                        new_lines.append(header_content)
                        if not header_content.endswith("\n"):
                            new_lines.append("\n")
                        new_lines.append(f"/* End expanded {header_file} */\n")
                    except Exception as e:
                        logger.warning("Could not read %s: %s", header_file, e)
                        new_lines.append(line)  # fallback
                else:
                    # Keep system includes and other code unchanged
                    new_lines.append(line)
            with open(tmp_file_path, 'w') as f:
                f.writelines(new_lines)

    tmp_file_path = os.path.join(tmpdir, f"expanded_{filename}")
    shutil.copy(input_file, tmp_file_path)

    # For #include, keep system headers, expand custom headers.
    while True:
        file_content_before = utils.read_file(tmp_file_path)
        expand_custom_headers(tmp_file_path, compile_flags)
        file_content_after = utils.read_file(tmp_file_path)
        if file_content_before.strip() == file_content_after.strip():
            break

    # remove all remaining headers, to be added after preprocessing
    includes_lines = {}
    new_lines = []
    lines = read_file_lines(tmp_file_path)
    for line in lines:
        if re.search(r"# *include", line):
            remove_marker = f"/* sactor remove marker: {len(includes_lines)} */\n"
            new_lines.append(remove_marker)
            includes_lines[remove_marker] = line
        else:
            new_lines.append(line)
    with open(tmp_file_path, "w") as f:
        f.writelines(new_lines)

    # expand macros
    # #ifdef __cplusplus will be automatically removed if there is no __cplusplus flag
    result = subprocess.run(
        ['cpp', '-C', '-P', '-xc', '-std=c99', tmp_file_path, *compile_flags],
        capture_output=True,
        text=True,
        check=True
    )

    # add removed headers
    content = result.stdout.splitlines(keepends=True)
    for i, line in enumerate(content[:]):
        if line in includes_lines:
            content[i] = includes_lines[line]

    with open(tmp_file_path, 'w') as f:
        f.writelines(content)

    # check if it can compile, if not, will raise an error
    # assume it is a library, compatible with the executable
    utils.compile_c_code(tmp_file_path, commands=commands, is_library=True)

    return tmp_file_path


def preprocess_source_code(input_file, commands: list[list[str]]) -> str:
    # Expand all macros in the input file
    expanded_file = expand_all_macros(input_file, commands)
    # Unfold all typedefs in the expanded file
    compile_flags = utils.get_compile_flags_from_commands(commands)
    include_flags = list(filter(lambda s: s.startswith("-I"), compile_flags))
    unfolded_file = unfold_typedefs(expanded_file, include_flags)
    cleaned_file = remove_inline_specifiers(unfolded_file, compile_flags)
    return cleaned_file


def unfold_typedefs(input_file, compile_flags: list[str] = []):
    c_parser = CParser(input_file, omit_error=True, extra_args=compile_flags)
    type_aliases = c_parser._type_alias

    text_str, data_bytes, b2s, s2b = utils.load_text_with_mappings(input_file)
    content = text_str

    typedef_nodes = c_parser.get_typedef_nodes()
    typedef_nodes.sort(key=lambda n: n.extent.start.offset, reverse=True)

    for node in typedef_nodes:
        if not node.location or not node.location.file:
            continue
        if not os.path.samefile(node.location.file.name, input_file):
            continue
        content = _rewrite_typedef_node(
            node,
            content,
            data_bytes,
            b2s,
        )

    content = _expand_type_alias_tokens(content, type_aliases)
    content = re.sub(r"\n{3,}", "\n\n", content)

    tmp_dir = utils.get_temp_dir()
    output_file = os.path.join(tmp_dir, 'unfolded_typedefs.c')
    with open(output_file, 'w') as f:
        f.write(content)

    return output_file


def _rewrite_typedef_node(
    node: cindex.Cursor,
    content: str,
    data_bytes: bytes,
    b2s: dict[int, int],
) -> str:
    struct_child: Optional[cindex.Cursor] = None
    enum_child: Optional[cindex.Cursor] = None
    for child in node.get_children():
        if child.kind in (cindex.CursorKind.STRUCT_DECL, cindex.CursorKind.UNION_DECL):
            struct_child = child
            break
        if child.kind == cindex.CursorKind.ENUM_DECL:
            enum_child = child
            break

    start_b = node.extent.start.offset
    end_b = utils.scan_ws_semicolon_bytes(data_bytes, node.extent.end.offset)
    start = utils.byte_to_str_index(b2s, start_b)
    end = utils.byte_to_str_index(b2s, end_b)

    if struct_child:
        replacement = _render_struct_union_typedef(node, struct_child, content, b2s)
        return content[:start] + replacement + content[end:]

    if enum_child:
        replacement = _render_enum_typedef(node, enum_child, content, b2s)
        return content[:start] + replacement + content[end:]

    underlying = node.underlying_typedef_type.get_canonical()
    if underlying.kind in {cindex.TypeKind.RECORD, cindex.TypeKind.ENUM}:
        decl = underlying.get_declaration()
        if decl is not None and decl.kind in (
            cindex.CursorKind.STRUCT_DECL,
            cindex.CursorKind.UNION_DECL,
            cindex.CursorKind.ENUM_DECL,
        ):
            if decl.is_definition():
                return content[:start] + content[end:]
            keyword = {
                cindex.CursorKind.STRUCT_DECL: "struct",
                cindex.CursorKind.UNION_DECL: "union",
                cindex.CursorKind.ENUM_DECL: "enum",
            }[decl.kind]
            name = decl.spelling or node.spelling
            if name:
                forward = f"{keyword} {name};"
                return content[:start] + forward + content[end:]
        return content[:start] + content[end:]
    if CParser.is_func_type(underlying):
        return content

    return content[:start] + content[end:]


def _render_struct_union_typedef(
    node: cindex.Cursor,
    struct_child: cindex.Cursor,
    content: str,
    b2s: dict[int, int],
) -> str:
    typedef_name = node.spelling
    struct_start = utils.byte_to_str_index(b2s, struct_child.extent.start.offset)
    struct_end = utils.byte_to_str_index(b2s, struct_child.extent.end.offset)
    struct_body = content[struct_start:struct_end]

    is_union = struct_child.kind == cindex.CursorKind.UNION_DECL
    keyword = "union" if is_union else "struct"
    brace_idx = struct_body.find("{")
    anonymous = True
    if brace_idx != -1:
        name_segment = struct_body[len(keyword):brace_idx]
        anonymous = name_segment.strip() == ""

    struct_name = struct_child.spelling or ""
    if anonymous and typedef_name:
        if brace_idx != -1:
            struct_text = f"{keyword} {typedef_name} " + struct_body[brace_idx:] + ";"
        else:
            struct_text = f"{keyword} {typedef_name} {{}};"
        struct_name = typedef_name
    else:
        struct_text = struct_body + ";"
        if not struct_name and typedef_name:
            struct_name = typedef_name

    return struct_text


def _render_enum_typedef(
    node: cindex.Cursor,
    enum_child: cindex.Cursor,
    content: str,
    b2s: dict[int, int],
) -> str:
    typedef_name = node.spelling
    enum_start = utils.byte_to_str_index(b2s, enum_child.extent.start.offset)
    enum_end = utils.byte_to_str_index(b2s, enum_child.extent.end.offset)
    enum_body = content[enum_start:enum_end]
    if typedef_name:
        if enum_body.startswith("enum"):
            suffix = enum_body[4:]
            suffix_no_ws = suffix.lstrip()
            ws_len = len(suffix) - len(suffix_no_ws)
            prefix_ws = suffix[:ws_len]
            idx = 0
            while idx < len(suffix_no_ws) and (suffix_no_ws[idx].isalnum() or suffix_no_ws[idx] == "_"):
                idx += 1
            identifier = suffix_no_ws[:idx]
            remainder = suffix_no_ws[idx:]
            if identifier:
                joiner = prefix_ws if prefix_ws else " "
                enum_text = f"enum{joiner}{typedef_name}{remainder};"
            else:
                enum_text = f"enum {typedef_name}{suffix};"
        else:
            enum_text = f"enum {typedef_name} {enum_body};"
    else:
        enum_text = enum_body + ";"

    return enum_text


def _expand_type_alias_tokens(content: str, type_aliases: dict[str, str]) -> str:
    if not type_aliases:
        return content

    prefix_lines = [f"typedef {target} {alias};" for alias, target in type_aliases.items()]
    prefix = "\n".join(prefix_lines)
    if prefix:
        prefix += "\n\n"

    tmp_dir = utils.get_temp_dir()
    tmp_file_path = os.path.join(tmp_dir, 'temp_unfolded.c')
    with open(tmp_file_path, 'w') as tmp_file:
        tmp_file.write(prefix + content)

    txt2, _b2, b2s, _s2b = utils.load_text_with_mappings(tmp_file_path)
    content = txt2
    prefix_len_chars = len(prefix)
    prefix_len_bytes = len(prefix.encode('utf-8'))
    tmp_file_abs = os.path.abspath(tmp_file_path)

    try:
        temp_parser = CParser(tmp_file_path, omit_error=True)
        tokens = list(temp_parser.translation_unit.get_tokens(extent=temp_parser.translation_unit.cursor.extent))

        replacements: list[_TypedefEdit] = []
        visited_offsets: set[int] = set()

        disallowed_cursor_kinds = {
            cindex.CursorKind.MEMBER_REF_EXPR,
            cindex.CursorKind.DECL_REF_EXPR,
            cindex.CursorKind.CALL_EXPR,
        }
        allowed_cursor_kinds = {
            cindex.CursorKind.TYPE_REF,
            cindex.CursorKind.TYPEDEF_DECL,
            cindex.CursorKind.PARM_DECL,
            cindex.CursorKind.VAR_DECL,
            cindex.CursorKind.FIELD_DECL,
            cindex.CursorKind.FUNCTION_DECL,
            cindex.CursorKind.STRUCT_DECL,
            cindex.CursorKind.UNION_DECL,
            cindex.CursorKind.ENUM_DECL,
        }

        def previous_token(index: int):
            for j in range(index - 1, -1, -1):
                tok = tokens[j]
                if not tok.location or not tok.location.file:
                    continue
                if os.path.abspath(tok.location.file.name) != tmp_file_abs:
                    continue
                if tok.extent.start.offset < prefix_len_bytes:
                    continue
                return tok
            return None

        for idx, token in enumerate(tokens):
            if token.kind != cindex.TokenKind.IDENTIFIER:
                continue
            alias = token.spelling
            if alias not in type_aliases:
                continue
            if token.extent.start.offset < prefix_len_bytes:
                continue
            replacement_text = type_aliases[alias]
            cursor = token.cursor
            if cursor is None:
                continue

            prev_token = previous_token(idx)
            if prev_token:
                if prev_token.spelling in {"struct", "union", "enum"}:
                    continue
                if prev_token.spelling in {'.', '->'}:
                    continue
                if (
                    prev_token.kind == cindex.TokenKind.IDENTIFIER
                    and prev_token.spelling not in type_aliases
                ):
                    continue

            special_context = prev_token and prev_token.spelling in {'const', 'sizeof'}

            if cursor.kind in disallowed_cursor_kinds:
                continue
            if cursor.kind not in allowed_cursor_kinds and not special_context:
                continue
            if (
                cursor.kind in {
                    cindex.CursorKind.PARM_DECL,
                    cindex.CursorKind.VAR_DECL,
                    cindex.CursorKind.FIELD_DECL,
                }
                and cursor.spelling
                and alias == cursor.spelling
            ):
                continue

            token_start_b = token.extent.start.offset
            if token_start_b in visited_offsets:
                continue
            visited_offsets.add(token_start_b)

            token_end_b = token.extent.end.offset
            start = utils.byte_to_str_index(b2s, token_start_b)
            end = utils.byte_to_str_index(b2s, token_end_b)
            if not (0 <= start <= end <= len(content)):
                continue
            if content[start:end] != token.spelling:
                continue

            replacements.append(_TypedefEdit(start, end, _format_alias_replacement(prev_token, replacement_text)))

        replacements.sort(key=lambda edit: edit.start, reverse=True)
        for edit in replacements:
            content = content[:edit.start] + edit.text + content[edit.end:]

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if prefix_len_chars:
        content = content[prefix_len_chars:]

    return content


def _format_alias_replacement(prev_token, replacement_text: str) -> str:
    if not prev_token:
        return replacement_text
    if (
        prev_token.kind == cindex.TokenKind.KEYWORD
        and prev_token.spelling == 'struct'
        and replacement_text.startswith('struct ')
    ):
        return re.sub(r'^struct\s+', '', replacement_text)
    if (
        prev_token.kind == cindex.TokenKind.KEYWORD
        and prev_token.spelling == 'enum'
        and replacement_text.startswith('enum ')
    ):
        return re.sub(r'^enum\s+', '', replacement_text)
    return replacement_text

def remove_inline_specifiers(input_file: str, compile_flags: list[str] | None = None) -> str:
    """Remove `inline` specifiers from all function declarations/definitions in ``input_file``."""
    compile_flags = compile_flags or []
    main_file_path = os.path.abspath(input_file)

    c_parser = CParser(input_file, omit_error=True, extra_args=compile_flags)
    content, _, b2s, _ = utils.load_text_with_mappings(input_file)

    spans_to_remove: list[tuple[int, int]] = []
    seen_spans: set[tuple[int, int]] = set()

    for cursor in c_parser.translation_unit.cursor.walk_preorder():
        if cursor.kind != cindex.CursorKind.FUNCTION_DECL:
            continue
        if cursor.location is None or cursor.location.file is None:
            continue

        cursor_file_name = getattr(cursor.location.file, "name", None)
        if not cursor_file_name:
            continue
        if os.path.abspath(cursor_file_name) != main_file_path:
            continue

        seen_lparen = False
        for token in utils.cursor_get_tokens(cursor):
            token_file = token.location.file
            token_file_name = getattr(token_file, "name", None) if token_file else None
            if not token_file_name:
                continue
            if os.path.abspath(token_file_name) != main_file_path:
                continue

            if token.spelling == '(':
                seen_lparen = True

            if seen_lparen:
                continue

            if token.kind == cindex.TokenKind.KEYWORD and token.spelling == 'inline':
                start_b = token.extent.start.offset
                end_b = token.extent.end.offset
                start = utils.byte_to_str_index(b2s, start_b)
                end = utils.byte_to_str_index(b2s, end_b)

                while end < len(content) and content[end] in (' ', '\t'):
                    end += 1

                span = (start, end)
                if span not in seen_spans:
                    spans_to_remove.append(span)
                    seen_spans.add(span)

    if not spans_to_remove:
        return input_file

    spans_to_remove.sort(key=lambda item: item[0], reverse=True)

    for start, end in spans_to_remove:
        content = content[:start] + content[end:]

    with open(input_file, 'w') as f:
        f.write(content)

    return input_file
