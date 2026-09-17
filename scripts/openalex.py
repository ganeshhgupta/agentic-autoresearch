"""OpenAlex connector — scholarly works, authors, topics, and citation graph.
No API key needed. Set RESEARCH_CONTACT_EMAIL to join the polite pool (higher
rate limits).

Usage:
    uv run scripts/openalex.py search "<query>" [--limit N]
    uv run scripts/openalex.py get <openalex_id_or_doi>
    uv run scripts/openalex.py citations <openalex_id>   # works that cite this one
    uv run scripts/openalex.py references <openalex_id>  # works this one cites
"""

import argparse
import os

from _common import get_json

BASE = "https://api.openalex.org"


def _params(extra: dict | None = None) -> dict:
    params = dict(extra or {})
    email = os.getenv("RESEARCH_CONTACT_EMAIL")
    if email:
        params["mailto"] = email
    return params


def _print_work(w: dict) -> None:
    title = w.get("title") or "(untitled)"
    year = w.get("publication_year")
    doi = w.get("doi")
    cited_by = w.get("cited_by_count")
    oa_url = (w.get("open_access") or {}).get("oa_url")
    authors = ", ".join(a["author"]["display_name"] for a in w.get("authorships", [])[:5])

    print(f"- {title} ({year})")
    if authors:
        print(f"  authors: {authors}")
    print(f"  id: {w.get('id')}  doi: {doi}  cited_by: {cited_by}")
    if oa_url:
        print(f"  full_text: {oa_url}")
    print()


def search(query: str, limit: int) -> None:
    data = get_json(f"{BASE}/works", params=_params({"search": query, "per_page": limit}))
    for w in data.get("results", []):
        _print_work(w)


def get(work_id: str) -> None:
    data = get_json(f"{BASE}/works/{work_id}", params=_params())
    _print_work(data)


def citations(work_id: str, limit: int) -> None:
    data = get_json(f"{BASE}/works", params=_params({"filter": f"cites:{work_id}", "per_page": limit}))
    for w in data.get("results", []):
        _print_work(w)


def references(work_id: str) -> None:
    data = get_json(f"{BASE}/works/{work_id}", params=_params())
    refs = data.get("referenced_works", [])
    print(f"{len(refs)} referenced works:")
    for r in refs:
        print(f"  {r}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)

    gp = sub.add_parser("get")
    gp.add_argument("work_id")

    cp = sub.add_parser("citations")
    cp.add_argument("work_id")
    cp.add_argument("--limit", type=int, default=10)

    rp = sub.add_parser("references")
    rp.add_argument("work_id")

    args = p.parse_args()
    if args.cmd == "search":
        search(args.query, args.limit)
    elif args.cmd == "get":
        get(args.work_id)
    elif args.cmd == "citations":
        citations(args.work_id, args.limit)
    elif args.cmd == "references":
        references(args.work_id)


if __name__ == "__main__":
    main()
