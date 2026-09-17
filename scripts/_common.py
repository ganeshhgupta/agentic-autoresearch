"""Shared HTTP helper for the research connector scripts. Not a standalone
tool — imported by the other scripts/*.py files.
"""

import sys

import httpx


def get_json(url: str, params: dict | None = None, headers: dict | None = None, timeout: float = 20.0):
    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        print(f"error: request to {url} failed: {e}", file=sys.stderr)
        sys.exit(1)
