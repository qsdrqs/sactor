import os
import json
import shlex
import shutil
from dataclasses import dataclass
from typing import Optional

from sactor import logging as sactor_logging
from sactor import utils, rust_ast_parser
from sactor.c_parser import CParser

logger = sactor_logging.get_logger(__name__)


@dataclass
class TuArtifact:
    tu_path: str
    result_dir: str  # per-TU result directory (root), contains translated_code_{variant}/


class ProjectCombiner:
    """
    Combine all TU-level Rust artefacts (unidiomatic/idiomatic) into a single Cargo project.

    Rules:
    - Preserve relative path hierarchy of C sources beneath the project root;
      map ".c" -> ".rs" and drop the leading "src/" segment if present.
    - Each non-entry TU becomes a standalone module file included via #[path = "..."] mod <name>;
      the entry TU becomes src/main.rs (bin). If no entry is found, create a library (src/lib.rs).
    - To satisfy unqualified calls across TUs, mark top-level functions as public and
      insert "use crate::<module>::<func>;" imports for cross-TU dependencies within
      each TU module and in main.
    - Run cargo fmt, cargo clippy --fix, cargo build; if bin exists, run project tests
      from test_cmd.json by substituting %t with the built binary path.
    """

    def __init__(
        self,
        *,
        config: dict,
        test_cmd_path: str,
        output_root: str,
        compile_commands_file: str,
        entry_tu_file: Optional[str],
        tu_artifacts: list[TuArtifact],
        variant: str = "unidiomatic",
    ) -> None:
        self.config = config
        self.test_cmd_path = test_cmd_path
        self.output_root = output_root
        self.compile_commands_file = os.path.realpath(compile_commands_file)
        self.entry_tu_file = os.path.realpath(entry_tu_file) if entry_tu_file else None
        self.tu_artifacts = tu_artifacts
        if variant not in {"unidiomatic", "idiomatic"}:
            raise ValueError(f"Unknown ProjectCombiner variant: {variant}")
        self.variant = variant

    # --------------- helpers ---------------
    def _project_root_dir(self) -> str:
        tus = self._list_translation_units()
        if tus:
            tu_dirs = [os.path.dirname(os.path.realpath(tu)) for tu in tus]
            common = os.path.commonpath(tu_dirs)
            if os.path.basename(common) == "src":
                return os.path.dirname(common)
            return common

        # Fallback: compile_commands.json is typically in <proj>/build/compile_commands.json.
        cc_dir = os.path.dirname(self.compile_commands_file)
        return os.path.realpath(os.path.join(cc_dir, os.pardir))

    def _crate_name(self) -> str:
        # Keep crate/bin name equal to project directory name
        return os.path.basename(self._project_root_dir())

    def _list_translation_units(self) -> list[str]:
        return utils.list_c_files_from_compile_commands(self.compile_commands_file)

    def _compile_flags_for(self, tu_path: str) -> list[str]:
        cmds = utils.load_compile_commands_from_file(self.compile_commands_file, tu_path)
        return utils.get_compile_flags_from_commands(cmds)

    def _find_entry_tu(self) -> Optional[str]:
        if self.entry_tu_file:
            return self.entry_tu_file
        candidates: list[str] = []
        for tu in self._list_translation_units():
            flags = self._compile_flags_for(tu)
            parser = CParser(tu, extra_args=flags, omit_error=True)
            for f in parser.get_functions() or []:
                if getattr(f, "name", "") == "main":
                    candidates.append(os.path.realpath(tu))
                    break
        if not candidates:
            return None
        if len(candidates) > 1:
            raise ValueError(
                "Multiple main functions detected. Please specify --entry-tu-file. Candidates: "
                + ", ".join(candidates)
            )
        return candidates[0]

    def _compute_source_root(self) -> str:
        # Use the project root as source root baseline
        return self._project_root_dir()

    def _rel_c_to_rs_path(self, tu_path: str, source_root: str) -> tuple[str, str]:
        rel = os.path.relpath(tu_path, source_root)
        parts = rel.split(os.sep)
        # Drop leading "src" segment if present; the crate already has src/
        if parts and parts[0] == "src":
            parts = parts[1:]
        stem = os.path.splitext(parts[-1])[0]
        parts[-1] = f"{stem}.rs"
        rs_rel_path = os.path.join(*parts) if parts else f"{stem}.rs"
        module_name = stem
        return rs_rel_path, module_name

    def _tu_result_dir_map(self) -> dict[str, str]:
        return {os.path.realpath(tu.tu_path): os.path.realpath(tu.result_dir) for tu in self.tu_artifacts}

    def _ensure_pub_functions(self, code: str) -> str:
        try:
            sigs = rust_ast_parser.get_func_signatures(code)
        except Exception:
            return code
        patched = code
        for name, sig in sigs.items():
            if name == "main":
                # main must not be pub
                continue
            # Already public
            if sig.lstrip().startswith("pub "):
                continue
            # Insert pub before fn/unsafe fn/extern
            new_sig = sig
            if sig.lstrip().startswith("fn "):
                new_sig = sig.replace("fn ", "pub fn ", 1)
            elif sig.lstrip().startswith("unsafe fn "):
                new_sig = sig.replace("unsafe fn ", "pub unsafe fn ", 1)
            elif sig.lstrip().startswith("extern "):
                # keep ABI, add pub before extern
                new_sig = sig.replace("extern", "pub extern", 1)
            if new_sig != sig and sig in patched:
                patched = patched.replace(sig, new_sig)
        return patched

    def _collect_rs_code_for_tu(self, unit_result_dir: str) -> str:
        base = os.path.join(unit_result_dir, f"translated_code_{self.variant}")
        chunks: list[str] = []
        for sub in ("structs", "enums", "global_vars", "functions"):
            subdir = os.path.join(base, sub)
            if not os.path.isdir(subdir):
                continue
            for entry in sorted(os.listdir(subdir)):
                if not entry.endswith(".rs"):
                    continue
                with open(os.path.join(subdir, entry), "r", encoding="utf-8") as fh:
                    chunks.append(fh.read())
        code = "\n\n".join(chunks)
        code = self._ensure_pub_functions(code)
        try:
            code = rust_ast_parser.dedup_items(code)
        except Exception:
            pass
        return code

    def _build_cross_tu_deps(self) -> tuple[dict[str, set[str]], dict[str, str]]:
        """
        Returns:
        - cross_deps: tu_path -> set of function names it calls that belong to other TUs
        - func_owner: function name (approx) -> owner tu path (best-effort; uses USR mapping)
        """
        tus = self._list_translation_units()
        # Map USR -> owner TU
        usr_to_owner: dict[str, str] = {}
        name_by_usr: dict[str, str] = {}
        for tu in tus:
            flags = self._compile_flags_for(tu)
            parser = CParser(tu, extra_args=flags, omit_error=True)
            for f in parser.get_functions() or []:
                usr = getattr(f, "usr", "") or ""
                if usr and usr not in usr_to_owner:
                    usr_to_owner[usr] = os.path.realpath(tu)
                    name_by_usr[usr] = getattr(f, "name", usr)

        cross_deps: dict[str, set[str]] = {os.path.realpath(tu): set() for tu in tus}
        func_owner_by_name: dict[str, str] = {}
        for tu in tus:
            flags = self._compile_flags_for(tu)
            parser = CParser(tu, extra_args=flags, omit_error=True)
            for f in parser.get_functions() or []:
                for ref in getattr(f, "function_dependencies", []) or []:
                    usr = getattr(ref, "usr", None)
                    if not usr:
                        continue
                    owner = usr_to_owner.get(usr)
                    if not owner:
                        continue
                    if os.path.realpath(owner) != os.path.realpath(tu):
                        ref_name = getattr(ref, "name", name_by_usr.get(usr, usr))
                        cross_deps[os.path.realpath(tu)].add(ref_name)
                        # record owner by name best-effort
                        func_owner_by_name.setdefault(ref_name, owner)
        return cross_deps, func_owner_by_name

    def _write_manifest(self, crate_dir: str, with_bin: bool, crate_name: str) -> None:
        manifest = [
            "[package]",
            f"name = \"{crate_name}\"",
            "version = \"0.1.0\"",
            "edition = \"2021\"",
            "",
            "[dependencies]",
            "libc = \"0.2.159\"",
        ]
        if not with_bin:
            manifest += [
                "",
                "[lib]",
                f"name = \"{crate_name}\"",
                "crate-type = [\"rlib\"]",
            ]
        else:
            manifest += [
                "",
                "[[bin]]",
                f"name = \"{crate_name}\"",
                "path = \"src/main.rs\"",
            ]
        manifest += [
            "",
            "[workspace]",
        ]
        with open(os.path.join(crate_dir, "Cargo.toml"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(manifest) + "\n")

    def _load_test_cmd(self) -> list[list[str]]:
        raw = utils.read_file(self.test_cmd_path).strip()
        arr = json.loads(raw)
        out: list[list[str]] = []
        for item in arr:
            cmd = item.get("command")
            if isinstance(cmd, str):
                out.append(cmd.split())
            elif isinstance(cmd, list):
                out.append([str(x) for x in cmd])
        return out

    def _run_project_tests(self, bin_path: str) -> tuple[bool, Optional[str]]:
        test_cmds = self._load_test_cmd()
        env = os.environ.copy()
        cwd = os.path.dirname(os.path.abspath(self.test_cmd_path))
        for cmd in test_cmds:
            expanded = [(bin_path if tok == "%t" else tok) for tok in cmd]
            logger.debug("Project test: %s", expanded)
            res = utils.run_command(expanded, cwd=cwd)
            if res.returncode != 0:
                return False, (res.stderr or res.stdout)
        return True, None

    # --------------- main entry ---------------
    def combine_and_build(self) -> tuple[bool, str, Optional[str]]:
        tu_map = self._tu_result_dir_map()
        src_root = self._compute_source_root()
        entry_tu = self._find_entry_tu()
        crate_name = self._crate_name()

        os.makedirs(self.output_root, exist_ok=True)
        crate_dir = os.path.join(self.output_root, crate_name)
        if os.path.isdir(crate_dir):
            shutil.rmtree(crate_dir)
        src_dir = os.path.join(crate_dir, "src")
        os.makedirs(src_dir, exist_ok=True)

        # Build cross-TU dependency table (name-based; best-effort)
        cross_deps, func_owner_by_name = self._build_cross_tu_deps()

        # Prepare module declarations for non-entry TUs and write module files
        module_decls: list[str] = []
        for tu_path, result_dir in tu_map.items():
            rs_rel_path, mod_name = self._rel_c_to_rs_path(tu_path, src_root)
            out_path = os.path.join(src_dir, rs_rel_path)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            code = self._collect_rs_code_for_tu(result_dir)

            # Inject cross-TU imports needed by this TU
            needed = sorted(cross_deps.get(os.path.realpath(tu_path), set()))
            import_lines: list[str] = []
            for fname in needed:
                owner = func_owner_by_name.get(fname)
                if not owner:
                    continue
                owner_rel, owner_mod = self._rel_c_to_rs_path(owner, src_root)
                # owner_rel unused; only module name matters
                import_lines.append(f"use crate::{owner_mod}::{fname};")
            import_block = "\n\n" + "\n".join(sorted(set(import_lines))) + ("\n\n" if import_lines else "")
            full_code = "#![allow(unused_imports, unused_variables, dead_code)]\n" + import_block + code
            utils.save_code(out_path, full_code)

            # Entry TU handled later as main.rs; still declare mod for other TUs
            if not (entry_tu and os.path.samefile(tu_path, entry_tu)):
                module_decls.append(f"#[path = \"{rs_rel_path.replace(os.sep, '/') }\"] mod {mod_name};")

        # Write manifest (bin if entry exists; otherwise lib)
        with_bin = bool(entry_tu)
        self._write_manifest(crate_dir, with_bin=with_bin, crate_name=crate_name)

        # Compose crate root
        if with_bin:
            # Main TU code goes into src/main.rs
            assert entry_tu is not None
            entry_rs_rel, entry_mod = self._rel_c_to_rs_path(entry_tu, src_root)
            # Gather code for entry
            entry_code = self._collect_rs_code_for_tu(tu_map[entry_tu])
            # In main.rs, declare all other modules
            root = ["#![allow(unused_imports, unused_variables, dead_code)]"]
            root.extend(module_decls)

            # Bring cross-TU deps used in entry into scope
            needed = sorted(cross_deps.get(os.path.realpath(entry_tu), set()))
            for fname in needed:
                owner = func_owner_by_name.get(fname)
                if not owner:
                    continue
                _, owner_mod = self._rel_c_to_rs_path(owner, src_root)
                root.append(f"use crate::{owner_mod}::{fname};")

            root.append("")
            root.append(entry_code)
            main_rs = "\n".join(root) + "\n"
            utils.save_code(os.path.join(src_dir, "main.rs"), main_rs)
        else:
            # No entry: build a library root that declares all modules
            root = ["#![allow(unused_imports, unused_variables, dead_code)]"]
            root.extend(module_decls)
            lib_rs = "\n".join(root) + "\n"
            utils.save_code(os.path.join(src_dir, "lib.rs"), lib_rs)

        # Build
        fmt = ["cargo", "fmt", "--manifest-path", os.path.join(crate_dir, "Cargo.toml")]
        res = utils.run_command(fmt)
        if res.returncode != 0:
            logger.error("Project fmt failed: %s", res.stderr)

        clippy_fix = ["cargo", "clippy", "--fix", "--allow-no-vcs", "--manifest-path", os.path.join(crate_dir, "Cargo.toml")]
        res = utils.run_command(clippy_fix)
        if res.returncode != 0:
            logger.error("Project clippy fix failed: %s", res.stderr)

        build_cmd = ["cargo", "build", "--manifest-path", os.path.join(crate_dir, "Cargo.toml")]
        res = utils.run_command(build_cmd)
        if res.returncode != 0:
            logger.error("Project build failed")
            return False, crate_dir, None

        # Tests (only when bin exists)
        bin_path = None
        if with_bin:
            bin_path = os.path.join(crate_dir, "target", "debug", self._crate_name())
            ok, msg = self._run_project_tests(bin_path)
            if not ok:
                logger.error("Project-level tests failed: %s", msg or "")
                return False, crate_dir, bin_path

        return True, crate_dir, bin_path
