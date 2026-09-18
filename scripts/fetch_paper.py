"""Fetch a paper's LaTeX source from arXiv — the prerequisite for
scripts/doc_ir.py, which needs real source text to parse, not just an
abstract. arXiv's e-print endpoint returns a gzipped tarball for
multi-file submissions or a bare gzipped .tex for single-file ones; this
handles both and finds the file with \\documentclass.

Usage:
    uv run scripts/fetch_paper.py <arxiv-id>
"""

import argparse
import gzip
import io
import os
import sys
import tarfile
from pathlib import Path

import httpx

ROOT = Path(os.environ.get("SHARED_ROOT", "/shared"))
PAPERS_DIR = ROOT / "papers"


def fetch(arxiv_id: str) -> None:
    dest = PAPERS_DIR / arxiv_id
    if dest.is_dir() and any(dest.glob("*.tex")):
        main = _find_main_tex(dest)
        if main:
            print(f"already fetched: {main}")
            return

    url = f"https://export.arxiv.org/e-print/{arxiv_id}"
    headers = {"User-Agent": "agentic-autoresearch/0.1 (paper ingestion)", "Accept": "*/*"}
    try:
        resp = httpx.get(url, timeout=30.0, follow_redirects=True, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        print(f"error: failed to fetch {url}: {e}", file=sys.stderr)
        sys.exit(1)

    dest.mkdir(parents=True, exist_ok=True)
    raw = resp.content

    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            tar.extractall(dest, filter="data")
    except tarfile.ReadError:
        # Single-file submission: bare gzip of one .tex file.
        try:
            text = gzip.decompress(raw)
        except OSError as e:
            print(f"error: response wasn't a tar.gz or gzip file: {e}", file=sys.stderr)
            sys.exit(1)
        (dest / f"{arxiv_id}.tex").write_bytes(text)

    main = _find_main_tex(dest)
    if not main:
        print(f"error: fetched files to {dest} but none contain \\documentclass", file=sys.stderr)
        sys.exit(1)
    print(f"fetched to {dest}")
    print(f"main file: {main}")


def _find_main_tex(dest: Path) -> Path | None:
    for tex in dest.rglob("*.tex"):
        try:
            if r"\documentclass" in tex.read_text(encoding="utf-8", errors="ignore"):
                return tex
        except OSError:
            continue
    return None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("arxiv_id")
    args = p.parse_args()
    fetch(args.arxiv_id)


if __name__ == "__main__":
    main()
