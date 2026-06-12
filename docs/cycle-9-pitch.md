# Cycle 9 — Identity Axis (v0.9)

*Status: SHIPPED 2026-06-12. All 8 steps complete. 274 tests pass. Branch: main, tagged v0.9.*

> **Resequence (2026-06-12):** identity-axis moat inserted as Cycle 9, ahead of chat. Retrieval (Cycle 8) shipped; the identity dimension is differentiator #1 and the biggest gap between blueprint and shipped reality. Chat → 10, MCP client → 11, auto-routing → 12, agent loop → 13. See [[project-mediator-vision]].

---

## Problem

The blueprint calls the **project × identity matrix** "THE WEDGE" (differentiator #1, Layer 3b, decisions #18/#19/#103) and it is *fully designed and locked*. But the shipped schema has **one partition column** — `project TEXT` — and **no identity axis at all** (ground-truth audit, 2026-06-10). The hard identity wall the whole privacy story rests on does not exist; Layer 3e's Stage-1 identity check has nothing to enforce.

Decision #104 deferred identity *"until daily use justifies it."* It now does: kage is daily-usable, and we have real multi-identity data to ground it — the `hsi-cancer-detection` NEU coursework repo (NEU identity) vs the `kage` / `kage-corrections` notes (Personal identity).

## Appetite

One cycle — the deliberate **moat** cycle, so it earns its weight. **Local-only, zero API cost** (jugaad-clean, same as Cycle 8).

## Solution — the identity axis, grounded on real data

### 1. Schema: many-to-many partition (blueprint #71)

Refactor partition from a single `project` string to join tables, so a memory can belong to ≥1 project and ≥1 identity (needed for `baseline` facts shared across identities):

```
memories(id, content_path, created_at, needs_embed, local_only, state)   ← + state
memory_projects(mem_id, project)        ← many-to-many
memory_identities(mem_id, identity)     ← many-to-many, ≥1 per memory (#18)
```

- `state ∈ {scoped, baseline, pending}` (default `scoped` when projects non-empty; chosen when project-empty).
- **Migration/backfill:** existing 25 notes → one `memory_projects` row from the old `project` string + `memory_identities = ['personal']` + `state = scoped` (or `baseline` if project-empty). Markdown frontmatter gains `identities:` + `state:`. Source-of-truth markdown is rewritten additively; indexes rebuilt.

### 2. The wall: SQLite pre-filter (#99), not store-by-store filtering

The many-to-many membership *forces the correct architecture* — multi-identity doesn't fit ChromaDB's scalar metadata. So the wall executes as a **SQLite pre-filter producing allowed note IDs**, and both FTS and vector search are constrained to that set (Chroma stays a dumb index — `where={"note_id": {"$in": allowed}}`). This is exactly decision #99.

**Filter logic (locked, blueprint Layer 3b):**
```
Given active identity I (default 'personal' if --identity omitted)
and optional active project P:

allowed note M  ⟺
    I ∈ M.identities                              (HARD identity wall, inviolable)
    AND NOT (M.state = pending)                   (pending never surfaces in search)
    AND (
         P is None                                (no project scope → all in identity)
      OR P ∈ M.projects                           (scoped exact match)
      OR (M.projects = [] AND M.state = baseline) (baseline spillover)
    )
```
- Cross-identity search (`--identity all`) is **out of scope** (Pattern C, v2).
- Default identity = `personal` makes the wall real by default; NEU data is invisible unless you pass `--identity neu`.

### 3. Surface: `--identity` flag + 3e re-check

- `--identity / -i` on `remember`, `recall`, `ask`, `list` (default `personal`). `remember` also takes `--state` (or infers: project given → scoped; no project → prompt baseline/pending).
- `_disclosure_gate` Stage-1 re-checks the identity wall before cloud dispatch (defense in depth — two independent walls).
- MCP tools (`kage_recall`/`kage_ask`) gain an optional `identity` param, default `personal`.
- **Layer 3a auto-detect is deferred** — identity is explicit this cycle.

### 4. Real-data seed + the moat as a test

- Backfill all existing notes → Personal.
- Import `hsi-cancer-detection` text files (README, PROJECT_LOG.md, docs/DECISIONS_*.md, APRIL09_CHECKPOINT.md, notebooks/completed/README.md, dataset_summary/*.txt) → `--identity neu --project hsi-cancer-detection`.
- **Wall-invariant test:** query as Personal → no NEU note ever returned; query as NEU → no Personal note ever returned. The moat's guarantee, executable.
- Extend `tests/eval_retrieval.py` with identity-scoped cases (the fixture corpus already has `school`/`finance`/`health` projects to repurpose as identities).

## Implementation order (per dev workflow, test + cloud-review after each step)

Re-sequenced to de-risk the high-blast-radius `_search` refactor (R2–R5): **TDD the wall in isolation first, land it incrementally, treat the migration as irreversible.**

1. **Schema only** — join tables (`memory_projects`, `memory_identities`) + `state` column. No migration yet. Test: schema creation idempotent.
2. **`_allowed_note_ids(identity, project)` — the wall, as a standalone pure function** (no FTS, no Chroma). **TDD against the blueprint re-walk table (M1–M7)** before anything depends on it (R2). This is the moat; harden it first.
3. **Migration / backfill — treated as Tier-3 / irreversible (R4):** back up `~/.kage` first; migration is idempotent + `--dry-run`; test on a *copy* before the real store. Existing 25 notes → `identities=['personal']`, project from old scalar, `state=scoped` (or `baseline` if project-empty). Markdown frontmatter rewritten additively.
4. **`_save` writes the matrix** — project(s) + identities + state into join tables; Chroma chunk metadata carries `note_id` only (identity lives in SQLite). Test: round-trip.
5. **Wall into the FTS / embeddings-off path first (R3)** — `_search_fts` constrained to allowed IDs. **Wall-invariant test green here** before touching the vector path.
6. **Wall into the hybrid / vector path** — Chroma `where={"note_id": {"$in": allowed}}`; reranker + RRF + fallbacks keep working on the filtered set. Cloud review (highest blast radius, never skipped). **Wall-invariant test across embeddings{on,off} × Ollama{up,down} (R5)** — prove no return path leaks.
7. **`--identity` / `--state` flags + MCP `identity` param + 3e Stage-1 re-check** (independent second wall). Test: CLI + gate.
8. **Seed real data + eval** — import HSI as NEU; extend `eval_retrieval.py` with identity-scoped cases; re-measure (no regression vs MRR 1.000).

## Future-proof seams (deferred ≠ skipped)

Per the future-proofing principle — these deferred pieces get their **seam left in place** this cycle so they drop in without rework:

- **Layer 3a auto-detect** → the wall is a pure `_allowed_note_ids(identity, project)` function; 3a later just *computes* `(identity, project)` and feeds the same function. No re-plumbing.
- **The pending auto-promptor** → the static `pending` state ships now, so its data model is ready when chat + Librarian arrive.
- **Cross-identity search (Pattern C)** → the wall already takes `identity`; a future `--identity all` relaxes one clause, doesn't restructure.
- **Multi-project / multi-identity membership** → join tables support it from day one even though current data is single-membership; no "migrate to join tables later" cycle.

## Out of scope (explicit)

- **Layer 3a auto-detection** (calendar/cwd/sticky cascade) — explicit `--identity` only this cycle.
- **The pending auto-promptor** (session-watcher that prompts to partition a maturing idea) — depends on `kage chat` + Librarian; ships later. See [[project-pending-promotion-vision]]. v0.9 ships the *static* `pending` state only.
- **Cross-identity search** (`--identity all`, Pattern C) — v2.
- **Bootstrap wizard** (auto-suggest identity groupings from account domains, #15/#35) — deferred until 3a.
- Any mediator feature (chat, MCP client, routing) — later cycles.

## Risks / rabbit holes

- **Migration data loss** — rewriting frontmatter + rebuilding indexes on 25+ notes. Mitigate: markdown is source-of-truth; back up `~/.kage` before migrating; migration idempotent + tested before running on real store.
- **`_search` refactor blast radius** — pre-filter touches the hottest path. Mitigate: keep FTS-only and Ollama-down fallbacks working; reranker (Cycle 8) must still fire on the filtered set.
- **Chroma `$in` on large candidate sets** — fine at personal scale; watch if it gets slow.
- **Default-identity surprise** — defaulting to `personal` hides NEU notes unless flagged. This is *intended* (the wall is the point), but document it clearly in `status`/`recall` output.

## Decisions (locked 2026-06-12)

- **D1 — Schema:** ✅ many-to-many join tables for BOTH project and identity (#71). Wall stays exact (set membership); multi-identity is opt-in, never a default.
- **D2 — Wall placement:** ✅ SQLite pre-filter → allowed IDs → Chroma searches within (#99). Forced by many-to-many + auditability.
- **D3 — States:** ✅ scoped + baseline + pending (static). Pending is groundwork; auto-promptor deferred.
- **D4 — Default identity:** ✅ `personal` when `--identity` omitted (wall real by default; cross-identity = v2).
- **D5 — 3a auto-detect:** ✅ deferred; explicit `--identity` this cycle.
- **D6 — Test data:** ✅ `hsi-cancer-detection` repo (text files only) = NEU identity; existing notes = Personal.
