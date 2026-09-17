"""LaTeX editor support: list/read/write .tex files under the workspace's
`latex/` folder and compile one with tectonic. Used by both the frontend
editor panel (/api/latex/*) and, indirectly, the agent itself (which can
read/write the same files with its own Write/Edit tools).
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(os.environ.get("SHARED_ROOT", "/shared"))
LATEX_DIR = ROOT / "latex"


class LatexError(Exception):
    pass


def _safe_path(name: str) -> Path:
    """Resolve `name` to a .tex file inside LATEX_DIR, rejecting traversal."""
    if not name.endswith(".tex"):
        raise LatexError("filename must end with .tex")
    candidate = (LATEX_DIR / Path(name).name).resolve()
    LATEX_DIR.mkdir(parents=True, exist_ok=True)
    if candidate.parent != LATEX_DIR.resolve():
        raise LatexError("invalid filename")
    return candidate


def list_files() -> list[str]:
    LATEX_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p.name for p in LATEX_DIR.glob("*.tex"))


def read_file(name: str) -> str:
    path = _safe_path(name)
    if not path.is_file():
        raise LatexError(f"{name} does not exist")
    return path.read_text(encoding="utf-8")


def write_file(name: str, content: str) -> None:
    path = _safe_path(name)
    path.write_text(content, encoding="utf-8")


def compile_file(name: str) -> tuple[bytes | None, str]:
    """Compile `name` with tectonic. Returns (pdf_bytes, log) — pdf_bytes is
    None if compilation failed; the log is always tectonic's combined output."""
    path = _safe_path(name)
    if not path.is_file():
        raise LatexError(f"{name} does not exist")

    try:
        proc = subprocess.run(
            ["tectonic", "--outdir", str(LATEX_DIR), path.name],
            cwd=LATEX_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as e:
        logger.warning("tectonic timed out compiling %s: %s", name, e)
        return None, "compilation timed out after 120s"

    log = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        logger.info("tectonic failed for %s (exit %d)", name, proc.returncode)
        return None, log

    pdf_path = path.with_suffix(".pdf")
    if not pdf_path.is_file():
        return None, log or "tectonic reported success but produced no PDF"
    return pdf_path.read_bytes(), log
