from clang import cindex
from clang.cindex import Cursor


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

    def __hash__(self) -> int:
        return hash(self.name) + hash(self.location)

    def __eq__(self, othter) -> bool:
        return self.name == othter.name and self.location == othter.location

    def __repr__(self) -> str:
        return f"{self.name} ({self.type})"

    def get_code(self) -> str:
        tokens = self.node.get_tokens()
        return " ".join([token.spelling for token in tokens])

    def get_decl(self) -> str:
        return f"{self.type} {self.name};"
