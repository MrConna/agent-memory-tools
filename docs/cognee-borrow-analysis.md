# cognee → agent-memory-tools: what we borrowed

Study of [topoteretes/cognee](https://github.com/topoteretes/cognee) and what applies here.

## What cognee is

A memory framework for agents whose core move is turning data into a **knowledge
graph**. Pipeline is Extract → **Cognify** (an LLM extracts `(entity)-[relation]->(entity)`
triples) → Load into a graph DB + vector DB + relational store (now unified on
Postgres/pgvector; Neo4j/Kuzu/Qdrant pluggable). Retrieval (`recall`) auto-routes
between vector similarity and **graph traversal**, optionally grounded by an ontology.

Its one genuine differentiator over plain vector RAG is **relationship-aware
retrieval**: follow edges to related nodes instead of only ranking isolated hits.
Everything else (persistence, cross-session, vector search) this project already had.

## What this project already covered

| cognee capability | here |
|---|---|
| Vector semantic search | `search.py` (FTS5 BM25 + sentence-transformers, rank fusion); `brain.py` cross-project |
| Persistent / cross-session memory | `learnings.jsonl` + `context` + `session bind` |
| Ingest sources → knowledge pages | `wiki add-source` / `add-page` with staleness tracking |
| Optional LLM, graceful degrade | `local_model.py` |

## The gap cognee exposed

All entries (memory / wiki / entity / concept / progress / pattern) were **flat
nodes** in the search index with no edges between them. Retrieval ranked; it never
followed relationships. That is precisely cognee's reason to exist.

## What we borrowed (shipped)

A lightweight, file-based graph layer — cognee's idea, this project's constraints
(one JSONL, no graph DB, no mandatory LLM):

- **`memory/edges.jsonl`** — directed edges
  `{from, to, relation, note, created_at, external_nodes}`. `external_nodes`
  records endpoints explicitly accepted via `--force`, so cleanup never mistakes
  an intentional external reference for abandoned data.
  Nodes reuse the ids the search index already assigns (`memory:<id>`,
  `knowledge:<path>`, `entity:<name>`, …).
- **`graph.py` / `bin/graph`** — `link`, `unlink`, `neighbors`, `list`, `nodes`,
  `relations`. Edge keys are validated against the live index (trust boundary);
  `--force` overrides.
- **Ontology-lite** — a controlled relation vocabulary: `relates-to`, `depends-on`,
  `implements`, `contradicts`, `supersedes`. This is cognee's ontology grounding,
  shrunk to a validated enum.
- **Graph-completion retrieval** — `search query --expand N` appends the N-hop
  neighbors of each hit, returning a connected subgraph. Neighbors are annotated
  with the relation and source node that pulled them in.

`supersedes` / `contradicts` double as memory hygiene: a newer learning can point
at the one it replaces, which is more expressive than the existing boolean `stale`
flag.

- **`graph doctor` (edge-driven memory hygiene)** — audits the graph for three
  issues and fixes the safe ones with `--fix`. All mutations use shared locks,
  strict JSONL validation, and atomic replacement:
  - *dangling edges* (endpoint no longer in the index) → removed;
  - *superseded-but-active* learnings (target of a `supersedes` edge, not yet
    `stale`) → marked `stale`, so they drop out of default recall;
  - *contradictions* (`contradicts` edges) → surfaced for human review (advisory).
  Legacy edges with unknown endpoints but no `external_nodes` declaration are
  reported as ambiguous and never automatically deleted.
  Exits non-zero when actionable issues remain, so it works as a CI/pre-commit check.

## What we deliberately did NOT borrow

- ❌ Postgres / pgvector / Neo4j / Kuzu backends — this project is intentionally
  file + sqlite, zero-infrastructure.
- ❌ A mandatory LLM `cognify` extraction pipeline — kept edges explicit/manual for
  now. Auto-extracting triples on ingest via `local_model` is a viable *optional*
  follow-up, but must degrade gracefully, never block.
- ❌ Async API surface (`await cognee.recall()`) — not this project's runtime model.

## Possible follow-ups

1. ~~self-review consuming `supersedes` / `contradicts` edges for dedup~~ — shipped
   as `graph doctor` (see above).
2. Optional `cognify-lite`: `wiki add-source` extracts entity/relation triples with
   `local_model`, auto-creating `wiki/entities/` pages + edges (off by default).
3. `search query --expand` honoring a `--relation` filter to scope the walk.
4. Auto-run `graph doctor` from the `lifecycle end` hook so hygiene stays current.
