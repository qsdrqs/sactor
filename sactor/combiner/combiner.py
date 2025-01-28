from abc import ABC, abstractmethod
from typing import Optional

from .combiner_types import CombineResult
from .rust_code import RustCode


class Combiner(ABC):
    def _merge_uses(self, all_uses: list[list[str]]) -> list[str]:
        libc_identifiers = {
            "::".join(use[1:])
            for use in all_uses
            if use[0] == 'libc'
        }

        # Collect all std::ffi identifiers
        ffi_identifiers = {
            "::".join(use[2:])
            for use in all_uses
            if use[0] == 'std' and use[1] == 'ffi'
        }

        converted_uses = []
        for use in all_uses:
            if use[0] == 'std' and use[1] == 'ffi':
                # If this identifier exists in libc, convert to libc path
                identifier = "::".join(use[2:])
                if identifier in libc_identifiers:
                    converted_uses.append(['libc'] + use[2:])
                else:
                    converted_uses.append(use)
            elif use[0] == 'std' and use[1] == 'os' and use[2] == 'raw':
                # Skip if this identifier exists in std::ffi
                identifier = "::".join(use[3:])
                if identifier in ffi_identifiers:
                    continue
                # If this identifier exists in libc, convert to libc path
                if identifier in libc_identifiers:
                    converted_uses.append(['libc'] + use[3:])
                else:
                    converted_uses.append(use)
            elif use[0] == 'libc':
                converted_uses.append(use)
            else:
                converted_uses.append(use)

        # Remove duplicates by converting to set of tuples (since lists aren't hashable)
        unique_uses = {tuple(use) for use in converted_uses}

        return [
            f'use {"::".join(use)};'
            for use in unique_uses
        ]

    def _combine_code(self, function_code: dict[str, RustCode], data_type_code: dict[str, RustCode]) -> str:
        # collect all uses in the functions and structs
        all_uses: list[list[str]] = []
        for function in function_code.keys():
            all_uses += function_code[function].used_code_list

        for struct in data_type_code.keys():
            all_uses += data_type_code[struct].used_code_list

        # deduplicate
        all_uses_tuples = set(tuple(x) for x in all_uses)
        all_uses = [list(x) for x in all_uses_tuples]

        # uses + structs + functions
        output_code = []
        uses_code = self._merge_uses(all_uses)
        output_code += uses_code

        for struct in data_type_code.keys():
            output_code.append(data_type_code[struct].remained_code)

        for function in function_code.keys():
            output_code.append(function_code[function].remained_code)

        output_code = '\n'.join(output_code)
        return output_code

    @abstractmethod
    def combine(self, *args, **kwargs) -> tuple[CombineResult, Optional[str]]:
        pass
