"""Crossref connector — DOI metadata, publishers, funders. No key needed; set
RESEARCH_CONTACT_EMAIL to join the polite pool (higher rate limits).

Usage:
    uv run scripts/crossref.py search "<query>" [--limit N]
    uv run scripts/crossref.py get <doi>
"""

import argparse
import os

from _common import get_json

BASE = "https://api.crossref.org"


def _headers() -> dict:
    email = os.getenv("RESEARCH_CONTACT_EMAIL")
    agent = "agentic-autoresearch/0.1"
    if email:
        agent += f" (mailto:{email})"
    return {"User-Agent": agent}


def _print_work(w: dict) -> None:
    title = (w.get("title") or ["(untitled)"])[0]
    year = ((w.get("issued") or {}).get("date-parts") or [[None]])[0][0]
    authors = ", ".join(
        f"{a.get('given', '')} {a.get('family', '')}".strip() for a in (w.get("author") or [])[:5]
    )
    doi = w.get("DOI")
    cited_by = w.get("is-referenced-by-count")
    funders = ", ".join(f.get("name", "") for f in (w.get("funder") or []))

    print(f"- {title} ({year})")
    if authors:
        print(f"  authors: {authors}")
    print(f"  doi: {doi}  cited_by: {cited_by}")
    if funders:
        print(f"  funders: {funders}")
    print()


def search(query: str, limit: int) -> None:
    data = get_json(
        f"{BASE}/works",
        params={"query": query, "rows": limit},
        headers=_headers(),
    )
    for w in data.get("message", {}).get("items", []):
        _print_work(w)


def get(doi: str) -> None:
    data = get_json(f"{BASE}/works/{doi}", headers=_headers())
    _print_work(data.get("message", {}))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)

    gp = sub.add_parser("get")
    gp.add_argument("doi")

    args = p.parse_args()
    if args.cmd == "search":
        search(args.query, args.limit)
    elif args.cmd == "get":
        get(args.doi)


if __name__ == "__main__":
    main()
