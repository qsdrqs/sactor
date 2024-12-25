from sactor import c_parser
from sactor.c_parser import CParser


class Dividier():
    def __init__(self, filename):
        self.c_parser = CParser(filename)
        self.struct_order = self._get_struct_order()
        self.function_order = self._get_function_order()

    def _get_struct_order(self):
        pass

    def _get_function_order(self):
        pass
