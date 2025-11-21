class SymbolRef:
    def __init__(self, name: str, usr: str | None = None,
                 tu_path: str | None = None, target=None,
                 location: str | None = None, notes: str | None = None):
        self.name = name
        self.usr = usr
        self.tu_path = tu_path
        self.target = target
        self.location = location
        self.notes = notes

    def __repr__(self) -> str:
        return f"SymbolRef(name={self.name!r}, usr={self.usr!r}, tu={self.tu_path!r})"


class FunctionDependencyRef(SymbolRef):
    @property
    def struct_dependencies(self):
        if getattr(self, "target", None) is not None:
            return getattr(self.target, "struct_dependencies", [])
        return []

    @property
    def node(self):
        # For compatibility with code paths that expect FunctionInfo-like objects
        if getattr(self, "target", None) is not None:
            return getattr(self.target, "node", None)
        return None


class StructRef(SymbolRef):
    pass


class EnumRef(SymbolRef):
    pass


class GlobalVarRef(SymbolRef):
    pass

