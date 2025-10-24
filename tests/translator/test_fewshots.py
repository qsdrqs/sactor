import json

import pytest

from sactor.translator.idiomatic_fewshots import (
    FUNCTION_FEWSHOTS,
    STRUCT_FEWSHOTS,
)
from sactor.verifier.spec.spec_types import (validate_basic_function_spec,
                                             validate_basic_struct_spec)


@pytest.mark.parametrize("example", STRUCT_FEWSHOTS)
def test_struct_fewshots_conform_to_schema(example):
    spec_obj = json.loads(example.spec)
    struct_name = spec_obj.get("struct_name", "")
    ok, msg = validate_basic_struct_spec(spec_obj, struct_name)
    assert ok, f"{example.label}: {msg}"


@pytest.mark.parametrize("example", FUNCTION_FEWSHOTS)
def test_function_fewshots_conform_to_schema(example):
    spec_obj = json.loads(example.spec)
    func_name = spec_obj.get("function_name", "")
    ok, msg = validate_basic_function_spec(spec_obj, func_name)
    assert ok, f"{example.label}: {msg}"
