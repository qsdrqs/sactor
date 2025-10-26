import json
import re
import os
from typing import Optional, Tuple

# Use jsonschema for full validation based on the bundled schema
from jsonschema import Draft202012Validator  # type: ignore

from sactor import utils

SPEC_START = "----SPEC----"
SPEC_END = "----END SPEC----"
_SCHEMA_CACHE: Optional[dict] = None


def extract_spec_block(text: str) -> Optional[str]:
    """Extract the JSON spec block between ----SPEC---- and ----END SPEC----.
    Returns the raw JSON text or None if not found.
    """
    pattern = re.compile(
        r"-+SPEC-+\n```(?:json)?\n(.*?)\n```\n-+END SPEC-+", re.S)
    m = pattern.search(text)
    if not m:
        # fallback: tolerate missing code fences
        alt = re.compile(r"-+SPEC-+\n(.*?)\n-+END SPEC-+", re.S)
        m = alt.search(text)
        if not m:
            return None
    return m.group(1).strip()


def validate_basic_struct_spec(spec: dict, struct_name: str) -> Tuple[bool, str]:
    """Validate struct spec strictly via JSON Schema.

    Function name is kept for backward compatibility with callers,
    but implementation now relies solely on the schema.
    """
    ok, msg = _validate_with_jsonschema(spec, expected_kind="struct")
    if not ok:
        return False, msg
    # Enforce name match when present
    if isinstance(spec, dict) and "struct_name" in spec and spec["struct_name"] != struct_name:
        return False, f"spec.struct_name mismatch: {spec.get('struct_name')} != {struct_name}"
    return True, ""


def validate_basic_function_spec(spec: dict, function_name: str) -> Tuple[bool, str]:
    """Validate function spec strictly via JSON Schema.

    Function name is kept for backward compatibility with callers,
    but implementation now relies solely on the schema.
    """
    ok, msg = _validate_with_jsonschema(spec, expected_kind="function")
    if not ok:
        return False, msg
    if isinstance(spec, dict) and "function_name" in spec and spec["function_name"] != function_name:
        return False, f"spec.function_name mismatch: {spec.get('function_name')} != {function_name}"
    return True, ""


def _load_schema() -> Optional[dict]:  # pragma: no cover - thin IO
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE
    try:
        schema_text = utils.load_spec_schema_text()
        _SCHEMA_CACHE = json.loads(schema_text)
        return _SCHEMA_CACHE
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _validate_with_jsonschema(spec: dict, expected_kind: str) -> Tuple[bool, str]:
    """Validate against the JSON Schema when possible.

    expected_kind: "struct" or "function" - used to target the sub-schema
    $defs.StructSpec or $defs.FunctionSpec so we don't pass on the oneOf.

    Returns (ok, msg). If jsonschema or schema is missing, return (False, "schema:unavailable").
    If validation fails via schema, return (False, "schema:<error message>").
    """
    schema = _load_schema()
    if not schema:
        return False, "schema:unavailable"

    # Select the precise sub-schema to enforce the expected top-level kind
    defs = schema.get("$defs", {})
    if expected_kind == "struct":
        ref = "#/$defs/StructSpec"
    elif expected_kind == "function":
        ref = "#/$defs/FunctionSpec"
    else:
        return False, "schema:unavailable"

    target_schema = {
        "$schema": schema.get("$schema", "https://json-schema.org/draft/2020-12/schema"),
        "$id": schema.get("$id", "sactor://spec.schema.json"),
        "$ref": ref,
        "$defs": defs,
    }

    try:
        Draft202012Validator(target_schema).validate(spec)
        return True, ""
    except Exception as e:
        return False, f"schema:{e}"


def save_spec(base_result_path: str, kind: str, name: str, raw_json: str) -> None:
    """Save spec under the translator/verifier result tree.

    base_result_path should typically be the idiomatic translation base
    (e.g., `<result_path>/translated_code_idiomatic`).
    """
    sub = "structs" if kind == "struct" else "functions"
    dir_path = os.path.join(base_result_path, "specs", sub)
    os.makedirs(dir_path, exist_ok=True)
    with open(os.path.join(dir_path, f"{name}.json"), "w") as f:
        f.write(raw_json)
