"""Review a GraphPatch manifest BEFORE it's committed via `kg.py apply-patch`.

The 5 specialized critics: Atomicity, Inference (the most important — a bad
derivation is worse than a bad atom), Scope, Provenance ("no source span ->
don't promote it"), and Canonicalization ("not merely similar" -> an
embedding score alone is never sufficient grounds to reuse or equate two
claims). This is a deliberately separate reasoning pass from whatever built
the patch: the agent that authored a claim/inference should not also be the
one that blesses it into the graph. Provenance and Canonicalization are
mechanical checks against the manifest itself; Atomicity, Scope, and
Inference call out to isolated `claude` subprocesses (see llm_judge.py) that
see only the text being judged, nothing else.

See docs/paper_ingestion.md for how this fits into the repair loop: build a
patch, run `critics.py review`, fix any BLOCKING finding and re-run (a few
times at most), then `apply-patch` once it's clean. A patch that still has
blocking issues after repeated attempts should be set aside via
`kg.py paper flag --status needs_review` rather than forced through.

Usage:
    uv run scripts/critics.py review <path/to/patch.json>
"""
from __future__ import annotations

import argparse
import json
import sys

from kg import _run
from llm_judge import judge

GENERAL_RESEARCH_PAPER_ID = "_general-research"
VALID_BASES = {"structural", "symbolic", "lexical", "llm_judge"}


def _finding(critic: str, tmp_id: str | None, blocking: bool, message: str) -> dict:
    return {"critic": critic, "tmp_id": tmp_id, "blocking": blocking, "message": message}


def _nl_content(node: dict) -> str:
    reps = node.get("representations", [])
    nl = next((r for r in reps if r.get("modality") == "nl"), None)
    if nl:
        return nl.get("content", "")
    return reps[0].get("content", "") if reps else ""


# --- 1. Provenance -----------------------------------------------------------

def critic_provenance(patch: dict) -> list[dict]:
    """Every representation must be grounded in a real Graph A source item,
    unless this patch is for the synthetic general-research paper (ordinary
    notes have no doc_ir.py span to ground into)."""
    findings: list[dict] = []
    is_general_notes = patch.get("paper_id") == GENERAL_RESEARCH_PAPER_ID

    all_nodes = patch.get("nodes_to_create", []) + patch.get("nodes_to_reuse", [])
    source_items_to_check: set[str] = set()

    for node in all_nodes:
        tmp_id = node.get("tmp_id") or node.get("existing_claim_id")
        for rep in node.get("representations", []):
            source_item = rep.get("source_item")
            if not source_item:
                if not is_general_notes:
                    findings.append(_finding(
                        "provenance", tmp_id, True,
                        "no --source-item / source_item: a representation with no source "
                        "span must not be promoted into the graph",
                    ))
                continue
            source_items_to_check.add(source_item)

    if source_items_to_check:
        found = _run(
            "MATCH (s:Source) WHERE s.id IN $ids RETURN collect(s.id) AS ids",
            ids=list(source_items_to_check),
        )[0]["ids"]
        missing = source_items_to_check - set(found)
        for m in missing:
            findings.append(_finding(
                "provenance", None, True,
                f"source item {m!r} does not exist in Graph A — run scripts/doc_ir.py first",
            ))

    return findings


# --- 2. Canonicalization ------------------------------------------------------

def critic_canonicalization(patch: dict) -> list[dict]:
    """Reuse/equivalence decisions need a defensible basis. An embedding
    score alone only ever surfaces a candidate — it never merges anything."""
    findings: list[dict] = []

    for node in patch.get("nodes_to_reuse", []):
        basis = node.get("basis")
        if basis not in VALID_BASES:
            findings.append(_finding(
                "canonicalization", node.get("tmp_id") or node.get("existing_claim_id"), True,
                "no defensible canonicalization basis: reuse/equivalence decisions need a "
                "structural, symbolic, lexical, or llm_judge basis — an embedding score alone "
                "is only a candidate signal, never sufficient grounds to merge",
            ))

    for edge in patch.get("equivalence_edges", []):
        basis = edge.get("basis")
        if basis not in VALID_BASES:
            tmp_id = f"{edge.get('from')} -> {edge.get('to')}"
            findings.append(_finding(
                "canonicalization", tmp_id, True,
                "no defensible canonicalization basis: reuse/equivalence decisions need a "
                "structural, symbolic, lexical, or llm_judge basis — an embedding score alone "
                "is only a candidate signal, never sufficient grounds to merge",
            ))

    return findings


# --- 3. Atomicity --------------------------------------------------------------

def critic_atomicity(patch: dict) -> list[dict]:
    nodes = patch.get("nodes_to_create", [])
    if not nodes:
        return []

    items = [{"tmp_id": n["tmp_id"], "content": _nl_content(n)} for n in nodes]
    prompt = (
        "You are reviewing proposed atomic claims for a scientific knowledge graph. "
        "For each claim below, judge whether it is a minimal, single-conclusion, "
        "independently truth-evaluable atomic statement: it must not bundle multiple "
        "separate claims together, and must not be vague or underspecified. "
        "Claims:\n" + json.dumps(items, indent=2) + "\n\n"
        "Respond with ONLY a JSON array, no markdown fences, with one object per claim "
        "in the same order: "
        '{"tmp_id": "...", "atomic": true or false, "issue": "short reason or null"}'
    )

    try:
        results = judge(prompt)
    except Exception as e:  # noqa: BLE001 - any judge-call failure degrades to a warning
        return [
            _finding("atomicity", n["tmp_id"], False,
                      f"atomicity critic call failed — could not verify, review manually ({e})")
            for n in nodes
        ]

    findings: list[dict] = []
    for r in results:
        if not r.get("atomic", True):
            findings.append(_finding("atomicity", r.get("tmp_id"), True,
                                       r.get("issue") or "not atomic"))
    return findings


# --- 4. Scope -------------------------------------------------------------------

def critic_scope(patch: dict) -> list[dict]:
    nodes = patch.get("nodes_to_create", [])
    if not nodes:
        return []

    items = [{"tmp_id": n["tmp_id"], "content": _nl_content(n)} for n in nodes]
    prompt = (
        "You are reviewing proposed claims for a scientific knowledge graph. "
        "For each claim below, judge whether its scope and assumptions are stated "
        "explicitly, and whether it overclaims generality beyond what is actually "
        "supported (for example, a result proven only for a special case must not "
        "read as fully general). "
        "Claims:\n" + json.dumps(items, indent=2) + "\n\n"
        "Respond with ONLY a JSON array, no markdown fences, with one object per claim "
        "in the same order: "
        '{"tmp_id": "...", "scoped": true or false, "issue": "short reason or null"}'
    )

    try:
        results = judge(prompt)
    except Exception as e:  # noqa: BLE001 - any judge-call failure degrades to a warning
        return [
            _finding("scope", n["tmp_id"], False,
                      f"scope critic call failed — could not verify, review manually ({e})")
            for n in nodes
        ]

    findings: list[dict] = []
    for r in results:
        if not r.get("scoped", True):
            findings.append(_finding("scope", r.get("tmp_id"), True,
                                       r.get("issue") or "scope not explicit"))
    return findings


# --- 5. Inference (the most important) ------------------------------------------

def critic_inference(patch: dict, run_fn) -> list[dict]:
    infs = patch.get("inference_nodes", [])
    if not infs:
        return []

    create_by_tmp = {n["tmp_id"]: n for n in patch.get("nodes_to_create", [])}
    # nodes_to_reuse entries may carry an optional tmp_id alias for the
    # already-existing claim they point at (apply_patch resolves these the
    # same way) — a premise/conclusion referencing that alias should
    # resolve to the real existing claim's content, not a Neo4j lookup by
    # the literal alias string (which would never match).
    reuse_alias_to_real = {
        n["tmp_id"]: n["existing_claim_id"]
        for n in patch.get("nodes_to_reuse", [])
        if "tmp_id" in n
    }

    def content_of(ref: str) -> str:
        node = create_by_tmp.get(ref)
        if node is not None:
            return _nl_content(node)
        real_id = reuse_alias_to_real.get(ref, ref)
        rows = run_fn(
            "MATCH (r:Representation {modality:'nl'})-[:OF]->(c:Claim {id:$id}) "
            "RETURN r.content AS content LIMIT 1",
            id=real_id,
        )
        if rows:
            return rows[0]["content"]
        return f"[unknown existing claim {ref}]"

    items = []
    for idx, inf in enumerate(infs):
        inf_id = inf.get("tmp_id") or f"inference[{idx}]"
        items.append({
            "id": inf_id,
            "method": inf.get("method"),
            "reasoning": inf.get("reasoning"),
            "premises": [{"id": p, "content": content_of(p)} for p in inf.get("premises", [])],
            "conclusion": {"id": inf.get("conclusion"), "content": content_of(inf.get("conclusion"))},
        })

    prompt = (
        "You are reviewing proposed derivation steps (inferences) for a scientific "
        "knowledge graph. Each inference lists premises, a method, reasoning, and a "
        "conclusion. For each one, judge two things: (1) does the conclusion actually "
        "follow from exactly these premises via the stated method, with no logical gap; "
        "(2) is the premise set minimal - would the inference still hold if any one "
        "premise were removed? If so, name which premise id is removable.\n\n"
        "Inferences:\n" + json.dumps(items, indent=2) + "\n\n"
        "Respond with ONLY a JSON array, no markdown fences, with one object per "
        "inference in the same order: "
        '{"id": "...", "valid": true or false, "minimal": true or false, '
        '"removable_premise": "premise id or null", "issue": "short reason or null"}'
    )

    try:
        results = judge(prompt)
    except Exception as e:  # noqa: BLE001 - any judge-call failure degrades to a warning
        return [
            _finding("inference", inf.get("tmp_id") or f"inference[{idx}]", False,
                      f"inference critic call failed — could not verify, review manually ({e})")
            for idx, inf in enumerate(infs)
        ]

    findings: list[dict] = []
    for r in results:
        if not r.get("valid", True):
            findings.append(_finding("inference", r.get("id"), True,
                                       "inference does not follow: " + (r.get("issue") or "unspecified gap")))
        elif not r.get("minimal", True):
            findings.append(_finding(
                "inference", r.get("id"), True,
                f"premise set is not minimal — {r.get('removable_premise')} can be removed "
                "without invalidating the inference",
            ))
    return findings


# --- aggregation + CLI -----------------------------------------------------------

CRITIC_ORDER = ["provenance", "canonicalization", "atomicity", "scope", "inference"]


def review(patch_path: str) -> None:
    with open(patch_path, encoding="utf-8") as f:
        patch = json.load(f)

    by_critic: dict[str, list[dict]] = {
        "provenance": critic_provenance(patch),
        "canonicalization": critic_canonicalization(patch),
        "atomicity": critic_atomicity(patch),
        "scope": critic_scope(patch),
        "inference": critic_inference(patch, _run),
    }

    all_findings: list[dict] = []
    for name in CRITIC_ORDER:
        findings = by_critic[name]
        all_findings.extend(findings)
        print(f"=== {name.upper()} ===")
        if not findings:
            print("  (no issues)")
            continue
        for f in findings:
            tag = "BLOCKING" if f["blocking"] else "warning"
            tmp = f"{f['tmp_id']}: " if f["tmp_id"] else ""
            print(f"  [{tag}] {tmp}{f['message']}")

    blocking = [f for f in all_findings if f["blocking"]]
    if blocking:
        print(f"\nBLOCKED ({len(blocking)} blocking issue(s) - fix and re-run, or after "
              "repeated failures mark the paper needs_review via 'kg.py paper flag')")
        sys.exit(1)
    print("\nPASS")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("review")
    rp.add_argument("patch_file")

    args = p.parse_args()
    if args.cmd == "review":
        review(args.patch_file)


if __name__ == "__main__":
    main()
