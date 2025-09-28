from clang import cindex
from clang.cindex import Cursor

from .enum_info import EnumInfo, EnumValueInfo


class GlobalVarInfo():
    def __init__(self, node: Cursor):
        self.node: Cursor = node
        self.name: str = node.spelling
        self.type: str = node.type.spelling
        self.location: str = f"{node.location.file.name}:{node.location.line}:{node.location.column}"

        # check if the global variable is a constant
        self.is_const: bool = False
        if self.node.type.is_const_qualified() or self.node.type.get_canonical().kind == cindex.TypeKind.CONSTANTARRAY:
            self.is_const = True

        self.is_array = False
        if self.node.type.get_canonical().kind == cindex.TypeKind.CONSTANTARRAY:
            self.is_array = True
            self.array_size = self.node.type.get_array_size()

        self.enum_value_dependencies: list[EnumValueInfo] = []
        self.enum_dependencies: list[EnumInfo] = []

    def __hash__(self) -> int:
        return hash(self.name) + hash(self.location)

    def __eq__(self, othter) -> bool:
        return self.name == othter.name and self.location == othter.location

    def __repr__(self) -> str:
        return f"{self.name} ({self.type})"

    def get_decl(self) -> str:
        return f"{self.type} {self.name};"

    def set_enum_dependencies(
        self,
        enum_values: list[EnumValueInfo],
        enum_defs: list[EnumInfo],
    ) -> None:
        self.enum_value_dependencies = enum_values
        self.enum_dependencies = enum_defs
