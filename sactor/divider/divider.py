from sactor.c_parser import CParser, StructInfo, FunctionInfo


class Divider():
    def __init__(self, c_parser: CParser):
        structs = c_parser.get_structs()
        self.struct_order = self._extract_order(structs, lambda s: s.dependencies)
        functions = c_parser.get_functions()
        # Build a fast lookup table so we can recover unresolved refs by name.
        func_by_name = {f.name: f for f in functions}

        # Use intra-TU function deps; if a ref's target is missing but its name
        # exists in this translation unit, treat it as a dependency too. This
        # guards against cases where Clang returns a ref without the target
        # attached (e.g., forward-declared prototypes), which would otherwise
        # make the topological order incomplete and trigger runtime dependency
        # errors later.
        self.function_order = self._extract_order(
            functions,
            lambda f: [
                ref.target if getattr(ref, 'target', None) is not None
                else func_by_name.get(getattr(ref, 'name', None))
                for ref in getattr(f, 'function_dependencies', [])
                if getattr(ref, 'target', None) is not None
                   or getattr(ref, 'name', None) in func_by_name
            ],
        )

    def get_struct_order(self) -> list[list[StructInfo]]:
        return self.struct_order

    def get_function_order(self) -> list[list[FunctionInfo]]:
        return self.function_order

    def _extract_order(self, lst: list, dependencies_accessor) -> list[list]:
        dependencies_table = {}
        for item in lst:
            dependencies_table[item] = set(dependencies_accessor(item))

        # Keep track of processed items and their positions
        processed = set()
        result = []

        while len(processed) < len(lst):
            available = []
            circular = set()  # Items involved in a circular dependency

            # First pass: find items with no remaining dependencies
            for item in lst:
                if item in processed:
                    continue

                unprocessed_deps = dependencies_table[item] - processed
                if len(unprocessed_deps) == 0:
                    available.append(item)

            # If we found items with no dependencies, add them individually
            if len(available) > 0:
                for item in available:
                    result.append([item])
                    processed.add(item)
                continue

            # Second pass: find circular dependencies
            # Start with any unprocessed item
            start = next(item for item in lst if item not in processed)
            visited = {start}
            stack = [start]
            path = {start}

            # DFS to find the cycle
            while stack:
                current = stack[-1]
                found_unvisited = False

                for dep in dependencies_table[current]:
                    if dep not in processed:  # Skip already processed items
                        if dep in path:  # Found a cycle
                            # Add all items in the current path to circular
                            idx = len(stack) - 1
                            while idx >= 0 and stack[idx] != dep:
                                circular.add(stack[idx])
                                idx -= 1
                            circular.add(dep)
                        elif dep not in visited:
                            visited.add(dep)
                            stack.append(dep)
                            path.add(dep)
                            found_unvisited = True
                            break

                if not found_unvisited:
                    # Backtrack
                    stack.pop()
                    path.remove(current)

            # Add all items in the circular dependency as one group
            circular_list = [item for item in lst if item in circular]
            result.append(circular_list)
            processed.update(circular)

        return result
