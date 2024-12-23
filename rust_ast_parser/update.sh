#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cargo run --manifest-path $SCRIPT_DIR/Cargo.toml
maturin develop --manifest-path $SCRIPT_DIR/Cargo.toml
