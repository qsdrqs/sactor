from clang import cindex


class StructInfo:
    def __init__(self, node, name, location, dependencies=None):
        self.node = node
        self.is_struct: bool = node.kind == cindex.CursorKind.STRUCT_DECL
        self.name = name
        self.location = location
        self.dependencies: list[StructInfo] = dependencies if dependencies is not None else []

    def __hash__(self):
        return hash(self.name) + hash(self.location)

    def __eq__(self, other):
        return self.name == other.name
