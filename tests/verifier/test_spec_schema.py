import json
from pathlib import Path

from jsonschema.validators import Draft202012Validator


SCHEMA_PATH = (
    Path(__file__)
    .resolve()
    .parent
    .parent
    .parent
    / "sactor"
    / "verifier"
    / "spec"
    / "schema.json"
)


def test_spec_schema_matches_json_schema_202012():
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)

    Draft202012Validator.check_schema(schema)
