"""Knowledge graph — the workspace's persistent research graph, backed by
Neo4j. Used both for ordinary research-session note-taking (`note`) and for
decomposing a full paper into atomic claims (see docs/paper_ingestion.md for
that workflow, and scripts/doc_ir.py for the lossless source-text layer this
points back into via provenance). One graph, shared across every conversation.

Schema:
    (:Claim:Local|Global {id, claim_type, status, domain_tags, created_at})
      -- Local: this paper's draft claim. Global: canonical, shared,
      -- reusable across papers. `claim promote` moves Local -> Global.
    (:Representation {id, modality, content, content_hash, lang_or_system,
                       source_paper, confidence, embedding, created_at})
      -[:OF]->(:Claim)
      -[:GROUNDED_IN]->(:Source)   -- provenance: exact doc-IR span, required
    (:Inference {id, method, reasoning, source_paper, created_at})
      -[:USES]->(:Claim)          -- one edge per premise (a set, not a chain)
      -[:PRODUCES]->(:Claim)      -- the conclusion
    (:Paper {id, title, is_survey, ingested_at, review_status?})
      -- review_status (`paper flag`): in_progress|needs_review|resolved —
      -- backs the repair-loop's "unresolved items go to NEEDS_REVIEW" rule.
      -[:ASSERTS|USES|CHALLENGES {created_at, contribution_type?}]->(:Claim:Global)
      -- contribution_type (Contribution Differencer, set via `paper link
      -- --contribution-type`): reused|novel-connection|new-claim|
      -- generalization|refutation|application — most papers don't
      -- introduce a wholly new claim, this records which kind of
      -- contribution the paper actually made to each claim it touches.
      -[:CITES]->(:Paper)
    (:Claim)-[:EQUIVALENT_TO|GENERALIZES|SPECIALIZES|ANALOGOUS_TO
              |CONTRADICTS|SUPPORTS|LED_TO|RELATED_TO {confidence?, basis?}]->(:Claim)
      -- basis (optional, audit trail only): structural|symbolic|lexical|
      -- llm_judge — which canonicalization tier actually justified this
      -- edge. Never "embedding" — embedding only surfaces candidates.

There is deliberately no update/delete command for Claim or Representation
content — only create, represent, link, promote, and search/canonicalize.
If a paper's claim contradicts or refines an existing one, add a new Claim/
Representation and a CONTRADICTS/GENERALIZES edge; never edit history.

Two ways to write:
  - Individual commands (claim create/represent/link, inference create/
    uses/produces) — immediate, one write per call. Fine for note-taking
    and simple cases.
  - `apply-patch <file.json>` — a typed GraphPatch manifest applied in one
    all-or-nothing transaction. Prefer this for paper ingestion: build the
    patch for one theorem/atomic-unit's worth of claims+inference+edges,
    then commit it atomically instead of many individual imperative calls.
    See `apply-patch --help` / docs/paper_ingestion.md for the schema.

Usage:
    uv run scripts/kg.py init
    uv run scripts/kg.py note --text "..." [--math "..."] [--code "..." --code-lang py]
    uv run scripts/kg.py paper upsert --id <arxiv-id-or-doi> --title "..." [--survey]
    uv run scripts/kg.py paper status --id <arxiv-id-or-doi>
    uv run scripts/kg.py paper link --paper <id> --claim <id> --relation ASSERTS|USES|CHALLENGES [--contribution-type reused|novel-connection|new-claim|generalization|refutation|application]
    uv run scripts/kg.py paper flag --id <arxiv-id-or-doi> --review-status in_progress|needs_review|resolved
    uv run scripts/kg.py canonicalize --text "..." [--math "..."] [--code "..."] [--top-k 5]
    uv run scripts/kg.py claim create --type theorem --status proven [--domain-tags "MSC:11A07"]
    uv run scripts/kg.py claim represent --claim <id> --modality nl --content "..." --paper <paper-id> --source-item <doc-ir-id> [--confidence 0.9]
    uv run scripts/kg.py claim link --type EQUIVALENT_TO --from <id> --to <id> [--confidence 0.8]
    uv run scripts/kg.py claim promote --claim <id>
    uv run scripts/kg.py inference create --method NAME --reasoning "..." --paper <paper-id>
    uv run scripts/kg.py inference uses --inference <id> --claim <id>
    uv run scripts/kg.py inference produces --inference <id> --claim <id>
    uv run scripts/kg.py apply-patch <path/to/patch.json>
    uv run scripts/kg.py show --claim <id>
    uv run scripts/kg.py show --paper <id>
"""

import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timezone

import httpx
from neo4j import GraphDatabase

from llm_judge import judge

EDGE_TYPES = [
    "EQUIVALENT_TO", "GENERALIZES", "SPECIALIZES", "ANALOGOUS_TO",
    "CONTRADICTS", "SUPPORTS", "LED_TO", "RELATED_TO",
]
PAPER_RELATIONS = ["ASSERTS", "USES", "CHALLENGES"]
CLAIM_TYPES = ["definition", "assumption", "axiom", "theorem", "lemma", "corollary",
               "claim", "conjecture", "algorithm", "empirical-result", "observation",
               "construction", "bound", "counterexample", "note"]
STATUSES = ["proven", "conjectured", "empirically-supported", "falsified", "asserted"]
MODALITIES = ["nl", "formal", "code"]
PAPER_REVIEW_STATUSES = ["in_progress", "needs_review", "resolved"]
CONTRIBUTION_TYPES = [
    "reused", "novel-connection", "new-claim", "generalization", "refutation", "application",
]

VOYAGE_MODEL = "voyage-4-large"
GENERAL_RESEARCH_PAPER_ID = "_general-research"  # synthetic Paper for note-taking outside paper ingestion


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def _content_hash(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _driver():
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    if not (uri and user and password):
        print("error: NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD must all be set", file=sys.stderr)
        sys.exit(1)
    return GraphDatabase.driver(uri, auth=(user, password))


def _run(cypher: str, **params) -> list[dict]:
    with _driver() as driver:
        with driver.session() as session:
            result = session.run(cypher, **params)
            return [dict(record) for record in result]


def _embed(text: str, input_type: str) -> list[float]:
    key = os.environ.get("VOYAGE_API_KEY")
    if not key:
        print("error: VOYAGE_API_KEY is not set", file=sys.stderr)
        sys.exit(1)
    try:
        resp = httpx.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {key}"},
            json={"input": text, "model": VOYAGE_MODEL, "input_type": input_type},
            timeout=30.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        print(f"error: embedding request failed: {e}", file=sys.stderr)
        sys.exit(1)
    return resp.json()["data"][0]["embedding"]


def _sympify(expr: str):
    """Best-effort parse of a math string into a SymPy expression for
    symbolic-equivalence checks. Returns None on any failure — most real
    LaTeX math won't parse and that's fine, this tier just skips it."""
    import sympy
    from sympy.parsing.latex import parse_latex

    for parser in (parse_latex, sympy.sympify):
        try:
            return parser(expr)
        except Exception:  # noqa: BLE001 - any parser failure just means "can't use this tier"
            continue
    return None


def init() -> None:
    statements = [
        "CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.id IS UNIQUE",
        "CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT inference_id IF NOT EXISTS FOR (i:Inference) REQUIRE i.id IS UNIQUE",
        "CREATE CONSTRAINT representation_id IF NOT EXISTS FOR (r:Representation) REQUIRE r.id IS UNIQUE",
        "CREATE CONSTRAINT source_id IF NOT EXISTS FOR (s:Source) REQUIRE s.id IS UNIQUE",
        """CREATE VECTOR INDEX representation_embedding IF NOT EXISTS
           FOR (r:Representation) ON (r.embedding)
           OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}""",
    ]
    for stmt in statements:
        _run(stmt)
    print("schema initialized")


def paper_upsert(paper_id: str, title: str, is_survey: bool) -> None:
    rows = _run(
        """MERGE (p:Paper {id: $id})
           ON CREATE SET p.title = $title, p.is_survey = $is_survey, p.ingested_at = $now, p.created = true
           ON MATCH SET p.created = false
           RETURN p.title AS title, p.is_survey AS is_survey, p.created AS created""",
        id=paper_id, title=title, is_survey=is_survey, now=_now(),
    )
    row = rows[0]
    if row["created"]:
        print(f"created paper {paper_id!r}: {row['title']}")
    else:
        print(f"paper {paper_id!r} already exists: {row['title']} (is_survey={row['is_survey']})")
    if row["is_survey"]:
        print("NOTE: marked as a survey/review — per instructions, skip ingesting its claims")


def paper_status(paper_id: str) -> None:
    rows = _run(
        """MATCH (p:Paper {id: $id})
           OPTIONAL MATCH (r:Representation {source_paper: $id})
           RETURN p.title AS title, p.is_survey AS is_survey, p.review_status AS review_status,
                  count(DISTINCT r) AS representation_count""",
        id=paper_id,
    )
    if not rows or rows[0]["title"] is None:
        print(f"paper {paper_id!r} not yet in the graph")
        return
    row = rows[0]
    line = f"{paper_id!r}: {row['title']}  survey={row['is_survey']}  representations_logged={row['representation_count']}"
    if row["review_status"]:
        line += f"  review_status={row['review_status']}"
    print(line)


def paper_flag(paper_id: str, review_status: str) -> None:
    rows = _run(
        "MATCH (p:Paper {id: $id}) SET p.review_status = $status RETURN p.id AS id",
        id=paper_id, status=review_status,
    )
    if not rows:
        print(f"error: no such paper {paper_id}", file=sys.stderr)
        sys.exit(1)
    print(f"{paper_id}: review_status set to {review_status}")


def paper_link(paper_id: str, claim_id: str, relation: str, contribution_type: str | None) -> None:
    rows = _run(
        f"""MATCH (p:Paper {{id: $paper_id}}), (c:Claim {{id: $claim_id}})
            CREATE (p)-[:{relation} {{created_at: $now, contribution_type: $contribution_type}}]->(c)
            RETURN p.id AS p""",
        paper_id=paper_id, claim_id=claim_id, now=_now(), contribution_type=contribution_type,
    )
    if not rows:
        print("error: paper or claim not found", file=sys.stderr)
        sys.exit(1)
    if contribution_type:
        print(f"{paper_id} -{relation}({contribution_type})-> {claim_id}")
    else:
        print(f"{paper_id} -{relation}-> {claim_id}")


def _ast_dump(code: str) -> str | None:
    """Best-effort structural normalization of Python code for the code
    canonicalization tier: parses to an AST and dumps its structure,
    which is invariant to whitespace/comments/formatting but NOT to
    identifier renaming (that would need alpha-equivalence normalization,
    not attempted here — this catches copy-with-reformatting duplicates,
    not copy-with-renamed-variables ones). Returns None on any parse
    failure (non-Python code, syntax errors) — same fallback pattern as
    _sympify: this tier just skips when it can't apply."""
    import ast

    try:
        return ast.dump(ast.parse(code))
    except Exception:  # noqa: BLE001 - any parse failure just means "can't use this tier"
        return None


def canonicalize(text: str, math: str | None, top_k: int, code: str | None = None) -> None:
    """The cascade: structural exact match -> symbolic (math only) ->
    code structural/AST (code only, Python) -> lexical overlap -> dense
    embedding -> LLM judge. Every tier before the LLM judge only SURFACES
    candidates with a tier label; nothing there merges anything. The LLM
    judge asks an isolated call to classify the single best surfaced
    candidate (EXACT_SAME/EQUIVALENT/GENERALIZES/SPECIALIZES/APPROXIMATES/
    CONTRADICTS/RELATED/NEW) — still advisory, not a decision made for
    you: read its reasoning, then act via `claim represent` (reuse) or
    `claim create` + `claim link` (new + edge), citing the tier that
    justified it as `--basis` in a GraphPatch's equivalence_edges/
    nodes_to_reuse entries. Physics (units/dimensions/coordinate system)
    and ML-experiment (dataset/split/metric/hyperparameters/seed) specific
    canonicalizers are NOT implemented — those need a real domain schema
    to compare against, which is a design decision, not a generic
    algorithm; until one exists, physics/ML claims fall back to the
    generic NL text tiers, which is a real limitation, not a silent gap."""
    found_any = False
    best_lexical = None
    best_embedding = None

    # Tier 1: structural exact match.
    h = _content_hash(text)
    exact = _run(
        """MATCH (r:Representation {content_hash: $h})-[:OF]->(c:Claim)
           RETURN DISTINCT c.id AS claim_id, r.content AS content, labels(c) AS labels""",
        h=h,
    )
    if exact:
        found_any = True
        print("=== TIER 1: structural exact match ===")
        for r in exact:
            scope = "Global" if "Global" in r["labels"] else "Local"
            print(f"  [{r['claim_id']}] ({scope}) {r['content'][:150]}")

    # Tier 2: symbolic equivalence (math only).
    if math:
        query_expr = _sympify(math)
        if query_expr is not None:
            candidates = _run(
                "MATCH (r:Representation {modality: 'formal'})-[:OF]->(c:Claim) RETURN c.id AS claim_id, r.content AS content LIMIT 500"
            )
            matches = []
            for cand in candidates:
                cand_expr = _sympify(cand["content"])
                if cand_expr is None:
                    continue
                try:
                    if query_expr.equals(cand_expr):
                        matches.append(cand)
                except Exception:  # noqa: BLE001 - equals() can raise on incompatible types
                    continue
            if matches:
                found_any = True
                print("=== TIER 2: symbolic equivalence (SymPy) ===")
                for m in matches:
                    print(f"  [{m['claim_id']}] {m['content'][:150]}")

    # Tier 2b: code structural match (AST dump comparison, Python only).
    # Separate from the text tiers below — code should never be judged by
    # word overlap or embedding similarity on its source text; two
    # implementations of the same algorithm in different variable names
    # would score low here even though the algorithm is identical, and
    # that's the honest limit of this tier (see _ast_dump's docstring),
    # not something to paper over with a text-similarity fallback.
    if code:
        query_dump = _ast_dump(code)
        if query_dump is not None:
            candidates = _run(
                "MATCH (r:Representation {modality: 'code'})-[:OF]->(c:Claim) RETURN c.id AS claim_id, r.content AS content, r.lang_or_system AS lang LIMIT 500"
            )
            matches = [
                cand for cand in candidates
                if (cand.get("lang") or "").lower() in ("python", "py", "")
                and _ast_dump(cand["content"]) == query_dump
            ]
            if matches:
                found_any = True
                print("=== TIER 2b: code structural match (AST) ===")
                for m in matches:
                    print(f"  [{m['claim_id']}] {m['content'][:150]}")

    # Tier 3: lexical overlap (crude Jaccard over a bounded candidate pool).
    query_words = set(text.lower().split())
    if query_words:
        candidates = _run(
            "MATCH (r:Representation {modality: 'nl'})-[:OF]->(c:Claim) RETURN c.id AS claim_id, r.content AS content LIMIT 200"
        )
        scored = []
        for cand in candidates:
            words = set(cand["content"].lower().split())
            if not words:
                continue
            jaccard = len(query_words & words) / len(query_words | words)
            if jaccard > 0.3:
                scored.append((jaccard, cand))
        if scored:
            found_any = True
            print("=== TIER 3: lexical overlap ===")
            ranked = sorted(scored, key=lambda x: -x[0])
            for score, cand in ranked[:top_k]:
                print(f"  [{cand['claim_id']}] overlap={score:.2f}  {cand['content'][:150]}")
            best_lexical = ranked[0][1]

    # Tier 4: dense embedding retrieval.
    vector = _embed(text, input_type="query")
    rows = _run(
        """MATCH (rep:Representation)
           SEARCH rep IN (VECTOR INDEX representation_embedding FOR $vector LIMIT $k) SCORE AS score
           MATCH (rep)-[:OF]->(c:Claim)
           RETURN c.id AS claim_id, c.claim_type AS claim_type, c.status AS status, labels(c) AS labels,
                  rep.content AS content, rep.source_paper AS source_paper, score
           ORDER BY score DESC""",
        k=top_k, vector=vector,
    )
    if rows:
        found_any = True
        print("=== TIER 4: dense embedding ===")
        for r in rows:
            scope = "Global" if "Global" in r["labels"] else "Local"
            print(f"  [{r['claim_id']}] ({scope}) score={r['score']:.3f}  ({r['claim_type']}, {r['status']})")
            print(f"      {r['content'][:200]}")
            print(f"      from {r['source_paper']}")
        best_embedding = rows[0]

    # Tier 5: LLM judge — one isolated call classifying the single best
    # candidate tiers 3/4 surfaced. Skipped entirely if nothing surfaced
    # (nothing to judge against; "this looks NEW" already covers that).
    best = best_embedding or best_lexical
    if best is not None:
        print("=== TIER 5: LLM judge ===")
        prompt = (
            "You are judging whether two research claims are the same idea. "
            "Classify the relationship of claim A to claim B into exactly one "
            "of these categories: EXACT_SAME, EQUIVALENT, GENERALIZES, "
            "SPECIALIZES, APPROXIMATES, CONTRADICTS, RELATED, NEW.\n\n"
            f"Claim A (new): {text}\n\n"
            f"Claim B (existing, id {best['claim_id']}): {best['content']}\n\n"
            'Respond with ONLY this JSON object, no markdown fences: '
            '{"classification": "...", "reasoning": "one short sentence"}'
        )
        try:
            verdict = judge(prompt)
            print(f"  [{best['claim_id']}] {verdict.get('classification')}: {verdict.get('reasoning')}")
        except Exception:  # noqa: BLE001 - a judge-tier failure must not take down the cascade output above
            print("  (LLM judge call failed — treat this pair as unresolved, judge manually)")

    if not found_any:
        print("no candidates at any tier — this looks NEW")


def claim_create(claim_type: str, status: str, domain_tags: list[str]) -> None:
    claim_id = _new_id("c")
    _run(
        """CREATE (c:Claim:Local {id: $id, claim_type: $claim_type, status: $status,
                                   domain_tags: $domain_tags, created_at: $now})""",
        id=claim_id, claim_type=claim_type, status=status, domain_tags=domain_tags, now=_now(),
    )
    print(f"created claim {claim_id} (Local — `claim promote` once you're confident in it)")


def claim_promote(claim_id: str) -> None:
    rows = _run(
        "MATCH (c:Claim:Local {id: $id}) REMOVE c:Local SET c:Global RETURN c.id AS id",
        id=claim_id,
    )
    if not rows:
        print(f"error: no such Local claim {claim_id} (already Global, or doesn't exist?)", file=sys.stderr)
        sys.exit(1)
    print(f"promoted {claim_id} to Global")


def claim_represent(claim_id: str, modality: str, content: str, lang_or_system: str | None,
                     source_paper: str, source_item: str | None, confidence: float) -> None:
    exists = _run("MATCH (c:Claim {id: $id}) RETURN c.id AS id", id=claim_id)
    if not exists:
        print(f"error: no such claim {claim_id}", file=sys.stderr)
        sys.exit(1)
    if source_item:
        item = _run("MATCH (s:Source {id: $id}) RETURN s.id AS id", id=source_item)
        if not item:
            print(f"error: no such source item {source_item} — run scripts/doc_ir.py first, or omit --source-item for non-paper notes", file=sys.stderr)
            sys.exit(1)

    rep_id = _new_id("r")
    embedding = _embed(content, input_type="document") if modality == "nl" else None
    _run(
        """MATCH (c:Claim {id: $claim_id})
           CREATE (r:Representation {id: $rep_id, modality: $modality, content: $content, content_hash: $hash,
                                      lang_or_system: $lang_or_system, source_paper: $source_paper,
                                      confidence: $confidence, created_at: $now, embedding: $embedding})-[:OF]->(c)""",
        claim_id=claim_id, rep_id=rep_id, modality=modality, content=content, hash=_content_hash(content),
        lang_or_system=lang_or_system, source_paper=source_paper,
        confidence=confidence, now=_now(), embedding=embedding,
    )
    if source_item:
        _run(
            "MATCH (r:Representation {id: $rep_id}), (s:Source {id: $source_item}) CREATE (r)-[:GROUNDED_IN]->(s)",
            rep_id=rep_id, source_item=source_item,
        )
    print(f"added {modality} representation {rep_id} to claim {claim_id}" + (f", grounded in {source_item}" if source_item else ""))


def claim_link(edge_type: str, src: str, dst: str, confidence: float | None) -> None:
    ids = _run("MATCH (c:Claim) WHERE c.id IN [$a, $b] RETURN collect(c.id) AS ids", a=src, b=dst)[0]["ids"]
    if src not in ids or dst not in ids:
        print("error: both claims must already exist", file=sys.stderr)
        sys.exit(1)
    _run(
        f"""MATCH (a:Claim {{id: $src}}), (b:Claim {{id: $dst}})
            CREATE (a)-[:{edge_type} {{confidence: $confidence, created_at: $now}}]->(b)""",
        src=src, dst=dst, confidence=confidence, now=_now(),
    )
    print(f"linked {src} -{edge_type}-> {dst}")


def inference_create(method: str, reasoning: str, source_paper: str) -> None:
    inf_id = _new_id("inf")
    _run(
        "CREATE (i:Inference {id: $id, method: $method, reasoning: $reasoning, source_paper: $source_paper, created_at: $now})",
        id=inf_id, method=method, reasoning=reasoning, source_paper=source_paper, now=_now(),
    )
    print(f"created inference {inf_id}")


def inference_edge(rel: str, inf_id: str, claim_id: str) -> None:
    rows = _run(
        f"""MATCH (i:Inference {{id: $inf_id}}), (c:Claim {{id: $claim_id}})
            CREATE (i)-[:{rel}]->(c)
            RETURN i.id AS inf_id""",
        inf_id=inf_id, claim_id=claim_id,
    )
    if not rows:
        print("error: inference or claim not found", file=sys.stderr)
        sys.exit(1)
    print(f"{inf_id} -{rel}-> {claim_id}")


def note(text: str, math: str | None, code: str | None, code_lang: str | None) -> None:
    """Convenience wrapper for ordinary research-session logging (not paper
    ingestion): one claim, one or more representations, attributed to a
    synthetic general-research 'paper' rather than a real source. Promoted
    to Global immediately — there's no paper-specific draft stage for notes."""
    _run(
        "MERGE (p:Paper {id: $id}) ON CREATE SET p.title = 'General research notes', p.is_survey = false, p.ingested_at = $now",
        id=GENERAL_RESEARCH_PAPER_ID, now=_now(),
    )
    claim_id = _new_id("c")
    _run(
        "CREATE (c:Claim:Global {id: $id, claim_type: 'note', status: 'asserted', domain_tags: [], created_at: $now})",
        id=claim_id, now=_now(),
    )
    claim_represent(claim_id, "nl", text, None, GENERAL_RESEARCH_PAPER_ID, None, 0.8)
    if math:
        claim_represent(claim_id, "formal", math, "informal-math", GENERAL_RESEARCH_PAPER_ID, None, 0.6)
    if code:
        claim_represent(claim_id, "code", code, code_lang, GENERAL_RESEARCH_PAPER_ID, None, 0.8)
    print(f"created note claim {claim_id}")


def show(claim_id: str | None, paper_id: str | None) -> None:
    if claim_id:
        rows = _run(
            """MATCH (c:Claim {id: $id})
               OPTIONAL MATCH (r:Representation)-[:OF]->(c)
               RETURN c.claim_type AS claim_type, c.status AS status, c.domain_tags AS domain_tags, labels(c) AS labels,
                      collect({modality: r.modality, content: r.content, source_paper: r.source_paper}) AS reps""",
            id=claim_id,
        )
        if not rows or rows[0]["claim_type"] is None:
            print(f"no such claim {claim_id}")
            return
        row = rows[0]
        scope = "Global" if "Global" in row["labels"] else "Local"
        print(f"[{claim_id}] {row['claim_type']} / {row['status']} / {scope}  tags={row['domain_tags']}")
        for r in row["reps"]:
            if r["modality"]:
                print(f"  {r['modality']} (from {r['source_paper']}): {r['content'][:200]}")
        edges = _run(
            "MATCH (c:Claim {id: $id})-[e]-(other:Claim) RETURN type(e) AS type, other.id AS other, startNode(e).id = $id AS outgoing",
            id=claim_id,
        )
        for e in edges:
            if e["outgoing"]:
                print(f"  -{e['type']}-> {e['other']}")
            else:
                print(f"  {e['other']} -{e['type']}-> (this claim)")
        inf_rows = _run(
            """MATCH (i:Inference)-[e]-(c:Claim {id: $id})
               RETURN i.id AS inf_id, i.method AS method, type(e) AS rel""",
            id=claim_id,
        )
        for r in inf_rows:
            if r["rel"] == "PRODUCES":
                print(f"  <- produced by {r['inf_id']} ({r['method']})")
            else:
                print(f"  -> used as a premise by {r['inf_id']} ({r['method']})")
    elif paper_id:
        paper_status(paper_id)
        rows = _run(
            "MATCH (r:Representation {source_paper: $id})-[:OF]->(c:Claim) RETURN DISTINCT c.id AS id, c.claim_type AS claim_type",
            id=paper_id,
        )
        for r in rows:
            print(f"  [{r['id']}] {r['claim_type']}")
    else:
        print("error: pass --claim or --paper", file=sys.stderr)
        sys.exit(1)


# --- GraphPatch: typed manifest + one atomic transaction --------------------

PATCH_HELP = """\
GraphPatch JSON schema (see docs/paper_ingestion.md for the full workflow):

{
  "paper_id": "...",
  "nodes_to_create": [
    {"tmp_id": "tmp1", "claim_type": "theorem", "status": "proven", "domain_tags": [],
     "representations": [{"modality": "nl", "content": "...", "source_item": "paperX.theorem1", "confidence": 0.9}]}
  ],
  "nodes_to_reuse": [
    {"existing_claim_id": "c_abc123", "basis": "structural",
     "representations": [{"modality": "nl", "content": "...", "source_item": "paperX.theorem2", "confidence": 0.85}]}
  ],
  "inference_nodes": [
    {"tmp_id": "inf1", "method": "DESCENT_LEMMA", "reasoning": "...",
     "premises": ["tmp1", "c_existing1"], "conclusion": "tmp2"}
  ],
  "equivalence_edges": [{"type": "GENERALIZES", "from": "tmp1", "to": "c_existing2", "confidence": 0.8, "basis": "llm_judge"}],
  "contradiction_edges": [{"from": "tmp1", "to": "c_existing3", "confidence": 0.7}],
  "provenance_links": []   # usually redundant with representations[].source_item; for extra links only
}

`tmp_id` values are resolved to real ids created within this same patch.
Everything else must already exist. The whole patch is validated BEFORE
anything is written, and applied in one transaction — either all of it
lands or none of it does.

`basis` (optional, on nodes_to_reuse and equivalence_edges) records which
canonicalization tier actually justified reusing/equating these claims:
one of structural, symbolic, lexical, llm_judge — never "embedding", since
embedding only ever surfaces candidates, it doesn't confirm equivalence.
This is audit-trail metadata here (apply-patch stores it but doesn't
enforce it); scripts/critics.py's canonicalization critic is what actually
blocks a patch that reuses/equates a claim with no basis or an
embedding-only basis.
"""


def _validate_patch(patch: dict) -> tuple[list[str], set[str]]:
    """Returns (errors, valid_reference_ids) — valid_reference_ids is every
    tmp_id plus every existing id confirmed to be in the graph."""
    errors: list[str] = []
    tmp_ids = {n["tmp_id"] for n in patch.get("nodes_to_create", []) if "tmp_id" in n}
    inf_tmp_ids = {n["tmp_id"] for n in patch.get("inference_nodes", []) if "tmp_id" in n}
    all_tmp = tmp_ids | inf_tmp_ids

    referenced_existing = set()
    for n in patch.get("nodes_to_reuse", []):
        referenced_existing.add(n["existing_claim_id"])
    for inf in patch.get("inference_nodes", []):
        for premise in inf.get("premises", []):
            if premise not in all_tmp:
                referenced_existing.add(premise)
        if inf.get("conclusion") not in all_tmp:
            referenced_existing.add(inf.get("conclusion"))
    for edge in patch.get("equivalence_edges", []) + patch.get("contradiction_edges", []):
        if edge["from"] not in all_tmp:
            referenced_existing.add(edge["from"])
        if edge["to"] not in all_tmp:
            referenced_existing.add(edge["to"])

    if referenced_existing:
        found = _run(
            "MATCH (c:Claim) WHERE c.id IN $ids RETURN collect(c.id) AS ids", ids=list(referenced_existing)
        )[0]["ids"]
        missing = referenced_existing - set(found)
        for m in missing:
            errors.append(f"referenced claim {m!r} does not exist and is not a tmp_id in this patch")

    source_items = set()
    for n in patch.get("nodes_to_create", []) + patch.get("nodes_to_reuse", []):
        for rep in n.get("representations", []):
            if rep.get("source_item"):
                source_items.add(rep["source_item"])
    if source_items:
        found = _run(
            "MATCH (s:Source) WHERE s.id IN $ids RETURN collect(s.id) AS ids", ids=list(source_items)
        )[0]["ids"]
        missing = source_items - set(found)
        for m in missing:
            errors.append(f"source item {m!r} does not exist — run scripts/doc_ir.py first")

    for n in patch.get("nodes_to_create", []):
        if n.get("claim_type") not in CLAIM_TYPES:
            errors.append(f"nodes_to_create {n.get('tmp_id')}: invalid claim_type {n.get('claim_type')!r}")
        if n.get("status") not in STATUSES:
            errors.append(f"nodes_to_create {n.get('tmp_id')}: invalid status {n.get('status')!r}")
    for edge in patch.get("equivalence_edges", []):
        if edge["type"] not in EDGE_TYPES:
            errors.append(f"equivalence_edges: invalid type {edge['type']!r}")

    return errors, all_tmp | referenced_existing


def apply_patch(patch_path: str) -> None:
    with open(patch_path, encoding="utf-8") as f:
        patch = json.load(f)

    errors, _ = _validate_patch(patch)
    if errors:
        print("GraphPatch validation FAILED — nothing was written:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    paper_id = patch.get("paper_id", GENERAL_RESEARCH_PAPER_ID)
    id_map: dict[str, str] = {}  # tmp_id -> real id
    created_claims = 0
    reused_claims = 0
    created_inferences = 0

    def resolve(ref: str) -> str:
        return id_map.get(ref, ref)

    with _driver() as driver:
        with driver.session() as session:

            def write(tx):
                nonlocal created_claims, reused_claims, created_inferences

                for n in patch.get("nodes_to_create", []):
                    claim_id = _new_id("c")
                    id_map[n["tmp_id"]] = claim_id
                    tx.run(
                        """CREATE (c:Claim:Local {id: $id, claim_type: $t, status: $s,
                                                   domain_tags: $tags, created_at: $now})""",
                        id=claim_id, t=n["claim_type"], s=n["status"], tags=n.get("domain_tags", []), now=_now(),
                    )
                    created_claims += 1
                    for rep in n.get("representations", []):
                        _write_representation(tx, claim_id, rep, paper_id)

                for n in patch.get("nodes_to_reuse", []):
                    claim_id = n["existing_claim_id"]
                    if "tmp_id" in n:
                        id_map[n["tmp_id"]] = claim_id
                    reused_claims += 1
                    for rep in n.get("representations", []):
                        _write_representation(tx, claim_id, rep, paper_id)

                for inf in patch.get("inference_nodes", []):
                    inf_id = _new_id("inf")
                    if "tmp_id" in inf:
                        id_map[inf["tmp_id"]] = inf_id
                    tx.run(
                        "CREATE (i:Inference {id: $id, method: $m, reasoning: $r, source_paper: $p, created_at: $now})",
                        id=inf_id, m=inf["method"], r=inf["reasoning"], p=paper_id, now=_now(),
                    )
                    created_inferences += 1
                    for premise in inf.get("premises", []):
                        tx.run(
                            "MATCH (i:Inference {id: $inf_id}), (c:Claim {id: $claim_id}) CREATE (i)-[:USES]->(c)",
                            inf_id=inf_id, claim_id=resolve(premise),
                        )
                    tx.run(
                        "MATCH (i:Inference {id: $inf_id}), (c:Claim {id: $claim_id}) CREATE (i)-[:PRODUCES]->(c)",
                        inf_id=inf_id, claim_id=resolve(inf["conclusion"]),
                    )

                for edge in patch.get("equivalence_edges", []):
                    tx.run(
                        f"""MATCH (a:Claim {{id: $src}}), (b:Claim {{id: $dst}})
                            CREATE (a)-[:{edge['type']} {{confidence: $conf, created_at: $now, basis: $basis}}]->(b)""",
                        src=resolve(edge["from"]), dst=resolve(edge["to"]), conf=edge.get("confidence"),
                        basis=edge.get("basis"), now=_now(),
                    )

                for edge in patch.get("contradiction_edges", []):
                    tx.run(
                        """MATCH (a:Claim {id: $src}), (b:Claim {id: $dst})
                           CREATE (a)-[:CONTRADICTS {confidence: $conf, created_at: $now}]->(b)""",
                        src=resolve(edge["from"]), dst=resolve(edge["to"]), conf=edge.get("confidence"), now=_now(),
                    )

            session.execute_write(write)

    print(f"patch applied: {created_claims} claims created, {reused_claims} reused, {created_inferences} inferences created")


def _write_representation(tx, claim_id: str, rep: dict, default_paper: str) -> None:
    content = rep["content"]
    modality = rep["modality"]
    embedding = _embed(content, input_type="document") if modality == "nl" else None
    rep_id = _new_id("r")
    tx.run(
        """MATCH (c:Claim {id: $claim_id})
           CREATE (r:Representation {id: $rep_id, modality: $modality, content: $content, content_hash: $hash,
                                      lang_or_system: $los, source_paper: $paper,
                                      confidence: $conf, created_at: $now, embedding: $embedding})-[:OF]->(c)""",
        claim_id=claim_id, rep_id=rep_id, modality=modality, content=content, hash=_content_hash(content),
        los=rep.get("lang_or_system"), paper=rep.get("source_paper", default_paper),
        conf=rep.get("confidence", 0.8), now=_now(), embedding=embedding,
    )
    if rep.get("source_item"):
        tx.run(
            "MATCH (r:Representation {id: $rep_id}), (s:Source {id: $sid}) CREATE (r)-[:GROUNDED_IN]->(s)",
            rep_id=rep_id, sid=rep["source_item"],
        )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")

    np = sub.add_parser("note")
    np.add_argument("--text", required=True)
    np.add_argument("--math")
    np.add_argument("--code")
    np.add_argument("--code-lang")

    pp = sub.add_parser("paper")
    psub = pp.add_subparsers(dest="paper_cmd", required=True)
    ppu = psub.add_parser("upsert")
    ppu.add_argument("--id", required=True)
    ppu.add_argument("--title", required=True)
    ppu.add_argument("--survey", action="store_true")
    pps = psub.add_parser("status")
    pps.add_argument("--id", required=True)
    ppl = psub.add_parser("link")
    ppl.add_argument("--paper", required=True)
    ppl.add_argument("--claim", required=True)
    ppl.add_argument("--relation", required=True, choices=PAPER_RELATIONS)
    ppl.add_argument("--contribution-type", choices=CONTRIBUTION_TYPES)
    ppf = psub.add_parser("flag")
    ppf.add_argument("--id", required=True)
    ppf.add_argument("--review-status", required=True, choices=PAPER_REVIEW_STATUSES)

    cnp = sub.add_parser("canonicalize")
    cnp.add_argument("--text", required=True)
    cnp.add_argument("--math")
    cnp.add_argument("--code", help="Python source, for the AST structural-match tier")
    cnp.add_argument("--top-k", type=int, default=5)

    cp = sub.add_parser("claim")
    csub = cp.add_subparsers(dest="claim_cmd", required=True)
    ccc = csub.add_parser("create")
    ccc.add_argument("--type", required=True, choices=CLAIM_TYPES)
    ccc.add_argument("--status", required=True, choices=STATUSES)
    ccc.add_argument("--domain-tags", default="", help="comma-separated, e.g. 'MSC:11A07,ACM:F.2.2'")
    ccr = csub.add_parser("represent")
    ccr.add_argument("--claim", required=True)
    ccr.add_argument("--modality", required=True, choices=MODALITIES)
    ccr.add_argument("--content", required=True)
    ccr.add_argument("--lang-or-system")
    ccr.add_argument("--paper", required=True)
    ccr.add_argument("--source-item", help="doc_ir.py item id this came from — required for real paper ingestion")
    ccr.add_argument("--confidence", type=float, default=0.8)
    ccl = csub.add_parser("link")
    ccl.add_argument("--type", required=True, choices=EDGE_TYPES)
    ccl.add_argument("--from", dest="src", required=True)
    ccl.add_argument("--to", dest="dst", required=True)
    ccl.add_argument("--confidence", type=float, default=None)
    ccp = csub.add_parser("promote")
    ccp.add_argument("--claim", required=True)

    ip = sub.add_parser("inference")
    isub = ip.add_subparsers(dest="inference_cmd", required=True)
    ic = isub.add_parser("create")
    ic.add_argument("--method", required=True)
    ic.add_argument("--reasoning", required=True)
    ic.add_argument("--paper", required=True)
    iu = isub.add_parser("uses")
    iu.add_argument("--inference", required=True)
    iu.add_argument("--claim", required=True)
    ipr = isub.add_parser("produces")
    ipr.add_argument("--inference", required=True)
    ipr.add_argument("--claim", required=True)

    apy = sub.add_parser("apply-patch", epilog=PATCH_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    apy.add_argument("patch_file")

    shp = sub.add_parser("show")
    shp.add_argument("--claim")
    shp.add_argument("--paper")

    args = p.parse_args()

    if args.cmd == "init":
        init()
    elif args.cmd == "note":
        note(args.text, args.math, args.code, args.code_lang)
    elif args.cmd == "paper":
        if args.paper_cmd == "upsert":
            paper_upsert(args.id, args.title, args.survey)
        elif args.paper_cmd == "status":
            paper_status(args.id)
        elif args.paper_cmd == "link":
            paper_link(args.paper, args.claim, args.relation, args.contribution_type)
        elif args.paper_cmd == "flag":
            paper_flag(args.id, args.review_status)
    elif args.cmd == "canonicalize":
        canonicalize(args.text, args.math, args.top_k, args.code)
    elif args.cmd == "claim":
        if args.claim_cmd == "create":
            tags = [t.strip() for t in args.domain_tags.split(",") if t.strip()]
            claim_create(args.type, args.status, tags)
        elif args.claim_cmd == "represent":
            claim_represent(args.claim, args.modality, args.content, args.lang_or_system,
                             args.paper, args.source_item, args.confidence)
        elif args.claim_cmd == "link":
            claim_link(args.type, args.src, args.dst, args.confidence)
        elif args.claim_cmd == "promote":
            claim_promote(args.claim)
    elif args.cmd == "inference":
        if args.inference_cmd == "create":
            inference_create(args.method, args.reasoning, args.paper)
        elif args.inference_cmd == "uses":
            inference_edge("USES", args.inference, args.claim)
        elif args.inference_cmd == "produces":
            inference_edge("PRODUCES", args.inference, args.claim)
    elif args.cmd == "apply-patch":
        apply_patch(args.patch_file)
    elif args.cmd == "show":
        show(args.claim, args.paper)


if __name__ == "__main__":
    main()
