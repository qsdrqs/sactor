from collections import deque
from functools import lru_cache

from clang import cindex
import os
import re
import tempfile

from sactor import logging as sactor_logging, utils
from sactor.utils import read_file, read_file_lines

from .enum_info import EnumInfo, EnumValueInfo
from .function_info import FunctionInfo
from .global_var_info import GlobalVarInfo
from .struct_info import StructInfo
from clang.cindex import CursorKind
from .refs import FunctionDependencyRef, StructRef, EnumRef, GlobalVarRef, SymbolRef

standard_io = [
    "stdin",
    "stdout",
    "stderr",
]


logger = sactor_logging.get_logger(__name__)


class CParser:
    def __init__(self, filename, extra_args=None, omit_error=False):
        self.filename = filename

        # Parse the C file
        index = cindex.Index.create()
        self.compiler_include_paths = utils.get_compiler_include_paths()
        args = ['-x', 'c', '-std=c99'] + (extra_args or [])
        args.extend([f"-I{path}" for path in self.compiler_include_paths])
        self.translation_unit = index.parse(
            self.filename, args=args, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        # check diagnostics
        if not omit_error and len(self.translation_unit.diagnostics) > 0:
            for diag in self.translation_unit.diagnostics:
                if diag.severity >= cindex.Diagnostic.Error:
                    logger.warning(
                        "Parsing error in %s: %s", filename, diag.spelling
                    )

        # Initialize data structures
        self._global_vars: dict[str, GlobalVarInfo] = {}
        self._enums: dict[str, EnumInfo] = {}
        self._structs_unions: dict[str, StructInfo] = {}
        self._functions: dict[str, FunctionInfo] = {}
        
        self._intrinsic_alias = _discover_intrinsic_aliases()
        self._type_alias: dict[str, str] = self._extract_type_alias()
        self._extract_structs_unions()
        self._update_structs_unions()

        self._extract_functions()
        self._update_functions()
        # only structs used by functions are preserved. Otherwise c2rust does not have corresponding translation
        self._structs_unions = self._get_all_used_structs()

    def backfill_nonfunc_refs(
        self,
        struct_def_map: dict[str, str] | None,
        enum_def_map: dict[str, str] | None,
        global_def_map: dict[str, str] | None,
    ) -> None:
        """Backfill project-level ownership for non-function refs based on USR maps.

        For each FunctionInfo in this parser, iterate `struct_dependency_refs`,
        `enum_dependency_refs`, and `global_dependency_refs`. If a ref has a USR
        and its `tu_path` is empty, set `tu_path` from the corresponding
        definition map. If the ref still cannot resolve (non-system symbols are
        the only ones recorded here), raise ValueError with actionable hints.
        """
        struct_def_map = struct_def_map or {}
        enum_def_map = enum_def_map or {}
        global_def_map = global_def_map or {}

        filled = {"struct": 0, "enum": 0, "global": 0}
        unresolved = 0

        def _resolve_list(kind: str, refs: list[SymbolRef], def_map: dict[str, str], owner_loc: str) -> None:
            nonlocal unresolved
            for ref in refs or []:
                if getattr(ref, "tu_path", None):
                    continue
                usr = getattr(ref, "usr", None)
                name = getattr(ref, "name", "<unknown>")
                if usr:
                    target = def_map.get(usr)
                    if target:
                        ref.tu_path = target
                        filled[kind] += 1
                        continue
                    unresolved += 1
                    raise ValueError(
                        (
                            f"Unresolved non-function reference: {kind} '{name}' (USR={usr}) at {owner_loc}. "
                            "Hint: ensure defining file is present in compile_commands.json and flags are correct."
                        )
                    )
                else:
                    unresolved += 1
                    raise ValueError(
                        (
                            f"Unresolved non-function reference: {kind} '{name}' (USR=None) at {owner_loc}. "
                            "Hint: ensure libclang can obtain USR; check headers and compile flags."
                        )
                    )

        for func in self.get_functions():
            owner_loc = getattr(func, "location", self.filename)
            _resolve_list("struct", getattr(func, "struct_dependency_refs", []), struct_def_map, owner_loc)
            _resolve_list("enum", getattr(func, "enum_dependency_refs", []), enum_def_map, owner_loc)
            _resolve_list("global", getattr(func, "global_dependency_refs", []), global_def_map, owner_loc)

        logger.info(
            "Backfill non-function refs complete: structs=%d, enums=%d, globals=%d, unresolved=%d",
            filled["struct"], filled["enum"], filled["global"], unresolved,
        )

    @staticmethod
    def is_func_type(t: cindex.Type) -> bool:
        try:
            if t.kind == cindex.TypeKind.POINTER:
                p = t.get_pointee()
                return p.kind in (cindex.TypeKind.FUNCTIONPROTO, cindex.TypeKind.FUNCTIONNOPROTO)
            return t.kind in (cindex.TypeKind.FUNCTIONPROTO, cindex.TypeKind.FUNCTIONNOPROTO)
        except Exception:
            return False

    def get_code(self):
        code = read_file(self.filename)
        return code

    def get_struct_info(self, struct_name):
        """
        Raises ValueError if the function is not found.
        """
        if struct_name in self._structs_unions:
            return self._structs_unions[struct_name]
        raise ValueError(f"Struct/Union {struct_name} not found")

    def get_structs(self) -> list[StructInfo]:
        return list(self._structs_unions.values())

    def get_function_info(self, function_name) -> FunctionInfo:
        """
        Raises ValueError if the function is not found.
        """
        if function_name in self._functions:
            return self._functions[function_name]
        raise ValueError(f"Function {function_name} not found")

    def get_functions(self) -> list[FunctionInfo]:
        return list(self._functions.values())

    def get_global_var_info(self, global_var_name):
        """
        Raises ValueError if the global variable is not found.
        """
        if global_var_name in self._global_vars:
            return self._global_vars[global_var_name]
        raise ValueError(f"Global variable {global_var_name} not found")

    def get_global_vars(self) -> list[GlobalVarInfo]:
        return list(self._global_vars.values())
    

    def get_enum_info(self, enum_name):
        """
        Raises ValueError if the enum is not found.
        """
        if enum_name in self._enums:
            return self._enums[enum_name]
        raise ValueError(f"Enum {enum_name} not found")

    def get_enums(self) -> list[EnumInfo]:
        return list(self._enums.values())

    def get_typedef_nodes(self):
        """
        Returns a list of all typedef declaration nodes in the C file.
        """
        typedef_nodes = []
        self._process_typedef_nodes(
            self.translation_unit.cursor, typedef_nodes=typedef_nodes)
        return typedef_nodes
    
    @staticmethod
    def _build_compiler_intrinsic_define_map(config: str) -> dict:
        ptn = re.compile(r"^#define +(\w+) +([\w ]+)")
        lines = config.splitlines()
        res = {}
        for line in lines:
            match = ptn.match(line)
            if match:
                res[match.group(1)] = match.group(2)
        return res

    # map from instrinsic alias to canonical type

    def _extract_type_alias(self):
        """
        Extracts type aliases (typedefs) from the C file.
        Returns a dictionary mapping alias names to their original types.
        """
        type_alias = {}
        self._process_typedef_nodes(
            self.translation_unit.cursor, type_alias=type_alias)
        type_alias.update(self._intrinsic_alias)
        return type_alias

    def _extract_structs_unions(self):
        """
        Parses the C file and extracts struct and union information, including dependencies.
        """
        self._collect_structs_and_unions(self.translation_unit.cursor)

    def _process_typedef_nodes(self, node, type_alias=None, typedef_nodes=None):
        """
        Unified function to process typedef nodes.
        Can collect type aliases and/or typedef nodes based on provided parameters.
        """
        if node.kind == cindex.CursorKind.TYPEDEF_DECL:
            if node.location and not self._is_in_system_header(node):
                if typedef_nodes is not None:
                    typedef_nodes.append(node)

                if type_alias is not None:
                    alias_name = node.spelling
                    underlying_type = node.underlying_typedef_type.get_canonical()
                    target_spelling = underlying_type.spelling

                    enum_child = None
                    struct_child = None
                    for child in node.get_children():
                        if child.kind == cindex.CursorKind.ENUM_DECL:
                            enum_child = child
                            break
                        elif child.kind == cindex.CursorKind.STRUCT_DECL or child.kind == cindex.CursorKind.UNION_DECL:
                            struct_child = child
                            break

                    # Handle anonymous enum/struct/union typedef like: typedef struct { ... } alias_name;
                    if enum_child and target_spelling.strip() == alias_name.strip():
                        target_spelling = f"enum {alias_name}"
                    elif struct_child and target_spelling.strip() == alias_name.strip():
                        target_spelling = f"struct {alias_name}"

                    if not self.is_func_type(underlying_type) and target_spelling.strip() != alias_name.strip():
                        type_alias[alias_name] = target_spelling

        for child in node.get_children():
            self._process_typedef_nodes(child, type_alias, typedef_nodes)

    def _update_function_dependencies(self, function: FunctionInfo):
        """
        Updates the depedencies of each function.
        """
        node = function.node
        # Collect references (with USR when available)
        refs = self._collect_function_dependency_refs(node)

        # Convert same-TU dependencies to refs with targets
        local_funcs = self._functions
        unified_refs: list[FunctionDependencyRef] = []
        called_function_names = set()
        for ref in refs:
            called_function_names.add(ref.name)
            if ref.name in local_funcs and local_funcs[ref.name].node is not None:
                # Same TU target
                target = local_funcs[ref.name]
                local_ref = FunctionDependencyRef(
                    name=ref.name,
                    usr=getattr(target, 'usr', None) or ref.usr,
                    tu_path=self.filename,
                    target=target,
                    location=ref.location,
                )
                unified_refs.append(local_ref)
            else:
                unified_refs.append(ref)

        function.function_dependencies = unified_refs
        function.called_function_names = sorted(called_function_names)

    def _update_struct_dependencies(self, struct_union: StructInfo):
        """
        Updates the dependencies of each struct or union.
        """
        node = struct_union.node
        used_struct_names = self._collect_structs_unions_dependencies(node)
        used_structs = set()
        type_aliases = {}
        for used_struct_name in used_struct_names:
            # Add the struct to the dependencies if it exists and is not the same as the current struct
            if used_struct_name in self._structs_unions and used_struct_name != struct_union.name:
                used_structs.add(self._structs_unions[used_struct_name])
            elif used_struct_name in self._type_alias:
                original_struct_name = self._type_alias[used_struct_name]
                if original_struct_name in self._structs_unions and original_struct_name != struct_union.name:
                    used_structs.add(
                        self._structs_unions[self._type_alias[used_struct_name]])
                type_aliases[used_struct_name] = original_struct_name

        struct_union.dependencies = list(used_structs)
        struct_union.type_aliases = type_aliases

        used_enums = self._collect_enum_dependencies(node)
        enum_values = set()
        enum_defs = set()
        for used_enum in used_enums:
            if isinstance(used_enum, EnumValueInfo):
                enum_values.add(used_enum)
                enum_defs.add(used_enum.definition)
            else:
                enum_defs.add(used_enum)

        struct_union.enum_value_dependencies = list(
            sorted(enum_values, key=lambda e: e.name)
        )
        struct_union.enum_dependencies = list(
            sorted(enum_defs, key=lambda e: e.name)
        )

    def _update_structs_unions(self):
        """
        Update the information of each struct or union. Needs to be called after all structs and unions are extracted.
        """
        for struct_union in self._structs_unions.values():
            self._update_struct_dependencies(struct_union)

    def _update_functions(self):
        """
        Update the information of each function. Needs to be called after all functions are extracted.
        """
        for function in self._functions.values():
            self._update_function_dependencies(function)

    def _extract_functions(self):
        """
        Parses the C file and extracts function information.
        """
        self._extract_function_info(self.translation_unit.cursor)

    def _collect_structs_and_unions(self, node):
        if (node.kind == cindex.CursorKind.STRUCT_DECL or node.kind == cindex.CursorKind.UNION_DECL) and node.is_definition():
            # Exclude structs declared in system headers
            if node.location and not self._is_in_system_header(node):
                name = node.spelling
                # ignore unnamed structs TODO: is this good?
                if name.find("unnamed at") == -1:
                    dependencies = []
                    struct_info = StructInfo(node, name, dependencies)
                    self._structs_unions[name] = struct_info
        for child in node.get_children():
            self._collect_structs_and_unions(child)

    def _get_all_used_structs(self) -> dict[str, StructInfo]:
        used = {}
        queue = deque()
        for function in self.get_functions():
            for dependency in function.struct_dependencies:
                if dependency.name not in used:
                    used[dependency.name] = dependency
                    queue.append(dependency)

        while queue:
            struct_union = queue.popleft()
            for dependency in struct_union.dependencies:
                if dependency.name not in used:
                    used[dependency.name] = dependency
                    queue.append(dependency)
        # TODO: global variable struct and enum dependencies
        # struct's enum dependencies
        # enum's struct dependencies
        return used        

    def _extract_function_info(self, node):
        """
        Recursively extracts function information from the AST.
        """
        if node.kind == cindex.CursorKind.FUNCTION_DECL:
            if node.is_definition():
                if not self._is_in_system_header(node):
                    name = node.spelling
                    return_type = node.result_type.spelling
                    arguments = [(arg.spelling, arg.type.spelling)
                                 for arg in node.get_arguments()]
                    location = f"{node.location.file}:{node.location.line}"

                    # Collect functions
                    called_functions = []  # Keep blank for now, update later

                    # Collect structs
                    used_struct_names = self._collect_structs_unions_dependencies(
                        node)
                    used_structs = set()
                    used_type_aliases = {}
                    for used_struct_name in used_struct_names:
                        if used_struct_name in self._structs_unions:
                            used_structs.add(
                                self._structs_unions[used_struct_name])
                        elif used_struct_name in self._type_alias:
                            original_struct_name = self._type_alias[used_struct_name]
                            if original_struct_name in self._structs_unions:
                                used_structs.add(
                                    self._structs_unions[self._type_alias[used_struct_name]])
                            used_type_aliases[used_struct_name] = self._type_alias[used_struct_name]

                    # Collect global variables
                    used_global_vars = self._collect_global_variable_dependencies(
                        node)
                    # Collect enums
                    used_enums = self._collect_enum_dependencies(node)
                    used_enum_values = set()
                    used_enum_definitions = set()
                    for used_enum in used_enums:
                        if type(used_enum) == EnumValueInfo:
                            used_enum_values.add(used_enum)
                        else:
                            used_enum_definitions.add(used_enum)
                    function_info = FunctionInfo(
                        node,
                        name,
                        return_type,
                        arguments,
                        called_functions,
                        list(used_structs),
                        list(used_global_vars),
                        list(used_enum_values),
                        list(used_enum_definitions),
                        used_type_aliases,
                        called_function_names=[]
                    )
                    try:
                        function_info.usr = node.get_usr()
                    except Exception:
                        function_info.usr = ""
                    # Populate new reference lists (struct/enum/global) for this function
                    function_info.struct_dependency_refs = self._collect_struct_refs(node)
                    function_info.enum_dependency_refs = self._collect_enum_refs(node)
                    function_info.global_dependency_refs = self._collect_global_refs(node)
                    self._functions[name] = function_info
                    self._collect_global_variable_dependencies(
                        node, True, name)
        for child in node.get_children():
            self._extract_function_info(child)

    def _collect_function_dependency_refs(self, node) -> list[FunctionDependencyRef]:
        """
        Recursively collect function dependency references with USR when available.
        Raises ValueError for unresolved non-system references.
        """
        refs: list[FunctionDependencyRef] = []
        if not node:
            return refs

        def is_function_reference(cursor: cindex.Cursor) -> bool:
            if cursor.kind == CursorKind.DECL_REF_EXPR:
                return bool(cursor.referenced and cursor.referenced.kind == CursorKind.FUNCTION_DECL)
            return False

        for child in node.get_children():
            if child.kind == CursorKind.CALL_EXPR or is_function_reference(child):
                called = child.referenced
                if called:
                    if called.location and not self._is_in_system_header(called):
                        usr = None
                        try:
                            usr = called.get_usr()
                        except Exception:
                            usr = None
                        loc = None
                        try:
                            if child.location and child.location.file:
                                loc = f"{child.location.file.name}:{child.location.line}"
                        except Exception:
                            loc = None
                        refs.append(FunctionDependencyRef(
                            name=called.spelling,
                            usr=usr,
                            tu_path=None,
                            target=None,
                            location=loc,
                        ))
                else:
                    # Unresolved reference not in system header -> raise
                    if not self._is_in_system_header(child):
                        callee = child.spelling or child.displayname or "<unknown>"
                        loc = None
                        try:
                            if child.location and child.location.file:
                                loc = f"{child.location.file.name}:{child.location.line}"
                        except Exception:
                            loc = None
                        raise ValueError(
                            f"Unresolved reference: {callee} (USR=None) at {loc or self.filename}. "
                            f"Hint: ensure defining .c is in compile_commands.json and flags are correct."
                        )
            refs.extend(self._collect_function_dependency_refs(child))
        return refs

    def _collect_struct_refs(self, node) -> list[StructRef]:
        refs: list[StructRef] = []
        if not node:
            return refs
        for child in node.get_children():
            kind = child.kind
            if kind in (cindex.CursorKind.TYPE_REF, cindex.CursorKind.STRUCT_DECL, cindex.CursorKind.UNION_DECL):
                ref_cursor = child.referenced if kind == cindex.CursorKind.TYPE_REF else child
                if ref_cursor and not self._is_in_system_header(ref_cursor):
                    name = ref_cursor.spelling
                    usr = None
                    try:
                        usr = ref_cursor.get_usr()
                    except Exception:
                        usr = None
                    tu_path = None
                    try:
                        decl = ref_cursor.get_definition() or ref_cursor
                        if decl and decl.location and decl.location.file and os.path.samefile(decl.location.file.name, self.filename):
                            tu_path = self.filename
                    except Exception:
                        tu_path = None
                    refs.append(StructRef(name=name, usr=usr, tu_path=tu_path))
            refs.extend(self._collect_struct_refs(child))
        return refs

    def _collect_enum_refs(self, node) -> list[EnumRef]:
        refs: list[EnumRef] = []
        if not node:
            return refs
        for child in node.get_children():
            if child.kind in (cindex.CursorKind.TYPE_REF, cindex.CursorKind.ENUM_DECL, cindex.CursorKind.DECL_REF_EXPR):
                ref_cursor = None
                if child.kind == cindex.CursorKind.TYPE_REF:
                    candidate = child.referenced
                    if candidate and candidate.kind == cindex.CursorKind.ENUM_DECL:
                        ref_cursor = candidate
                elif child.kind == cindex.CursorKind.ENUM_DECL:
                    ref_cursor = child
                elif child.kind == cindex.CursorKind.DECL_REF_EXPR and child.referenced and child.referenced.kind == cindex.CursorKind.ENUM_CONSTANT_DECL:
                    ref_cursor = child.referenced.semantic_parent
                if ref_cursor and not self._is_in_system_header(ref_cursor):
                    name = ref_cursor.spelling
                    usr = None
                    try:
                        usr = ref_cursor.get_usr()
                    except Exception:
                        usr = None
                    tu_path = None
                    try:
                        decl = ref_cursor.get_definition() or ref_cursor
                        if decl and decl.location and decl.location.file and os.path.samefile(decl.location.file.name, self.filename):
                            tu_path = self.filename
                    except Exception:
                        tu_path = None
                    refs.append(EnumRef(name=name, usr=usr, tu_path=tu_path))
            refs.extend(self._collect_enum_refs(child))
        return refs

    def _collect_global_refs(self, node) -> list[GlobalVarRef]:
        refs: list[GlobalVarRef] = []
        if not node:
            return refs
        for child in node.get_children():
            if child.kind == cindex.CursorKind.DECL_REF_EXPR and not self._is_in_system_header(child):
                ref_cursor = child.referenced
                if ref_cursor and ref_cursor.kind == cindex.CursorKind.VAR_DECL:
                    if ref_cursor.spelling in standard_io:
                        pass
                    else:
                        name = ref_cursor.spelling
                        usr = None
                        try:
                            usr = ref_cursor.get_usr()
                        except Exception:
                            usr = None
                        tu_path = None
                        try:
                            decl = ref_cursor.get_definition() or ref_cursor
                            if decl and decl.location and decl.location.file and os.path.samefile(decl.location.file.name, self.filename):
                                tu_path = self.filename
                        except Exception:
                            tu_path = None
                        refs.append(GlobalVarRef(name=name, usr=usr, tu_path=tu_path))
            refs.extend(self._collect_global_refs(child))
        return refs

    def _collect_structs_unions_dependencies(self, node):
        """
        Recursively collects the names of structs / unions used within the given node.
        """
        used_structs = set()
        for child in node.get_children():
            if child.kind == cindex.CursorKind.TYPE_REF or child.kind == cindex.CursorKind.STRUCT_DECL or child.kind == cindex.CursorKind.UNION_DECL:
                # Exclude structs declared in system headers
                # TODO: Maybe problematic if we ignore dependencies in system headers (e.g. network socket structs)
                if child.location and not self._is_in_system_header(child):
                    if child.spelling.startswith("struct ") or child.spelling.startswith("union "):
                        # handle the `struct NAME` and `union NAME` cases
                        used_structs.add(child.spelling.split(" ")[1])
                    else:
                        used_structs.add(child.spelling)
            used_structs.update(
                self._collect_structs_unions_dependencies(child))
        return used_structs

    def _collect_global_variable_dependencies(self, node, stdio=False, function_name=None):
        """
        Recursively collects the names of global variables used within the given node.
        """
        used_global_vars = set()
        for child in node.get_children():
            if child.kind == cindex.CursorKind.DECL_REF_EXPR and not self._is_in_system_header(child):
                referenced_cursor = child.referenced
                if referenced_cursor.kind == cindex.CursorKind.VAR_DECL:
                    if referenced_cursor.storage_class == cindex.StorageClass.STATIC or referenced_cursor.linkage == cindex.LinkageKind.EXTERNAL:
                        global_var = GlobalVarInfo(referenced_cursor)
                        used_enums = self._collect_enum_dependencies(referenced_cursor)
                        enum_values = set()
                        enum_defs = set()
                        for used_enum in used_enums:
                            if isinstance(used_enum, EnumValueInfo):
                                enum_values.add(used_enum)
                                enum_defs.add(used_enum.definition)
                            else:
                                enum_defs.add(used_enum)
                        global_var.set_enum_dependencies(
                            sorted(enum_values, key=lambda e: e.name),
                            sorted(enum_defs, key=lambda e: e.name),
                        )
                        used_global_vars.add(global_var)
                        self._global_vars[global_var.name] = global_var
            elif child.kind == cindex.CursorKind.DECL_REF_EXPR and child.spelling in standard_io and stdio:
                # for standard I/O
                assert function_name is not None
                self._functions[function_name].add_stdio(child.spelling)
            used_global_vars.update(self._collect_global_variable_dependencies(
                child,
                stdio,
                function_name
            ))
        return used_global_vars

    def _collect_enum_dependencies(self, node):
        """
        Recursively collects all the enum items used within the given node.
        """
        used_enums = set()
        for child in node.get_children():
            if child.kind == cindex.CursorKind.DECL_REF_EXPR and not self._is_in_system_header(child):
                referenced_cursor = child.referenced
                if referenced_cursor.kind == cindex.CursorKind.ENUM_CONSTANT_DECL:
                    enum_value_info = EnumValueInfo(referenced_cursor)
                    self._enums[enum_value_info.definition.name] = enum_value_info.definition
                    used_enums.add(enum_value_info)
            elif child.kind == cindex.CursorKind.TYPE_REF or child.kind == cindex.CursorKind.ENUM_DECL:
                if child.kind == cindex.CursorKind.TYPE_REF:
                    referenced_type = child.referenced
                    if referenced_type.kind == cindex.CursorKind.ENUM_DECL:
                        enum_info = EnumInfo(referenced_type)
                        self._enums[enum_info.name] = enum_info
                        used_enums.add(enum_info)
                else:  # ENUM_DECL
                    enum_info = EnumInfo(child)
                    self._enums[enum_info.name] = enum_info
                    used_enums.add(enum_info)

            used_enums.update(self._collect_enum_dependencies(child))
        return used_enums

    def retrieve_all_struct_dependencies(self, struct_union: StructInfo):
        """
        Recursively collects all dependent structs/unions of the given struct/union.
        """
        result = set()
        result.add(struct_union.name)
        for dependency in struct_union.dependencies:
            if dependency not in result:
                result.update(self.retrieve_all_struct_dependencies(
                    self._structs_unions[dependency.name]))

        return result
    def extract_function_code(self, function_name):
        """
        Extracts the code of the function with the given name from the file.

        Raises ValueError if the function is not found
        """
        function = self.get_function_info(function_name)
        function_node = function.node
        if not function_node.is_definition():
            function_node = function_node.get_definition()

        lines = read_file_lines(self.filename)
        start_line = function_node.extent.start.line - 1
        end_line = function_node.extent.end.line
        return "".join(lines[start_line:end_line])

    def extract_struct_union_definition_code(self, struct_union_name):
        """
        Extracts the code of the struct or union definition with the given name from the file.
        handle the `typedef struct` and `struct` cases

        Raises ValueError if the function is not found
        """
        struct_union = self.get_struct_info(struct_union_name)
        struct_union_node = struct_union.node
        if not struct_union_node.is_definition():
            struct_union_node = struct_union_node.get_definition()

        lines = read_file_lines(self.filename)
        start_line = struct_union_node.extent.start.line - 1
        end_line = struct_union_node.extent.end.line
        return "".join(lines[start_line:end_line])

    def extract_enum_definition_code(self, enum_name):
        """
        Extracts the code of the enum definition with the given name from the file.

        Raises ValueError if the function is not found
        """
        enum = self._enums[enum_name]
        enum_node = enum.node
        if not enum_node.is_definition():
            enum_node = enum_node.get_definition()

        lines = read_file_lines(self.filename)
        start_line = enum_node.extent.start.line - 1
        end_line = enum_node.extent.end.line
        return "".join(lines[start_line:end_line])

    def extract_global_var_definition_code(self, global_var_name):
        """
        Extracts the code of the global variable definition with the given name from the file.

        Raises ValueError if the function is not found
        """
        global_var = self.get_global_var_info(global_var_name)
        global_var_node = global_var.node

        lines = read_file_lines(self.filename)
        start_line = global_var_node.extent.start.line - 1
        end_line = global_var_node.extent.end.line
        return "".join(lines[start_line:end_line])

    def _is_in_system_header(self, node):
        """
        Determines if the location is in a system header.
        """
        node_definition = node.get_definition()
        subject = node_definition
        if subject is None:
            # Prefer referenced entity for references
            try:
                if node.kind == cindex.CursorKind.DECL_REF_EXPR and node.referenced is not None:
                    subject = node.referenced
            except Exception:
                subject = None
        if subject is None:
            # Fallback to node's own location heuristic
            location = getattr(node, "location", None)
            if location and getattr(location, "file", None):
                node_file_name = location.file.name
                for include_path in self.compiler_include_paths:
                    if node_file_name.startswith(include_path):
                        return True
                return bool(cindex.conf.lib.clang_Location_isInSystemHeader(location))
            return True
        try:
            node_file_name = subject.location.file.name
        except AttributeError:
            return False
        # search for the file in the include paths
        for include_path in self.compiler_include_paths:
            if node_file_name.startswith(include_path):
                return True

        return bool(cindex.conf.lib.clang_Location_isInSystemHeader(getattr(subject, "location", node.location)))

    def print_ast(self, node=None, indent=0):
        """
        Prints the AST of the given node.
        """
        if node is None:
            node = self.translation_unit.cursor
            for child in node.get_children():
                self.print_ast(child, indent)
        if node.location.file is None or node.location.file.name != self.filename:
            # don't print nodes from other files
            return
        logger.debug('%s%s %s %s', ' ' * indent, node.kind, node.spelling, node.location)
        for child in node.get_children():
            self.print_ast(child, indent + 2)

    def statistic(self):
        result = ""
        for struct_union in self._structs_unions.values():
            result += f"Struct/Union Name: {struct_union.name}\n"
            result += "Dependencies:\n"
            for dependency in struct_union.dependencies:
                result += f"  {dependency}\n"
            result += '-' * 40 + "\n"

        for func in self._functions.values():
            result += f"Function Name: {func.name}\n"
            result += f"Return Type: {func.return_type}\n"
            result += "Arguments:\n"
            for param_name, param_type in func.arguments:
                result += f"  {param_type} {param_name}\n"
            result += f"Location: {func.location}\n"
            result += "Function Dependencies:\n"
            for called_func in func.function_dependencies:
                result += f"  {called_func}\n"
            result += "Struct Dependencies:\n"
            for used_struct in func.struct_dependencies:
                result += f"  {used_struct.name}\n"
                result += "    Dependencies:\n"
                for dependency in used_struct.dependencies:
                    result += f"        {dependency}\n"
            result += "Global Var Dependencies:\n"
            for used_global_var in func.global_vars_dependencies:
                result += f"  {used_global_var.name}\n"
            result += "Enum Dependencies:\n"
            for used_enum in func.enum_values_dependencies:
                result += f"  {used_enum.name} = {used_enum.value}\n"
                result += f"    Definition: {
                    used_enum.definition_node.extent.start.line}\n"
            result += "-" * 40 + "\n"

        result += "Function Code:\n"
        locs = []
        for func in self._functions.values():
            result += f"Function Name: {func.name}\n"
            code = self.extract_function_code(func.name)
            if code:
                result += code + "\n"
                loc = len(code.split("\n"))
                locs.append(loc)
            result += "-" * 40 + "\n"

        if locs:  # Added check to avoid division by zero
            result += f"Avg Func LOC: {sum(locs) / len(locs)}\n"
            result += f"Max Func LOC: {max(locs)}\n"
            result += f"Min Func LOC: {min(locs)}\n"
            result += '-' * 40 + "\n"

        result += "Struct/Union Code:\n"
        for struct_union in self._structs_unions.values():
            code = self.extract_struct_union_definition_code(struct_union.name)
            if code:
                result += f"Struct/Union Name: {struct_union.name}\n"
                result += code + "\n"
            result += "-" * 40 + "\n"

        result += "Global Variables:\n"
        for global_var in self._global_vars.values():
            result += f"Global Var Name: {global_var.name}\n"
            result += f"Type: {global_var.type}\n"
            result += f"Location: {global_var.location}\n"
            result += "-" * 40 + "\n"

        return result


@lru_cache(maxsize=1)
def _discover_intrinsic_aliases() -> dict[str, str]:
    """Probe the active compiler once to discover intrinsic typedef aliases."""

    alias_intrinsic = {
        "size_t": "__SIZE_TYPE__",
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "empty.c")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")
        compiler = "clang"
        result = utils.run_command([compiler, "-E", "-P", "-v", "-dD", path], check=True)
        config = result.stdout

    intrinsic_canonical = CParser._build_compiler_intrinsic_define_map(config)
    alias_canonical: dict[str, str] = {}
    for alias, intrinsic in alias_intrinsic.items():
        alias_canonical[alias] = intrinsic_canonical[intrinsic]
    return alias_canonical
