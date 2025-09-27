import os
import subprocess
import tempfile
import textwrap
import json
from typing import List, Optional, Tuple

from sactor import logging as sactor_logging, utils


logger = sactor_logging.get_logger(__name__)


class StructRoundTripTester:
    """Create a temp Rust crate containing the combined code and a minimal
    U->I->U (Unidiomatic->Idiomatic->Unidiomatic) roundtrip test for the target
    struct, then run `cargo test`.

    Assumptions:
    - `combined_code` contains: idiomatic `{Struct}`, unidiomatic `C{Struct}`,
      and both converters:
        unsafe fn {Struct}_to_C{Struct}_mut(&mut {Struct}) -> *mut C{Struct}
        unsafe fn C{Struct}_to_{Struct}_mut(*mut C{Struct}) -> &'static mut {Struct}
    - We exercise the roundtrip starting from a zeroed unidiomatic (C{{Struct}})
      value. This avoids constructing idiomatic values that could be UB to
      zero-initialize.
    """

    def __init__(self, cargo_bin: str = "cargo", llm=None, spec_root: Optional[str] = None):
        self.cargo_bin = cargo_bin
        self.llm = llm
        self.spec_root = spec_root

    def run_minimal(
        self,
        combined_code: str,
        struct_name: str,
        *,
        allow_fallback: bool = True,
    ) -> tuple[bool, str]:
        """Return (ok, combined_output_snippet).

        When `allow_fallback` is False, the first attempted harness result (LLM or
        samples, whichever runs) is returned immediately without trying the
        zeroed smoke fallback. Primarily used by tests that want to observe the
        initial failure.
        """
        if os.environ.get("SACTOR_DISABLE_SELFTEST") == "1":
            return True, "selftest disabled by SACTOR_DISABLE_SELFTEST"
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "src"), exist_ok=True)

            cargo_toml = textwrap.dedent(
                """
                [package]
                name = "sactor_selftest_rt"
                version = "0.1.0"
                edition = "2021"

                [lib]
                crate-type = ["lib"]

                [dependencies]
                libc = "0.2"
                """
            )
            with open(os.path.join(td, "Cargo.toml"), "w") as f:
                f.write(cargo_toml)

            attempts: List[Tuple[str, bool, str]] = []

            llm_block, _ = self._generate_llm_fill_block(combined_code, struct_name)
            sample_blocks = self._render_sample_blocks(struct_name)
            compare_fields = self._collect_compare_fields(struct_name)

            def attempt(fill_blocks: List[str]) -> Tuple[bool, str]:
                lib_rs = self._materialize_lib_rs(
                    combined_code, struct_name, fill_blocks, compare_fields
                )
                with open(os.path.join(td, "src", "lib.rs"), "w") as f:
                    f.write(lib_rs)
                return self._run_cargo(td)

            if llm_block is not None:
                ok, snippet = attempt([llm_block])
                attempts.append(("llm", ok, snippet))
                if ok or not allow_fallback:
                    return ok, snippet

            if sample_blocks:
                ok, snippet = attempt(sample_blocks)
                attempts.append(("samples", ok, snippet))
                if ok or not allow_fallback:
                    return ok, snippet

            ok, snippet = attempt([])
            attempts.append(("zeroed", ok, snippet))
            if not allow_fallback:
                return ok, snippet

            if ok:
                return True, snippet

            combined = "\n\n".join(
                f"[{label}:{'PASS' if success else 'FAIL'}]\n{snip}".strip()
                for label, success, snip in attempts
            )
            combined = combined[-4000:]
            return False, combined

    def _materialize_lib_rs(
        self,
        code: str,
        struct_name: str,
        fill_blocks: List[str],
        compare_fields: List[dict],
    ) -> str:
        s = struct_name
        tests_body = self._gen_tests(struct_name, fill_blocks, compare_fields)
        tests = f"""
#![allow(dead_code, unused_imports)]
// === BEGIN: combined code from verifier ===
{code}
// === END ===

#[cfg(test)]
mod tests {{
    use super::*;

    {tests_body}
}}
"""
        return tests

    def _run_cargo(self, workdir: str) -> Tuple[bool, str]:
        try:
            p = subprocess.run(
                [self.cargo_bin, "test", "--quiet"],
                cwd=workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as e:
            return False, f"cargo test timeout: {e}"

        ok = p.returncode == 0
        out = (p.stdout or "") + ("\n" if p.stdout else "") + (p.stderr or "")
        snippet = out[-4000:]
        return ok, snippet

    def _generate_llm_fill_block(self, combined_code: str, struct_name: str) -> Tuple[Optional[str], bool]:
        if self.llm is None:
            return None, False

        formatted_code = utils.format_rust_snippet(combined_code)

        prompt = textwrap.dedent(f"""
You are assisting with automated Rust roundtrip tests.

The following code defines the idiomatic struct, the repr(C) struct, and the converters:
```rust
{formatted_code}
```

We will place your statements inside an existing unsafe block that already contains:
```rust
let mut c0: C{struct_name} = core::mem::zeroed();
// <INSERT YOUR STATEMENTS HERE>
let p0 = &mut c0 as *mut C{struct_name};
```

Goal: populate `c0` with representative non-default data so the conversions exercise real values.
Provide only the Rust statements to insert in the marked location.
Use fully-qualified calls (e.g., `std::ffi::CString::new`). Remember to call `core::mem::forget` for Vecs
whose pointers are stored in `c0`. Avoid declaring functions or modules.

Return the statements between these tags, without backticks:
----FILL----
(statements)
----END FILL----
""").strip()

        try:
            raw = self.llm.query(prompt)
        except Exception as e:
            logger.error("LLM struct sample generation failed: %s", e)
            return None, True

        try:
            parsed = utils.parse_llm_result(raw, "fill")["fill"]
            block = textwrap.dedent(parsed).strip("\n")
            if block.strip():
                return block, True
        except Exception as e:
            logger.error("Failed to parse LLM fill result: %s", e)
        return None, True

    def _render_sample_blocks(self, struct_name: str) -> List[str]:
        samples = self._load_samples(struct_name)
        blocks: List[str] = []
        for sample in samples:
            block = self._render_fill_block_from_sample(struct_name, sample)
            if block.strip():
                blocks.append(block)
        return blocks

    def _collect_compare_fields(self, struct_name: str) -> List[dict]:
        spec = self._load_struct_spec(struct_name)
        compare_entries: List[dict] = []
        if not isinstance(spec, dict):
            return compare_entries
        for field in spec.get("fields", []):
            compare_mode = field.get("compare")
            if compare_mode not in {"by_value", "by_slice"}:
                continue
            i_field = field.get("i_field") or {}
            path = i_field.get("name")
            if not path or path == "ret":
                continue
            compare_entries.append(
                {
                    "path": path,
                    "mode": compare_mode,
                }
            )
        return compare_entries

    def _load_samples(self, struct_name: str) -> list[dict] | None:
        # Prefer explicit path
        path = os.environ.get("SACTOR_SAMPLES")
        if not path:
            # default location under result path used by verifier
            default_path = os.path.join(
                os.getcwd(),
                "translated_code_idiomatic",
                "specs",
                "samples.jsonl",
            )
            path = default_path if os.path.exists(default_path) else None
        if not path or not os.path.exists(path):
            return []
        samples: list[dict] = []
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if obj.get("struct_name") == struct_name:
                        samples.append(obj)
                        if len(samples) >= 3:
                            break
        except Exception:
            return []
        return samples

    def _load_struct_spec(self, struct_name: str) -> Optional[dict]:
        # Prefer explicit override via environment
        path = os.environ.get("SACTOR_STRUCT_SPEC")
        if path and os.path.exists(path):
            return self._read_struct_spec(path, struct_name)

        candidate_dirs: List[str] = []
        if self.spec_root:
            candidate_dirs.append(self.spec_root)

        default_root = os.path.join(
            os.getcwd(),
            "translated_code_idiomatic",
            "specs",
            "structs",
        )
        if os.path.exists(default_root):
            candidate_dirs.append(default_root)

        for directory in candidate_dirs:
            spec_path = os.path.join(directory, f"{struct_name}.json")
            if os.path.exists(spec_path):
                return self._read_struct_spec(spec_path, struct_name)
        return None

    def _read_struct_spec(self, path: str, struct_name: str) -> Optional[dict]:
        try:
            with open(path, "r") as f:
                obj = json.load(f)
            if obj.get("struct_name") and obj.get("struct_name") != struct_name:
                return obj if obj.get("fields") else None
            return obj
        except Exception:
            return None

    def _gen_tests(
        self,
        struct_name: str,
        fill_blocks: List[str],
        compare_fields: List[dict],
    ) -> str:
        s = struct_name
        if not fill_blocks:
            body = textwrap.dedent(
                f"""
                #[test]
                fn rt_c_rust_c_min() {{
                    unsafe {{
                        let mut c0: C{s} = core::mem::zeroed();
                        let p0 = &mut c0 as *mut C{s};
                        let r: &'static mut {s} = C{s}_to_{s}_mut(p0);
                        let p1: *mut C{s} = {s}_to_C{s}_mut(r);
                        assert!(!p1.is_null());
                        assert_ne!(p1 as usize, p0 as usize);
                    }}
                }}
                """
            ).strip("\n")
            return self._indent_block(body, 4)

        tests: List[str] = []
        for idx, block in enumerate(fill_blocks):
            fill_section = self._indent_block(block.strip("\n"), 8) if block.strip() else ""
            snapshot_section = (
                self._indent_block(self._render_expected_snapshot_block(struct_name), 8)
                if compare_fields
                else ""
            )
            compare_section = (
                self._indent_block(self._render_compare_block(struct_name, compare_fields), 8)
                if compare_fields
                else ""
            )

            test_body = textwrap.dedent(
                f"""
                #[test]
                fn rt_generated_{idx}() {{
                    unsafe {{
                        let mut c0: C{s} = core::mem::zeroed();
{fill_section}
{snapshot_section}
                        let p0 = &mut c0 as *mut C{s};
                        let r: &'static mut {s} = C{s}_to_{s}_mut(p0);
                        let p1: *mut C{s} = {s}_to_C{s}_mut(r);
                        assert!(!p1.is_null());
                        assert_ne!(p1 as usize, p0 as usize);
{compare_section}
                    }}
                }}
                """
            ).strip("\n")
            tests.append(test_body)

        combined = "\n\n".join(tests)
        return self._indent_block(combined, 4)

    def _render_fill_block_from_sample(self, struct_name: str, sample: dict) -> str:
        chunks: List[str] = []
        fields = sample.get("fields", [])
        for field in fields:
            cf = field.get("u_field")
            if not cf:
                continue
            kind = field.get("kind")
            if kind is None and "bytes" in field:
                raw_hex = field.get("bytes", "")
                if not raw_hex:
                    continue
                arr = ", ".join(
                    [f"0x{raw_hex[i:i+2]}" for i in range(0, len(raw_hex), 2)]
                )
                count = len(raw_hex) // 2
                chunks.append(
                    textwrap.dedent(
                        f"""
                        let _{cf}_bytes: [u8; {count}] = [ {arr} ];
                        std::ptr::copy_nonoverlapping(
                            _{cf}_bytes.as_ptr(),
                            (&mut c0.{cf} as *mut _ as *mut u8),
                            _{cf}_bytes.len(),
                        );
                        """
                    ).strip("\n")
                )
            elif kind == "cstring":
                hexs = field.get("cstring")
                if hexs in (None, "null"):
                    chunks.append(f"c0.{cf} = core::ptr::null_mut();")
                else:
                    arr = ", ".join(
                        [f"0x{hexs[i:i+2]}" for i in range(0, len(hexs), 2)]
                    )
                    count = len(hexs) // 2
                    chunks.append(
                        textwrap.dedent(
                            f"""
                            let _{cf}_bytes: [u8; {count}] = [ {arr} ];
                            let _{cf}_cs = std::ffi::CString::from_vec_with_nul(_{cf}_bytes.to_vec()).expect(\"valid c string\");
                            c0.{cf} = _{cf}_cs.into_raw();
                            """
                        ).strip("\n")
                    )
            elif kind in ("slice", "ref"):
                raw_hex = field.get("bytes", "")
                if not raw_hex:
                    continue
                arr = ", ".join(
                    [f"0x{raw_hex[i:i+2]}" for i in range(0, len(raw_hex), 2)]
                )
                count = len(raw_hex) // 2
                body = textwrap.dedent(
                    f"""
                    let mut _{cf}_bytes: [u8; {count}] = [ {arr} ];
                    let mut _{cf}_vec = _{cf}_bytes.to_vec();
                    let _{cf}_ptr = _{cf}_vec.as_mut_ptr();
                    c0.{cf} = _{cf}_ptr as _;
                    core::mem::forget(_{cf}_vec);
                    """
                ).strip("\n")
                if kind == "slice":
                    lf = field.get("len_from")
                    cnt = field.get("count", 0)
                    if lf:
                        body += f"\nc0.{lf} = ({cnt}) as _;"
                chunks.append(body)
            else:
                note = field.get("llm_note")
                if note:
                    chunks.append(f"// TODO: {note}")
        return "\n".join(filter(None, chunks))

    def _indent_block(self, code: str, spaces: int) -> str:
        pad = " " * spaces
        lines = code.splitlines()
        return "\n".join(f"{pad}{line}" if line else "" for line in lines)

    def _render_expected_snapshot_block(self, struct_name: str) -> str:
        return textwrap.dedent(
            f"""
            let mut expected_c = core::mem::MaybeUninit::<C{struct_name}>::uninit();
            core::ptr::copy_nonoverlapping(
                &c0 as *const C{struct_name},
                expected_c.as_mut_ptr(),
                1,
            );
            let mut expected_c = expected_c.assume_init();
            let expected_ptr: *mut C{struct_name} = &mut expected_c as *mut C{struct_name};
            let expected_r: &'static mut {struct_name} = C{struct_name}_to_{struct_name}_mut(expected_ptr);
            """
        ).strip("\n")

    def _render_compare_block(
        self,
        struct_name: str,
        compare_fields: List[dict],
    ) -> str:
        if not compare_fields:
            return ""
        lines: List[str] = []
        lines.append(
            f"let actual_r: &'static mut {struct_name} = C{struct_name}_to_{struct_name}_mut(p1);"
        )
        for entry in compare_fields:
            path = entry.get("path", "")
            if not path:
                continue
            is_len = path.endswith(".len")
            expected_expr = self._render_idiomatic_expr("expected_r", path)
            actual_expr = self._render_idiomatic_expr("actual_r", path)
            if is_len:
                lines.append(
                    f"assert_eq!({expected_expr}, {actual_expr}, \"field {path} mismatch\");"
                )
            else:
                lines.append(
                    f"assert_eq!(&({expected_expr}), &({actual_expr}), \"field {path} mismatch\");"
                )
        return "\n".join(lines)

    def _render_idiomatic_expr(self, base: str, path: str) -> str:
        tokens = [seg.strip() for seg in path.split(".") if seg.strip()]
        expr = base
        for idx, token in enumerate(tokens):
            if token == "len" and idx == len(tokens) - 1:
                expr = f"({expr}).len()"
            else:
                expr = f"{expr}.{token}"
        return expr
