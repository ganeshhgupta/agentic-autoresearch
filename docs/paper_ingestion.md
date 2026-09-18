# Paper ingestion

Use this workflow — instead of the general research pipeline in
`docs/pipeline.md` — when the user gives you a specific paper (a PDF, an
arXiv id, a DOI, a pasted paper) and asks you to add it to the knowledge
graph, not just research a question.

Three tools, three layers, in this order:

```
scripts/fetch_paper.py  ->  scripts/doc_ir.py  ->  scripts/kg.py
   (get the source)         (lossless parse:        (semantic layer:
                              Graph A, immutable)     Claims, Inferences,
                                                       Graph B/C)
```

Read `scripts/kg.py`'s module docstring now if you haven't already this
session — it has the full schema and the `apply-patch` JSON format.

## The one rule that matters most

**Never modify or delete an existing Claim, Representation, or Source
item.** Nothing in these three scripts has an update/delete command for
any of them. If a new paper's version of an idea differs from, extends,
or contradicts something already in the graph, that's a new
Representation, or a new Claim plus an edge (`CONTRADICTS`,
`GENERALIZES`, ...), never an edit to what's there. This is what lets the
graph grow from thousands of papers without anyone ever having to go back
and reconcile old entries.

**Never invent a `--source-item`.** Every `claim represent` call for a
real paper must point at a real Graph A item id (`doc_ir.py show --paper
<id>` lists them). No source span, no promotion to the graph — that's
Graph A's whole job: it's the provenance layer everything else is
answerable to.

## Step 0 — decide whether to ingest this paper at all

Skip it (say so, don't ingest) if it's a **survey, review, or summary
paper** — it doesn't contain novel provable claims of its own, only
restatements of others'. Look for it self-describing as a survey/review,
or a structure that's entirely "prior work says X, prior work says Y"
with no new theorem/method/result of the paper's own.

## Step 1 — fetch the source

```
uv run scripts/fetch_paper.py <arxiv-id>
```

Downloads and extracts the LaTeX source into the shared workspace,
prints the path to the main `.tex` file. Idempotent — re-running on an
already-fetched id is a no-op that just reports the existing path. If
the paper isn't on arXiv (a PDF, a DOI-only publisher paper), you don't
have a source-extraction tool for it — read the PDF/text directly and
use judgment about `--source-item` (see Step 2's note on that case).

## Step 2 — build the Document IR (Graph A)

```
uv run scripts/doc_ir.py parse --paper <arxiv-id> --tex <path-from-step-1>
```

Walks the LaTeX into a lossless tree of Section/Paragraph/Equation/
Figure/Table/Algorithm/Theorem-like/Proof/Reference items, each with a
stable id (`<paper>.section4.paragraph2`, `<paper>.eq17`,
`<paper>.theorem1.proof`, ...), and writes it to Neo4j as immutable
`:Source` nodes. This is a parse, not a summary — don't hand-edit or
skip pieces of it. Idempotent per paper (refuses to re-parse a paper
that's already in Graph A).

Inspect it with:
```
uv run scripts/doc_ir.py show --paper <arxiv-id>       # per-kind counts + id list
uv run scripts/doc_ir.py get --id <source-item-id>      # one item's full content
```

If you have no LaTeX source (PDF-only paper), skip this step and note in
your `claim represent` calls that provenance is a page/section
reference rather than a `--source-item` id — this is the degraded path,
not the default.

## Step 3 — walk the paper's atomic units, in order

Prefer papers where Step 2 gives you `\theorem`, `\lemma`, `\definition`,
`\algorithm` items with explicit internal references ("by Lemma 3.2") —
that hands you both the atomic units and the derivation edges almost for
free. Physics-style prose with un-numbered derivations is harder — use
judgment about what counts as one atomic, citable unit; err toward
splitting too fine rather than too coarse (a Claim should be one
independently provable statement, not a whole section).

Register the paper first:
```
uv run scripts/kg.py paper upsert --id <arxiv-id> --title "..."
```
Idempotent — if it's already in the graph, it reports the title and how
many representations are already logged from it.

For each atomic unit:

1. **Extract the NL statement**, tied to its Graph A source item id.

2. **Run it through the canonicalization cascade before creating
   anything new:**
   ```
   uv run scripts/kg.py canonicalize --text "<the NL statement>" [--math "<latex, if applicable>"]
   ```
   This runs structural (exact-hash), symbolic (SymPy, when `--math` is
   given), lexical, and dense-embedding tiers in sequence and prints
   candidates from each, tagged Local or Global. **Embedding-tier
   matches are candidates only — never treat a high embedding score
   alone as grounds to reuse a claim id.** A structural or symbolic exact
   match is safe to reuse automatically; a lexical or embedding match
   needs you to actually read the candidate and judge whether it's the
   same claim, a generalization/specialization of it, or just
   topically related.

3a. **If it's the same claim** — reuse that Claim id. Add this paper's
    version as a new representation, keeping existing ones untouched:
    ```
    uv run scripts/kg.py claim represent --claim <id> --modality nl \
      --content "<this paper's phrasing>" --paper <paper-id> \
      --source-item <graph-a-item-id>
    ```

3b. **If it's new** — create the Claim as Local (scoped to this paper
    until something warrants sharing it), then attach its first
    representation:
    ```
    uv run scripts/kg.py claim create --type theorem --status proven \
      --domain-tags "MSC:11A07"   # or ACM:F.2.2, or a PACS code — whatever fits
    uv run scripts/kg.py claim represent --claim <new-id> --modality nl \
      --content "..." --paper <paper-id> --source-item <graph-a-item-id>
    ```
    `--type` is one of: definition, axiom, theorem, lemma, corollary,
    conjecture, algorithm, empirical-result, construction, note.
    `--status` is one of: proven, conjectured, empirically-supported,
    falsified, asserted.

    Promote it out of Local scope, once it's clearly reusable beyond
    this one paper (cited approvingly elsewhere, restated in a way that
    shows independent value):
    ```
    uv run scripts/kg.py claim promote --claim <id>
    ```
    Don't promote reflexively — an un-promoted Local claim is not a
    failure state, it's the default for anything only this paper needs.

4. **Attach code if the paper ships an algorithm/implementation** for
   this claim:
   ```
   uv run scripts/kg.py claim represent --claim <id> --modality code \
     --content "..." --lang-or-system python --paper <paper-id> \
     --source-item <graph-a-algorithm-item-id>
   ```

5. **Record the derivation as an Inference, not a bare edge.** A proof
   or derivation step is a first-class object with explicit premises,
   never an implied "K1 supports K2":
   ```
   uv run scripts/kg.py inference create --method "apply Lagrange's theorem" \
     --reasoning "the subgroup generated by a has order dividing |G|" --paper <paper-id>
   uv run scripts/kg.py inference uses --inference <inf-id> --claim <premise-1-id>
   uv run scripts/kg.py inference uses --inference <inf-id> --claim <premise-2-id>
   uv run scripts/kg.py inference produces --inference <inf-id> --claim <this-claim-id>
   ```
   Use the **minimal sufficient set of premises** — if the inference
   still holds with one of the premises removed, drop it; don't list
   every claim that happens to be true nearby. One Inference per
   derivation route. Not everything needs one (a foundational
   definition has no premises to record).

6. **Link cross-claim relationships that aren't derivations** where you
   notice them: `EQUIVALENT_TO`, `GENERALIZES`/`SPECIALIZES`,
   `ANALOGOUS_TO` (weak, cross-domain — this is where a CS argument and
   a physics argument can connect), `CONTRADICTS`:
   ```
   uv run scripts/kg.py claim link --type <TYPE> --from <id> --to <id>
   ```

7. **Record the paper's overall relationship to claims it didn't
   originate**, once you've placed its own contributions:
   ```
   uv run scripts/kg.py paper link --paper <paper-id> --claim <id> --relation ASSERTS
   ```
   `--relation` is one of `ASSERTS` (this paper's own claim),
   `USES` (relies on a prior claim without contesting it), `CHALLENGES`
   (disputes or falsifies a prior claim).

## Batch writes: apply-patch

For a paper with many atomic units, it's often cleaner to stage a whole
batch of nodes/edges as one JSON manifest and commit it atomically
instead of issuing dozens of individual commands:
```
uv run scripts/kg.py apply-patch <patch.json>
```
See the `apply-patch` command's `--help` (`PATCH_HELP` in `kg.py`) for
the exact schema — `nodes_to_create`, `nodes_to_reuse`,
`inference_nodes`, `equivalence_edges`, `provenance_links`, and
`contradiction_edges`, with `tmp_id` placeholders for forward references
within the same patch. It validates everything (every referenced claim
id exists or is a `tmp_id` in this patch, every `source_item` exists in
Graph A, every enum value is legal) before writing anything — a
validation failure writes nothing at all, so it's safe to retry after
fixing the reported errors.

## Step 4 — report back

Same as the general pipeline: text output only for substance (say what
you found, cite it), tool calls stay silent. At the end of ingesting a
paper, give a short summary: how many claims were new vs. reused
(deduped) via canonicalization matches, how many were promoted to
Global, and anything notably novel or connected to prior work already in
the graph.
