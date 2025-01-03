from abc import ABC, abstractmethod

from .rust_code import RustCode
from .combiner_types import CombineResult


class Combiner(ABC):
    def _merge_uses(self, all_uses: list[list[str]]) -> list[str]:
        return [
            f'use {"::".join(use)};'
            for use in all_uses
        ]

    def _combine_code(self, function_code: dict[str, RustCode], struct_code: dict[str, RustCode]) -> str:
        # collect all uses in the functions and structs
        all_uses: list[list[str]] = []
        for function in function_code.keys():
            all_uses += function_code[function].used_code_list

        for struct in struct_code.keys():
            all_uses += struct_code[struct].used_code_list

        # deduplicate
        all_uses_tuples = set(tuple(x) for x in all_uses)
        all_uses = [list(x) for x in all_uses_tuples]

        # uses + structs + functions
        output_code = []
        uses_code = self._merge_uses(all_uses)
        output_code += uses_code

        for struct in struct_code.keys():
            output_code.append(struct_code[struct].remained_code)

        for function in function_code.keys():
            output_code.append(function_code[function].remained_code)

        output_code = '\n'.join(output_code)
        return output_code

    @abstractmethod
    def combine(self, *args, **kwargs) -> tuple[CombineResult, str | None]:
        pass
