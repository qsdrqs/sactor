import os
import re
from clang.cindex import Cursor


def _sanitize_enum_name(node: Cursor) -> str:
    raw_name = (node.spelling or "").strip()
    if raw_name and "unnamed" not in raw_name and "/" not in raw_name:
        sanitized = raw_name
    else:
        file_part = "unknown"
        line = 0
        column = 0
        if node.location and node.location.file:
            file_part = os.path.splitext(os.path.basename(node.location.file.name))[0]
            line = node.location.line
            column = node.location.column
        sanitized = f"enum_{file_part}_{line}_{column}"

    sanitized = re.sub(r"[^0-9A-Za-z_]", "_", sanitized)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        sanitized = "enum_unnamed"
    if sanitized[0].isdigit():
        sanitized = f"enum_{sanitized}"
    return sanitized


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
        self.name: str = _sanitize_enum_name(node)
        self.location: str = f"{node.location.file.name}:{node.location.line}:{node.location.column}"

    def __hash__(self):
        return hash(self.name) + hash(self.location)

    def __eq__(self, other):
        return self.name == other.name and self.location == other.location

    def __repr__(self):
        return f"EnumInfo({self.name})"
