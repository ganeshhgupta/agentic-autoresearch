"""OpenAIRE connector — research products linked to datasets, software,
projects, and funders. No key needed for the Graph API's public rate limits.

Usage:
    uv run scripts/openaire.py search "<query>" [--limit N]
    uv run scripts/openaire.py get <openaire_id>

Note: the OpenAIRE Graph API has changed shape before (v3 -> v4). If this
starts returning errors, check https://graph.openaire.eu/docs/apis/graph-api/
for the current base URL and response fields.
"""

import argparse

from _common import get_json

BASE = "https://api.openaire.eu/graph/v1/researchProducts"


def _print_product(p: dict) -> None:
    title = p.get("mainTitle") or "(untitled)"
    date = p.get("publicationDate")
    authors = ", ".join(a.get("fullName", "") for a in (p.get("authors") or [])[:5])
    pids = ", ".join(f"{pid.get('scheme')}:{pid.get('value')}" for pid in (p.get("pids") or []))
    instances = [i.get("urls") for i in (p.get("instances") or []) if i.get("urls")]
    urls = [u for group in instances for u in group][:1]

    print(f"- {title} ({date})")
    if authors:
        print(f"  authors: {authors}")
    print(f"  id: {p.get('id')}  pids: {pids}")
    if urls:
        print(f"  full_text: {urls[0]}")
    print()


def search(query: str, limit: int) -> None:
    data = get_json(BASE, params={"search": query, "pageSize": limit})
    for p in data.get("results", []):
        _print_product(p)


def get(openaire_id: str) -> None:
    data = get_json(f"{BASE}/{openaire_id}")
    _print_product(data)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)

    gp = sub.add_parser("get")
    gp.add_argument("openaire_id")

    args = p.parse_args()
    if args.cmd == "search":
        search(args.query, args.limit)
    elif args.cmd == "get":
        get(args.openaire_id)


if __name__ == "__main__":
    main()
