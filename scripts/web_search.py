"""General web search — discovery fallback for material outside the scholarly
APIs (blogs, lab pages, company research, docs, talks). No key needed.

Usage:
    uv run scripts/web_search.py "<query>" [--limit N]
"""

import argparse
import sys

from ddgs import DDGS


def search(query: str, limit: int) -> None:
    try:
        results = DDGS().text(query, max_results=limit)
    except Exception as e:
        print(f"error: web search failed: {e}", file=sys.stderr)
        sys.exit(1)

    for r in results:
        title = r.get("title") or "(untitled)"
        url = r.get("href") or ""
        body = (r.get("body") or "").strip()
        print(f"- {title}")
        print(f"  {url}")
        if body:
            print(f"  {body[:200]}")
        print()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()
    search(args.query, args.limit)


if __name__ == "__main__":
    main()
