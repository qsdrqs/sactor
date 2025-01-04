from clang import cindex
from sactor.data_types import DataTypes


class StructInfo:
    def __init__(self, node, name, location, dependencies=None):
        self.node = node
        self.name: str = name
        self.location = location
        self.dependencies: list[StructInfo] = dependencies if dependencies is not None else []
        # determine datatype of struct
        if node.kind == cindex.CursorKind.STRUCT_DECL:
            self.data_type = DataTypes.STRUCT
        else:
            self.data_type = DataTypes.UNION

    def __hash__(self):
        return hash(self.name) + hash(self.location)

    def __eq__(self, other):
        return self.name == other.name
