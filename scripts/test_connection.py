"""One-shot check that every research connector is reachable and, where
required, correctly authenticated.

Usage:
    uv run scripts/test_connection.py
"""

import os
import sys

import httpx


def check(name: str, fn) -> bool:
    try:
        fn()
    except Exception as e:  # noqa: BLE001 - report any failure, keep checking the rest
        print(f"FAIL  {name}: {e}")
        return False
    print(f"OK    {name}")
    return True


def check_openalex() -> None:
    r = httpx.get("https://api.openalex.org/works", params={"search": "test", "per_page": 1}, timeout=10)
    r.raise_for_status()


def check_semantic_scholar() -> None:
    key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    headers = {"x-api-key": key} if key else {}
    r = httpx.get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={"query": "test", "limit": 1},
        headers=headers,
        timeout=10,
    )
    r.raise_for_status()


def check_crossref() -> None:
    r = httpx.get("https://api.crossref.org/works", params={"query": "test", "rows": 1}, timeout=10)
    r.raise_for_status()


def check_arxiv() -> None:
    r = httpx.get("http://export.arxiv.org/api/query", params={"search_query": "all:test", "max_results": 1}, timeout=10)
    r.raise_for_status()


def check_core() -> None:
    key = os.getenv("CORE_API_KEY")
    if not key:
        raise RuntimeError("CORE_API_KEY not set")
    r = httpx.get(
        "https://api.core.ac.uk/v3/search/works",
        params={"q": "test", "limit": 1},
        headers={"Authorization": f"Bearer {key}"},
        timeout=10,
    )
    r.raise_for_status()


def check_openaire() -> None:
    r = httpx.get("https://api.openaire.eu/graph/v1/researchProducts", params={"search": "test", "pageSize": 1}, timeout=10)
    r.raise_for_status()


def check_web_search() -> None:
    from ddgs import DDGS

    list(DDGS().text("test", max_results=1))


def main() -> None:
    checks = [
        ("OpenAlex", check_openalex),
        ("Semantic Scholar", check_semantic_scholar),
        ("Crossref", check_crossref),
        ("arXiv", check_arxiv),
        ("CORE", check_core),
        ("OpenAIRE", check_openaire),
        ("Web search", check_web_search),
    ]
    results = [check(name, fn) for name, fn in checks]
    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
