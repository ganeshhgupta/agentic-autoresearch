"""Isolated one-shot `claude` CLI calls used as LLM-judge decisions —
canonicalization's final tier (scripts/kg.py's `canonicalize`) and the
Atomicity/Scope/Inference critics (scripts/critics.py).

Each call is a fresh, tool-less subprocess: no conversation history, no
file access, no system prompt, judging only the text handed to it in the
prompt. That isolation is deliberate — the same reasoning pass that built
a claim/patch should not be the one that blesses it (this is what makes
these "critics" rather than the agent grading its own homework).

`claude` must be on PATH and already authenticated (inherits
CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY from the parent environment,
same as the outer agent process this script is invoked from).
"""
from __future__ import annotations

import json
import re
import subprocess

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _extract_json(text: str):
    text = text.strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)


def judge(prompt: str, timeout: float = 120.0):
    """Run one isolated judge call and return its parsed JSON response
    (dict or list, whatever the prompt asked for). Raises RuntimeError on
    a CLI failure, subprocess.TimeoutExpired on timeout, and
    json.JSONDecodeError if the model didn't return valid JSON — callers
    should treat all of these as "this judge call is unusable" and either
    retry once or surface it as a NEEDS_REVIEW condition, never silently
    swallow it as a pass.
    """
    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "json", "--max-turns", "1"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"llm judge call failed (exit {result.returncode}): {result.stderr[:500]}")
    envelope = json.loads(result.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"llm judge call errored: {envelope.get('result', '')[:500]}")
    return _extract_json(envelope.get("result", ""))
