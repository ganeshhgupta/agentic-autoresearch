"""Lean 4 + Mathlib connector — formally typecheck a .lean file against the
full Mathlib library. Use this to check whether a hypothesis, once stated
precisely as a formal claim, actually holds (falsification stage of the
pipeline) rather than relying on prose reasoning alone.

Mathlib runs as its own service (see lean-service/) because loading its
environment needs real RAM this app's container doesn't have. Set
LEAN_SERVICE_URL (and LEAN_SERVICE_TOKEN if the service requires auth) to
point at it.

Usage:
    uv run scripts/lean.py new <path/to/file.lean>    # scaffold a file with `import Mathlib`
    uv run scripts/lean.py check <path/to/file.lean>  # typecheck it
"""

import argparse
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(os.environ.get("SHARED_ROOT", "/shared"))
SERVICE_URL = os.environ.get("LEAN_SERVICE_URL", "").rstrip("/")
SERVICE_TOKEN = os.environ.get("LEAN_SERVICE_TOKEN")

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
    if not SERVICE_URL:
        print("error: LEAN_SERVICE_URL is not set", file=sys.stderr)
        sys.exit(1)

    target = _resolve(path)
    if not target.is_file():
        print(f"error: {target} does not exist", file=sys.stderr)
        sys.exit(1)

    headers = {"Authorization": f"Bearer {SERVICE_TOKEN}"} if SERVICE_TOKEN else {}
    try:
        resp = httpx.post(
            f"{SERVICE_URL}/check",
            json={"code": target.read_text(encoding="utf-8")},
            headers=headers,
            timeout=310.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        print(f"error: request to lean-service failed: {e}", file=sys.stderr)
        sys.exit(1)

    data = resp.json()
    if data["ok"]:
        print("OK: typechecks with no errors")
        if data["output"].strip():
            print(data["output"])
    else:
        print("FAILED: does not typecheck")
        print(data["output"])
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
