#!/usr/bin/env python3

import sys
import subprocess
import shutil
import translate_unidiomatic

import os
from parse_c import FunctionInfo, extract_functions, extract_structs_unions, get_code_of_function, get_code_of_struct_union_definition, init as parse_c_init, get_all_dependent_structs
from embed_test import embed_test_rust
from rust_ast_parser import get_func_signatures
from llm import AzureGPT4LLM

test_cmd = None
functions_depedency = {}
structs_depedency = {}

cwd = os.path.dirname(os.path.realpath(__file__))
TRANSLATED_CODE_PATH = os.path.join(cwd, "result/translated_code_unidiomatic")
TRANSLATED_CODE_IDIOMATIC_PATH = os.path.join(cwd, "result/translated_code_idiomatic")
BUILD_ATTEMPT_PATH = os.path.join(cwd, "build/build_attempt")
MAX_ATTEMPTS = 6

def save_code_to_file(path, function_name, code):
    os.makedirs(path, exist_ok=True)
    with open(f"{path}/{function_name}.rs", "w") as f:
        f.write(code)

def generate_test_harness(function_name, code):
    # Get function signature of unidiomatic code
    with open(f'{TRANSLATED_CODE_PATH}/{function_name}.rs', 'r') as file:
        unidiomatic_code = file.read()
        unidio_function_signatures = get_func_signatures(unidiomatic_code)
        if function_name not in unidio_function_signatures:
            exit(f"Error: Function signature not found in the unidiomatic code for function {unidio_function_signatures}")
        unidio_function_signature = unidio_function_signatures[function_name]

    idio_function_signatures = get_func_signatures(code)
    if function_name not in idio_function_signatures:
        exit(f"Error: Function signature not found in the idiomatic code for function {function_name}")
    idio_function_signature = idio_function_signatures[function_name]

    prompt = f'''
This is a idiomatic translation of Rust code from C, the signature is like
```rust
{idio_function_signature.replace("{function_name}", "{function_name}_idiomatic")}
```
This is the unidiomatic translation of Rust code from C, the signature is like
```rust
{unidio_function_signature}
```
Please write a test harness function, which looks like
```rust
{unidio_function_signature} {{
    // Your code here: Covert the input to Rust types, can use `unsafe` if needed
    // Invoke the function: {function_name}_idiomatic with the converted input
    // Convert the output back to C types, can use `unsafe` if needed
}}
```
'''

    prompt += f'''
Output the generated test harness function into this format (wrap with the following tags):
----FUNCTION----
```rust
// Test harness function here
```
----END FUNCTION----
'''

    result = query_llm(prompt)
    print(result)

    llm_result = parse_llm_result(result, "function")
    function_result = llm_result["function"]

    return function_result

def translate_structs_idiomatic(struct, attempts=0):
    pass


def translate_function_idiomatic(function: FunctionInfo, error_message=None, error_translation=None, error_tests=None, attempts=0):
    function_name = function.name
    if attempts > MAX_ATTEMPTS - 1:
        exit(f"Error: Failed to translate function {function_name} after {MAX_ATTEMPTS} attempts")
    print(f"Translating function idiomatically: {function_name} (attempts: {attempts})")

    function_dependencies = functions_depedency[function_name]
    # check the presence of the dependencies
    function_depedency_signatures = []
    for f in function_dependencies:
        if f == function_name:
            # Skip self dependencies
            continue
        if not os.path.exists(f"{TRANSLATED_CODE_IDIOMATIC_PATH}/{f}.rs"):
            exit(f"Error: Dependency {f} of function {function_name} is not translated yet")
        # get the translated function signatures
        with open(f"{TRANSLATED_CODE_IDIOMATIC_PATH}/{f}.rs", "r") as file:
            code = file.read()
            function_signatures = get_func_signatures(code)
            if f not in function_signatures:
                exit(f"Error: Function signature not found in the idiomatic code for function {f}: {function_signatures}")
            function_depedency_signatures.append(function_signatures[f])

    # extract Struct dependencies, get the translation order
    structs_in_function = function.struct_dependencies


    # Translate the Structs using LLM, combined with crown

    # Translate harness for structs

    # Test Structs translation and harness

    # Translate the function using LLM from unidiomatic to idiomatic
    # TODO:
    with open(f'{TRANSLATED_CODE_PATH}/{function_name}.rs', 'r') as file:
        unidiomatic_code = file.read()
    prompt = f'''
Here is the unidiomatic Rust code for the function `{function_name}`:
```rust
{unidiomatic_code}
```
Think about all the `unsafe` uses and unidiomatic Rust code usages one by one and try to make them idiomatic.
Finally, output the idiomatic translation of the function.
Try not to use any dependencies if possible. For libc functions, translate into Rust std functions.
'''
    structs_result = '' # TODO: get the structs translation
    function_result = '' # query_llm(prompt)

    # TODO: test harness
    test_harness_function = generate_test_harness(function_name, structs_result + function_result)
    idiomatic_function_result = function_result.replace(f"{function_name}", f"{function_name}_idiomatic")

    # Embed test
    # res = embed_test_rust(function, structs_result + idiomatic_function_result + test_harness_function, test_cmd)


def get_c2rust_translation(filename):
    # check c2rust executable
    if not shutil.which("c2rust"):
        print("c2rust executable not found")
        exit(1)
    filename_noext = os.path.splitext(filename)[0]
    if os.path.exists(filename_noext + ".rs"):
        os.remove(filename_noext + ".rs")

    # run c2rust
    cmd = ['c2rust', 'transpile', filename, '--', '-I/nix/store/wlavaybjbzgllhq11lib6qgr7rm8imgp-glibc-2.39-52-dev/include', '-I/nix/store/34b85326i0lva4s8qzwlsc8g9zs0dbmq-clang-13.0.1-lib/lib/clang/13.0.1/include']
    print(cmd)
    # add C_INCLUDE_PATH to the environment if needed
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("c2rust failed")
        os.remove(filename_noext + ".rs")
        exit(1)

    assert os.path.exists(filename_noext + ".rs") # this is the translated Rust code

    with open(filename_noext + ".rs") as f:
        c2rust_content = f.read()
    return c2rust_content



def find_cycle(function, visited, stack, remain_functions):
    # Helper function to find a cycle using DFS
    if function in visited:
        return []

    visited.add(function)
    stack.append(function)

    for called_function in function.called_functions:
        if called_function in stack:
            # Cycle detected, return the cycle
            cycle_start = stack.index(called_function)
            return stack[cycle_start:]
        for f in remain_functions:
            if f.name == called_function:
                called_function_info = f
                break
        result = find_cycle(called_function_info, visited, stack, remain_functions)
        if result:
            return result

    stack.pop()
    return []

def get_function_translation_order(remain_functions, functions_order):
    # first, find the function that has no dependencies (i.e., len(function.called_functions) == 0 or function.called_functions == [function.name])
    # then, remove the function from remain_functions and add them as a list to functions_order
    # then, remove the function from the called_functions of other functions if it exists
    # repeat until remain_functions is empty
    # if remain_functions is not empty, then there is a cycle in the function calls
    # if there is a cycle, then we add a turple of the functions that are in the cycle to functions_order

    while len(remain_functions) > 0:
        current_simul_trans = []
        for f in remain_functions:
            if len(f.called_functions) == 0 or f.called_functions == set([f.name]):
                current_simul_trans.append(f)
        if len(current_simul_trans) > 0:
            functions_order.append(current_simul_trans)
            for f in current_simul_trans:
                remain_functions.remove(f)
                for ff in remain_functions:
                    if f.name in ff.called_functions:
                        ff.called_functions.remove(f.name)
        else:
            for f in remain_functions:
                print(f.name)
                print(f.called_functions)
            exit("Error: Cycle found")
            # # If we reach here, there is a cycle. Find the minimum cycle.
            # visited = set()
            # for f in remain_functions:
            #     stack = []
            #     cycle = find_cycle(f, visited, stack, remain_functions)
            #     if cycle:
            #         # We found a cycle, add it to the order
            #         functions_order.append(tuple(cycle))
            #         # Remove the functions in the cycle from remain_functions
            #         for func_in_cycle in cycle:
            #             if func_in_cycle in remain_functions:
            #                 remain_functions.remove(func_in_cycle)
            #         break  # Only process one cycle at a time
            # if not cycle:
            #     exit("Error: Cycle not found")

def get_struct_translation_order(remain_structs, structs_order):
    while len(remain_structs) > 0:
        current_simul_trans = []
        for s in remain_structs:
            if len(s.dependencies) == 0 or s.dependencies == set([s.name]):
                current_simul_trans.append(s)
        if len(current_simul_trans) > 0:
            structs_order.append(current_simul_trans)
            for s in current_simul_trans:
                remain_structs.remove(s)
                for ss in remain_structs:
                    if s.name in ss.dependencies:
                        ss.dependencies.remove(s.name)
        else:
            for s in remain_structs:
                print(s.name)
                print(s.dependencies)
            exit("Error: Cycle found")


def main():
    global test_cmd, functions_depedency, structs_depedency
    if len(sys.argv) != 3:
        print("Usage: python script.py <c_file> <test_cmd>")
        sys.exit(1)
    filename = sys.argv[1]
    test_cmd = sys.argv[2]
    parse_c_init(filename)
    functions = extract_functions(filename)
    structs =  extract_structs_unions(filename)

    # get c2rust translation
    c2rust_translation = get_c2rust_translation(filename)

    for f in functions:
        functions_depedency[f.name] = f.called_functions.copy()

    functions_order = []
    get_function_translation_order(functions, functions_order)
    print("Translation order:")
    for fs in functions_order:
        print([f.name for f in fs])

    for s in structs:
        structs_depedency[s.name] = s.dependencies.copy()
    structs_order = []
    get_struct_translation_order(structs, structs_order)
    print("Structs translation order:")
    for ss in structs_order:
        print([s.name for s in ss])

    for ss in structs_order:
        for s in ss:
            if os.path.exists(f"{TRANSLATED_CODE_PATH}/{s.name}.rs"):
                continue
            translate_unidiomatic.translate_struct(s, c2rust_translation)

    for fs in functions_order:
        for f in fs:
            if os.path.exists(f"{TRANSLATED_CODE_PATH}/{f.name}.rs"):
                continue
            translate_function_unidiomatic(f)

    # for ss in structs_order:
    #     for s in ss:
    #         if os.path.exists(f"{TRANSLATED_CODE_IDIOMATIC_PATH}/{s.name}.rs"):
    #             continue
    #         translate_structs_idiomatic(s)
    # for fs in functions_order:
    #     for f in fs:
    #         if os.path.exists(f"{TRANSLATED_CODE_PATH}/{f.name}.rs"):
    #             continue
    #         translate_function_unidiomatic(f)


if __name__ == '__main__':
    main()
