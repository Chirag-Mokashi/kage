# Cycle 12 — Modularity (injectable seams): full architecture (v3, two cold reviews)

*Status: SHIPPED v0.12.0 (`3d6eb3d`) — plan (complete architecture authored before execution).*
*Discipline: 7-step dev-workflow gate. Local writes code/tests; cloud reviews every slice.*
*Date: 2026-06-18*

> **v2 changelog (cold review #1, architecture/rework):** v1's egress claim was wrong.
> Fixes: gated chokepoint (C1+C2), call-time forwarder rule (§4/H2), precise egress
> invariant (§10), `Config` re-reads on access (§5.1/H3), `runtime.reset()` lifecycle
> (§4/M1), async arm handlers (§7/M2), multi-slice test rule (§3.2/H1), `_post_json` one
> helper (L1), DB-swap deferred (§1/M3). 5 seams + 2 registries confirmed justified (L2).
>
> **v3 changelog (cold review #2, completeness + 10-characteristics + jugaad + ponytail):**
> (1) The v2 row-shaped `dispatch_cloud` did NOT cover the multi-turn path (`chat` /
> session `kage_ask` → `_call_cloud_chat` with conversation-turn gating). Redesigned:
> **the egress sink is the existing `CloudClient.complete()`** — both shapes already
> funnel through it (post-WI-2 `_call_cloud` wraps `_call_cloud_chat`); enforcement is
> gate-before-sink at each caller; golden test records at the sink + remote-arm transport
> (§5.6). Jugaad: reuse the existing sink, don't build a new function the chat path
> bypasses. (2) Added a full **function→module table** (§6.5) — ~15 functions were
> unmapped, most critically `_save`/`reindex`/`import_`, the active-context cluster, and
> the dormant Google arm path. New **`notes.py`** module (write path). (3) `Store.init_schema`
> must keep `init()`'s three idempotent `ALTER TABLE` guards (§5.2) — one adds `local_only`,
> the gate flag. (4) `VectorIndex.collection()` keeps raising `OllamaUnavailable` (§5.4).
> Reviewer #2: jugaad + ponytail discipline sound; risk is execution fidelity, concentrated
> in the (now-fixed) egress spec.

---

## 1. Goal (locked 2026-06-18; DB scope set after cold review)

Three things — **not** enforced layer walls:

1. **Swappable backends** — different **vector store / LLM** without editing call sites.
   *DB swap is **deferred**:* `Store` stays a thin connection-provider; there is no second
   DB in hand, so making SQLite swappable now would be speculative (ponytail). Revisit if a
   real second backend appears.
2. **Readable file layout** — no more ~2300-line `cli.py`.
3. **Pluggable extensions** — arms / providers register as drop-ins.

One refactor, not three. **Not a rewrite** — the code works and is tested; we move only the seams.

## 2. The coupling wall (the problem we're dissolving)

Tests monkeypatch `cli` internals ~405×. `setattr(cli, "_embed", fake)` only rebinds
`cli`'s attribute, so a function that moves to another module and is called from a third
silently loses its stub (green test that tests nothing). See
`memory/project_cli_split_coupling_wall.md`. §4 dissolves this at the root.

---

## 3. TEST AUDIT ("reconsider all the tests" deliverable)

Full pass over `tests/test_cli.py` (4,703 lines, 356 tests). The suite is **good** — high
coverage, real invariants guarded. The problem is *style coupling*, not quality.

### 3.1 Three styles

| Style | ~Count | Mechanism | Survives refactor? |
|---|---|---|---|
| Boundary (subprocess) | 40 | `run([...], home)` runs the real binary, isolated `KAGE_HOME` | **YES** — gold standard |
| Pure-unit | 63 | calls a pure fn (`_pii_scan`, `_chunk_note`, `_rrf_fuse`, `_condense_query`) | **YES** (re-export, proven) |
| In-process monkeypatch | **286 (80%)** | `monkeypatch.setattr(cli, <seam>, …)` then call directly | **NO** — breaks when seam moves |

(a) path/state isolation (patch `KAGE_HOME`/`CONFIG_PATH`, run real logic — cheap) vs.
(b) behavior stubs (patch `_embed`/`_get_chroma`/`_post_json` — convert to injected fakes; the bulk).
Good existing pattern: `test_get_chroma_returns_collection` patches `chromadb.PersistentClient`
(library boundary, not `cli`) — already refactor-proof; conversion target makes (b) look like it.

### 3.2 Conversion rules (ponytail — minimize churn)

> **R1.** Convert a test only when a seam it patches moves in the current slice.
>
> **R2 (cold review H1).** A test that patches seams assigned to *different* slices
> converts **fully in the earliest slice that touches any of its seams**, using the
> `fakes` fixture (§8) for seams not yet extracted. **No half-converted hybrids across
> PRs** — a test patching `cli._embed` while `runtime.embed` is already the live path is
> green-but-testing-nothing, the exact failure we're killing. Measured: 96 tests patch ≥2
> seams; 66 span slices — these all convert in their earliest slice.

### 3.3 Redundancy (delete during the relevant slice)

- `_get_chroma` tested twice — early pair (415, 430) appears subsumed by the fuller set (1006–1064).
- `_search_vec` sprawl — ~15 tests, several assert near-identical tuple shape. Collapse when `VectorIndex` lands.
- `_call_cloud` vs `TestAnswerDispatcher` — dispatch covered twice; after WI-2's wrapper, some double-cover. Prune when `CloudClient` lands.

### 3.4 Coverage gaps (add)

- **Egress golden test (the moat) — MISSING.** Added in Slice 1, guarding the §5.6 chokepoint (not per-caller assembly).
- **Seam-swap test — MISSING.** Once a seam is injectable, inject a second trivial impl and run a recall through it — proves goal (1) real.

### 3.5 Unchanged

The ~40 boundary + ~63 pure-unit tests stay; they are the per-slice safety net. We **expand** the boundary set, never shrink it.

---

## 4. Injection mechanism — `kage/runtime.py` (foundational, chosen once for all seams)

A module `kage/runtime.py` holds live seam instances as module attributes. Every module
calls `runtime.<seam>.<method>(...)`. To swap a backend or inject a fake, replace
`runtime.<seam>`.

```python
# kage/runtime.py (sketch)
config: Config       = None
store:  Store        = None
embed:  Embedder     = None
vector: VectorIndex  = None
cloud:  CloudClient  = None

def reset():                       # (re)build all seams from current env (KAGE_HOME/config.json)
    global config, store, embed, vector, cloud
    config = Config.from_env()
    store  = Store(config)
    embed  = Embedder(config)
    vector = VectorIndex(config, embed)
    cloud  = CloudClient(config)
```

**Why this, not a threaded `Deps` object:** every module reads `runtime.<seam>` at *call
time*, so swapping reaches every caller in every module — the exact thing
`setattr(cli, "_embed", …)` could not do. Conversion is
`monkeypatch.setattr(cli, "_embed", fake)` → `monkeypatch.setattr(runtime, "embed", FakeEmbedder())`.

**Lifecycle (cold review M1):** `runtime.reset()` is called once at **CLI `main()` startup**
and once at **MCP server boot**. Tests rebuild via the `fakes` fixture (auto-reset by
monkeypatch teardown). No other production reset.

**Forwarder rule (cold review H2 — critical):** during transition, `cli.py` re-exports moved
symbols so old/boundary tests keep working. For a **swappable seam**, the shim MUST be a
**call-time forwarder**, never a bound alias or default-arg:
```python
def _embed(text):            # OK — reads runtime at call time
    return runtime.embed.embed(text)
# _embed = runtime.embed.embed         ← FORBIDDEN (binds once at import → rebuilds the wall)
# def f(e=runtime.embed): ...          ← FORBIDDEN (default captured at import)
```
Pure re-exports (`pii`, `chunk`) are the only exception — they are never swapped.

**Ponytail:** `runtime` is a plain module with module-level instances. No DI framework,
container, or service locator. Module-level singletons are a deliberate ceiling
(single-process CLI). Upgrade path if concurrent isolated contexts are ever needed:
`runtime` becomes a context object threaded from the command layer. Not built.

---

## 5. The five seam interfaces (fixed now) + the egress chokepoint

Minimal surfaces — only methods current code needs (`Protocol`-typed).

### 5.1 Config (leaf; no kage imports)
```
from_env() -> Config            # derives paths from KAGE_HOME
.home / .db_path / .chroma_dir / .state_path / .audit_path
.data -> dict                   # re-reads config.json ON ACCESS ({} if missing/invalid)
.get(key, default)
```
**Re-read on access (cold review H3):** `arm auth` writes `config.json` mid-process and a
later arm call must see it; today `_config()` re-reads every call. `Config.data` preserves
that (property re-reading the file). Cheap; single-process.

### 5.2 Store (thin — DB swap deferred, §1/M3)
```
__init__(config)
.connect() -> sqlite3.Connection     # WAL + row factory
.init_schema()                       # full init() behavior — DDL + the THREE idempotent
                                     #   ALTER TABLE guards (needs_embed, local_only, state)
                                     #   that upgrade existing DBs. Dropping these is a
                                     #   silent regression — `local_only` is the gate flag.
.allowed_note_ids(identity, project) -> set[str]   # the patched query helper
```
Raw SQL stays at call sites (`_search_fts`, `privacy`, `status`, `forget`, sessions). This
interface does NOT claim DB swappability — see §1.

### 5.3 Embedder
```
__init__(config)
.embed(text) -> list[float]          # ollama nomic-embed-text; raises OllamaUnavailable
.status() -> tuple[bool, str]
```

### 5.4 VectorIndex
```
__init__(config, embedder)
.collection() / .collection_meta()   # _get_chroma + schema-version guard;
                                     #   MUST keep raising OllamaUnavailable (+ stderr
                                     #   reindex hint) — _save/_search_vec rely on
                                     #   `except OllamaUnavailable: pass` and tests assert it
.search(query_vec, project, limit, identity) -> list[tuple]
.add(chunk_id, vec, metadata) / .delete(note_id)
```

### 5.5 CloudClient (provider transport only)
```
__init__(config)
.complete(provider, system, messages) -> str    # _call_cloud_chat; per-type dispatch behind §7 registry
```
`_post_json` stays **one shared low-level helper** (`http.py` leaf) used by CloudClient,
Embedder, and the Ollama path — NOT duplicated (cold review L1; protects the urllib
User-Agent fix from regressing in a copy).

### 5.6 The gated egress sink (cold reviews C1+C2, and #2's multi-turn fix)

There are **two** cloud egress shapes, not one:
- **single-shot** (`ask`, stateless `kage_ask`) → `_call_cloud(provider, system, user_msg)`
- **multi-turn** (`chat`, session `kage_ask`) → `_answer(... history ...)` → `_call_cloud_chat`,
  which also gates conversation **turns** via `_gate_conversation`, not just rows.

A row-shaped `dispatch_cloud(rows)` (v2) could not express the multi-turn path, so the chat
cloud path would flow *around* it. **Fix (jugaad — reuse the existing sink):** since WI-2
made `_call_cloud` a thin wrapper over `_call_cloud_chat`, **both shapes already funnel
through one transport: `CloudClient.complete()`.** That IS the single egress sink. No new
function.

Enforcement = **gate before the sink**, at every caller:
```
# shared row→context helper (privacy.py) so single-shot/stateless don't each reinvent it:
def assemble_context(allowed_rows) -> str: ...          # ONLY gate-allowed rows

# single-shot caller:
allowed, withheld = _disclosure_gate(rows, cfg, identity, project)
runtime.cloud.complete(dest, SYSTEM, [{"role":"user","content": assemble_context(allowed)+question}])

# multi-turn caller (chat/session): additionally gate turns
allowed, _ = _disclosure_gate(rows, cfg, identity, project)
safe_turns  = _gate_conversation(history, cfg, identity, project)   # existing
runtime.cloud.complete(dest, SYSTEM, build_messages(assemble_context(allowed), safe_turns, question))
```

- **Golden test records at `CloudClient.complete()`** (the one sink both shapes hit) **and**
  at the **remote-arm transport** (the other off-machine path). It seeds known PII /
  local-only / cross-identity content and asserts it never appears in any recorded payload,
  across `ask` **and** `chat` **and** both `kage_ask` modes. Data-seeded (not purely
  structural), but it covers every off-machine sink — which the v2 single-function spec did not.
- **Local Ollama / embed do NOT pass through here** (localhost, on-machine, exempt — §10).
- `assemble_context` is the only *new* code; it removes the row-assembly duplication that
  single-shot + stateless share. The multi-turn path keeps its turn-gating on top.

Non-seam functions (`_disclosure_gate`, `_search`, `_rrf_fuse`, `_rerank`, `_session_*`,
`_chunk_note`, `_pii_scan`) call seams via `runtime`; they stay normal functions, move to
topic modules in Slice 4.

---

## 6. Final module layout (goal 2 — fixed now, realized in Slice 4)

```
kage/
  runtime.py    seam holder + reset() (§4)
  http.py       _post_json (shared low-level; leaf)
  config.py     Config                          (leaf)
  store.py      Store                           (← config)
  embed.py      Embedder + _ollama_status       (← config, http)
  vector.py     VectorIndex                     (← config, embed)
  cloud.py      CloudClient + ProviderRegistry  (← config, http)
  chunk.py      [done] pure
  pii.py        [done] pure
  privacy.py    _disclosure_gate, _gate_conversation, _write_audit, assemble_context (← pii, runtime)
  retrieval.py  _search, _search_fts, _rrf_fuse, _rerank, _get_reranker, _RERANK_POOL, _reranker_cache (← runtime, chunk)
  notes.py      _save, reindex-body, import-body, _read_body, _read_section (← runtime, chunk)  [NEW]
  context.py    _resolve_context, _read_active, _write_active             (← config)  [NEW]
  session.py    _session_*, _condense_query, _new_id                      (← runtime)
  arms.py       _detect_arms/_call_arm/_connect_arm/_select_tool/_serialize_arm_result/
                _check_arm_health/_get_google_token[DORMANT] + ArmRegistry (← runtime, config)
  cli.py        Typer commands ONLY + call-time forwarder shims + _disp
  mcp_server.py [exists] (← runtime + notes + session + privacy + context)
```
DAG strictly one-directional: `http/config → {store, embed} → vector → cloud → runtime →
{privacy, retrieval, notes, context, session, arms} → cli`. Nothing imports `cli`. No cycles.

**`mcp_server.py` (cold review M4 + #2 DAG fix):** it calls ~23 `_cli._*` symbols and has its
own Ollama egress + gate-before-sink logic. It repoints to `runtime` **and several topic
modules** (`notes`, `session`, `privacy`, `context`) — not just `runtime`; the cloud path
goes through the §5.6 sink. Kept working via §4 call-time forwarders during transition; final
repoint listed per slice (§9).

## 6.5 Function → destination map (completeness — cold review #2)

Every `cli.py` def accounted for. "Forwarder" = stays callable as `cli.X` via §4 call-time
shim. Commands stay in `cli.py` (Typer entry points) but call seams/topic-modules via `runtime`.

| Destination | Functions / symbols |
|---|---|
| http.py | `_post_json` |
| config.py (Config) | `_config`→`.data`; `KAGE_HOME`/`CONFIG_PATH`/`CHROMA_DIR`/`STATE_PATH`→`.paths` |
| store.py (Store) | `_connect`→`.connect`; `init` DDL **+ 3 ALTER guards**→`.init_schema`; `_allowed_note_ids`→`.allowed_note_ids`; `_require_init` (calls Store) |
| embed.py (Embedder) | `_embed`→`.embed`; `_ollama_status`→`.status` |
| vector.py (VectorIndex) | `_get_chroma`→`.collection`; `_search_vec`→`.search`; add/delete used by notes/forget |
| cloud.py (CloudClient) | `_call_cloud_chat`→`.complete`; `_call_cloud`→ wrapper; `DEFAULT_PROVIDERS`; (registry Slice 5) |
| chunk.py [done] | `_split_on_headers`, `_hard_windows`, `_window_by_pieces`, `_chunk_note` |
| pii.py [done] | `_PII_PATTERNS`, `_pii_scan` |
| privacy.py | `_disclosure_gate`, `_gate_conversation`, `_write_audit`, `assemble_context` [new] |
| retrieval.py | `_search`, `_search_fts`, `_rrf_fuse`, `_rerank`, `_get_reranker`, `_RERANK_POOL`, `_reranker_cache` |
| **notes.py [new]** | `_save`, `reindex`-body, `import_`-body, `_read_body`, `_read_section` |
| **context.py [new]** | `_resolve_context`, `_read_active`, `_write_active` |
| session.py | `_session_create/_load/_append/_turns/_switch`, `_session_approvals`, `_condense_query`, `_new_id` |
| arms.py | `_detect_arms`, `_call_arm`, `_connect_arm`, `_select_tool`, `_serialize_arm_result`, `_check_arm_health`, `_get_google_token`[DORMANT], `ARM_KEYWORDS`, `_arm_tool_cache` |
| cli.py (commands + forwarders) | `main`, `init`, `remember`, `import_`, `reindex`, `list_`, `recall`, `ask`, `forget`, `status`, `doctor`, `migrate`, `chat`, `use_`, `where`, `arm_auth`, `mcp_serve`, `_disp`, `_migrate_identity_axis` |

Notes:
- **`_save`/`reindex`/`import_` straddle Store+Embedder+VectorIndex** → they live in `notes.py`
  (above the seams, below cli), so `mcp_server` can import them without touching `cli`. During
  Slice 2/3 they **stay in cli and just repoint** their seam calls to `runtime`; they **move**
  to `notes.py` only in Slice 4. So Slices 2 and 3 stay cleanly separable (nothing straddles a slice).
- **`migrate`/`_migrate_identity_axis`** — raw-SQL data migration; command stays in cli, calls Store.
- **Dormant Google/`sse` path** (`_get_google_token`, `arm_auth`, the `sse` branch) → moves
  **verbatim, stays inert**, keeps its DORMANT banner. Not dead code to delete.
- **status vs doctor** convention (locked project concept) preserved — both stay command-level
  in cli, calling Store/Embedder.status/VectorIndex; the split must not blur them.

## 7. Registries (goal 3 — designed now, built Slice 5)

- **ProviderRegistry** (`cloud.py`): `register_provider_type(name, dispatch_fn)` replaces the
  claude/openai-compat/gemini ladder. Built-ins self-register. Real second users exist (5 providers).
- **ArmRegistry** (`arms.py`): `register_arm(name, keywords, transport, handler)`. **Handlers are
  `async`** (cold review M2 — arms use `await`/`sse_client`/`stdio`); registry stores coroutine
  functions. Formalizes `ARM_KEYWORDS` + config arms + `shell`/`stdio`/`sse` dispatch.
- Agents (Layer 2, future) reuse the ArmRegistry pattern — **out of scope** (no second user yet).

## 8. Test architecture (end-to-end — fixed now)

- **`tests/fakes.py`** (new): `FakeEmbedder`, `FakeVectorIndex` (in-mem dict), `FakeStore`
  (temp sqlite), `RecordingCloud` (captures every `.complete()` payload), `FakeConfig`
  (inline dict + temp home). Each implements its §5 Protocol.
- **Conversion recipe:** `monkeypatch.setattr(cli, "_embed", …)` →
  `monkeypatch.setattr(runtime, "embed", FakeEmbedder([...]))`.
- **`fakes` fixture:** builds a default seam set + configures `runtime`, auto-reset by teardown.
- **Thread-safety (cold review #2):** `_search` hits FTS + vector from a `ThreadPoolExecutor`,
  so `FakeEmbedder`/`FakeVectorIndex` must be safe under concurrent `.embed`/`.search` (no shared
  mutable cursor; return fresh lists). Cheap to honor; easy to forget.
- Boundary + pure-unit untouched. Egress golden (records at `CloudClient.complete()` + remote-arm
  transport, §5.6) + seam-swap tests added.

---

## 9. Slice sequence (each = one PR through the 7-step gate)

```
Slice 0  Analysis only — THIS audit + /security-review baseline                [docs, no code]
Slice 1  runtime + http + Config + CloudClient(thin) + assemble_context + gate-before-sink
         at ask/chat/mcp + EGRESS GOLDEN TESTS (record at complete() + remote-arm)  ← security-first
Slice 2  Embedder + VectorIndex   (the ~135-patch seam — biggest win; _save/reindex repoint, stay in cli)
Slice 3  Store + finish Config     (~26 patches; raw SQL stays — DB swap deferred)
Slice 4  File splits: http/privacy/retrieval/notes/context/session/arms leave cli.py
Slice 5  ProviderRegistry + ArmRegistry (goal 3)
```

**Why Slice 1 first:** the gated egress chokepoint is both the architectural foundation
(`runtime`) and the **security boundary**. Building `dispatch_cloud` + `CloudClient` first
means the golden tests record against the final interface → never rewritten.
"Security-first" and "architecture-first" are the same move. Slice 1 wraps existing dispatch
with **no behavior change**; the provider-registry refactor of its internals waits for Slice 5.

Per slice: cloud plans → local writes seam + converts that slice's tests (R1/R2) → cloud
reviews (hard, silent-miss + forwarder-rule focus) → cloud plans new tests → local writes →
cloud reviews → local runs full suite (**green before merge**). Mistake-log every correction.

## 10. Invariants — must never regress (any slice)

- Identity × project wall (`Store.allowed_note_ids`)
- **Egress invariant (precise):** withheld **note content** (PII / local_only / cross-identity)
  must never reach a **cloud provider** or a **remote arm (SSE)**. **Local Ollama / embed are
  exempt** (localhost, on-machine — that is the whole point of routing locally). The Slice-1
  golden tests enforce the cloud half by guarding `dispatch_cloud`; the remote-arm half is a
  separate recorder asserting withheld content is not passed to a remote-transport arm.
- Save-wall (#16 — no unconfirmed writes)

## 11. Ponytail guardrails (whole cycle)

- Exactly 5 seams + 2 registries (cold review confirmed none collapse). No framework, no agent registry yet.
- A seam method exists only if current code needs it. No repository CRUD nobody calls; `Store` stays thin.
- Seams default to real impls; injection is opt-in. Transition shims are call-time forwarders (§4).
- Convert a test only when its seam moves (R1), fully in the earliest slice when it spans slices (R2). Delete redundancy; don't port it.
- No registry until a second concrete user exists (providers/arms qualify; agents don't yet).
- Full suite green + boundary tests untouched at every slice boundary. One slice per PR. Correct over fast.

## 12. Open questions — resolved by cold review

1. `runtime` module-singletons vs threaded context → **singletons** (single-process); upgrade path noted (§4).
2. `Store` thin vs repository → **thin; DB swap deferred** (§1, §5.2).
3. Does CloudClient-first eliminate golden-test rework? → needed the §5.6 sink (record at
   existing `CloudClient.complete()`, both shapes funnel through it) + gate-before-sink, because
   gate≠assembly AND there are two egress shapes (single-shot + multi-turn). Fixed in v3.
4. Any §5 interface a later slice forces to change? → none found; arm handlers typed `async` up front (§7).
5. Over-engineering? → 5 seams + 2 registries justified (both reviews; reviewer #2 re-checked independently).
6. (review #2) Completeness — every cli.py def mapped? → yes now (§6.5); `notes.py`/`context.py` added.
7. (review #2) Does the egress sink cover multi-turn (`chat`/session)? → yes — both shapes funnel
   through `CloudClient.complete()` (post-WI-2); golden test records there + remote-arm (§5.6, §10).
