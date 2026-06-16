# Cycle 10.5 — Active Context

*Status: PITCH (cloud-authored plan, Opus). Cold-reviewed once by an independent no-context agent; the three critical correctness findings are folded in. To be built per the locked 7-step dev workflow: plan cloud → write local (Qwen3) → review cloud → plan tests cloud → write tests local → review tests cloud → run tests local. Created 2026-06-15.*

*Scope was deliberately cut: this cycle implements **active context only**. The Layer 3a signal-chain abstraction (pluggable `Signal` interface, calendar/cwd stubs) is explicitly NOT built here — pre-building it changes the objective. The resolver is a plain function; a future signal is just another branch in it.*

---

## One line

kage gains a persistent, kage-owned pointer to the current `(identity, project)` — "active context" — set once via `kage use`, honored by every surface (CLI, MCP/Claude, Odysseus) without restating it on each call.

## Appetite

Half-cycle. One focused sitting. **The competition is NOT gated on this** — if it lands fast, use it; if it drags, start the competition with explicit `--identity` flags and finish this alongside.

## Version / branch

`v0.10.1` (additive, backward-compatible). Branch `cycle-10.5`.

---

## Problem

Identity + project must be restated on every call. Unset reads default to `personal`; the MCP write tool `kage_remember` hard-codes `personal` and has no `identity` param at all (`mcp_server.py:34`). There is no "where am I working" pointer, so kage can't be the thing that remembers context — the user has to, on every surface. That is backwards for a broker.

## Solution

A plain resolver consulted at the command / MCP layer:

```
_resolve_context(arg_identity, arg_project) -> (identity, project, source)

    active = _read_active()                    # {} if missing / corrupt
    identity = arg_identity or active.get("identity") or "personal"     # always concrete
    project  = arg_project if arg_project is not None else active.get("project")
    source   = "explicit" if arg_identity else ("sticky" if active.get("identity") else "fallback")
    return (identity, project, source)
```

Precedence: **explicit arg → sticky (state store) → fallback (`personal` / no project)**. `project=None` is a legitimate resolved value (means "all projects + baseline" per `_allowed_note_ids`, `cli.py:586`), distinct from "unresolved"; `source` still reports `sticky` when the sticky project is `None`.

---

## The hard contract (correctness — NOT seams, do not skip)

`None` is **not** a safe value through the engine: `_allowed_note_ids` binds `:identity` into `WHERE mi.identity = :identity` (`cli.py:583`), so a `None` identity silently returns an **empty wall**, not "identical behavior." Therefore:

1. **The resolver is total** — it always returns a concrete identity (fallback guarantees `("personal", None)`), and it runs **before any value reaches `_search` / `_allowed_note_ids`.**
2. **Do NOT change the defaults of** `_save`, `_search_fts`, `_search_vec`, or `_disclosure_gate`. They keep `"personal"` / `None` as today. The resolver substitutes a concrete identity *above* them. Flipping their defaults buys nothing and risks empty-wall bugs.
3. Only **CLI option defaults** and **MCP tool params** flip to `None` → resolved in the command body before the first `_search`.

This preserves `test_save_writes_personal_identity_by_default` (`test_cli.py:783`) and the MCP recall/ask tests (`test_cli.py:2157-2242`). All 338 existing tests must stay green — that is the gate on this cycle.

## State store

`~/.kage/state.json`, separate from `config.json` (config is user-authored and error-swallowing; active context is machine-written runtime state — same convention as `audit.jsonl` / `kage.db` living outside config). Two mandatory properties:

1. **Path derives from `KAGE_HOME`**, not `Path.home()` (mirror `CONFIG_PATH`, `cli.py:49`) — otherwise the dev machine's real `state.json` leaks into the test suite and makes it flaky.
2. **Atomic write** — temp file + `os.replace` — so a concurrent `kage where` / Odysseus read cannot observe a torn write. Corrupt / missing → silent fallback to `{}` (defense in depth).

## Sessions carve-out (do not break Cycle 10)

`kage_ask(session_id=...)` (`mcp_server.py:71`) and `kage chat` (`cli.py:2008`) take identity/project from the **pinned session row**, not params. So:

- Active context **seeds a new session once** at `chat` startup / `session_create`.
- It **never re-resolves per turn and never overrides a live session.** The Cycle 10 "session is pinned" invariant is preserved.

## `kage_remember` footgun

The MCP tool takes a **scalar** `identity`, but `_save` expects `identities: list[str]`. Must wrap `identities=[identity]`. Passing the bare string makes the join-table loop iterate characters (`for ident in "neu"` → `n`, `e`, `u`). Explicit in step 5.

---

## Surface

```
kage use neu/kaggle-capstone     set active context (identity/project)
kage use neu                     identity only, project cleared
kage use --clear                 reset to fallback (personal / none)
kage where                       show resolved context + its source   (Aware / Transparent)
```

- `kage use` mirrors `kubectl use-context` / `nvm use`.
- **`kage where` calls `_resolve_context`** (shows the winning source), not just the raw sticky store — so it stays truthful if signals are added later.
- **`kage status`** gains a single read-only echo line of active context; counts stay un-filtered (no scope creep).

---

## Implementation order (each step = full 7-step gate + mistake-log entry)

1. **State store** — `_read_active` / `_write_active`, `KAGE_HOME`-derived path, atomic write, corrupt/missing → `{}`
2. **`_resolve_context`** — flat explicit → sticky → fallback, total; **dedicated precedence unit tests**
3. **`kage use` / `kage where`** — `where` calls the resolver
4. **Wire CLI** — `recall` / `ask` / `list` / `remember` default via resolver when flag omitted; explicit flag always wins; backward-compat tests
5. **Wire MCP** — `kage_recall` / `kage_ask` / `kage_remember` resolve when args omitted; add scalar `identity` to `kage_remember` (wrap as `[identity]`); **leave the `session_id` branch and `chat` pinning untouched**
6. **`kage status`** — echo line for active context
7. **Integration wall test** — `use neu/kaggle-capstone` → `remember` → `recall` returns the note → a `personal` query does **not** (proves both walls hold under the new flow)
8. **Docs** — README command table + a short retro at the bottom of this file

---

## Out of scope (deliberately deferred)

- Pluggable `Signal` interface / resolver chain
- Calendar signal, terminal-cwd signal
- Per-signal opt-in toggles, audit of context changes
- Auto-flip / watcher (daemon era)

None of these are stubbed in this cycle. When Layer 3a is built for real, the resolver gains branches; nothing here is throwaway.

## Decisions locked for this cycle

- State location: separate `state.json` (KAGE_HOME path, atomic write) — endorsed by cold review.
- `use` syntax: slash form `neu/kaggle-capstone`.
- Project name for the competition: `kaggle-capstone` (distinct from `hsi` → cleaner soft-wall test). **Note:** kage creates no partition until the user explicitly starts the project.

---

## Retro

**Shipped 2026-06-15. 347 tests, 338 pre-existing all green.**

- Steps 1-3 (state store, resolver, `kage use`/`where`) landed cleanly. Qwen3 reproduced both functions correctly on first try; only PEP-8 fix (missing blank line) needed on apply.
- Step 4 (CLI wire): Qwen3 correctly identified all four commands and the `identity → None` default flip.
- Step 5 (MCP wire): `kage_remember` footgun confirmed — Qwen3 correctly added `identity` param and wrapped `[identity]` for `_save`. The `kage_ask` session branch was left untouched.
- Step 6 (status echo): applied directly (1-line addition).
- **Key bug caught during test writing**: `STATE_PATH` was not in the existing `_mcp_home` inline monkeypatch dicts. After `kage use` is run on the real machine, `~/.kage/state.json` would have leaked into all MCP test runs — resolver would read "neu" identity from the real file and break "personal"-identity tests. Fixed by `replace_all` across 45 occurrences.
- **FTS anomaly**: test `test_wall_holds_under_active_context` originally used `_search` end-to-end. SQLite FTS5 returned "personal diary entry" for query "kaggle capstone" (unexpected). Root cause unclear (possible FTS thread/index interaction in tests). Fixed by testing the wall directly via `_allowed_note_ids` — cleaner assertion and closer to the actual invariant anyway.
- **Mistake log entry** (2026-06-15, Step 7 tests): Qwen3 generated tests that relied on FTS search returning 0 results for a query with no term overlap. SQLite FTS5 behavior under ThreadPoolExecutor in tests was inconsistent. Pattern: test identity wall invariants at the wall layer (`_allowed_note_ids`), not at the search layer.
