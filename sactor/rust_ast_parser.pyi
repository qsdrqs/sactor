# This file is automatically generated by pyo3_stub_gen
# ruff: noqa: E501, F401


def combine_struct_function(struct_code:str,function_code:str) -> str:
    ...

def count_unsafe_blocks(code:str) -> int:
    ...

def expose_function_to_c(source_code:str) -> str:
    ...

def get_func_signatures(source_code:str) -> dict[str, str]:
    ...

def get_struct_definition(source_code:str,struct_name:str) -> str:
    ...

def get_union_definition(source_code:str,union_name:str) -> str:
    ...

def get_uses_code(code:str) -> list[str]:
    ...

def rename_function(code:str,old_name:str,new_name:str) -> str:
    ...

