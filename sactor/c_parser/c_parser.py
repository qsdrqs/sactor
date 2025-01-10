from clang import cindex

from sactor import utils

from .enum_info import EnumInfo
from .function_info import FunctionInfo
from .struct_info import StructInfo


class CParser:
    def __init__(self, filename):
        self.filename = filename

        # Parse the C file
        index = cindex.Index.create()
        self.compiler_include_paths = utils.get_compiler_include_paths()
        args = ['-x', 'c', '-std=c99']
        args.extend([f"-I{path}" for path in self.compiler_include_paths])
        self.translation_unit = index.parse(
            self.filename, args=args, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)

        self._type_alias: dict[str, str] = self._extract_type_alias()

        structs_unions_list = self._extract_structs_unions()
        self._structs_unions = dict((struct_union.name, struct_union)
                                    for struct_union in structs_unions_list)
        self._update_structs_unions()

        functions_list = self._extract_functions()
        self._functions = dict((func.name, func) for func in functions_list)
        self._update_functions()

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

    def get_function_info(self, function_name):
        """
        Raises ValueError if the function is not found.
        """
        if function_name in self._functions:
            return self._functions[function_name]
        raise ValueError(f"Function {function_name} not found")

    def get_functions(self) -> list[FunctionInfo]:
        return list(self._functions.values())

    def _extract_type_alias(self):
        """
        Extracts type aliases (typedefs) from the C file.
        Returns a dictionary mapping alias names to their original types.
        """
        type_alias = {}

        # Start processing from the translation unit
        self._process_typedef(self.translation_unit.cursor, type_alias)

        return type_alias

    def _extract_structs_unions(self) -> list[StructInfo]:
        """
        Parses the C file and extracts struct and union information, including dependencies.
        """
        structs_unions = self._collect_structs_and_unions(
            self.translation_unit.cursor)
        return structs_unions

    def _process_typedef(self, node, type_alias: dict[str, str]):
        if node.kind == cindex.CursorKind.TYPEDEF_DECL:
            # Skip system headers
            if node.location and not self._is_in_system_header(node):
                alias_name = node.spelling

                # Get the underlying type
                underlying_type = node.underlying_typedef_type
                if underlying_type:
                    target_spelling = underlying_type.spelling
                    # handle the `typedef struct` and `struct` cases
                    if target_spelling.startswith("struct ") or target_spelling.startswith("union "):
                        target_spelling = target_spelling.split(" ")[1]
                    if target_spelling.strip() == alias_name.strip():
                        # Skip self-referencing typedefs
                        return
                    type_alias[alias_name] = target_spelling

        for child in node.get_children():
            self._process_typedef(child, type_alias)

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
                    used_structs.add(self._structs_unions[self._type_alias[used_struct_name]])
                type_aliases[used_struct_name] = self._type_alias[used_struct_name]

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

    def _extract_functions(self) -> list[FunctionInfo]:
        """
        Parses the C file and extracts function information.
        """
        functions = self._extract_function_info(
            self.translation_unit.cursor)
        return functions

    def _collect_structs_and_unions(self, node):
        structs = []
        if (node.kind == cindex.CursorKind.STRUCT_DECL or node.kind == cindex.CursorKind.UNION_DECL) and node.is_definition():
            # Exclude structs declared in system headers
            if node.location and not self._is_in_system_header(node):
                name = node.spelling
                # ignore unnamed structs TODO: is this good?
                if name.find("unnamed at") == -1:
                    location = f"{node.location.file}:{node.location.line}"
                    dependencies = []
                    structs.append(StructInfo(
                        node, name, location, dependencies))
        for child in node.get_children():
            structs.extend(self._collect_structs_and_unions(child))
        return structs

    def _extract_function_info(self, node):
        """
        Recursively extracts function information from the AST.
        """
        functions = []
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

                    functions.append(FunctionInfo(
                        node,
                        name,
                        return_type,
                        arguments,
                        location,
                        called_functions,
                        used_structs,
                        used_global_vars,
                        used_enums,
                        used_type_aliases
                    ))
        for child in node.get_children():
            functions.extend(
                self._extract_function_info(child))
        return functions

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

    def _collect_global_variable_dependencies(self, node):
        """
        Recursively collects the names of global variables used within the given node.
        """
        used_global_vars = set()
        for child in node.get_children():
            if child.kind == cindex.CursorKind.DECL_REF_EXPR and not self._is_in_system_header(child):
                referenced_cursor = child.referenced
                if referenced_cursor.kind == cindex.CursorKind.VAR_DECL:
                    if referenced_cursor.storage_class == cindex.StorageClass.STATIC or referenced_cursor.linkage == cindex.LinkageKind.EXTERNAL:
                        used_global_vars.add(referenced_cursor)
            used_global_vars.update(
                self._collect_global_variable_dependencies(child))
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
                    enum_info = EnumInfo(referenced_cursor, referenced_cursor.spelling,
                                         referenced_cursor.enum_value, referenced_cursor.get_definition())
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
                result += f"  {used_global_var.spelling}\n"
            result += "Enum Dependencies:\n"
            for used_enum in func.enum_dependencies:
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

        return result
