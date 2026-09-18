"""Document IR — a lossless structural parse of a paper's LaTeX source into
Graph A (the Source graph): Section/Paragraph/Equation/Figure/Table/
Algorithm/Theorem-like-environments/Proof/Reference, each with a stable ID
and its exact verbatim source text preserved. This is deliberately NOT a
summary and NOT semantic extraction (see scripts/kg.py for that layer) —
every item's `content` is the raw source text, unedited.

IDs look like: paper123.section4.paragraph2, paper123.eq17, paper123.figure3,
paper123.theorem1, paper123.theorem1.proof, paper123.reference1

Source items are immutable once written — there is no update command. Run
scripts/fetch_paper.py first to get LaTeX source to parse.

Usage:
    uv run scripts/doc_ir.py parse --paper <arxiv-id> --tex <path/to/main.tex>
    uv run scripts/doc_ir.py show --paper <arxiv-id>
    uv run scripts/doc_ir.py get --id <source-item-id>
"""

import argparse
import os
import re
import sys
from pathlib import Path

from neo4j import GraphDatabase
from pylatexenc.latexwalker import (
    LatexCharsNode,
    LatexEnvironmentNode,
    LatexGroupNode,
    LatexMacroNode,
    LatexWalker,
)

THEOREM_LIKE = {
    "theorem", "lemma", "corollary", "proposition", "definition",
    "conjecture", "claim", "assumption", "axiom", "example", "remark",
}
EQUATION_ENVS = {"equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*"}
FIGURE_ENVS = {"figure", "figure*"}
TABLE_ENVS = {"table", "table*"}
ALGORITHM_ENVS = {"algorithm", "algorithmic"}
SECTION_MACROS = {"section", "section*"}


def _driver():
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    if not (uri and user and password):
        print("error: NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD must all be set", file=sys.stderr)
        sys.exit(1)
    return GraphDatabase.driver(uri, auth=(user, password))


class DocIRBuilder:
    def __init__(self, paper_id: str):
        self.paper_id = paper_id
        self.items: list[dict] = []
        self._order = 0
        self._section_num = 0
        self._current_section_id: str | None = None
        self._paragraph_num = 0
        self._eq_num = 0
        self._figure_num = 0
        self._table_num = 0
        self._algorithm_num = 0
        self._kind_counters: dict[str, int] = {}
        self._reference_num = 0
        self._last_theorem_id: str | None = None
        self._used_ids: set[str] = set()

    def _dedupe_id(self, item_id: str) -> str:
        """Heuristics (e.g. 'attach this proof to the last theorem-like item')
        can collide — e.g. two proofs both landing on the same parent when an
        intervening remark/corollary has no proof of its own. Guarantee
        uniqueness rather than silently overwriting/losing an item."""
        if item_id not in self._used_ids:
            self._used_ids.add(item_id)
            return item_id
        n = 2
        while f"{item_id}{n}" in self._used_ids:
            n += 1
        deduped = f"{item_id}{n}"
        self._used_ids.add(deduped)
        return deduped

    def _add(self, kind: str, content: str, parent_id: str | None) -> str:
        if kind == "section":
            self._section_num += 1
            item_id = f"{self.paper_id}.section{self._section_num}"
        elif kind == "paragraph":
            item_id = f"{parent_id}.paragraph{self._paragraph_num}"
        elif kind == "equation":
            self._eq_num += 1
            item_id = f"{self.paper_id}.eq{self._eq_num}"
        elif kind == "figure":
            self._figure_num += 1
            item_id = f"{self.paper_id}.figure{self._figure_num}"
        elif kind == "table":
            self._table_num += 1
            item_id = f"{self.paper_id}.table{self._table_num}"
        elif kind == "algorithm":
            self._algorithm_num += 1
            item_id = f"{self.paper_id}.algorithm{self._algorithm_num}"
        elif kind == "proof":
            item_id = f"{parent_id}.proof"
        elif kind == "reference":
            self._reference_num += 1
            item_id = f"{self.paper_id}.reference{self._reference_num}"
        elif kind == "abstract":
            item_id = f"{self.paper_id}.abstract"
        elif kind in THEOREM_LIKE:
            self._kind_counters[kind] = self._kind_counters.get(kind, 0) + 1
            item_id = f"{self.paper_id}.{kind}{self._kind_counters[kind]}"
        else:
            item_id = f"{self.paper_id}.{kind}{len(self.items)}"

        item_id = self._dedupe_id(item_id)
        self._order += 1
        self.items.append(
            {"id": item_id, "kind": kind, "content": content, "parent_id": parent_id, "order": self._order}
        )
        return item_id

    def add_paragraph_text(self, text: str) -> None:
        for para in re.split(r"\n\s*\n", text):
            para = para.strip()
            if len(para) < 5:
                continue
            self._paragraph_num += 1
            parent = self._current_section_id or self.paper_id
            self._add("paragraph", para, parent)

    def walk(self, nodelist) -> None:
        i = 0
        while i < len(nodelist):
            n = nodelist[i]
            if isinstance(n, LatexMacroNode) and n.macroname in SECTION_MACROS:
                title = ""
                if n.nodeargd and n.nodeargd.argnlist:
                    last = n.nodeargd.argnlist[-1]
                    if isinstance(last, LatexGroupNode):
                        title = "".join(c.latex_verbatim() for c in last.nodelist)
                self._current_section_id = self._add("section", title.strip(), None)
                self._paragraph_num = 0

            elif isinstance(n, LatexEnvironmentNode):
                env = n.environmentname
                body = "".join(c.latex_verbatim() for c in n.nodelist)
                if env in EQUATION_ENVS:
                    self._add("equation", n.latex_verbatim(), self._current_section_id)
                elif env in FIGURE_ENVS:
                    self._add("figure", n.latex_verbatim(), self._current_section_id)
                elif env in TABLE_ENVS:
                    self._add("table", n.latex_verbatim(), self._current_section_id)
                elif env in ALGORITHM_ENVS:
                    self._add("algorithm", n.latex_verbatim(), self._current_section_id)
                elif env in THEOREM_LIKE:
                    self._last_theorem_id = self._add(env, body.strip(), self._current_section_id)
                elif env == "proof":
                    if self._last_theorem_id:
                        self._add("proof", body.strip(), self._last_theorem_id)
                    else:
                        self._add("proof", body.strip(), self._current_section_id)
                elif env == "abstract":
                    self._add("abstract", body.strip(), None)
                elif env == "thebibliography":
                    self._walk_bibliography(n.nodelist)
                elif env == "document":
                    self.walk(n.nodelist)
                else:
                    # Unknown environment: recurse so its content isn't lost.
                    self.walk(n.nodelist)

            elif isinstance(n, LatexCharsNode):
                self.add_paragraph_text(n.chars)

            # Inline macros/math nodes inside running text are captured as
            # part of the surrounding LatexCharsNode's verbatim text via
            # the raw source slice, not walked individually — see parse().

            i += 1

    def _walk_bibliography(self, nodelist) -> None:
        for n in nodelist:
            if isinstance(n, LatexMacroNode) and n.macroname == "bibitem":
                self._add("reference", n.latex_verbatim(), None)


def _document_body(nodes) -> list:
    """Everything before \\begin{document} is preamble (macro definitions,
    \\newtheorem declarations, packages) — walking it produces garbage
    pseudo-paragraphs from macro arguments. Only the document environment's
    contents are real paper text."""
    for n in nodes:
        if isinstance(n, LatexEnvironmentNode) and n.environmentname == "document":
            return n.nodelist
    return nodes  # no \begin{document} found (e.g. a fragment) — walk everything


def parse(paper_id: str, tex_path: str) -> None:
    text = Path(tex_path).read_text(encoding="utf-8", errors="ignore")
    walker = LatexWalker(text)
    nodes, _, _ = walker.get_latex_nodes()

    builder = DocIRBuilder(paper_id)
    builder.walk(_document_body(nodes))

    if not builder.items:
        print("error: parsed zero items — is this a valid LaTeX file?", file=sys.stderr)
        sys.exit(1)

    driver = _driver()
    with driver:
        with driver.session() as session:
            existing = session.run(
                "MATCH (s:Source {paper_id: $paper_id}) RETURN count(s) AS c", paper_id=paper_id
            ).single()["c"]
            if existing:
                print(
                    f"error: {existing} Source items already exist for paper {paper_id!r} — "
                    "the source graph is immutable, refusing to add a possibly-duplicate parse. "
                    "Use `show --paper` to inspect what's there.",
                    file=sys.stderr,
                )
                sys.exit(1)

            def write(tx):
                for item in builder.items:
                    tx.run(
                        """CREATE (s:Source {id: $id, paper_id: $paper_id, kind: $kind,
                                              content: $content, parent_id: $parent_id, order: $order})""",
                        id=item["id"], paper_id=paper_id, kind=item["kind"],
                        content=item["content"], parent_id=item["parent_id"], order=item["order"],
                    )
                for item in builder.items:
                    if item["parent_id"]:
                        tx.run(
                            """MATCH (p:Source {id: $parent_id}), (c:Source {id: $id})
                               CREATE (p)-[:CONTAINS]->(c)""",
                            parent_id=item["parent_id"], id=item["id"],
                        )

            session.execute_write(write)

    print(f"parsed {len(builder.items)} source items for {paper_id!r}")
    kinds: dict[str, int] = {}
    for item in builder.items:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    for k, n in sorted(kinds.items()):
        print(f"  {k}: {n}")


def show(paper_id: str) -> None:
    driver = _driver()
    with driver:
        with driver.session() as session:
            rows = session.run(
                "MATCH (s:Source {paper_id: $paper_id}) RETURN s.id AS id, s.kind AS kind, s.content AS content ORDER BY s.order",
                paper_id=paper_id,
            ).data()
    if not rows:
        print(f"no source items for paper {paper_id!r} — run `parse` first")
        return
    for r in rows:
        preview = r["content"].replace("\n", " ")[:80]
        print(f"[{r['id']}] ({r['kind']}) {preview}")


def get(item_id: str) -> None:
    driver = _driver()
    with driver:
        with driver.session() as session:
            row = session.run("MATCH (s:Source {id: $id}) RETURN s.kind AS kind, s.content AS content", id=item_id).single()
    if not row:
        print(f"no such source item {item_id!r}", file=sys.stderr)
        sys.exit(1)
    print(f"({row['kind']})")
    print(row["content"])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("parse")
    pp.add_argument("--paper", required=True)
    pp.add_argument("--tex", required=True)

    sp = sub.add_parser("show")
    sp.add_argument("--paper", required=True)

    gp = sub.add_parser("get")
    gp.add_argument("--id", required=True)

    args = p.parse_args()
    if args.cmd == "parse":
        parse(args.paper, args.tex)
    elif args.cmd == "show":
        show(args.paper)
    elif args.cmd == "get":
        get(args.id)


if __name__ == "__main__":
    main()
