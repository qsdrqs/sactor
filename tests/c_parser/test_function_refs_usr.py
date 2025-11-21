import os
from sactor.c_parser import CParser


def test_function_usr_and_dependency_usr_match(tmp_path):
    # util.c defines util(); helper.c calls util() from another TU
    util_c = tmp_path / "util.c"
    helper_c = tmp_path / "helper.c"

    util_c.write_text("int util(void){return 42;}\n", encoding="utf-8")
    helper_c.write_text(
        "int util(void);\nint helper(void){return util();}\n",
        encoding="utf-8",
    )

    util_parser = CParser(str(util_c))
    helper_parser = CParser(str(helper_c))

    util_info = util_parser.get_function_info("util")
    assert util_info.usr is not None and util_info.usr != ""

    helper_info = helper_parser.get_function_info("helper")
    # helper references util(); allow multiple occurrences (DECL_REF + CALL_EXPR)
    deps = [ref for ref in helper_info.function_dependencies if ref.name == "util"]
    assert len(deps) >= 1
    usrs = {ref.usr for ref in deps if ref.usr}
    assert util_info.usr in usrs
    # Cross-file references should not be resolved to local target at single-TU stage
    assert all(getattr(ref, "tu_path", None) in (None, "") for ref in deps)
