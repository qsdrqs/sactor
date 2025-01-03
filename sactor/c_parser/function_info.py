from .struct_info import StructInfo
from .enum_info import EnumInfo
from clang.cindex import Cursor

class FunctionInfo:
    def __init__(self, node, name, return_type, arguments, location, called_functions=None, used_structs=None, used_global_vars=None, used_enums=None):
        self.node = node
        self.name: str = name
        self.return_type = return_type
        self.arguments = arguments
        self.location = location
        self.function_dependencies: list[FunctionInfo] = called_functions if called_functions is not None else []
        self.struct_dependencies: list[StructInfo] = used_structs if used_structs is not None else []
        self.global_vars_dependencies: list[Cursor] = used_global_vars if used_global_vars is not None else []
        self.enum_dependencies: list[EnumInfo] = used_enums if used_enums is not None else []

    def get_signature(self, function_name_sub=None):
        return_type = self.return_type
        function_name = self.name if function_name_sub is None else function_name_sub
        arg_list = []
        for arg_name, arg_type in self.arguments:
            if arg_type.find("[") == -1 and arg_type.find("]") == -1:
                arg_list.append(f"{arg_type} {arg_name}")
            else:
                # int[] a -> int a[]
                arg_list.append(
                    f"{arg_type.replace('[', '').replace(']', '')} {arg_name}[]")
        signature = f"{return_type} {function_name}({', '.join(arg_list)})"
        return signature

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

    def __hash__(self):
        return hash(self.name) + hash(self.location)

    def __eq__(self, other):
        return self.name == other.name
