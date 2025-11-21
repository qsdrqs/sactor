#!/usr/bin/env python3

import argparse
import subprocess
import sys
from pathlib import Path


EXPECTED_OUTPUT = "sum=3 product=12 avg=3.00 max=5 dot=35"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify cmake_multi executable output.")
    parser.add_argument("executable", help="Path to the cmake_multi executable to run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = Path(args.executable)

    if not target.exists():
        print(f"expected executable at {target}, but it does not exist", file=sys.stderr)
        return 1
    if not target.is_file():
        print(f"expected {target} to be a file", file=sys.stderr)
        return 1

    try:
        result = subprocess.run(
            [str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"execution failed for {target}: {exc}", file=sys.stderr)
        if exc.stdout:
            print(exc.stdout, file=sys.stderr)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        return exc.returncode or 1

    actual = result.stdout.strip()
    if actual != EXPECTED_OUTPUT:
        print(
            f"unexpected output from {target}:\nexpected: {EXPECTED_OUTPUT}\nactual:   {actual}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
