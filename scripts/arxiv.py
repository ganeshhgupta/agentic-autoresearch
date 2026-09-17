"""arXiv connector — latest CS/AI/math/physics preprints. No key needed.

Usage:
    uv run scripts/arxiv.py search "<query>" [--limit N]
    uv run scripts/arxiv.py get <arxiv_id>
"""

import argparse
import sys
import xml.etree.ElementTree as ET

import httpx

BASE = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}


def _fetch(params: dict) -> ET.Element:
    try:
        resp = httpx.get(BASE, params=params, timeout=20.0)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        print(f"error: request to arXiv failed: {e}", file=sys.stderr)
        sys.exit(1)
    return ET.fromstring(resp.text)


def _print_entry(entry: ET.Element) -> None:
    title = (entry.findtext("atom:title", default="", namespaces=NS) or "").strip()
    summary = (entry.findtext("atom:summary", default="", namespaces=NS) or "").strip()
    published = entry.findtext("atom:published", default="", namespaces=NS)
    arxiv_id = (entry.findtext("atom:id", default="", namespaces=NS) or "").rsplit("/", 1)[-1]
    authors = ", ".join(
        a.findtext("atom:name", default="", namespaces=NS) for a in entry.findall("atom:author", NS)
    )
    pdf_url = ""
    for link in entry.findall("atom:link", NS):
        if link.get("title") == "pdf":
            pdf_url = link.get("href", "")

    print(f"- {title} ({published[:10]})")
    if authors:
        print(f"  authors: {authors}")
    print(f"  id: {arxiv_id}")
    if pdf_url:
        print(f"  full_text: {pdf_url}")
    if summary:
        print(f"  abstract: {summary[:300]}")
    print()


def search(query: str, limit: int) -> None:
    root = _fetch({"search_query": f"all:{query}", "start": 0, "max_results": limit})
    for entry in root.findall("atom:entry", NS):
        _print_entry(entry)


def get(arxiv_id: str) -> None:
    root = _fetch({"id_list": arxiv_id})
    for entry in root.findall("atom:entry", NS):
        _print_entry(entry)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)

    gp = sub.add_parser("get")
    gp.add_argument("arxiv_id")

    args = p.parse_args()
    if args.cmd == "search":
        search(args.query, args.limit)
    elif args.cmd == "get":
        get(args.arxiv_id)


if __name__ == "__main__":
    main()
