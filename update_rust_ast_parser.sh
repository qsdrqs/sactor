#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ORIGINAL_PWD=$(pwd)

trap "cd ${ORIGINAL_PWD}" EXIT

cd $SCRIPT_DIR
cargo run --no-default-features --bin stub_gen
maturin develop -m rust_ast_parser/Cargo.toml --uv
