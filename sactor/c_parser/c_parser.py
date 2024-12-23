import ctypes
import sys

from clang import cindex
from .struct_info import StructInfo
from .function_info import FunctionInfo
from .enum_info import EnumInfo

# Load the clang_Location_isInSystemHeader function from the libclang library
cindex.conf.lib.clang_Location_isInSystemHeader.argtypes = [
    cindex.SourceLocation,
]
cindex.conf.lib.clang_Location_isInSystemHeader.restype = ctypes.c_bool


class CParser:
    def __init__(self, filename):
        self.filename = filename
        structs_unions_list = self._extract_structs_unions()
        self.structs_unions = dict((struct_union.name, struct_union)
                                   for struct_union in structs_unions_list)

        functions_list = self._extract_functions()
        self.functions = dict((func.name, func) for func in functions_list)
        self._update_functions()

    def _extract_structs_unions(self) -> list[StructInfo]:
        """
        Parses the C file and extracts struct and union information, including dependencies.
        """
        index = cindex.Index.create()
        translation_unit = index.parse(self.filename)
        structs_unions = self.get_structs_unions(translation_unit.cursor)
        return structs_unions

    def _update_function_dependencies(self, function: FunctionInfo):
        """
        Updates the depedencies of each function.
        """
        node = function.node
        function_names = set(self.functions.keys())
        called_function_names = self.get_called_functions(
            node, function_names)
        called_functions = set()
        for called_function_name in called_function_names:
            if called_function_name in self.functions:
                called_functions.add(
                    self.functions[called_function_name])

        function.function_dependencies = list(called_functions)


    def _update_functions(self):
        """
        Update the information of each function. Needs to be called after all functions are extracted.
        """
        for function in self.functions.values():
            self._update_function_dependencies(function)

    def _extract_functions(self) -> list[FunctionInfo]:
        """
        Parses the C file and extracts function information.
        """
        index = cindex.Index.create()
        translation_unit = index.parse(self.filename)
        function_names = self.collect_function_names(translation_unit.cursor)
        functions = self.get_functions(translation_unit.cursor, function_names)
        return functions

    def collect_function_names(self, node):
        """
        Collects the names of all functions
        """
        names = set()
        if node.kind == cindex.CursorKind.FUNCTION_DECL:
            if node.is_definition():
                if node.location.file and node.location.file.name == self.filename:
                    names.add(node.spelling)
        for child in node.get_children():
            names.update(self.collect_function_names(child))
        return names

    def get_structs_unions(self, node):
        structs = []
        if (node.kind == cindex.CursorKind.STRUCT_DECL or node.kind == cindex.CursorKind.UNION_DECL) and node.is_definition():
            name = node.spelling
            if name.find("unnamed at") == -1:  # ignore unnamed structs TODO: is this good?
                location = f"{node.location.file}:{node.location.line}"
                dependencies = self.get_used_structs_unions(node)
                for dependency in dependencies:
                    if dependency == name:
                        # Remove self-reference
                        dependencies.remove(dependency)
                        break
                structs.append(StructInfo(node, name, location, dependencies))
        for child in node.get_children():
            structs.extend(self.get_structs_unions(child))
        return structs

    def get_functions(self, node, function_names):
        """
        Recursively extracts function information from the AST.
        """
        functions = []
        if node.kind == cindex.CursorKind.FUNCTION_DECL:
            if node.is_definition():
                if node.location.file and node.location.file.name == self.filename:
                    name = node.spelling
                    return_type = node.result_type.spelling
                    arguments = [(arg.spelling, arg.type.spelling)
                                 for arg in node.get_arguments()]
                    location = f"{node.location.file}:{node.location.line}"

                    # Collect functions
                    called_functions = [] # Keep blank for now, update later

                    # Collect structs
                    used_struct_names = self.get_used_structs_unions(node)
                    used_structs = set()
                    for used_struct_name in used_struct_names:
                        if used_struct_name in self.structs_unions:
                            used_structs.add(
                                self.structs_unions[used_struct_name])

                    # Collect global variables
                    used_global_vars = self.get_used_global_vars(node)
                    # Collect enums
                    used_enums = self.get_used_enums(node)

                    functions.append(FunctionInfo(node, name, return_type, arguments, location,
                                     called_functions, used_structs, used_global_vars, used_enums))
        for child in node.get_children():
            functions.extend(self.get_functions(child, function_names))
        return functions

    def get_called_functions(self, node, function_names):
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
                    if called_func_cursor.location and not self.is_in_system_header(called_func_cursor):
                        called_functions.add(called_func_cursor.spelling)
                else:
                    # For unresolved references, include if in function_names
                    called_func_name = child.spelling or child.displayname
                    if called_func_name in function_names:
                        called_functions.add(called_func_name)
            called_functions.update(
                self.get_called_functions(child, function_names))
        return called_functions

    def get_used_structs_unions(self, node):
        """
        Recursively collects the names of structs / unions used within the given node.
        """
        used_structs = set()
        for child in node.get_children():
            if child.kind == cindex.CursorKind.TYPE_REF or child.kind == cindex.CursorKind.STRUCT_DECL or child.kind == cindex.CursorKind.UNION_DECL:
                if child.spelling.startswith("struct ") or child.spelling.startswith("union "):
                    # handle the `struct NAME` and `union NAME` cases
                    used_structs.add(child.spelling.split(" ")[1])
                else:
                    used_structs.add(child.spelling)
            used_structs.update(self.get_used_structs_unions(child))
        return used_structs

    def get_used_global_vars(self, node):
        """
        Recursively collects the names of global variables used within the given node.
        """
        used_global_vars = set()
        for child in node.get_children():
            if child.kind == cindex.CursorKind.DECL_REF_EXPR:
                referenced_cursor = child.referenced
                if referenced_cursor.kind == cindex.CursorKind.VAR_DECL:
                    if referenced_cursor.storage_class == cindex.StorageClass.STATIC or referenced_cursor.linkage == cindex.LinkageKind.EXTERNAL:
                        used_global_vars.add(referenced_cursor)
            used_global_vars.update(self.get_used_global_vars(child))
        return used_global_vars

    def get_used_enums(self, node):
        """
        Recursively collects all the enum items used within the given node.
        """
        used_enums = set()
        for child in node.get_children():
            if child.kind == cindex.CursorKind.DECL_REF_EXPR:
                referenced_cursor = child.referenced
                if referenced_cursor.kind == cindex.CursorKind.ENUM_CONSTANT_DECL:
                    enum_info = EnumInfo(referenced_cursor, referenced_cursor.spelling,
                                         referenced_cursor.enum_value, referenced_cursor.get_definition())
                    used_enums.add(enum_info)
            used_enums.update(self.get_used_enums(child))
        return used_enums

    def get_all_dependent_structs(self, struct_union: StructInfo):
        """
        Recursively collects all dependent structs/unions of the given struct/union.
        """
        result = set()
        result.add(struct_union.name)
        for dependency in struct_union.dependencies:
            if dependency not in result:
                result.update(self.get_all_dependent_structs(
                    self.structs_unions[dependency]))

        return result

    def get_code_of_function(self, function_name):
        """
        Extracts the code of the function with the given name from the file.
        """
        index = cindex.Index.create()
        translation_unit = index.parse(self.filename)
        for node in translation_unit.cursor.get_children():
            if node.kind == cindex.CursorKind.FUNCTION_DECL and node.spelling == function_name:
                node = node.get_definition()
                with open(self.filename, "r") as file:
                    lines = file.readlines()
                    start_line = node.extent.start.line - 1
                    end_line = node.extent.end.line
                    return "".join(lines[start_line:end_line])
        return None

    def get_code_of_struct_union_definition(self, struct_union_name):
        """
        Extracts the code of the struct or union definition with the given name from the file.
        handle the `typedef struct` and `struct` cases
        """
        index = cindex.Index.create()
        translation_unit = index.parse(self.filename)
        for node in translation_unit.cursor.get_children():
            if (node.kind == cindex.CursorKind.TYPE_REF
                or node.kind == cindex.CursorKind.UNION_DECL
                    or node.kind == cindex.CursorKind.STRUCT_DECL) and node.spelling == struct_union_name:
                node = node.get_definition()
                with open(self.filename, "r") as file:
                    lines = file.readlines()
                    start_line = node.extent.start.line - 1
                    end_line = node.extent.end.line
                    return "".join(lines[start_line:end_line])

        return None

    def is_in_system_header(self, node):
        """
        Determines if the location is in a system header.
        """
        node_definition = node.get_definition()
        if node_definition is None:
            return True
        return False

    def statistic(self):
        result = ""
        for struct_union in self.structs_unions.values():
            result += f"Struct/Union Name: {struct_union.name}\n"
            result += "Dependencies:\n"
            for dependency in struct_union.dependencies:
                result += f"  {dependency}\n"
            result += '-' * 40 + "\n"

        for func in self.functions.values():
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
        for func in self.functions.values():
            result += f"Function Name: {func.name}\n"
            code = self.get_code_of_function(func.name)
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
        for struct_union in self.structs_unions.values():
            code = self.get_code_of_struct_union_definition(struct_union.name)
            if code:
                result += f"Struct/Union Name: {struct_union.name}\n"
                result += code + "\n"
            result += "-" * 40 + "\n"

        return result


def main():
    if len(sys.argv) != 2:
        print("Usage: python parse_c.py <c_file>")
        sys.exit(1)
    filename = sys.argv[1]


if __name__ == '__main__':
    main()
