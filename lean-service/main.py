"""Standalone Lean 4 + Mathlib typechecking service. Runs on its own host
(an Oracle Cloud Always-Free VM, in this project's case) because loading
Mathlib's environment needs real RAM — 2-4GB+ — that a small free web
service instance doesn't have. The main app's scripts/lean.py is an HTTP
client to this.

Usage: uvicorn main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
import secrets
import subprocess
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

LEAN_PROJECT_DIR = os.environ.get("LEAN_PROJECT_DIR", "/opt/lean/research")
TOKEN = os.environ.get("LEAN_SERVICE_TOKEN")
SCRATCH_DIR = Path(os.environ.get("LEAN_SCRATCH_DIR", "/tmp/lean-scratch"))

app = FastAPI()


class CheckRequest(BaseModel):
    code: str


class CheckResponse(BaseModel):
    ok: bool
    output: str


def _require_auth(authorization: str | None) -> None:
    if not TOKEN:
        return  # no token configured: auth disabled (fine for a private VM behind its own firewall)
    expected = f"Bearer {TOKEN}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/check", response_model=CheckResponse)
async def check(req: CheckRequest, authorization: str | None = Header(default=None)) -> CheckResponse:
    _require_auth(authorization)

    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    target = SCRATCH_DIR / f"{uuid.uuid4().hex}.lean"
    target.write_text(req.code, encoding="utf-8")

    try:
        proc = subprocess.run(
            ["lake", "env", "lean", str(target)],
            cwd=LEAN_PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return CheckResponse(ok=False, output="lean timed out after 300s")
    finally:
        target.unlink(missing_ok=True)

    output = (proc.stdout or "") + (proc.stderr or "")
    return CheckResponse(ok=proc.returncode == 0, output=output)
