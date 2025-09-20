SPEC: Idiomatic Translation Mapping

Scope
- Defines the machine-readable JSON spec used to map unidiomatic (repr(C)) Rust structures/arguments to idiomatic Rust types for harness generation and roundtrip verification.
- Applies to both struct specs and function specs (arguments treated as an anonymous unidiomatic struct).

Storage
- Saved under `<result>/translated_code_idiomatic/specs/{structs|functions}/{name}.json`.

Formal Schema
- JSON Schema file: `sactor/verifier/spec/schema.json` (draft 2020-12).
- Top-level is one of:
  - StructSpec: { version?, struct_name?, fields: Field[] }
  - FunctionSpec: { version?, function_name?, fields: Field[] }
- Field: maps one unidiomatic field to an idiomatic Rust field path.
  - u_field: object { name: string, type?: string, shape: "scalar" | PtrShape }
  - i_field: object { name: string, type?: string }
  - PtrShape: { ptr: { kind: slice|cstring|ref, len_from?: string, len_const?: number } }
  - Optional hints (used by verification/generation when available):
    - ownership: owning|transient
    - compare: by_value|by_slice|skip
    - llm_note: free-form note for complex cases that auto rules can't express (e.g., aliasing/offset views)

Pointer Kinds
- slice: pointer to contiguous memory with a length.
  - length must be provided via one of:
    - len_from: name of an unidiomatic length field (e.g., "len")
    - len_const: non-negative constant number of elements
- cstring: NUL-terminated C string.
- ref: single-element pointer (equivalent to slice + len_const:1).

 Constraints and Current Codegen Limits
- Dot paths are permitted in spec (u_field.name / i_field.name). Current harness generation supports `i_field` paths of the form `<field>.len` for derived length handling; other dot-paths (especially on `u_field`) still trigger the TODO skeleton fallback.
- Allowed pointer kinds are exactly: slice, cstring, ref.
- Nullability (explicit): set `u_field.shape.ptr.null` to control semantics.
  - `nullable`: pointer may be NULL; idiomatic side should use Option when needed.
  - `forbidden`: pointer must not be NULL; codegen inserts `assert!(!ptr.is_null())`.
- Length sources:
  - len_from must reference an unidiomatic field name in the same struct/argument set; expressions are not supported.

- Validation is performed against `schema.json`; additional free-form fields (like `llm_note`) are allowed and ignored by validators.

Roundtrip Selftest
- Struct harness verification clones the initial repr(C) value, runs the `{C -> Rust -> C}` converters, and fails if the process panics or yields a NULL pointer.
- Fields annotated with `compare: by_value` or `compare: by_slice` add value assertions after the roundtrip: the idiomatic struct built from the cloned C value before `{Rust -> C}` must match the idiomatic struct reconstructed from the final C pointer.
- Paths ending in `.len` are compared by value (`expected.field.len() == actual.field.len()`); other comparisons borrow in place so owned data is not moved (`&expected.field == &actual.field`).
- Fields without `compare`, or explicitly marked `compare: skip`, are ignored so selftests stay permissive unless the spec author opts in to stronger checks. Use `skip` liberally for cases that can diverge without signalling a bug (raw pointers, aliasing views, externally-owned buffers, handles, allocator state, etc.). It is safer to skip and keep a valid harness than to over-constrain and reject correct conversions.

Current Harness Codegen Coverage (2025-09)
- Struct harnesses
  - Scalar <-> scalar fields (with automatic `as` casts for common libc numeric types).
  - `*const/*mut c_char` <-> `String`/`Option<String>` with CString allocation and lossless fallback.
  - `*const/*mut T` slices (`kind: "slice"`) <-> `Vec<T>` / `&[T]` / `Option<Vec<T>>` / `Option<&[T]>` when `len_from`/`len_const` is provided. Optional slices honour NULL + zero-length semantics. `len_from` fields are reused automatically on the U side.
  - `kind: "ref"` pointers <-> boxed idiomatic types (`Box<T>`/`Option<Box<T>>`) using the generated `T_to_CT_mut` helpers when the inner struct spec exists.
  - Derived length idiomatic paths like `data.len` are recognised: the harness initialises the Vec/slice and reuses the associated length field when round-tripping without emitting TODOs.
  - Blocking cases: dotted unidiomatic field names (`u_field.name` containing `.`) or unsupported pointer kinds still trigger the `_struct_todo_skeleton` fallback so downstream LLMs can finish the converter.

- Function harnesses
  - All conversions above for argument structs (cstring, slices, refs, Options) are supported when the spec describes them.
  - `&mut Struct` parameters: require the struct name in `struct_dep_names`; harness calls the generated `C{Struct}_to_{Struct}_mut`/`{Struct}_to_C{Struct}_mut` helpers and copies back after the call.
  - `&mut T` (scalar) parameters mapped from `*mut T` with `null: "forbidden"` now produce an in-place borrow (`&mut *ptr`) guarded by `assert!(!ptr.is_null())`.
  - Return mapping via `i_field.name == "ret"`:
    - Scalars: returned directly or written back through `*mut` out-pointers.
    - C strings: crate allocation + `into_raw()` and stored into the provided `*mut *mut libc::c_char`.
    - Slices / Vec returns: boxed slices with pointer + length copies to the designated out parameters.
  - Idiomatic function names in tests follow the `*_idiomatic` suffix; spec-driven wrappers always call the idiomatic symbol verbatim from the parsed signature.
  - Unsupported combinations (e.g., nullable `*mut T` without Option on the idiomatic side, dotted unidiomatic paths, unknown pointer kinds) fall back to emitting TODOs so the verifier escalates to the LLM fixer.

Examples:

StructSpec (Student):
{
  "struct_name": "Student",
  "version": "1",
  "fields": [
    { "u_field": { "name": "name", "type": "*const c_char", "shape": { "ptr": { "kind": "cstring" } } },
      "i_field": { "name": "name", "type": "String" } },
    { "u_field": { "name": "scores", "type": "*const u32", "shape": { "ptr": { "kind": "slice", "len_from": "scores_len" } } },
      "i_field": { "name": "scores", "type": "Vec<u32>" } },
    { "u_field": { "name": "scores_len", "type": "usize", "shape": "scalar" },
      "i_field": { "name": "scores_len", "type": "usize" } },
    { "u_field": { "name": "id", "type": "u32", "shape": "scalar" },
      "i_field": { "name": "id", "type": "u32" } }
  ]
}

FunctionSpec (updateStudentInfo):
{
  "function_name": "updateStudentInfo",
  "version": "1",
  "fields": [
    { "u_field": { "name": "student", "type": "*mut CStudent", "shape": { "ptr": { "kind": "ref" } } },
      "i_field": { "name": "student", "type": "&mut Student" } },
    { "u_field": { "name": "newName", "type": "*const c_char", "shape": { "ptr": { "kind": "cstring" } } },
      "i_field": { "name": "new_name", "type": "&str" } },
    { "u_field": { "name": "scores_ptr", "type": "*const u32", "shape": { "ptr": { "kind": "slice", "len_from": "scores_len" } } },
      "i_field": { "name": "scores", "type": "&[u32]" } },
    { "u_field": { "name": "scores_len", "type": "usize", "shape": "scalar" },
      "i_field": { "name": "scores_len", "type": "usize" } }
  ]
}

Struct -> Enum Mapping (optional)
- Some C layouts use a tag + union inside a struct, while idiomatic Rust prefers an enum. Represent this with:
  - `i_kind: "enum"`, `i_type: "YourEnum"`
  - `variants: [ { name, when: { tag: "<u_field_of_tag>", equals: <value> }, payload: Field[] } ]`
- The `payload` list describes how to map active union fields for that variant into the enum's payload (if any). Non-active fields are ignored.

Example:
{
  "struct_name": "ValueHolder",
  "i_kind": "enum",
  "i_type": "Value",
  "fields": [
    { "u_field": { "name": "tag", "type": "i32", "shape": "scalar" },
      "i_field": { "name": "tag", "type": "i32" } },
    { "u_field": { "name": "u.i", "type": "i32", "shape": "scalar" },
      "i_field": { "name": "int_val", "type": "i32" } },
    { "u_field": { "name": "u.s", "type": "*const c_char", "shape": { "ptr": { "kind": "cstring", "null": "nullable" } } },
      "i_field": { "name": "str_val", "type": "Option<String>" } }
  ],
  "variants": [
    { "name": "Int", "when": { "tag": "tag", "equals": 0 },
      "payload": [ { "u_field": { "name": "u.i", "type": "i32", "shape": "scalar" }, "i_field": { "name": "0", "type": "i32" } } ] },
    { "name": "Str", "when": { "tag": "tag", "equals": 1 },
      "payload": [ { "u_field": { "name": "u.s", "type": "*const c_char", "shape": { "ptr": { "kind": "cstring", "null": "nullable" } } }, "i_field": { "name": "0", "type": "String" } } ] }
  ]
}

Note: current PoC harness codegen supports i_kind="enum" for flat (non-nested) layouts with a tag and separate payload fields. Nested union field paths (e.g., "u.i") and real Rust unions are not yet auto-generated; such cases fall back to LLM harness. Support can be extended incrementally.

Complex Aliasing/Offsets (llm_note)
- When a field must alias another pointer with an offset/length view that the current schema cannot express, describe it with `llm_note` on that Field. The spec-driven generator will keep automatic rules for simple parts and pass the notes to an LLM fallback to finish the harness.

Example (aliasing second half without copying):
Given C layout:
```c
struct Arr {
    void *arr_head;
    uint32_t len;
    void *arr_half; // arr_half = arr_head + len/2;
};
```
Spec (idiomatic Rust side uses `Vec<u8>` and `&mut [u8]`):
```json
{
  "struct_name": "Arr",
  "fields": [
    { "u_field": { "name": "arr_head", "type": "*mut u8", "shape": { "ptr": { "kind": "slice", "len_from": "len" } } },
      "i_field": { "name": "data", "type": "Vec<u8>" } },

    { "u_field": { "name": "len", "type": "u32", "shape": "scalar" },
      "i_field": { "name": "data.len", "type": "usize" } },

    { "u_field": { "name": "arr_half", "type": "*mut u8", "shape": { "ptr": { "kind": "slice", "len_from": "len" } } },
      "i_field": { "name": "second_half", "type": "&mut [u8]" },
      "llm_note": "arr_half must alias the same allocation as arr_head, starting at len/2 with length len/2; no extra allocation or copying allowed." }
  ]
}
```
- The generator will allocate `data` for `arr_head` and compute `arr_half = arr_head + len/2`, then create a mutable sub-slice for `second_half` without copying, guided by `llm_note`.

Authoring Guidance (LLM prompts)
- Emit both code and SPEC blocks:
  - ----STRUCT----/----END STRUCT---- or ----FUNCTION----/----END FUNCTION---- for code
  - ----SPEC----/----END SPEC---- for spec, fenced with ```json
- Use only pointer kinds: slice | cstring | ref.
- For slice, include len_from (preferred) or len_const.
- Keep fields minimal: u_field { name, type?, shape }, i_field { name, type? }.
- If the schema cannot express something (e.g., aliasing/offset/subview), add an `llm_note` on that Field with a concise natural-language description. The generator prioritizes automatic rules; if TODOs remain, it will pass these notes to an LLM to finish the harness.
