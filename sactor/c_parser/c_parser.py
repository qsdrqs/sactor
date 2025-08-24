from clang import cindex

from sactor import utils

from .enum_info import EnumInfo, EnumValueInfo
from .function_info import FunctionInfo
from .global_var_info import GlobalVarInfo
from .struct_info import StructInfo

standard_io = [
    "stdin",
    "stdout",
    "stderr",
]


class CParser:
    def __init__(self, filename, extra_args=None, omit_error=False):
        self.filename = filename

        # Parse the C file
        index = cindex.Index.create()
        self.compiler_include_paths = utils.get_compiler_include_paths()
        args = ['-x', 'c', '-std=c99'] + (extra_args or [])
        args.extend([f"-I{path}" for path in self.compiler_include_paths])
        self.translation_unit = index.parse(
            self.filename, args=args, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)

        # check diagnostics
        if not omit_error and len(self.translation_unit.diagnostics) > 0:
            for diag in self.translation_unit.diagnostics:
                if diag.severity >= cindex.Diagnostic.Error:
                    print(
                        f"Warning: Parsing error in {filename}: {diag.spelling}")

        # Initialize data structures
        self._global_vars: dict[str, GlobalVarInfo] = {}
        self._enums: dict[str, EnumInfo] = {}
        self._structs_unions: dict[str, StructInfo] = {}
        self._functions: dict[str, FunctionInfo] = {}

        self._type_alias: dict[str, str] = self._extract_type_alias()

        self._extract_structs_unions()
        self._update_structs_unions()

        self._extract_functions()
        self._update_functions()

    @staticmethod
    def is_func_type(t: cindex.Type) -> bool:
        try:
            if t.kind == cindex.TypeKind.POINTER:
                p = t.get_pointee()
                return p.kind in (cindex.TypeKind.FUNCTIONPROTO, cindex.TypeKind.FUNCTIONNOPROTO)
            return t.kind in (cindex.TypeKind.FUNCTIONPROTO, cindex.TypeKind.FUNCTIONNOPROTO)
        except Exception:
            return False

    def get_code(self):
        with open(self.filename, "r") as file:
            return file.read()

    def get_struct_info(self, struct_name):
        """
        Raises ValueError if the function is not found.
        """
        if struct_name in self._structs_unions:
            return self._structs_unions[struct_name]
        raise ValueError(f"Struct/Union {struct_name} not found")

    def get_structs(self) -> list[StructInfo]:
        return list(self._structs_unions.values())

    def get_function_info(self, function_name) -> FunctionInfo:
        """
        Raises ValueError if the function is not found.
        """
        if function_name in self._functions:
            return self._functions[function_name]
        raise ValueError(f"Function {function_name} not found")

    def get_functions(self) -> list[FunctionInfo]:
        return list(self._functions.values())

    def get_global_var_info(self, global_var_name):
        """
        Raises ValueError if the global variable is not found.
        """
        if global_var_name in self._global_vars:
            return self._global_vars[global_var_name]
        raise ValueError(f"Global variable {global_var_name} not found")

    def get_global_vars(self) -> list[GlobalVarInfo]:
        return list(self._global_vars.values())

    def get_enum_info(self, enum_name):
        """
        Raises ValueError if the enum is not found.
        """
        if enum_name in self._enums:
            return self._enums[enum_name]
        raise ValueError(f"Enum {enum_name} not found")

    def get_enums(self) -> list[EnumInfo]:
        return list(self._enums.values())

    def get_typedef_nodes(self):
        """
        Returns a list of all typedef declaration nodes in the C file.
        """
        typedef_nodes = []
        self._process_typedef_nodes(
            self.translation_unit.cursor, typedef_nodes=typedef_nodes)
        return typedef_nodes

    def _extract_type_alias(self):
        """
        Extracts type aliases (typedefs) from the C file.
        Returns a dictionary mapping alias names to their original types.
        """
        type_alias = {}
        self._process_typedef_nodes(
            self.translation_unit.cursor, type_alias=type_alias)
        return type_alias

    def _extract_structs_unions(self):
        """
        Parses the C file and extracts struct and union information, including dependencies.
        """
        self._collect_structs_and_unions(self.translation_unit.cursor)

    def _process_typedef_nodes(self, node, type_alias=None, typedef_nodes=None):
        """
        Unified function to process typedef nodes.
        Can collect type aliases and/or typedef nodes based on provided parameters.
        """
        if node.kind == cindex.CursorKind.TYPEDEF_DECL:
            if node.location and not self._is_in_system_header(node):
                if typedef_nodes is not None:
                    typedef_nodes.append(node)

                if type_alias is not None:
                    alias_name = node.spelling
                    underlying_type = node.underlying_typedef_type.get_canonical()
                    target_spelling = underlying_type.spelling

                    enum_child = None
                    struct_child = None
                    for child in node.get_children():
                        if child.kind == cindex.CursorKind.ENUM_DECL:
                            enum_child = child
                            break
                        elif child.kind == cindex.CursorKind.STRUCT_DECL or child.kind == cindex.CursorKind.UNION_DECL:
                            struct_child = child
                            break

                    # Handle anonymous enum/struct/union typedef like: typedef struct { ... } alias_name;
                    if enum_child and target_spelling.strip() == alias_name.strip():
                        target_spelling = f"enum {alias_name}"
                    elif struct_child and target_spelling.strip() == alias_name.strip():
                        target_spelling = f"struct {alias_name}"

                    if not self.is_func_type(underlying_type) and target_spelling.strip() != alias_name.strip():
                        type_alias[alias_name] = target_spelling

        for child in node.get_children():
            self._process_typedef_nodes(child, type_alias, typedef_nodes)

    def _update_function_dependencies(self, function: FunctionInfo):
        """
        Updates the depedencies of each function.
        """
        node = function.node
        function_names = set(self._functions.keys())
        called_function_names = self._collect_function_dependencies(
            node, function_names)
        called_functions = set()
        for called_function_name in called_function_names:
            # Add the function to the dependencies if it exists and is not the same as the current function
            if called_function_name in self._functions and called_function_name != function.name:
                called_functions.add(
                    self._functions[called_function_name])

        function.function_dependencies = list(called_functions)

    def _update_struct_dependencies(self, struct_union: StructInfo):
        """
        Updates the dependencies of each struct or union.
        """
        node = struct_union.node
        used_struct_names = self._collect_structs_unions_dependencies(node)
        used_structs = set()
        type_aliases = {}
        for used_struct_name in used_struct_names:
            # Add the struct to the dependencies if it exists and is not the same as the current struct
            if used_struct_name in self._structs_unions and used_struct_name != struct_union.name:
                used_structs.add(self._structs_unions[used_struct_name])
            elif used_struct_name in self._type_alias:
                original_struct_name = self._type_alias[used_struct_name]
                if original_struct_name in self._structs_unions and original_struct_name != struct_union.name:
                    used_structs.add(
                        self._structs_unions[self._type_alias[used_struct_name]])
                type_aliases[used_struct_name] = original_struct_name

        struct_union.dependencies = list(used_structs)

    def _update_structs_unions(self):
        """
        Update the information of each struct or union. Needs to be called after all structs and unions are extracted.
        """
        for struct_union in self._structs_unions.values():
            self._update_struct_dependencies(struct_union)

    def _update_functions(self):
        """
        Update the information of each function. Needs to be called after all functions are extracted.
        """
        for function in self._functions.values():
            self._update_function_dependencies(function)

    def _extract_functions(self):
        """
        Parses the C file and extracts function information.
        """
        self._extract_function_info(self.translation_unit.cursor)

    def _collect_structs_and_unions(self, node):
        if (node.kind == cindex.CursorKind.STRUCT_DECL or node.kind == cindex.CursorKind.UNION_DECL) and node.is_definition():
            # Exclude structs declared in system headers
            if node.location and not self._is_in_system_header(node):
                name = node.spelling
                # ignore unnamed structs TODO: is this good?
                if name.find("unnamed at") == -1:
                    dependencies = []
                    struct_info = StructInfo(node, name, dependencies)
                    self._structs_unions[name] = struct_info
        for child in node.get_children():
            self._collect_structs_and_unions(child)

    def _extract_function_info(self, node):
        """
        Recursively extracts function information from the AST.
        """
        if node.kind == cindex.CursorKind.FUNCTION_DECL:
            if node.is_definition():
                if not self._is_in_system_header(node):
                    name = node.spelling
                    return_type = node.result_type.spelling
                    arguments = [(arg.spelling, arg.type.spelling)
                                 for arg in node.get_arguments()]
                    location = f"{node.location.file}:{node.location.line}"

                    # Collect functions
                    called_functions = []  # Keep blank for now, update later

                    # Collect structs
                    used_struct_names = self._collect_structs_unions_dependencies(
                        node)
                    used_structs = set()
                    used_type_aliases = {}
                    for used_struct_name in used_struct_names:
                        if used_struct_name in self._structs_unions:
                            used_structs.add(
                                self._structs_unions[used_struct_name])
                        elif used_struct_name in self._type_alias:
                            original_struct_name = self._type_alias[used_struct_name]
                            if original_struct_name in self._structs_unions:
                                used_structs.add(
                                    self._structs_unions[self._type_alias[used_struct_name]])
                            used_type_aliases[used_struct_name] = self._type_alias[used_struct_name]

                    # Collect global variables
                    used_global_vars = self._collect_global_variable_dependencies(
                        node)
                    # Collect enums
                    used_enums = self._collect_enum_dependencies(node)
                    used_enum_values = set()
                    used_enum_definitions = set()
                    for used_enum in used_enums:
                        if type(used_enum) == EnumValueInfo:
                            used_enum_values.add(used_enum)
                        else:
                            used_enum_definitions.add(used_enum)
                    function_info = FunctionInfo(
                        node,
                        name,
                        return_type,
                        arguments,
                        called_functions,
                        list(used_structs),
                        list(used_global_vars),
                        list(used_enum_values),
                        list(used_enum_definitions),
                        used_type_aliases
                    )
                    self._functions[name] = function_info
                    self._collect_global_variable_dependencies(
                        node, True, name)
        for child in node.get_children():
            self._extract_function_info(child)

    def _collect_function_dependencies(self, node, function_names):
        """
        Recursively collects the names of functions called within the given node,
        excluding standard library functions.
        """
        called_functions = set()
        for child in node.get_children():
            if child.kind == cindex.CursorKind.CALL_EXPR:
                called_func_cursor = child.referenced
                if called_func_cursor:
                    # Exclude functions declared in system headers
                    if called_func_cursor.location and not self._is_in_system_header(called_func_cursor):
                        called_functions.add(called_func_cursor.spelling)
                else:
                    # For unresolved references, include if in function_names
                    called_func_name = child.spelling or child.displayname
                    if called_func_name in function_names:
                        called_functions.add(called_func_name)
            called_functions.update(
                self._collect_function_dependencies(child, function_names))
        return called_functions

    def _collect_structs_unions_dependencies(self, node):
        """
        Recursively collects the names of structs / unions used within the given node.
        """
        used_structs = set()
        for child in node.get_children():
            if child.kind == cindex.CursorKind.TYPE_REF or child.kind == cindex.CursorKind.STRUCT_DECL or child.kind == cindex.CursorKind.UNION_DECL:
                # Exclude structs declared in system headers
                # TODO: Maybe problematic if we ignore dependencies in system headers (e.g. network socket structs)
                if child.location and not self._is_in_system_header(child):
                    if child.spelling.startswith("struct ") or child.spelling.startswith("union "):
                        # handle the `struct NAME` and `union NAME` cases
                        used_structs.add(child.spelling.split(" ")[1])
                    else:
                        used_structs.add(child.spelling)
            used_structs.update(
                self._collect_structs_unions_dependencies(child))
        return used_structs

    def _collect_global_variable_dependencies(self, node, stdio=False, function_name=None):
        """
        Recursively collects the names of global variables used within the given node.
        """
        used_global_vars = set()
        for child in node.get_children():
            if child.kind == cindex.CursorKind.DECL_REF_EXPR and not self._is_in_system_header(child):
                referenced_cursor = child.referenced
                if referenced_cursor.kind == cindex.CursorKind.VAR_DECL:
                    if referenced_cursor.storage_class == cindex.StorageClass.STATIC or referenced_cursor.linkage == cindex.LinkageKind.EXTERNAL:
                        global_var = GlobalVarInfo(referenced_cursor)
                        used_global_vars.add(global_var)
                        self._global_vars[global_var.name] = global_var
            elif child.kind == cindex.CursorKind.DECL_REF_EXPR and child.spelling in standard_io and stdio:
                # for standard I/O
                assert function_name is not None
                self._functions[function_name].add_stdio(child.spelling)
            used_global_vars.update(self._collect_global_variable_dependencies(
                child,
                stdio,
                function_name
            ))
        return used_global_vars

    def _collect_enum_dependencies(self, node):
        """
        Recursively collects all the enum items used within the given node.
        """
        used_enums = set()
        for child in node.get_children():
            if child.kind == cindex.CursorKind.DECL_REF_EXPR and not self._is_in_system_header(child):
                referenced_cursor = child.referenced
                if referenced_cursor.kind == cindex.CursorKind.ENUM_CONSTANT_DECL:
                    enum_value_info = EnumValueInfo(referenced_cursor)
                    self._enums[enum_value_info.definition.name] = enum_value_info.definition
                    used_enums.add(enum_value_info)
            elif child.kind == cindex.CursorKind.TYPE_REF or child.kind == cindex.CursorKind.ENUM_DECL:
                if child.kind == cindex.CursorKind.TYPE_REF:
                    referenced_type = child.referenced
                    if referenced_type.kind == cindex.CursorKind.ENUM_DECL:
                        enum_info = EnumInfo(referenced_type)
                        self._enums[enum_info.name] = enum_info
                        used_enums.add(enum_info)
                else:  # ENUM_DECL
                    enum_info = EnumInfo(child)
                    self._enums[enum_info.name] = enum_info
                    used_enums.add(enum_info)

            used_enums.update(self._collect_enum_dependencies(child))
        return used_enums

    def retrieve_all_struct_dependencies(self, struct_union: StructInfo):
        """
        Recursively collects all dependent structs/unions of the given struct/union.
        """
        result = set()
        result.add(struct_union.name)
        for dependency in struct_union.dependencies:
            if dependency not in result:
                result.update(self.retrieve_all_struct_dependencies(
                    self._structs_unions[dependency.name]))

        return result

    def extract_function_code(self, function_name):
        """
        Extracts the code of the function with the given name from the file.

        Raises ValueError if the function is not found
        """
        function = self.get_function_info(function_name)
        function_node = function.node
        if not function_node.is_definition():
            function_node = function_node.get_definition()

        with open(self.filename, "r") as file:
            lines = file.readlines()
            start_line = function_node.extent.start.line - 1
            end_line = function_node.extent.end.line
            return "".join(lines[start_line:end_line])

    def extract_struct_union_definition_code(self, struct_union_name):
        """
        Extracts the code of the struct or union definition with the given name from the file.
        handle the `typedef struct` and `struct` cases

        Raises ValueError if the function is not found
        """
        struct_union = self.get_struct_info(struct_union_name)
        struct_union_node = struct_union.node
        if not struct_union_node.is_definition():
            struct_union_node = struct_union_node.get_definition()

        with open(self.filename, "r") as file:
            lines = file.readlines()
            start_line = struct_union_node.extent.start.line - 1
            end_line = struct_union_node.extent.end.line
            return "".join(lines[start_line:end_line])

    def extract_enum_definition_code(self, enum_name):
        """
        Extracts the code of the enum definition with the given name from the file.

        Raises ValueError if the function is not found
        """
        enum = self._enums[enum_name]
        enum_node = enum.node
        if not enum_node.is_definition():
            enum_node = enum_node.get_definition()

        with open(self.filename, "r") as file:
            lines = file.readlines()
            start_line = enum_node.extent.start.line - 1
            end_line = enum_node.extent.end.line
            return "".join(lines[start_line:end_line])

    def extract_global_var_definition_code(self, global_var_name):
        """
        Extracts the code of the global variable definition with the given name from the file.

        Raises ValueError if the function is not found
        """
        global_var = self.get_global_var_info(global_var_name)
        global_var_node = global_var.node

        with open(self.filename, "r") as file:
            lines = file.readlines()
            start_line = global_var_node.extent.start.line - 1
            end_line = global_var_node.extent.end.line
            return "".join(lines[start_line:end_line])

    def _is_in_system_header(self, node):
        """
        Determines if the location is in a system header.
        """
        node_definition = node.get_definition()
        if node_definition is None:
            return True
        try:
            node_file_name = node_definition.location.file.name
        except AttributeError:
            return False
        # search for the file in the include paths
        for include_path in self.compiler_include_paths:
            if node_file_name.startswith(include_path):
                return True

        return bool(cindex.conf.lib.clang_Location_isInSystemHeader(node.location))

    def print_ast(self, node=None, indent=0):
        """
        Prints the AST of the given node.
        """
        if node is None:
            node = self.translation_unit.cursor
            for child in node.get_children():
                self.print_ast(child, indent)
        if node.location.file is None or node.location.file.name != self.filename:
            # don't print nodes from other files
            return
        print(' ' * indent, node.kind, node.spelling, node.location)
        for child in node.get_children():
            self.print_ast(child, indent + 2)

    def statistic(self):
        result = ""
        for struct_union in self._structs_unions.values():
            result += f"Struct/Union Name: {struct_union.name}\n"
            result += "Dependencies:\n"
            for dependency in struct_union.dependencies:
                result += f"  {dependency}\n"
            result += '-' * 40 + "\n"

        for func in self._functions.values():
            result += f"Function Name: {func.name}\n"
            result += f"Return Type: {func.return_type}\n"
            result += "Arguments:\n"
            for param_name, param_type in func.arguments:
                result += f"  {param_type} {param_name}\n"
            result += f"Location: {func.location}\n"
            result += "Function Dependencies:\n"
            for called_func in func.function_dependencies:
                result += f"  {called_func}\n"
            result += "Struct Dependencies:\n"
            for used_struct in func.struct_dependencies:
                result += f"  {used_struct.name}\n"
                result += "    Dependencies:\n"
                for dependency in used_struct.dependencies:
                    result += f"        {dependency}\n"
            result += "Global Var Dependencies:\n"
            for used_global_var in func.global_vars_dependencies:
                result += f"  {used_global_var.name}\n"
            result += "Enum Dependencies:\n"
            for used_enum in func.enum_values_dependencies:
                result += f"  {used_enum.name} = {used_enum.value}\n"
                result += f"    Definition: {
                    used_enum.definition_node.extent.start.line}\n"
            result += "-" * 40 + "\n"

        result += "Function Code:\n"
        locs = []
        for func in self._functions.values():
            result += f"Function Name: {func.name}\n"
            code = self.extract_function_code(func.name)
            if code:
                result += code + "\n"
                loc = len(code.split("\n"))
                locs.append(loc)
            result += "-" * 40 + "\n"

        if locs:  # Added check to avoid division by zero
            result += f"Avg Func LOC: {sum(locs) / len(locs)}\n"
            result += f"Max Func LOC: {max(locs)}\n"
            result += f"Min Func LOC: {min(locs)}\n"
            result += '-' * 40 + "\n"

        result += "Struct/Union Code:\n"
        for struct_union in self._structs_unions.values():
            code = self.extract_struct_union_definition_code(struct_union.name)
            if code:
                result += f"Struct/Union Name: {struct_union.name}\n"
                result += code + "\n"
            result += "-" * 40 + "\n"

        result += "Global Variables:\n"
        for global_var in self._global_vars.values():
            result += f"Global Var Name: {global_var.name}\n"
            result += f"Type: {global_var.type}\n"
            result += f"Location: {global_var.location}\n"
            result += "-" * 40 + "\n"

        return result
