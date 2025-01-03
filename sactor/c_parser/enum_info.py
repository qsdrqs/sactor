class EnumInfo:
    def __init__(self, node, name, value, definition_node):
        self.node = node
        self.name: str = name
        self.value = value
        self.definition_node = definition_node

    def __hash__(self):
        return hash(self.name) + hash(self.value)

    def __eq__(self, other):
        return self.name == other.name
