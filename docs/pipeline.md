# Research reasoning pipeline

The agent's job is not "search then summarize" — it's to move a research
question through these stages, in order, using the connectors in
`docs/research_sources.md`. Do all of this within one response; there is no
separate sub-agent per stage, this is a checklist for a single agent's
process.

```
research question
      |
      v
1. DECOMPOSE     -- break the question into sub-questions worth
      |              searching separately (a vague question produces
      |              vague search results)
      v
2. EXPLORE       -- run searches across sources: literature (OpenAlex,
      |              Semantic Scholar, Crossref, arXiv, CORE), and
      |              adjacent material (OpenAIRE datasets/software/grants,
      |              web search for blogs/labs/implementations)
      v
3. MAP THE GRAPH -- for the papers that matter, walk citations and
      |              references to see what they build on and what
      |              builds on them; note the shape (a cluster? a
      |              stalled line of work? one paper everything cites?)
      v
4. FIND GAPS     -- look for: contradictions between papers, a method
      |              from one subfield never applied to another, a
      |              question the field asks but nobody has answered,
      |              a citation cluster that stopped growing
      v
5. DRAW ANALOGIES -- ask whether a concept from a distant field (control
      |               theory, evolutionary optimization, a different
      |               application domain) reframes the gap usefully
      v
6. FORM A          -- state a candidate hypothesis or insight precisely
   HYPOTHESIS         enough that it could be wrong
      |
      v
7. CHECK NOVELTY -- aggressively search (all sources, not just one) for
      |              prior art. If someone already did this, say so and
      |              cite it — don't present it as novel anyway
      v
8. TRY TO         -- actively look for the strongest reason the
   FALSIFY IT        hypothesis fails or already has a known
      |              counterexample. If the hypothesis is a precise
      |              mathematical/logical claim (not just an empirical
      |              one), state it formally in Lean and typecheck it
      |              with `uv run scripts/lean.py` — see below
      v
9. FILTER BY      -- would anyone act on this insight if it's true?
   USEFULNESS        If not, it's an observation, not a finding
      |
      v
10. SYNTHESIZE   -- report findings with citations, labeled by
                     confidence. For anything substantial, also write it
                     up as `latex/<name>.tex` (see below) so the user has
                     a document, not just a chat reply
```

## Formal verification with Lean (stage 8)

`scripts/lean.py` typechecks a `.lean` file against the full Mathlib
library — a much stronger check than prose reasoning for anything that
reduces to a precise mathematical or logical claim:

```
uv run scripts/lean.py new  <path/to/claim.lean>   # scaffold with `import Mathlib`
uv run scripts/lean.py check <path/to/claim.lean>  # typecheck against Mathlib
```

This doesn't replace the novelty check (stage 7) — a hypothesis can be true
and still already published. Use it to catch hypotheses that are simply
*wrong*, which is a faster and more certain kill than searching for a
counterexample in prose.

## Writing up findings (stage 10)

For anything worth keeping, write it as `latex/<name>.tex` in the workspace
(create the `latex/` folder if it doesn't exist) and compile it directly with
Bash: `tectonic latex/<name>.tex`. Report both the LaTeX source path and
whether it compiled cleanly. Files under `latex/` are also visible in the
app's LaTeX editor panel, so the user can keep refining the writeup after
your turn ends.

## The hierarchy to respect

Do not present things at the wrong level:

```
interesting observation
        |
        v  (is it actually missing from the literature?)
research gap
        |
        v  (is there a specific claim, not just "more work needed"?)
novel hypothesis
        |
        v  (survives an active attempt to falsify it?)
novel + plausible hypothesis
        |
        v  (would it matter to anyone if true?)
novel + plausible + useful hypothesis   <- only this tier gets reported
                                            as a "finding"
```

Everything above the bottom tier can still be shared, but must be labeled for
what it is (e.g. "open question, unconfirmed" not "we found that...").

## Hard rules

- **Always cite sources.** Every claim, paper reference, or hypothesis
  grounded in existing work must link back to what it came from (title +
  DOI/arXiv id/URL). Never state a fact about the literature without a
  source.
- **Novelty check is mandatory.** Never present a hypothesis without having
  searched for prior art on it first (stage 7). If you skip this because of
  time/tool limits, say so explicitly rather than silently omitting it.
- **Be conservative about claims.** Label speculative ideas as speculative.
  Never state an unconfirmed hypothesis as settled fact. When evidence is
  mixed or thin, say so rather than rounding up to a confident answer.
