"""Knowledge graph — the workspace's persistent research graph, backed by
Neo4j. Used both for ordinary research-session note-taking (`note`) and for
decomposing a full paper into atomic claims (see docs/paper_ingestion.md for
that workflow). One graph, shared across every conversation.

Schema (see docs/paper_ingestion.md for the full design rationale):
    (:Claim {id, claim_type, status, domain_tags, created_at})
    (:Representation {id, modality, content, lang_or_system, source_paper,
                       span, confidence, created_at})-[:OF]->(:Claim)
    (:ProofStep {id, proof_route, source_paper, created_at})
    (:Paper {id, title, is_survey, ingested_at})
    (:ProofStep)-[:USES]->(:Claim)          -- a premise
    (:ProofStep)-[:PRODUCES]->(:Claim)      -- the conclusion
    (:Claim)-[:EQUIVALENT_TO|GENERALIZES|SPECIALIZES|ANALOGOUS_TO
              |CONTRADICTS|SUPPORTS|LED_TO|RELATED_TO {confidence?}]->(:Claim)
    (:Paper)-[:CITES]->(:Paper)

There is deliberately no update/delete command for Claim or Representation
content — only create, represent, link, and search. If a paper's claim
contradicts or refines an existing one, add a new Claim/Representation and a
CONTRADICTS/GENERALIZES edge; never edit history.

Usage:
    uv run scripts/kg.py init
    uv run scripts/kg.py note --text "..." [--math "..."] [--code "..." --code-lang py]
    uv run scripts/kg.py paper upsert --id <arxiv-id-or-doi> --title "..." [--survey]
    uv run scripts/kg.py paper status --id <arxiv-id-or-doi>
    uv run scripts/kg.py search --text "..." [--top-k 5]
    uv run scripts/kg.py claim create --type theorem --status proven [--domain-tags "MSC:11A07,ACM:F.2.2"]
    uv run scripts/kg.py claim represent --claim <id> --modality nl --content "..." --paper <paper-id> [--span "..."] [--confidence 0.9]
    uv run scripts/kg.py claim link --type EQUIVALENT_TO --from <id> --to <id> [--confidence 0.8]
    uv run scripts/kg.py proofstep create --route "..." --paper <paper-id>
    uv run scripts/kg.py proofstep uses --proofstep <id> --claim <id>
    uv run scripts/kg.py proofstep produces --proofstep <id> --claim <id>
    uv run scripts/kg.py show --claim <id>
    uv run scripts/kg.py show --paper <id>
"""

import argparse
import os
import secrets
import sys
from datetime import datetime, timezone

import httpx
from neo4j import GraphDatabase

EDGE_TYPES = [
    "EQUIVALENT_TO",
    "GENERALIZES",
    "SPECIALIZES",
    "ANALOGOUS_TO",
    "CONTRADICTS",
    "SUPPORTS",
    "LED_TO",
    "RELATED_TO",
]
CLAIM_TYPES = ["definition", "axiom", "theorem", "lemma", "corollary", "conjecture", "algorithm", "empirical-result", "construction", "note"]
STATUSES = ["proven", "conjectured", "empirically-supported", "falsified", "asserted"]
MODALITIES = ["nl", "formal", "code"]

VOYAGE_MODEL = "voyage-4-large"

GENERAL_RESEARCH_PAPER_ID = "_general-research"  # synthetic Paper for note-taking outside paper ingestion


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


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


def init() -> None:
    statements = [
        "CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.id IS UNIQUE",
        "CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT proofstep_id IF NOT EXISTS FOR (ps:ProofStep) REQUIRE ps.id IS UNIQUE",
        "CREATE CONSTRAINT representation_id IF NOT EXISTS FOR (r:Representation) REQUIRE r.id IS UNIQUE",
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
           RETURN p.title AS title, p.is_survey AS is_survey, count(DISTINCT r) AS representation_count""",
        id=paper_id,
    )
    if not rows or rows[0]["title"] is None:
        print(f"paper {paper_id!r} not yet in the graph")
        return
    row = rows[0]
    print(f"{paper_id!r}: {row['title']}  survey={row['is_survey']}  representations_logged={row['representation_count']}")


def search(text: str, top_k: int) -> None:
    vector = _embed(text, input_type="query")
    rows = _run(
        """MATCH (rep:Representation)
           SEARCH rep IN (VECTOR INDEX representation_embedding FOR $vector LIMIT $k) SCORE AS score
           MATCH (rep)-[:OF]->(c:Claim)
           RETURN c.id AS claim_id, c.claim_type AS claim_type, c.status AS status,
                  rep.content AS content, rep.source_paper AS source_paper, score
           ORDER BY score DESC""",
        k=top_k, vector=vector,
    )
    if not rows:
        print("no candidates found (graph may be empty, or vector index still building)")
        return
    for r in rows:
        print(f"[{r['claim_id']}] score={r['score']:.3f}  ({r['claim_type']}, {r['status']})")
        print(f"    {r['content'][:200]}")
        print(f"    from {r['source_paper']}")


def claim_create(claim_type: str, status: str, domain_tags: list[str]) -> None:
    claim_id = _new_id("c")
    _run(
        """CREATE (c:Claim {id: $id, claim_type: $claim_type, status: $status,
                             domain_tags: $domain_tags, created_at: $now})""",
        id=claim_id, claim_type=claim_type, status=status, domain_tags=domain_tags, now=_now(),
    )
    print(f"created claim {claim_id}")


def claim_represent(claim_id: str, modality: str, content: str, lang_or_system: str | None,
                     source_paper: str, span: str | None, confidence: float) -> None:
    exists = _run("MATCH (c:Claim {id: $id}) RETURN c.id AS id", id=claim_id)
    if not exists:
        print(f"error: no such claim {claim_id}", file=sys.stderr)
        sys.exit(1)

    rep_id = _new_id("r")
    embedding = _embed(content, input_type="document") if modality == "nl" else None
    _run(
        """MATCH (c:Claim {id: $claim_id})
           CREATE (r:Representation {id: $rep_id, modality: $modality, content: $content,
                                      lang_or_system: $lang_or_system, source_paper: $source_paper,
                                      span: $span, confidence: $confidence, created_at: $now,
                                      embedding: $embedding})-[:OF]->(c)""",
        claim_id=claim_id, rep_id=rep_id, modality=modality, content=content,
        lang_or_system=lang_or_system, source_paper=source_paper, span=span,
        confidence=confidence, now=_now(), embedding=embedding,
    )
    print(f"added {modality} representation {rep_id} to claim {claim_id}")


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


def proofstep_create(route: str, source_paper: str) -> None:
    ps_id = _new_id("ps")
    _run(
        "CREATE (ps:ProofStep {id: $id, proof_route: $route, source_paper: $source_paper, created_at: $now})",
        id=ps_id, route=route, source_paper=source_paper, now=_now(),
    )
    print(f"created proof step {ps_id}")


def proofstep_edge(rel: str, ps_id: str, claim_id: str) -> None:
    rows = _run(
        f"""MATCH (ps:ProofStep {{id: $ps_id}}), (c:Claim {{id: $claim_id}})
            CREATE (ps)-[:{rel}]->(c)
            RETURN ps.id AS ps_id""",
        ps_id=ps_id, claim_id=claim_id,
    )
    if not rows:
        print("error: proof step or claim not found", file=sys.stderr)
        sys.exit(1)
    print(f"{ps_id} -{rel}-> {claim_id}")


def note(text: str, math: str | None, code: str | None, code_lang: str | None) -> None:
    """Convenience wrapper for ordinary research-session logging (not paper
    ingestion): one claim, one or more representations, attributed to a
    synthetic general-research 'paper' rather than a real source."""
    _run(
        "MERGE (p:Paper {id: $id}) ON CREATE SET p.title = 'General research notes', p.is_survey = false, p.ingested_at = $now",
        id=GENERAL_RESEARCH_PAPER_ID, now=_now(),
    )
    claim_id = _new_id("c")
    _run(
        "CREATE (c:Claim {id: $id, claim_type: 'note', status: 'asserted', domain_tags: [], created_at: $now})",
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
               RETURN c.claim_type AS claim_type, c.status AS status, c.domain_tags AS domain_tags,
                      collect({modality: r.modality, content: r.content, source_paper: r.source_paper}) AS reps""",
            id=claim_id,
        )
        if not rows or rows[0]["claim_type"] is None:
            print(f"no such claim {claim_id}")
            return
        row = rows[0]
        print(f"[{claim_id}] {row['claim_type']} / {row['status']}  tags={row['domain_tags']}")
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

    sp = sub.add_parser("search")
    sp.add_argument("--text", required=True)
    sp.add_argument("--top-k", type=int, default=5)

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
    ccr.add_argument("--span")
    ccr.add_argument("--confidence", type=float, default=0.8)
    ccl = csub.add_parser("link")
    ccl.add_argument("--type", required=True, choices=EDGE_TYPES)
    ccl.add_argument("--from", dest="src", required=True)
    ccl.add_argument("--to", dest="dst", required=True)
    ccl.add_argument("--confidence", type=float, default=None)

    pfp = sub.add_parser("proofstep")
    pfsub = pfp.add_subparsers(dest="proofstep_cmd", required=True)
    pfc = pfsub.add_parser("create")
    pfc.add_argument("--route", required=True)
    pfc.add_argument("--paper", required=True)
    pfu = pfsub.add_parser("uses")
    pfu.add_argument("--proofstep", required=True)
    pfu.add_argument("--claim", required=True)
    pfpr = pfsub.add_parser("produces")
    pfpr.add_argument("--proofstep", required=True)
    pfpr.add_argument("--claim", required=True)

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
    elif args.cmd == "search":
        search(args.text, args.top_k)
    elif args.cmd == "claim":
        if args.claim_cmd == "create":
            tags = [t.strip() for t in args.domain_tags.split(",") if t.strip()]
            claim_create(args.type, args.status, tags)
        elif args.claim_cmd == "represent":
            claim_represent(args.claim, args.modality, args.content, args.lang_or_system,
                             args.paper, args.span, args.confidence)
        elif args.claim_cmd == "link":
            claim_link(args.type, args.src, args.dst, args.confidence)
    elif args.cmd == "proofstep":
        if args.proofstep_cmd == "create":
            proofstep_create(args.route, args.paper)
        elif args.proofstep_cmd == "uses":
            proofstep_edge("USES", args.proofstep, args.claim)
        elif args.proofstep_cmd == "produces":
            proofstep_edge("PRODUCES", args.proofstep, args.claim)
    elif args.cmd == "show":
        show(args.claim, args.paper)


if __name__ == "__main__":
    main()
