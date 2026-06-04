# Cycle 1 Pitch — kage v0.1 (the thin slice)

> **Status:** PITCH — the gate to Stage 1. Approve → start building.
> *Date: 2026-06-04 (Session 14).* **Appetite: ~1 cycle (≈1 month).** Fixed time; scope flexes.
> Companion: [blueprint.md](blueprint.md) (the full roadmap this grows into).

---

## 0 · Foundations check (does v0.1 rest only on STABLE decisions?)

v0.1 depends ONLY on decisions that are locked AND change-resilient:

| Rests on | Why it's stable |
|---|---|
| #70 markdown source-of-truth | survived the Odysseus swap **untouched**; data is plain files |
| #16 save-wall (explicit save + confirm) | the project's spine; well-defended |
| #18 tag schema — **project tags only** (identity dim deferred) | additive; schema can grow later for free |
| #71 SQLite + FTS5 (BM25) | stock, boring, reliable; the partition filter lives here (#99) |
| Layer 1 #91/#95 — one engine + `init/status/doctor` | build-core-once |

**None of these are in the deferred/volatile set** (identity matrix, 3e, Layer 4 routing, Odysseus). → *Nothing we defer can invalidate what we build.* ✓ This directly answers the "what if a later decision changes everything?" worry.

## 1 · Problem

To use a cloud model well, Chirag re-explains his context every time; his notes live scattered or in his head. And the deeper problem the red-team named: **14 planning sessions, 0 shipped** — the tool meant to fight procrastination *became* it. v0.1 must be the smallest thing he opens **every day**.

## 2 · Solution — a local CLI (standalone, no Odysseus yet)

- **`kage init`** — scaffold `~/.kage/` (config, `memory/` markdown by project, `kage.db` SQLite). Transparent installer-style report with "✓ local" markers (#78).
- **`kage remember "<text>" [--project X]`** — save one markdown memory (file + frontmatter tags) via the wall: show suggested tag → confirm / edit / discard (#16, #20). **Project tags only.**
- **`kage recall "<query>" [--project X]`** — FTS5 BM25 search over the markdown; return top-N with source paths. Project-filtered via SQLite (the partition wall, #99).
- **`kage recall --pipe` (or `kage ask`)** — copy recalled context + query to clipboard (zero API setup) → you paste into Claude. **This is THE workflow: my notes → my model.** (`ask` = direct Claude API call is a fast-follow once the clipboard flow proves useful.)
- **`kage status` / `kage doctor`** — state snapshot + health, scoped to v0.1 (#97).
- **`kage test`** — unit + **invariant** tests for the above (project-filter correctness, wall behavior). NOT the local-vs-cloud benchmark — there's no local model or routing in v0.1.

## 3 · What's IN
markdown SoT + SQLite FTS5 (BM25) · project tags · the wall + confirm · recall→clipboard→Claude · status/doctor · tests.

## 4 · NOT in v0.1 (deferred — the volatile / moat layers)
- **Identity dimension** (project tags only for now)
- **Semantic search** / ChromaDB / embeddings / reranker — FTS5 BM25 is plenty at personal scale
- **Layer 3e selective disclosure** — you already trust Claude with everything today
- **Layer 4** multi-vendor routing / local Qwen / reputation table / Safety Copilot
- **Internal agents, Docker sandbox, daemon, MCP in/out, interactive REPL**
- **Odysseus integration** — v0.1 is standalone; it doesn't need the substrate yet
- The 1000-case benchmark corpus

## 5 · Rabbit holes to avoid
- Don't tune BM25 / don't add embeddings — FTS5 defaults are fine.
- Don't build the REPL — one-shot commands only.
- Don't add identity tags "just in case" — markdown SoT makes the migration cheap *later*.
- Don't wire Odysseus — resist; it's deferred for a reason.

## 6 · Definition of done
Chirag uses `kage recall → Claude` **daily for two weeks.** Then real-usage data — not planning — decides what's added next (identity? semantic? routing? Odysseus?).

## 7 · How it grows
The full blueprint is the **roadmap**, not discarded. v0.1 is the stable core; the moat (identity matrix, 3e, routing, Odysseus) gets added **when daily use earns it** — proven, not assumed.
