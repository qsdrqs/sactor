from clang import cindex
from clang.cindex import Cursor

from sactor.data_types import DataType


class StructInfo:
    def __init__(self, node, name, dependencies=None, type_aliases=None):
        self.node: Cursor = node
        self.name: str = name
        self.location = f"{node.location.file}:{node.location.line}"
        self.dependencies: list[StructInfo] = dependencies if dependencies is not None else []
        self.type_aliases: dict[str, str] = type_aliases if type_aliases is not None else {}
        # determine datatype of struct
        if node.kind == cindex.CursorKind.STRUCT_DECL:
            self.data_type = DataType.STRUCT
        else:
            self.data_type = DataType.UNION

    def __hash__(self):
        return hash(self.name) + hash(self.location)

    def __eq__(self, other):
        return self.name == other.name and self.location == other.location

    def __repr__(self):
        return f"StructInfo({self.name})"
