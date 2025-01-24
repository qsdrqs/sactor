from clang.cindex import Cursor

class EnumValueInfo:
    def __init__(self, node):
        self.node: Cursor = node
        self.name: str = node.spelling
        self.value = node.enum_value
        self.definition = EnumInfo(node.get_definition().semantic_parent)

    def __hash__(self):
        return hash(self.name) + hash(self.value)

    def __eq__(self, other):
        return self.name == other.name and self.value == other.value

    def __repr__(self):
        return f"EnumValueInfo({self.name} = {self.value})"

class EnumInfo:
    def __init__(self, node):
        self.node: Cursor = node
        self.name: str = node.spelling
        self.location: str = f"{node.location.file.name}:{node.location.line}:{node.location.column}"

    def __hash__(self):
        return hash(self.name) + hash(self.location)

    def __eq__(self, other):
        return self.name == other.name and self.location == other.location

    def __repr__(self):
        return f"EnumInfo({self.name})"
