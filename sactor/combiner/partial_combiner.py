from typing import override, Optional

from .combiner import Combiner
from .combiner_types import CombineResult
from .rust_code import RustCode


class PartialCombiner(Combiner):
    def __init__(self, functions: dict[str, str], data_types: dict[str, str]):
        self.functions = functions
        self.data_types = data_types


    @override
    def combine(self) -> tuple[CombineResult, Optional[str]]:
        function_code: dict[str, RustCode] = {}
        data_type_code: dict[str, RustCode] = {}
        # Initialize the function_code and struct_code dictionaries
        for function_name, f_code in self.functions.items():
            function_code[function_name] = RustCode(f_code)

        for dt_name, s_code in self.data_types.items():
            data_type_code[dt_name] = RustCode(s_code)

        output_code = self._combine_code(function_code, data_type_code)

        return CombineResult.SUCCESS, output_code
