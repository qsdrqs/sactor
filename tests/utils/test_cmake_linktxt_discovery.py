import os
from sactor.verifier.unidiomatic_verifier import UnidiomaticVerifier
from sactor import utils


def test_cmake_linktxt_autodiscover_libs_for_entry():
    base = os.path.join(os.getcwd(), 'tests', 'c_examples', 'cmake_multi')
    cc_path = os.path.join(base, 'build', 'compile_commands.json')
    entry_tu = os.path.join(base, 'src', 'main.c')
    test_cmd = os.path.join(base, 'test_cmd.json')

    config = utils.try_load_config(None)

    v = UnidiomaticVerifier(
        test_cmd_path=test_cmd,
        config=config,
        processed_compile_commands=[],
        link_args=[],
        compile_commands_file=cc_path,
        entry_tu_file=entry_tu,
        link_closure=[],
    )

    libs = v._discover_cmake_libs()
    assert isinstance(libs, list)
    # The sample CMake project links libm only
    assert '-lm' in libs
    # Order should preserve CMake link.txt order; here it's a single item
    assert libs[-1] == '-lm'
