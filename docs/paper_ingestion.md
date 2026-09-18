# Paper ingestion

Use this workflow — instead of the general research pipeline in
`docs/pipeline.md` — when the user gives you a specific paper (a PDF, an
arXiv id, a DOI, a pasted paper) and asks you to add it to the knowledge
graph, not just research a question. Tool: `scripts/kg.py` (see its
docstring for the full schema and command reference). Read that docstring
now if you haven't already this session.

## The one rule that matters most

**Never modify or delete an existing Claim or Representation.** `kg.py`
has no update/delete command for either — only `create`, `represent`, and
`link`. If a new paper's version of an idea differs from, extends, or
contradicts something already in the graph, that's a new Representation
or a new Claim plus an edge (`CONTRADICTS`, `GENERALIZES`, ...), never an
edit to what's there. This is what lets the graph grow from thousands of
papers without anyone ever having to go back and reconcile old entries.

## Step 1 — decide whether to ingest this paper at all

Skip it (say so, don't ingest) if it's a **survey, review, or summary
paper** — it doesn't contain novel provable claims of its own, only
restatements of others'. Look for it self-describing as a survey/review,
or a structure that's entirely "prior work says X, prior work says Y"
with no new theorem/method/result of the paper's own.

Otherwise:

```
uv run scripts/kg.py paper upsert --id <arxiv-id-or-doi> --title "..."
```

This is idempotent — if the paper's already in the graph, it tells you
its title and how many representations are already logged from it. If
it's already fully ingested, don't repeat the work; if partially, pick up
wherever it stops making sense to assume you left off (there's no
in-progress marker, so use judgment — check `show --paper <id>`).

## Step 2 — walk the paper's atomic units, in order

Prefer papers where this is easy: LaTeX `\theorem`, `\lemma`, `\definition`,
`\algorithm` environments with explicit internal references ("by Lemma
3.2") hand you both the atomic units and the derivation edges almost for
free. Physics-style prose with un-numbered derivations is harder — use
judgment about what counts as one atomic, citable unit; err toward
splitting too fine rather than too coarse (a Claim should be one provable
statement, not a whole section).

For each atomic unit:

1. **Extract the NL statement.**

2. **Search for an existing match before creating anything new:**
   ```
   uv run scripts/kg.py search --text "<the NL statement>"
   ```
   This embeds your text and returns the closest existing Claims with a
   similarity score. Use judgment on the threshold — a score that reads as
   "this is clearly the same idea, just phrased differently" means reuse
   the existing claim id; don't hard-code a fixed number in your head as
   gospel, look at the actual returned content and decide. A same-topic-
   but-different-claim result is not a match.

3a. **If it's a match** — reuse that Claim id. Just add this paper's
    version as a new representation, keeping the existing ones untouched:
    ```
    uv run scripts/kg.py claim represent --claim <id> --modality nl \
      --content "<this paper's phrasing>" --paper <paper-id> [--span "Thm 2.3"]
    ```

3b. **If it's new** — create the Claim, then attach its first representation:
    ```
    uv run scripts/kg.py claim create --type theorem --status proven \
      --domain-tags "MSC:11A07"   # or ACM:F.2.2, or a PACS code — whatever fits
    uv run scripts/kg.py claim represent --claim <new-id> --modality nl \
      --content "..." --paper <paper-id> --span "Thm 2.3"
    ```
    `--type` is one of: definition, axiom, theorem, lemma, corollary,
    conjecture, algorithm, empirical-result, construction, note.
    `--status` is one of: proven, conjectured, empirically-supported,
    falsified, asserted.

4. **Attempt a formal representation when it's a precise mathematical
   claim.** Try stating it in Lean (`scripts/lean.py new` + `check`,
   against Mathlib). If it typechecks, attach it:
   ```
   uv run scripts/kg.py claim represent --claim <id> --modality formal \
     --content "<lean statement>" --lang-or-system lean4 --paper <paper-id>
   ```
   This is genuinely hard and often won't succeed — that's expected (see
   `docs/pipeline.md`'s falsification-stage note on autoformalization
   being unreliable). Don't force it; a claim with only an NL
   representation is still a valid, useful node.

5. **Attach code if the paper ships an algorithm/implementation** for
   this claim:
   ```
   uv run scripts/kg.py claim represent --claim <id> --modality code \
     --content "..." --lang-or-system python --paper <paper-id>
   ```

6. **Record the derivation.** If this claim's proof in this paper used
   one or more prior claims (from this paper or elsewhere in the graph —
   check via `search` or by having ingested them earlier in this same
   session), create a ProofStep and link it:
   ```
   uv run scripts/kg.py proofstep create --route "apply Lagrange's theorem to the subgroup generated by a" --paper <paper-id>
   uv run scripts/kg.py proofstep uses --proofstep <ps-id> --claim <premise-1-id>
   uv run scripts/kg.py proofstep uses --proofstep <ps-id> --claim <premise-2-id>
   uv run scripts/kg.py proofstep produces --proofstep <ps-id> --claim <this-claim-id>
   ```
   One ProofStep per derivation route. If a claim has no clear premises
   in the graph yet (e.g. it's a foundational definition), skip this step
   for it — not everything needs a ProofStep.

7. **Link cross-claim relationships that aren't derivations** where you
   notice them: `EQUIVALENT_TO`, `GENERALIZES`/`SPECIALIZES`,
   `ANALOGOUS_TO` (weak, cross-domain — this is where a CS argument and a
   physics argument can connect), `CONTRADICTS`. Use `claim link --type
   <TYPE> --from <id> --to <id>`.

## Step 3 — report back

Same as the general pipeline: text output only for substance (say what
you found, cite it), tool calls stay silent. At the end of ingesting a
paper, give a short summary: how many claims were new vs. reused
(deduped) via existing-node matches, and anything notably novel or
connected to prior work already in the graph.
