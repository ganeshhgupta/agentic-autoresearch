"""Workspace knowledge graph — one persistent graph for the whole workspace
(not per-conversation) that keeps growing as research progresses. Each node
is one atomic fact/claim, optionally with a formal statement (math) and/or
code. Edges record the causal/logical chain between nodes (what led to,
supports, contradicts, or refines what) — this is what the app's Graph tab
visualizes live.

Add a node for anything worth keeping as a standalone claim: a finding from
a source, a hypothesis, a falsification result, a synthesis conclusion.
Then link it to whatever node(s) it followed from — a graph with no edges is
just a pile of facts, not a causal chain.

Usage:
    uv run scripts/graph.py add-node --text "..." [--math "..."] [--code "..."] [--code-lang "python"]
    uv run scripts/graph.py add-edge --from n1 --to n2 [--label "supports"]
    uv run scripts/graph.py show
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("SHARED_ROOT", "/shared"))
GRAPH_FILE = ROOT / "graph.json"


def _load() -> dict:
    if not GRAPH_FILE.is_file():
        return {"nodes": [], "edges": []}
    try:
        data = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"error: {GRAPH_FILE} contains invalid JSON, refusing to overwrite it", file=sys.stderr)
        sys.exit(1)
    return {"nodes": data.get("nodes", []), "edges": data.get("edges", [])}


def _save(data: dict) -> None:
    GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = GRAPH_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(GRAPH_FILE)


def _next_id(nodes: list[dict]) -> str:
    existing = {n["id"] for n in nodes}
    i = len(nodes) + 1
    while f"n{i}" in existing:
        i += 1
    return f"n{i}"


def add_node(text: str, math: str | None, code: str | None, code_lang: str | None) -> None:
    data = _load()
    node_id = _next_id(data["nodes"])
    node = {"id": node_id, "text": text}
    if math:
        node["math"] = math
    if code:
        node["code"] = code
        node["code_lang"] = code_lang or ""
    data["nodes"].append(node)
    _save(data)
    print(f"created node {node_id}")


def add_edge(src: str, dst: str, label: str | None) -> None:
    data = _load()
    ids = {n["id"] for n in data["nodes"]}
    if src not in ids:
        print(f"error: no such node {src}", file=sys.stderr)
        sys.exit(1)
    if dst not in ids:
        print(f"error: no such node {dst}", file=sys.stderr)
        sys.exit(1)
    edge = {"from": src, "to": dst}
    if label:
        edge["label"] = label
    data["edges"].append(edge)
    _save(data)
    print(f"linked {src} -> {dst}" + (f" ({label})" if label else ""))


def show() -> None:
    data = _load()
    if not data["nodes"]:
        print("graph is empty")
        return
    print(f"{len(data['nodes'])} nodes, {len(data['edges'])} edges\n")
    for n in data["nodes"]:
        print(f"[{n['id']}] {n['text']}")
        if n.get("math"):
            print(f"    math: {n['math']}")
        if n.get("code"):
            print(f"    code ({n.get('code_lang') or 'text'}): {n['code'][:80]}")
    if data["edges"]:
        print("\nedges:")
        for e in data["edges"]:
            label = f" ({e['label']})" if e.get("label") else ""
            print(f"  {e['from']} -> {e['to']}{label}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    np = sub.add_parser("add-node")
    np.add_argument("--text", required=True)
    np.add_argument("--math")
    np.add_argument("--code")
    np.add_argument("--code-lang")

    ep = sub.add_parser("add-edge")
    ep.add_argument("--from", dest="src", required=True)
    ep.add_argument("--to", dest="dst", required=True)
    ep.add_argument("--label")

    sub.add_parser("show")

    args = p.parse_args()
    if args.cmd == "add-node":
        add_node(args.text, args.math, args.code, args.code_lang)
    elif args.cmd == "add-edge":
        add_edge(args.src, args.dst, args.label)
    elif args.cmd == "show":
        show()


if __name__ == "__main__":
    main()
