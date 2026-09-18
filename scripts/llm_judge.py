"""Isolated one-shot `claude` CLI calls used as LLM-judge decisions —
canonicalization's final tier (scripts/kg.py's `canonicalize`) and the
Atomicity/Scope/Inference critics (scripts/critics.py).

Each call is a fresh, tool-less subprocess: no conversation history, no
file access, no system prompt, judging only the text handed to it in the
prompt. That isolation is deliberate — the same reasoning pass that built
a claim/patch should not be the one that blesses it (this is what makes
these "critics" rather than the agent grading its own homework).

`claude` must be on PATH. Auth is NOT simply inherited: when this script
runs from inside the outer agent's own Bash tool (the normal case — a
`claude` process's own Bash tool deliberately scrubs CLAUDE_CODE_OAUTH_TOKEN
and ANTHROPIC_API_KEY from the environment it hands to child shell
commands, so a compromised/prompt-injected tool call can't exfiltrate the
long-lived credential via `env`), those two vars are simply absent by the
time a plain subprocess gets here — confirmed by testing this exact
subprocess.run call against the deployed container, which failed with
"Not logged in" despite CLAUDE_CODE_OAUTH_TOKEN genuinely being set on the
service. Ordinary app secrets (NEO4J_PASSWORD, VOYAGE_API_KEY) are NOT
scrubbed this way — only the Claude-auth-specific vars are.

The fix: a second, differently-named env var (`JUDGE_OAUTH_TOKEN`, same
token value, set alongside CLAUDE_CODE_OAUTH_TOKEN on the deployment) that
isn't on that scrub-list, which `judge()` below renames back to
CLAUDE_CODE_OAUTH_TOKEN in the explicit env it builds for the nested
subprocess. Falls back to any already-present CLAUDE_CODE_OAUTH_TOKEN /
ANTHROPIC_API_KEY for contexts where nothing strips them (e.g. running
this script directly outside the agent sandbox, as in local dev).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

# One fixed, isolated CLAUDE_CONFIG_DIR for all judge calls in this
# container's lifetime — never the per-user session dir the outer agent
# uses (that dir has no stored login; auth here comes entirely from the
# injected token below), and reused across calls rather than a fresh
# tempfile.mkdtemp() per call so repeated judge() calls don't accumulate
# throwaway directories.
_JUDGE_CONFIG_DIR = Path(tempfile.gettempdir()) / "llm-judge-claude-config"


def _extract_json(text: str):
    text = text.strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    token = env.get("JUDGE_OAUTH_TOKEN") or env.get("CLAUDE_CODE_OAUTH_TOKEN")
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    _JUDGE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    env["CLAUDE_CONFIG_DIR"] = str(_JUDGE_CONFIG_DIR)
    return env


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
        env=_subprocess_env(),
    )
    if result.returncode != 0:
        # A failed API/auth call reports its real error in the JSON
        # envelope's `result` field on stdout, not stderr — stderr is
        # only populated for an actual CLI crash. Surface whichever one
        # actually has content.
        detail = result.stderr.strip()
        if not detail and result.stdout.strip():
            try:
                detail = json.loads(result.stdout).get("result", "")
            except json.JSONDecodeError:
                detail = result.stdout.strip()
        raise RuntimeError(f"llm judge call failed (exit {result.returncode}): {detail[:500]}")
    envelope = json.loads(result.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"llm judge call errored: {envelope.get('result', '')[:500]}")
    return _extract_json(envelope.get("result", ""))
