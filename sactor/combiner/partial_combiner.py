from typing import override

from .combiner import Combiner
from .combiner_types import CombineResult
from .rust_code import RustCode


class PartialCombiner(Combiner):
    def __init__(self, functions: dict[str, str], structs: dict[str, str]):
        self.functions = functions
        self.structs = structs


    @override
    def combine(self) -> tuple[CombineResult, str | None]:
        function_code: dict[str, RustCode] = {}
        struct_code: dict[str, RustCode] = {}
        # Initialize the function_code and struct_code dictionaries
        for function_name, f_code in self.functions.items():
            function_code[function_name] = RustCode(f_code)

        for struct_name, s_code in self.structs.items():
            struct_code[struct_name] = RustCode(s_code)

        output_code = self._combine_code(function_code, struct_code)

        return CombineResult.SUCCESS, output_code
