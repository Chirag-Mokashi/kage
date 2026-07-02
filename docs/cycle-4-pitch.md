# Cycle 4 Pitch — kage v0.4 (semantic chunking + grounded ask)

> **Status:** SHIPPED v0.4 (`85e6eb2`). Reviewed ×2 — two independent cold-agent audits complete.
> *Date: 2026-06-07.* Companion: [cycle-3-pitch.md](cycle-3-pitch.md) (shipped v0.3) · [blueprint.md](blueprint.md).

---

## Problem

`kage ask "what is Layer 3e?" -p kage` returned "Account Routing" — a hallucination — despite hybrid retrieval correctly surfacing 5 notes about Selective Disclosure. Two compounding bugs caused this:

**Bug 1 — Retrieval gap (embedding truncation)**
`nomic-embed-text` sees only the first 6000 chars of each note. Content past that point is invisible to vector search. The blueprint note is 192KB — the Layer 3e definition lives deep inside it, past the cutoff. The vector index has never seen it.

**Bug 2 — Context assembly gap (mixed-topic dumps)**
Even when retrieval returns the right note, `kage ask` passes a raw 6000-char dump of the entire note to the LLM. The relevant section is buried in mixed-topic content. The embedding over-compressed 40+ topics into a single vector — it matched the note but not the section.

**Bug 3 — No grounding constraint**
The system prompt does not instruct the model to stay in context. Qwen3 fills gaps with training priors and produces a plausible-sounding wrong answer. `kage ask` cannot be trusted for factual recall until this is fixed.

## Why now

These three bugs compound each other — fixing one without the others leaves the hallucination in place. The smoke test from Cycle 3 proved this is not theoretical. `kage ask` is the primary user-facing feature of v0.3; fixing it is the unblock for daily use.

Research confirmation (Cosmos, 2026-06-07): controlled ablation studies show semantic/adaptive chunking improves RAG answer accuracy from 50% → 87% (vs fixed-size chunking, same model). Chunking wins for retrieval precision regardless of model — even when content fits within the embedding model's context window, section-level embeddings outperform whole-document embeddings for mixed-topic notes.

## Audience reminder

kage is built for engineers. Architecture decisions must hold at 10,000+ notes per project. The chunking schema introduced here is a one-time breaking change; it must be done cleanly so it does not need to be redone.

---

## Solution — Semantic Chunking + Parent Retrieval (Layer 3d)

### Core idea

```
TODAY
  note (192KB)
    → embed first 6000 chars → 1 vector (whole note)
    → LLM gets 6000-char dump

CYCLE 4
  note (192KB)
    → split on ## headers → N chunks (each ~500–3000 chars)
    → embed each chunk → N vectors (section-level)
    → retrieval returns best matching chunk
    → LLM gets that section's text (focused, short)
```

### Chunking logic

Split each note body on `##` and `###` markdown headers. Each contiguous block of text under a header becomes one chunk. Rules:

- Min chunk size: 100 chars (skip empty/boilerplate headers)
- Fallback: if no headers exist (single-paragraph `kage remember` notes), treat the whole note as one chunk
- Each chunk stores: `note_id` (parent), `section_title` (the header line), `char_start`, `char_end` (character offsets into the note body string — not byte offsets)
- Text is NOT duplicated — offsets are stored in SQLite; section text is read from the `.md` file at query time by reading the full file then slicing: `body[char_start:char_end]`. Never use `file.seek()` — it is unreliable for non-ASCII text (Japanese, emoji) in Python text mode (markdown = source of truth)

### Retrieval path

```
query
  │
  ├──[Thread A]── FTS5 BM25 → note-level results ──────────────────────┐
  │                                                                      ├── RRF(k=60) → top-N notes
  └──[Thread B]── _embed(query) → ChromaDB chunk search                 │
                    returns chunk ids                                    │
                    → deduplicate: best chunk score per parent note ─────┘
                                                                         │
                                        resolve top-N notes → read matched section text from .md
                                                                         │
                                                          pass section texts to Qwen3
```

RRF fusion operates at **note level** — if multiple chunks from the same note match, only the highest-scoring chunk's score represents that note. This keeps the existing RRF logic intact.

### kage ask — context assembly + system prompt

**Before (Cycle 3):**
```
Here are relevant notes:

[raw 6000-char note dump]
[raw 6000-char note dump]
```

**After (Cycle 4):**
```
Answer ONLY using the context below.
If the answer is not present in the context, say exactly:
I don't know — this isn't in my notes.
Do not use any outside knowledge.

Context:

[blueprint.md § Layer 3e — Selective Disclosure]
<section text — focused ~1000 chars>

[cycle-3-pitch.md § Retrieval]
<section text — focused ~800 chars>
```

**kage ask output:**
```
Answer: Selective Disclosure is Layer 3e — ...

Sources:
  • blueprint.md  §  Layer 3e — Selective Disclosure
  • cycle-3-pitch.md  §  Retrieval
```

`--no-sources` flag suppresses the Sources block for scripting use.

---

## What changes (complete map)

### Schema changes

**SQLite — new table:**
```sql
CREATE TABLE IF NOT EXISTS chunks (
    id           TEXT PRIMARY KEY,        -- {note_id}_c{index}
    note_id      TEXT NOT NULL,           -- FK → memories.id
    section_title TEXT NOT NULL DEFAULT '',
    char_start   INTEGER NOT NULL,
    char_end     INTEGER NOT NULL,
    needs_embed  INTEGER NOT NULL DEFAULT 1
);
```

**ChromaDB — new collection:**
- Collection name: `chunks` (replaces old `memories` collection — the name used by v0.3)
- Metadata per chunk: `{parent_note_id, section_title, project, created_at, content_path}`
- Old `memories` collection is deleted (`client.delete_collection("memories")`) then a new `chunks` collection is created on `kage reindex --force`
- Chunk ID scheme: `{note_id}_c{index}` (e.g. `20260605T230332-664a70_c3`)
- Dimensions unchanged: 768 (nomic-embed-text)

**Migration banner** — on any command that touches ChromaDB before reindex --force is run:
```
⚠ embedding schema changed in v0.4 — run: kage reindex --force to migrate
```

### New functions

```
_chunk_note(body) → list[Chunk(title, char_start, char_end)]
    split on ## and ### headers
    skip chunks < 100 chars
    fallback: single chunk covering entire body if no headers
    offsets are character positions in the body string (not byte positions)

_read_section(content_path, char_start, char_end) → str
    body = _read_body(content_path)   ← reuse existing helper (strips frontmatter)
    return body[char_start:char_end]  ← character slice; never use file.seek()
    returns empty string on OSError (caller handles gracefully)
```

### Modified functions

```
_save(text, project, source=None, embed=True)
    existing markdown write + FTS5 insert UNCHANGED
    REPLACE: single whole-note embed
    WITH: _chunk_note(text) → chunks = list of Chunk objects
          wrap ALL chunk INSERTs in a single SQLite transaction:
            for each chunk: INSERT INTO chunks (id, note_id, section_title, char_start, char_end)
            if any INSERT fails: rollback all chunk rows for this note (no partial state)
          commit transaction
          if embed=True: for each chunk independently (loop, one connection per chunk as per
                         existing _save pattern — NOT batched):
                           _embed(body[char_start:char_end][:6000]) → ChromaDB chunks.add()
                           UPDATE chunks SET needs_embed=0 WHERE id=chunk_id  ← per-chunk
                           commit
                         if Ollama down mid-loop: remaining chunks stay needs_embed=1;
                           reindex normal path picks them up (correct by design)
          if embed=False: all chunks stay needs_embed=1 (reindex picks them all up)

_get_chroma() → chromadb.Collection
    NOW targets 'chunks' collection (was 'memories')
    metadata: {"embed_model": config_model, "schema_version": "4"}
    schema_version missing or mismatch → typer.echo(migration banner) THEN raise OllamaUnavailable
    Banner prints BEFORE raising — so callers that catch OllamaUnavailable and pass still show it.
    This matches the existing pattern (lines 327-331 in cli.py) — echo fires before raise.
    (callers already catch OllamaUnavailable and fall back to FTS5 — contract unchanged)
    DO NOT return None — every caller does coll.add()/coll.query() on the return value

_search_vec(query_vec, project, limit) → note-level rows
    query ChromaDB chunks collection
    filter by project metadata
    GUARD against ChromaDB raising when n_results > matching document count:
      if project filter active:
          ids = collection.get(where={"project": project}, include=[])["ids"]
          count = len(ids)            ← ChromaDB has no count(where=...) API; use get()
      else:
          count = collection.count()
      if count == 0: return []
      n_results = min(limit, count)
    deduplicate: group by parent_note_id, keep highest-scoring chunk per note
    return 8-tuples: (note_id, project, created_at, content_path, best_chunk_score, section_title, char_start, char_end)
    row positions: 0=note_id, 1=project, 2=created_at, 3=content_path, 4=score, 5=section_title, 6=char_start, 7=char_end

_rrf_fuse(fts_rows, vec_rows, k=60) → rows
    UNCHANGED in logic — still fuses by note_id
    vec_rows now carry section metadata (section_title, char_start, char_end) as extra fields
    fused rows retain whichever section had the best vec score

_search(query, project, limit) → normalized 8-tuples
    UNCHANGED in structure
    OUTPUT NORMALIZATION (new): all rows returned are 8-tuples regardless of source
      FTS-only rows padded to: (note_id, project, created_at, content_path, snippet, None, None, None)
      vec rows already 8-tuples from _search_vec
      This keeps ALL callers safe — recall, ask, recall --pipe all unpack row[0..4] only;
      ask additionally uses row[5..7] for section assembly (guards None before calling _read_section)

recall / ask (context assembly)
    recall / recall --pipe: UNCHANGED in behaviour — still passes full note body.
      Code update needed: change strict 5-unpack `_id, proj, created, path, snip = row`
      to extended unpack `_id, proj, created, path, snip, *_ = row` in both the pipe block
      and the display loop. This is the ONLY change to recall — no logic change.
    ask:  was: read full note body → pass 6000-char dump per note
          now: for each fused row, if row[6] is not None: _read_section(row[3], row[6], row[7])
               else: _read_body(row[3])[:2000]  ← fallback for FTS-only matches with no section
               pass section text to LLM (no secondary char cap — sections are naturally short)

ask (system prompt)
    REPLACE soft prompt
    WITH hard grounding constraint (exact wording in Solution section above)
    ADD: print Sources block after answer
    ADD: --no-sources flag

forget(ident, yes)
    existing markdown unlink + SQLite DELETE memories UNCHANGED
    ORDER MATTERS:
      1. SELECT id FROM chunks WHERE note_id=?  → collect chunk_ids list
      2. DELETE FROM chunks WHERE note_id=?     → remove chunk rows from SQLite
      3. ChromaDB chunks.delete(ids=chunk_ids)  → remove vectors (uses ids from step 1)
    Step 1 must come before step 2 — once rows are deleted, the IDs are gone.
    If _get_chroma() raises OllamaUnavailable (includes schema_version mismatch before reindex --force):
      the existing try/except in forget shows "vector index not updated — run: kage reindex"
      this is CORRECT before migration — the chunks collection doesn't exist yet, nothing to delete.
      After reindex --force, the schema is correct and forget works normally.

reindex [--force]
    was: embed whole notes WHERE needs_embed=1
    now:
      --force: re-chunk ALL notes → delete chunks table rows + ChromaDB chunks collection
               → recreate from scratch (handles migration from v0.3 schema)
      normal:  embed chunks WHERE needs_embed=1 (already chunked, just missing vector)
    progress: "  [3/18] 20260605T230332-664a70_c2  §  Layer 3e — Selective Disclosure"

import_ (bulk add)
    UNCHANGED — still sets embed=False, prints reindex hint

doctor
    REPLACE old needs_embed count on memories
    WITH needs_embed count on chunks
    KEEP model mismatch check (now checks schema_version too)
```

### Config — no new keys needed

`embed_model` and `embeddings` already added in Cycle 3 (Step 11). No changes.

---

## What is NOT in this cycle (deferred)

- **Embedding model upgrade** (qwen3-embedding:0.6b) — 32K context, 639 MB. Deferred to Cycle 5 after chunking is proven. Chunking is the right fix regardless of model.
- **Cross-encoder re-ranking** — highest single quality gain after chunking; adds sentence-transformers dep; Cycle 5.
- **Sub-query expansion (RAG-Fusion)** — LLM generates query variants before retrieval; Cycle 6.
- **Identity dimension** — second partitioning axis; Layer 3e work.
- **Multi-turn / REPL ask** — one-shot is correct for now.
- **`needs_rechunk` flag** — for re-chunking edited notes. Notes are rarely edited post-creation; defer.

---

## Tests to add (per-step, mandatory)

```
Step 1 (schema)
  test_chunks_table_created_on_init
      fresh init() → chunks table exists with correct columns

Step 2 (_chunk_note)
  test_chunk_note_splits_on_headers
      body with 3 ## sections → 3 chunks, correct char_start/char_end
  test_chunk_note_fallback_no_headers
      body with no ## → 1 chunk covering full body
  test_chunk_note_skips_tiny_sections
      ## header with < 100 chars of content → skipped

Step 3 (_read_section)
  test_read_section_returns_correct_slice
      write file, store offsets, read back → matches original section text
  test_read_section_returns_empty_on_missing_file
      non-existent path → returns ""

Step 4 (_save chunking)
  test_save_creates_chunk_rows
      save note with 3 sections → 3 rows in chunks table
  test_save_chunk_ids_are_sequential
      chunk ids follow {note_id}_c0, _c1, _c2 pattern
  test_save_embed_false_sets_needs_embed_on_chunks
      import path: all chunks have needs_embed=1

Step 5 (reindex)
  test_reindex_force_rechunks_all_notes
      save 2 notes → manually corrupt chunks table → reindex --force → chunks table rebuilt correctly
  test_reindex_normal_only_embeds_pending_chunks
      2 chunks needs_embed=1, 1 chunk needs_embed=0 → reindex → only 2 embed calls

Step 6 (_search_vec deduplication)
  test_search_vec_deduplicates_chunks_by_parent_note
      2 chunks from same note both match → only 1 note-level result returned

Step 7 (RRF unchanged)
  existing test_rrf_fuse_merges_correctly still passes (no change to logic)

Step 8 (forget)
  test_forget_deletes_all_chunks_for_note
      save note → verify chunk rows exist → forget → chunk rows gone + ChromaDB ids gone

Step 9 (ask — system prompt + sources)
  test_ask_hard_system_prompt_present
      mock LLM call → verify system prompt contains "ONLY" and "I don't know"
  test_ask_shows_sources_in_output
      mock retrieval → verify "Sources:" block in output with section_title
  test_ask_no_sources_flag_suppresses_block
      --no-sources → "Sources:" not in output

Step 10 (migration)
  test_migration_banner_shown_before_reindex
      v0.3 ChromaDB present (schema_version missing) → any ask/recall command → banner in output

Existing tests that MUST be updated in Step 11 (will fail on first CI run otherwise):
  test_vec_search_respects_project_partition
      currently hardcodes collection name "memories" → update to "chunks"
  test_search_vec_returns_correct_shape  (if it exists)
      currently asserts len(result[0]) == 5 → update assertion to 8

New test to add (recall --pipe row shape safety):
  test_recall_pipe_works_with_extended_row_shape
      mock _search to return 8-tuples (with None section fields)
      invoke recall --pipe → exits 0, no TypeError, output contains note body
```

---

## Implementation order

```
Step 1   Schema          chunks table in SQLite; init() creates it
Step 2   _chunk_note()   header splitter + fallback; character offset based
Step 3   _read_section() body[char_start:char_end] slice; no file.seek()
Step 4   _get_chroma()   target 'chunks' collection; schema_version check; keep raising OllamaUnavailable
Step 5   _save() update  chunk + transactional INSERT; embed each chunk via updated _get_chroma()
Step 6   reindex update  --force: delete 'memories' collection + rechunk; normal: embed pending chunks
Step 7   _search_vec()   query chunks; per-project n_results guard; deduplicate to note level
Step 8   forget() update collect chunk ids → delete SQLite rows → delete ChromaDB vectors (in order)
Step 9   ask update      section texts via _read_section; hard system prompt; Sources output
Step 10  doctor update   count chunks.needs_embed=1; schema_version check
Step 11  tests           per-step as listed above
```

---

## Done when

`kage ask "what is Layer 3e?" -p kage` returns the correct answer (Selective Disclosure / privacy gate) and the Sources block shows `blueprint.md § Layer 3e`. The partition wall test passes on the chunk path. All tests pass. CI green.

## No new dependencies

ChromaDB already added in Cycle 3. No new deps.

## Setup (after upgrade from v0.3)

```bash
kage reindex --force   # rechunks all notes + rebuilds ChromaDB chunks collection
kage doctor            # verify: 0 chunks unembedded, schema_version=4
kage ask "what is Layer 3e?" -p kage   # smoke test
```
