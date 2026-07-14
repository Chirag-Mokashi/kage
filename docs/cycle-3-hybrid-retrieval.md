# Cycle 3 Pitch — kage v0.3 (hybrid retrieval)

> **Status:** SHIPPED v0.3 (`0981114`). Locked plan — reviewed twice by independent agents.
> *Date: 2026-06-06.* Companion: [cycle-2-brain-real-data.md](cycle-2-brain-real-data.md) (shipped v0.2) · [blueprint.md](blueprint.md).

---

## Problem

FTS5 BM25 ranks by term frequency, not meaning. A long keyword-dense document beats a short accurate one. `kage ask` returns wrong notes as context and gives wrong answers. This is not a data problem — it is a retrieval problem.

## Why now

v0.2 shipped `ask` (local + cloud). The retrieval layer is now the bottleneck. Usage data from v0.2 confirmed the symptom (Odysseus reconciliation doc dominated every query). Semantic retrieval unblocks the quality needed to use kage as a real daily tool.

## Audience reminder

kage is built for engineers — not only for one user. Design decisions must hold at 10,000+ notes per project, not just 20. "At this scale" is not an acceptable justification for cutting corners on architecture.

---

## Solution — Hybrid Retrieval (Layer 3c)

### Pipeline (dependency-graph parallel — NOT purely sequential, NOT fully parallel)

```
query
  │
  ├──[Thread A]──→ FTS5 BM25 search (no embedding needed, starts immediately)  ─┐
  │                                                                               ├──→ RRF(k=60) → top N → LLM
  └──[Thread B]──→ _embed(query) ──→ ChromaDB vec search                        ─┘
                   (vec depends on embed, but embed runs concurrently with FTS5)
```

Design principle: each retrieval source runs as independently as possible. Both contribute candidates (OR logic). ChromaDB re-ranks the union. Nothing is discarded before comparison.

### Vector store: ChromaDB embedded mode (blueprint decision #85)

```python
chromadb.PersistentClient(path=str(CHROMA_DIR))
```

- No server, no daemon — pure Python library
- HNSW indexing built-in — scales from 10 to 1M+ notes transparently
- Works on Mac and Linux (no native extension risk)
- Stored at `~/.kage/chroma/` alongside existing `~/.kage/indexes/kage.db`

### Embedding model: nomic-embed-text via Ollama

- Called via existing `_post_json()` at `http://localhost:11434/api/embed`
- 768-dim output, ~8192-token context window
- ~15-50ms warm, up to 8s cold (first call after model load)
- No new Python dep — Ollama already required for `ask`

### RRF Fusion

- `score = 1/(k + rank_A) + 1/(k + rank_B)`, k=60
- Rank-based — sidesteps BM25/cosine score incompatibility
- Union before fusion (OR, not AND) — both lists contribute before any cut

---

## What changes (complete function map)

### New functions

```
_embed(text) → list[float]
    POST Ollama /api/embed with {"model": embed_model, "input": text}
    timeout = 10s  (4s is too tight for cold model load — will spuriously fall back)
    truncate input at 32000 chars (safe approximation of 8192-token limit; no tokenizer in scope)
    raises OllamaUnavailable on URLError/TimeoutError

_get_chroma() → chromadb.Collection
    opens PersistentClient at CHROMA_DIR
    validates collection metadata embed_model matches config["embed_model"]
    on model mismatch: log warning + fall back to FTS5 (do NOT exit 1 — recall must always return)

_search_vec(query_vec, project, limit) → rows  [same shape as _search_fts rows]
    queries ChromaDB collection with query_vec
    filters by project metadata (partition wall enforced — same invariant as SQL wall)
    returns [(id, project, created_at, content_path, score), ...]

_rrf_fuse(fts_rows, vec_rows, k=60) → rows
    pure function — zero I/O, no side effects
    merges candidate lists by note ID
    scores each by position in each list (missing from one list = large rank penalty)
    deduplicates, sorts descending by RRF score
    returns merged list (caller slices to limit)
```

### Modified functions

```
_search(query, project, limit, any_terms=False)
    IF embeddings enabled AND Ollama reachable:
        Thread A: _search_fts(query, project, limit*2)        [concurrent]
        Thread B: _embed(query) → _search_vec(vec, project, limit*2)  [concurrent with A]
        wait for both → _rrf_fuse() → return [:limit]
    ELSE (Ollama down OR embeddings=false in config OR model mismatch):
        return _search_fts(query, project, limit, any_terms)   [existing path, unchanged]

_save(text, project, source=None)
    existing markdown write + FTS5 insert stays UNCHANGED
    ADD: attempt _embed(text) → store in ChromaDB with metadata {id, project}
    if Ollama unavailable: set needs_embed=1, continue (do NOT fail the save)
    if Ollama available:   set needs_embed=0

forget(ident, yes)
    existing markdown unlink + SQLite DELETE stays UNCHANGED
    ADD: _get_chroma().delete(ids=[mem_id])   ← MUST ADD or ghost vectors persist forever
    if ChromaDB unavailable: log warning, continue (forget must not fail)

init()
    ADD: create CHROMA_DIR (~/.kage/chroma/)
    ADD: initialise ChromaDB collection with metadata {"embed_model": config embed_model}
    ADD: PRAGMA journal_mode=WAL in _connect() or schema init
         (required for concurrent FTS5 + ChromaDB reads without serialisation)
```

### Schema change (additive — no breaking change)

```sql
ALTER TABLE memories ADD COLUMN needs_embed INTEGER NOT NULL DEFAULT 1;
-- 1 = not yet embedded, 0 = embedded
-- existing rows default to 1 (unembedded) until kage reindex is run
```

### New command: `kage reindex [--force]`

```
finds all notes WHERE needs_embed=1  (or all notes if --force)
for each note:
    body = _read_body(content_path)
    vec  = _embed(body)
    store in ChromaDB
    UPDATE memories SET needs_embed=0 WHERE id=?
    print progress: "  [3/18] 20260606T150534-14ec4c"
idempotent: skip already-embedded notes unless --force
crash-safe: each note committed individually (partial reindex = valid state)
if Ollama unavailable: exit 1 with message "start Ollama first: ollama serve"
```

### Modified commands

```
import (bulk add)
    DO NOT embed per file — would block on 500 Ollama calls with no feedback
    instead: set needs_embed=1 on every imported note (same as Ollama-down path)
    after import: print "  → run: kage reindex to enable semantic search"

doctor
    ADD check: count WHERE needs_embed=1
    if > 0:  "  ⚠ N notes not yet embedded → run: kage reindex"
    ADD check: embed_model in config vs ChromaDB collection metadata
    if mismatch: "  ✗ embedding model changed → run: kage reindex --force"

status
    no change needed
```

### Config changes

```json
{
  "embeddings": true,
  "embed_model": "nomic-embed-text"
}
```

DO NOT add `embed_dim` — ChromaDB infers dimensionality from first insert. Storing it creates three-way drift risk (config vs collection vs actual model output).

---

## What is NOT in this cycle (deferred)

- **Cross-encoder re-ranking** (Cycle 3b) — `ms-marco-MiniLM-L-6-v2` via sentence-transformers; highest single quality gain; adds new dep; defer
- **Time-based scoring boost** — recency as a signal modifier inside RRF
- **Type/label metadata filter** — note categorisation (decision, log, reference)
- **RAG-Fusion sub-query expansion** — LLM generates variant queries before retrieval
- **Identity dimension** — second axis of partitioning (project × identity)
- **SPLADE learned sparse retrieval** — upgrade path after BM25+dense proves insufficient

---

## Tests to add (5 — all mandatory)

```
test_rrf_fuse_merges_correctly
    pure unit test, zero I/O
    seed: fts_rows = [A, B, C], vec_rows = [B, D, A]
    verify: fusion order and deduplication correct (B should score highest — top of both)

test_search_falls_back_to_fts_when_ollama_down
    mock _embed to raise OllamaUnavailable
    verify: _search() returns FTS5 results, does not raise, exit code 0

test_save_sets_needs_embed_when_ollama_down
    mock _embed to raise OllamaUnavailable
    verify: note is saved to markdown + FTS5, needs_embed=1 in DB

test_reindex_idempotent
    run reindex twice
    verify: no duplicate embeddings in ChromaDB after second run

test_vec_search_respects_project_partition    ← CRITICAL — same invariant as test_partition_wall
    save note in projA, save note in projB
    mock _embed to return distinct fixed vectors
    verify: _search_vec() for projA returns projA note only, not projB
```

---

## Implementation order (do not reorder — each step depends on previous)

```
Step 1   _rrf_fuse()                pure function — write + test before any I/O code
Step 2   schema migration           needs_embed column + WAL mode + CHROMA_DIR in init
Step 3   _embed()                   Ollama /api/embed, 10s timeout, 32k char truncation
Step 4   _get_chroma()              PersistentClient + model validation + soft fallback
Step 5   _search_vec()              ChromaDB query + project partition filter
Step 6   _search() update           dependency-graph hybrid with ThreadPoolExecutor
Step 7   _save() update             embed on write + needs_embed flag
Step 8   import_ update             set needs_embed=1, skip embedding, print reindex hint
Step 9   kage reindex               idempotent, per-note commit, progress output
Step 10  kage doctor update         needs_embed count + model mismatch warning
Step 11  config update              embeddings + embed_model fields
Step 12  tests                      5 tests in order listed above
```

---

## Done when

`kage ask "what is Layer 3e?" -p kage` returns the correct answer from the Current State Summary — not from the Odysseus reconciliation doc. The partition wall test passes for the vec path. All 14 tests pass (9 existing + 5 new). CI green.

## New dependency

`chromadb` added to `pyproject.toml`. No other new deps.

## Setup (one-time, before first use)

```bash
ollama pull nomic-embed-text   # ~274 MB
kage reindex                   # embed existing notes
kage doctor                    # verify: 0 notes unembedded
```
