"""Workspace knowledge graph: read-only access to the persistent nodes+edges
the agent builds via scripts/graph.py. One graph for the whole workspace —
it spans every conversation, never scoped to a single thread.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(os.environ.get("SHARED_ROOT", "/shared"))
GRAPH_FILE = ROOT / "graph.json"


def read_graph() -> dict:
    if not GRAPH_FILE.is_file():
        return {"nodes": [], "edges": []}
    try:
        data = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("failed to read %s: %s", GRAPH_FILE, e)
        return {"nodes": [], "edges": []}
    return {"nodes": data.get("nodes", []), "edges": data.get("edges", [])}
