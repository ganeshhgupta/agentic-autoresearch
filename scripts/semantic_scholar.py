"""Semantic Scholar connector — papers, citation/reference graph, and
recommendations. Works without a key; set SEMANTIC_SCHOLAR_API_KEY for higher
rate limits.

Usage:
    uv run scripts/semantic_scholar.py search "<query>" [--limit N]
    uv run scripts/semantic_scholar.py get <paper_id>
    uv run scripts/semantic_scholar.py citations <paper_id> [--limit N]
    uv run scripts/semantic_scholar.py references <paper_id> [--limit N]
    uv run scripts/semantic_scholar.py recommend <paper_id> [--limit N]
"""

import argparse
import os

from _common import get_json

GRAPH_BASE = "https://api.semanticscholar.org/graph/v1"
REC_BASE = "https://api.semanticscholar.org/recommendations/v1"
FIELDS = "title,year,authors,abstract,externalIds,citationCount,openAccessPdf,venue"


def _headers() -> dict:
    key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    return {"x-api-key": key} if key else {}


def _print_paper(w: dict) -> None:
    title = w.get("title") or "(untitled)"
    year = w.get("year")
    authors = ", ".join(a.get("name", "") for a in (w.get("authors") or [])[:5])
    doi = (w.get("externalIds") or {}).get("DOI")
    cited_by = w.get("citationCount")
    pdf = (w.get("openAccessPdf") or {}).get("url")

    print(f"- {title} ({year})")
    if authors:
        print(f"  authors: {authors}")
    print(f"  id: {w.get('paperId')}  doi: {doi}  cited_by: {cited_by}")
    if pdf:
        print(f"  full_text: {pdf}")
    print()


def search(query: str, limit: int) -> None:
    data = get_json(
        f"{GRAPH_BASE}/paper/search",
        params={"query": query, "limit": limit, "fields": FIELDS},
        headers=_headers(),
    )
    for w in data.get("data", []):
        _print_paper(w)


def get(paper_id: str) -> None:
    data = get_json(f"{GRAPH_BASE}/paper/{paper_id}", params={"fields": FIELDS}, headers=_headers())
    _print_paper(data)


def citations(paper_id: str, limit: int) -> None:
    data = get_json(
        f"{GRAPH_BASE}/paper/{paper_id}/citations",
        params={"limit": limit, "fields": FIELDS},
        headers=_headers(),
    )
    for edge in data.get("data", []):
        paper = edge.get("citingPaper") or {}
        _print_paper(paper)


def references(paper_id: str, limit: int) -> None:
    data = get_json(
        f"{GRAPH_BASE}/paper/{paper_id}/references",
        params={"limit": limit, "fields": FIELDS},
        headers=_headers(),
    )
    for edge in data.get("data", []):
        paper = edge.get("citedPaper") or {}
        _print_paper(paper)


def recommend(paper_id: str, limit: int) -> None:
    data = get_json(
        f"{REC_BASE}/papers/forpaper/{paper_id}",
        params={"limit": limit, "fields": FIELDS},
        headers=_headers(),
    )
    for w in data.get("recommendedPapers", []):
        _print_paper(w)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)

    gp = sub.add_parser("get")
    gp.add_argument("paper_id")

    cp = sub.add_parser("citations")
    cp.add_argument("paper_id")
    cp.add_argument("--limit", type=int, default=10)

    rp = sub.add_parser("references")
    rp.add_argument("paper_id")
    rp.add_argument("--limit", type=int, default=10)

    xp = sub.add_parser("recommend")
    xp.add_argument("paper_id")
    xp.add_argument("--limit", type=int, default=10)

    args = p.parse_args()
    if args.cmd == "search":
        search(args.query, args.limit)
    elif args.cmd == "get":
        get(args.paper_id)
    elif args.cmd == "citations":
        citations(args.paper_id, args.limit)
    elif args.cmd == "references":
        references(args.paper_id, args.limit)
    elif args.cmd == "recommend":
        recommend(args.paper_id, args.limit)


if __name__ == "__main__":
    main()
