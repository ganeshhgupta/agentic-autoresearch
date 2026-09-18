"""Workspace knowledge graph: read-only access to the persistent Claim/
Inference graph the agent builds via scripts/kg.py (and the immutable
Source graph from scripts/doc_ir.py, not rendered here — see that module).
One graph for the whole workspace — it spans every conversation and every
ingested paper, never scoped to a single thread. Backed by Neo4j; see
scripts/kg.py for the schema.
"""
from __future__ import annotations

import logging
import os

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

logger = logging.getLogger(__name__)

EMPTY: dict = {"nodes": [], "edges": []}

# Cap what the UI renders — this is a live diagram, not a database export.
NODE_LIMIT = 300
EDGE_LIMIT = 1000


def _driver():
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    if not (uri and user and password):
        return None
    return GraphDatabase.driver(uri, auth=(user, password))


SCHEMA_STATEMENTS = [
    "CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT inference_id IF NOT EXISTS FOR (i:Inference) REQUIRE i.id IS UNIQUE",
    "CREATE CONSTRAINT representation_id IF NOT EXISTS FOR (r:Representation) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT source_id IF NOT EXISTS FOR (s:Source) REQUIRE s.id IS UNIQUE",
    """CREATE VECTOR INDEX representation_embedding IF NOT EXISTS
       FOR (r:Representation) ON (r.embedding)
       OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}""",
]


def init_schema() -> None:
    """Best-effort, idempotent constraint/index setup — run at backend
    startup so scripts/kg.py always has somewhere to write, regardless of
    whether the agent ever runs `kg.py init` itself."""
    driver = _driver()
    if driver is None:
        logger.info("Neo4j not configured (NEO4J_URI/USER/PASSWORD unset) — skipping schema init")
        return
    try:
        with driver:
            with driver.session() as session:
                for stmt in SCHEMA_STATEMENTS:
                    session.run(stmt)
        logger.info("Neo4j schema ready")
    except Neo4jError as e:
        logger.warning("Neo4j schema init failed (will retry on next startup): %s", e)


def read_graph() -> dict:
    driver = _driver()
    if driver is None:
        return EMPTY

    try:
        with driver:
            with driver.session() as session:
                claim_rows = session.run(
                    """
                    MATCH (c:Claim)
                    OPTIONAL MATCH (r:Representation)-[:OF]->(c)
                    WITH c, r ORDER BY r.created_at
                    WITH c, collect(r) AS reps, labels(c) AS labels
                    RETURN c.id AS id, c.claim_type AS claim_type, c.status AS status, labels, reps
                    LIMIT $limit
                    """,
                    limit=NODE_LIMIT,
                ).data()

                nodes = []
                for row in claim_rows:
                    reps = row["reps"]
                    nl = next((r for r in reps if r.get("modality") == "nl"), None)
                    formal = next((r for r in reps if r.get("modality") == "formal"), None)
                    code = next((r for r in reps if r.get("modality") == "code"), None)
                    nodes.append(
                        {
                            "id": row["id"],
                            "kind": "claim",
                            "claim_type": row["claim_type"],
                            "status": row["status"],
                            "scope": "global" if "Global" in row["labels"] else "local",
                            "text": (nl or {}).get("content", "(no NL representation yet)"),
                            "math": (formal or {}).get("content"),
                            "code": (code or {}).get("content"),
                            "code_lang": (code or {}).get("lang_or_system"),
                        }
                    )

                inf_rows = session.run(
                    "MATCH (i:Inference) RETURN i.id AS id, i.method AS method LIMIT $limit",
                    limit=NODE_LIMIT,
                ).data()
                for row in inf_rows:
                    nodes.append({"id": row["id"], "kind": "inference", "text": row["method"]})

                edge_rows = session.run(
                    """
                    MATCH (a)-[e]->(b)
                    WHERE (a:Claim OR a:Inference) AND (b:Claim OR b:Inference)
                    RETURN a.id AS from, b.id AS to, type(e) AS type
                    LIMIT $limit
                    """,
                    limit=EDGE_LIMIT,
                ).data()
                edges = [{"from": r["from"], "to": r["to"], "label": r["type"]} for r in edge_rows]
    except Neo4jError as e:
        logger.warning("failed to read graph from Neo4j: %s", e)
        return EMPTY

    return {"nodes": nodes, "edges": edges}
