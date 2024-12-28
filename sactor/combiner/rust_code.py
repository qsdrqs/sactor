from sactor import rust_ast_parser

class RustCode():
    def __init__(self, code: str):
        self.code = code

        self.used_code_list = rust_ast_parser.get_standalone_uses_code_paths(code)
        self.remained_code = rust_ast_parser.get_code_other_than_uses(code)
