"""CORE connector — open-access full-text corpus. Requires a free API key:
https://core.ac.uk/services/api — set CORE_API_KEY.

Usage:
    uv run scripts/core.py search "<query>" [--limit N]
    uv run scripts/core.py get <core_id>
"""

import argparse
import os
import sys

from _common import get_json

BASE = "https://api.core.ac.uk/v3"


def _headers() -> dict:
    key = os.getenv("CORE_API_KEY")
    if not key:
        print("error: CORE_API_KEY is not set (get a free key at https://core.ac.uk/services/api)", file=sys.stderr)
        sys.exit(1)
    return {"Authorization": f"Bearer {key}"}


def _print_result(w: dict) -> None:
    title = w.get("title") or "(untitled)"
    year = w.get("yearPublished")
    authors = ", ".join(w.get("authors", []) if isinstance(w.get("authors"), list) else [])
    doi = w.get("doi")
    download_url = w.get("downloadUrl")

    print(f"- {title} ({year})")
    if authors:
        print(f"  authors: {authors}")
    print(f"  id: {w.get('id')}  doi: {doi}")
    if download_url:
        print(f"  full_text: {download_url}")
    print()


def search(query: str, limit: int) -> None:
    data = get_json(f"{BASE}/search/works", params={"q": query, "limit": limit}, headers=_headers())
    for w in data.get("results", []):
        _print_result(w)


def get(core_id: str) -> None:
    data = get_json(f"{BASE}/works/{core_id}", headers=_headers())
    _print_result(data)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)

    gp = sub.add_parser("get")
    gp.add_argument("core_id")

    args = p.parse_args()
    if args.cmd == "search":
        search(args.query, args.limit)
    elif args.cmd == "get":
        get(args.core_id)


if __name__ == "__main__":
    main()
