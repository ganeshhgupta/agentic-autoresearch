# Research sources

Each source is a script in `scripts/`. Run with `uv run scripts/<name>.py <args>`.
Run `uv run scripts/test_connection.py` any time a connector seems broken.

| Script | Source | Good for | Key needed |
|---|---|---|---|
| `openalex.py` | OpenAlex | Broad scholarly search, citation graph (`citations`/`references`), topics | No |
| `semantic_scholar.py` | Semantic Scholar | Citation/reference graph, `recommend` for "papers like this one" | No (optional, for rate limit) |
| `crossref.py` | Crossref | DOI metadata, publisher/funder info, resolving a DOI to canonical metadata | No |
| `arxiv.py` | arXiv | Latest CS/AI/math/physics preprints, often ahead of formal publication | No |
| `core.py` | CORE | Full open-access text, not just abstracts | Yes — `CORE_API_KEY` |
| `openaire.py` | OpenAIRE | Research products linked to datasets, software, and funded projects | No |
| `web_search.py` | Web (DuckDuckGo) | Blog posts, lab pages, company research, docs, talks — anything not indexed as a formal paper | No |

## When to use which

- Start broad: `openalex.py search` or `semantic_scholar.py search` for an overview of a topic.
- Trace a citation graph: `openalex.py citations/references` or `semantic_scholar.py citations/references` on a specific paper's id, to see what it built on and what built on it.
- Need the DOI's canonical metadata (funder, publisher, retraction status): `crossref.py get <doi>`.
- Need the newest work, possibly not peer-reviewed yet: `arxiv.py search`.
- Need to actually read the paper, not just the abstract: `core.py search` (full text) or check `full_text` / `openAccessPdf` fields returned by the other connectors.
- Need what's adjacent to the literature — implementations, funded-but-unpublished work, informal writeups: `openaire.py` (datasets/software/grants) and `web_search.py` (everything else).

## Combining sources for citation-graph reasoning

A single paper found via one connector can be cross-referenced in others:

1. Find a candidate paper (`openalex.py search` or `semantic_scholar.py search`).
2. Pull its DOI, then check `crossref.py get <doi>` for funder/publisher context.
3. Walk its citation graph both directions (`citations` = who built on it, `references` = what it built on) via `openalex.py` or `semantic_scholar.py`.
4. Check `semantic_scholar.py recommend <paper_id>` for papers Semantic Scholar's embedding model considers similar — useful for surfacing adjacent-domain work that citation links alone would miss.
5. Check `openaire.py search` for linked datasets/software/grants.
6. Check `web_search.py` for non-paper material (blog writeups, GitHub discussion, criticism).

See `docs/pipeline.md` for how this feeds into the full reasoning process.
