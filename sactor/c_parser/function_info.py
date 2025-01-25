from clang import cindex
from clang.cindex import Cursor

from sactor import utils

from .enum_info import EnumValueInfo
from .struct_info import StructInfo
from .global_var_info import GlobalVarInfo


class FunctionInfo:
    def __init__(
        self,
        node,
        name,
        return_type,
        arguments,
        called_functions=None,
        used_structs=None,
        used_global_vars=None,
        used_enums=None,
        used_type_aliases=None,
        standard_io=None
    ):
        self.node: Cursor = node
        self.name: str = name
        self.return_type = return_type
        self.arguments = arguments
        self.location = f"{node.location.file}:{node.location.line}"
        self.function_dependencies: list[FunctionInfo] = called_functions if called_functions is not None else []
        self.struct_dependencies: list[StructInfo] = used_structs if used_structs is not None else []
        self.global_vars_dependencies: list[GlobalVarInfo] = used_global_vars if used_global_vars is not None else []
        self.enum_dependencies: list[EnumValueInfo] = used_enums if used_enums is not None else []
        self.type_alias_dependencies: dict[str, str] = used_type_aliases if used_type_aliases is not None else {}

        self.stdio_list = []

    def add_stdio(self, stdio: str):
        if stdio not in self.stdio_list:
            self.stdio_list.append(stdio)

    def get_signature(self, function_name_sub=None):
        '''
        function_name_sub is used to substitute the function name in the signature
        '''
        tokens = []
        for token in utils.cursor_get_tokens(self.node):
            if token.kind.name == 'PUNCTUATION' and token.spelling == '{':
                break
            tokens.append(token.spelling)

        signature = ' '.join(tokens)

        # If a function name substitution is requested, replace the original name
        if function_name_sub is not None:
            signature = signature.replace(self.name, function_name_sub)

        return signature.strip()

    def get_structs_in_signature(self) -> list[StructInfo]:
        struct_dependencies_tbl = {}
        for struct in self.struct_dependencies:
            struct_dependencies_tbl[struct.name] = struct
        structs_in_signature = set()
        for name in struct_dependencies_tbl:
            if self.return_type.find(name) != -1:
                structs_in_signature.add(struct_dependencies_tbl[name])
            for _, arg_type in self.arguments:
                if arg_type.find(name) != -1:
                    structs_in_signature.add(struct_dependencies_tbl[name])

        # check type aliases
        for type_alias in self.type_alias_dependencies.keys():
            if self.return_type.find(type_alias) != -1:
                struct_name = self.type_alias_dependencies[type_alias]
                if struct_name in struct_dependencies_tbl:
                    structs_in_signature.add(struct_dependencies_tbl[struct_name])
                else:
                    print(f"Warning: {struct_name} not found in struct_dependencies_tbl")
            for _, arg_type in self.arguments:
                if arg_type.find(type_alias) != -1:
                    struct_name = self.type_alias_dependencies[type_alias]
                    if struct_name in struct_dependencies_tbl:
                        structs_in_signature.add(struct_dependencies_tbl[struct_name])
                    else:
                        print(f"Warning: {struct_name} not found in struct_dependencies_tbl")

        return list(structs_in_signature)

    def get_arg_types(self):
        return [arg_type for _, arg_type in self.arguments]

    def get_pointer_count_in_signature(self):
        count = 0
        if self.return_type.find("*") != -1:
            count += 1
        for _, arg_type in self.arguments:
            if arg_type.find("*") != -1:
                count += 1

        return count

    def get_declaration_node(self):
        canonical = self.node.canonical

        if canonical and canonical.kind == cindex.CursorKind.FUNCTION_DECL and not canonical.is_definition():
            return canonical

        return None

    def __hash__(self):
        return hash(self.name) + hash(self.location)

    def __eq__(self, other):
        return self.name == other.name and self.location == other.location

    def __repr__(self):
        return f"FunctionInfo({self.get_signature()})"
