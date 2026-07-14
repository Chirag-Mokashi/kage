# Cycle 8 — Retrieval Quality (v0.8)

*Status: SHIPPED v0.8 (`37fd875`) — pitch (cloud-authored plan). Created 2026-06-10.*

> **Resequencing (confirmed 2026-06-10):** retrieval quality = Cycle 8. The mediator roadmap in [[project-mediator-vision]] shifts down one → Cycle 9 chat+streaming · 10 MCP client · 11 auto-routing · 12 agent loop.

---

## Problem

The ground-truth audit (2026-06-10) found retrieval is weaker than the blueprint claims, and two gaps are cheap, unblocked, and high-leverage:

1. **Headerless notes become one monolithic chunk.** `_chunk_note` splits only on `##`/`###` headers; a note with no headers is a single chunk, so retrieval can't isolate the relevant part.
2. **No reranker.** RRF fusion returns candidates but never re-scores them against the query — the right note can sit at rank 5 instead of 1. `bge-reranker-v2-m3` was *locked* (decision #51) but never implemented.

Every future mediator feature (chat, routing, agent loop) sits on top of retrieval. **Fix the foundation before building on it.**

## Appetite

One cycle. **Local-only — zero API cost (jugaad-clean).**

## Solution — three parts

### 1. Recursive chunking fallback
When a note has no `##`/`###` headers, *or* a header-section exceeds the target size, split recursively: **paragraph (`\n\n`) → sentence → hard char-window**, with small overlap.
- Target ~1500 chars (~375 tokens) per chunk, min 100, ~150-char overlap.
- Preserve `char_start`/`char_end` semantics so `_read_section` still works unchanged.
- Requires `kage reindex` to re-chunk + re-embed existing notes.
- 2026 best-practice basis: recursive splitting degrades gracefully where structure is absent (the same problem Apple's semantic index sidesteps by not depending on headings).

### 2. bge-reranker-v2-m3 (#51) — behind a swappable interface, OPTIONAL
After RRF fusion, take the top ~25 fused candidates, fetch their text, score `(query, passage)` pairs with the cross-encoder, return the top `limit` by rerank score.
- Library: `sentence-transformers` `CrossEncoder` (the locked "SentenceTransformer interface").
- **Heavy dependency** (`torch` + ~500MB model) for a currently-lightweight tool — so:
- **Optional + graceful:** config `rerank: true|false`; if disabled, or `torch`/model unavailable → fall back to RRF order (same pattern as the existing Ollama-down fallback). Keeps the default install light; the reranker is opt-in.
- Memory: ~500MB alongside Qwen3-14B (~10GB) on 24GB — within the #49 budget. Verify on first run.

### 3. Retrieval eval — so we can SEE the gain (not vibes)
- Fixture corpus: ~15–20 small notes (deliberately including **headerless** and **multi-section** ones to exercise the chunking fix) + `query → expected_note_id(s)` cases. **Chirag authors the cases** (locked `kage test` principle).
- Metrics: **recall@k + MRR**, measured **before and after** each change.
- Report numbers; **do not hard-fail on arbitrary thresholds** — data sets thresholds (locked principle), so the cycle's job is to *show movement*, not pass a made-up bar.

## Implementation order (per dev workflow, test after each step)

1. **Eval harness + fixtures + Chirag's cases** → record BASELINE numbers.
2. **Recursive chunking** in `_chunk_note` + `reindex` → re-measure.
3. **Reranker** interface + bge integration + config + graceful fallback → re-measure.
4. Tests written after each step; cloud review at steps 2 and 3 (never skipped).

## Out of scope (explicit)

- **Embedding swap** `nomic-embed-text` → Granite 311M R2 (#50): deferred. Full re-embed for uncertain marginal gain; `nomic` works.
- **LightRAG dual-level keyword split** (#49): deferred.
- Any mediator feature (chat, routing, agent loop) — later cycles.

## Risks / rabbit holes

- **Dependency weight:** `torch`/`sentence-transformers` bloats install → mitigated by optional+graceful design; document the extra install step.
- **Reranker latency:** scoring ~25 candidates adds tens–hundreds of ms → measure, accept if reasonable.
- **Eval corpus realism:** must include headerless + multi-section notes or it won't actually test the chunking fix.
- **Reindex churn:** chunking change re-chunks everything → ensure markdown source-of-truth is untouched (only derived indexes rebuild).

## Decisions (locked 2026-06-10)

- **D1 — Reranker posture:** ✅ OPTIONAL + graceful fallback to RRF order (config flag; torch/model missing → skip).
- **D2 — Eval corpus:** ✅ fixtures (~15–20 dedicated test notes incl. headerless + multi-section).
- **D5 — Cycle renumber:** ✅ retrieval = Cycle 8; mediator cycles → 9–12.
- **D3 — Chunk target (~1500 chars + ~150 overlap):** build-time default, tune against eval numbers.
- **D4 — Eval surface (`kage eval` vs pytest-only):** build-time default — start pytest-harness; promote to a command only if useful.
