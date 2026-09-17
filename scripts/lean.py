"""Lean 4 + Mathlib connector — formally typecheck a .lean file against the
full Mathlib library. Use this to check whether a hypothesis, once stated
precisely as a formal claim, actually holds (falsification stage of the
pipeline) rather than relying on prose reasoning alone.

The prebuilt Lean project (with Mathlib) lives outside the workspace at
LEAN_PROJECT_DIR (baked into the image at /opt/lean/research); this script
just points `lake env lean` at a file you wrote anywhere under the workspace.

Usage:
    uv run scripts/lean.py new <path/to/file.lean>    # scaffold a file with `import Mathlib`
    uv run scripts/lean.py check <path/to/file.lean>  # typecheck it
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("SHARED_ROOT", "/shared"))
LEAN_PROJECT_DIR = os.environ.get("LEAN_PROJECT_DIR", "/opt/lean/research")

STARTER = """import Mathlib

-- State your claim as a theorem/example and prove or refute it.
example : True := trivial
"""


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def new(path: str) -> None:
    target = _resolve(path)
    if target.suffix != ".lean":
        print("error: file must end with .lean", file=sys.stderr)
        sys.exit(1)
    if target.exists():
        print(f"error: {target} already exists", file=sys.stderr)
        sys.exit(1)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(STARTER, encoding="utf-8")
    print(f"created {target}")


def check(path: str) -> None:
    target = _resolve(path)
    if not target.is_file():
        print(f"error: {target} does not exist", file=sys.stderr)
        sys.exit(1)

    try:
        proc = subprocess.run(
            ["lake", "env", "lean", str(target)],
            cwd=LEAN_PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("error: lean timed out after 300s", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(
            f"error: `lake` not found or {LEAN_PROJECT_DIR} missing — "
            "the Lean/Mathlib toolchain may not be installed in this image",
            file=sys.stderr,
        )
        sys.exit(1)

    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        print("OK: typechecks with no errors")
        if output.strip():
            print(output)
    else:
        print("FAILED: does not typecheck")
        print(output)
        sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    np = sub.add_parser("new")
    np.add_argument("path")

    cp = sub.add_parser("check")
    cp.add_argument("path")

    args = p.parse_args()
    if args.cmd == "new":
        new(args.path)
    elif args.cmd == "check":
        check(args.path)


if __name__ == "__main__":
    main()
