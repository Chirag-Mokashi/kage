# Cycle 17 — Agent Gap Fixes (v0.18.0)

*Status: PITCH v3 (2026-06-28). Gaps identified via post-Cycle-16 code review. v3 = 2 cold reviews complete (4 BLOCKERs + 10 WARNs resolved total).*
*Detailed gap definitions live in [docs/gaps/gap-tracker.md](gaps/gap-tracker.md).*
*Built per the 7-step dev workflow: plan cloud → write local (Qwen3) → review cloud → plan tests cloud → write tests local → review tests cloud → run tests local.*

---

## North star

> Fix the ten structural gaps that prevent the Scout → Librarian → Monitor
> pipeline from running end-to-end. No new features. No new abstractions.
> The pipeline exists in the pitch; this cycle makes it exist in the code.

---

## What this cycle is NOT

- Not a new agent or capability
- Not the sensitive vault (P01 — separate cycle)
- Not UI or CLI surface changes (except what gaps require)
- Not a refactor

---

## Gaps in scope (priority order)

```
  HIGH — pipeline is broken or crashes without these
  ────────────────────────────────────────────────────────────────────
  G05  staging_queue.priority migration split → Librarian crashes
  G03  Scout → Librarian deposit link missing → pipeline doesn't flow
  G02  Scout never writes scout_runs → Monitor blind to Scout
  G01  Scout _pii_seam stub → personal memory hits cloud unredacted

  MED — pipeline works but gives wrong results
  ────────────────────────────────────────────────────────────────────
  G04  Librarian wrong config key → silently ignores cloud routing
  G07  MonitorDigest no output_key → fragile event scan
  G09  observe _observe_loop app="" → Monitor can't see what user works in
  G08  check_mcp_health non-shell path → reports "healthy" for dead servers

  LOW — edge cases and rate limits
  ────────────────────────────────────────────────────────────────────
  G10  read_observe_log multi-day coverage wrong
  G06  Librarian no rate limiting between cloud calls
```

---

## Implementation steps

Each step is a self-contained diff. Steps within a priority tier can be
ordered freely; steps across tiers must respect HIGH → MED → LOW order.
Each step follows the 7-step gate: cloud plans → local writes → cloud reviews.

---

### Step 1 — G05: Move `priority` migration into Librarian

**File:** `src/kage/librarian.py`

Add `ALTER TABLE staging_queue ADD COLUMN priority INTEGER DEFAULT 0` (with
try/except) to Librarian's `_apply_migrations`, right after the
`CREATE TABLE staging_queue` block. Monitor's migration stays (idempotent
no-op if column already exists).

**Test:** `test_librarian_run_without_monitor_migration` — call
`get_staging_queue()` on a fresh DB where Monitor's `_apply_migrations` has
never run. Must not raise.

---

### Step 2 — G02: Scout writes `scout_runs` after each run

**File:** `src/kage/scout.py`

After `_write_report()` in `scout.run()`, create the table if needed and
insert a row with `created_at`, `notes_fetched`, `mode`. Use
`runtime.store.connect()` (same pattern as all other DB writes in the
codebase).

**CRITICAL — FakeRuntime stub update required:** 5 existing scout tests define
an inline `FakeRuntime` class (each test has its OWN inline definition) with
only a `.config` attribute. These are NOT a single shared class — there are 5
separate inline definitions inside:
`test_run_filters_seen_items_from_corpus`, `test_bootstrap_seeds_cache`,
`test_run_refuses_on_empty_cache`, `test_dry_run_skips_report_and_cache`,
`test_run_calls_run_once_with_corpus`.

Qwen3 must update ALL 5 inline `FakeRuntime` definitions to add a `.store`
attribute (a real `Store` pointed at a tmp db, or a `MagicMock()`). Do NOT
assume a single class to patch. Alternatively, replace all 5 with a shared
`@pytest.fixture` and update callers. Either approach is acceptable.

**Test:** `test_scout_run_writes_scout_runs` — call `scout.run(mode="bootstrap")`
with mocked `fetch` and `build_pipeline`, with an isolated store. Assert
`scout_runs` table has one row with correct `notes_fetched` count.

---

### Step 3 — G03: Scout deposits Tier 1 items into Librarian queue

**File:** `src/kage/scout.py`

After `_write_report()`, parse `## Tier 1` section of `final` output and
call `librarian.deposit_to_queue` for each `- ` line. Guard with try/except
so a Librarian DB error never aborts the Scout run. Only deposit when
`mode != "dry-run"` (dry-run writes nothing by design).

**Correct `deposit_to_queue` signature:**
```python
deposit_to_queue(content, source, reason="", project=None, identity=None)
```
`source` is positional. Call as:
```python
deposit_to_queue(line.lstrip("- "), "scout", project=project)
```

**Project context:** `project` is NOT in scope at the point of deposit in
`scout.run()`. `_resolve_context` IS already imported in scout.py (line 11).
Call it unconditionally at the top of `run()` to get the active project:
```python
ctx = _resolve_context(None, None)
project = ctx.get("project")
```
Then pass `project=project` to `deposit_to_queue`. No hedge needed.

**CRITICAL — same FakeRuntime issue as Step 2:** `deposit_to_queue` calls
`_connect()` → `runtime.store.connect()`. The FakeRuntime stub fix from Step 2
covers this — Steps 2 and 3 share the same stub update. Implement them together.

**Test:** `test_scout_deposits_tier1_to_queue` — mock `_write_report` and
patch `deposit_to_queue` at `kage.librarian.deposit_to_queue`. Assert it was
called for each Tier 1 item and not for Tier 2 items. Use isolated store
(same as Step 2 fixture).

---

### Step 4 — G01: Scout `_pii_seam` real gate

**File:** `src/kage/scout.py`

Replace the `return None` stub with the 4-line `_gate_text` delegation used
in `monitor.py:_pii_seam`. Add `from kage.pii import _gate_text` to imports.

**Test:** `test_scout_pii_seam_strips_email` — construct a fake
`llm_request` with an email in `contents[0].parts[0].text`. Call `_pii_seam`.
Assert the email is replaced with `[REDACTED_PII]`.

---

### Step 5 — G04: Librarian correct config key fallback

**File:** `src/kage/librarian.py`

Two changes (lines 373 and 695). The actual expressions in the code are:
```python
# before (both locations):
cfg.get("librarian", {}).get("cloud_provider", cfg.get("default_provider", "claude"))
# after (both locations):
cfg.get("librarian", {}).get("cloud_provider", cfg.get("cloud_provider", "claude"))
```
Only the innermost fallback key changes: `"default_provider"` → `"cloud_provider"`.
The outer `librarian.cloud_provider` lookup is already correct. Make sure to
search for and change ONLY the inner fallback, not the outer expression.

**Test:** `test_librarian_uses_cloud_provider_key` — `distill_and_judge`
reads config via `runtime.config.data`, NOT from a function argument (its
signature is `distill_and_judge(content: str, source: str)`). To inject a
test config, monkeypatch `runtime.config.data` to a dict with only
`"cloud_provider": "openrouter-free"` (no `"default_provider"` key). Also
monkeypatch `_litellm_target` to return a dummy `("model", "key", None)` tuple
to avoid a real API call. Call `distill_and_judge("test content", "scout")`.
Assert `_litellm_target` was called with `provider="openrouter-free"`.

---

### Step 6 — G07: MonitorDigest `output_key`

**File:** `src/kage/monitor.py`

Add `output_key="monitor_digest"` to `digest_agent` in `build_monitor`.
In `_run_once_impl`, replace the event-scan loop with a session state re-fetch.

**Async pattern warning:** `_run_once_impl` uses a mixed sync/async pattern —
`runner.run()` is called synchronously with a separate `asyncio.run()` for
session creation. The session re-fetch must use a NEW `asyncio.run()` call:
```python
session = asyncio.run(runner.session_service.get_session(
    app_name="kage-monitor", user_id="kage", session_id=session.id
))
digest = (session.state.get("monitor_digest") or "") if session else ""
```
`InMemoryRunner` stores session data in-process (not event-loop-local), so
a second `asyncio.run()` can read the same session. This is safe here — do
NOT refactor `_run_once_impl` into a full async wrapper (out of scope).

**Test:** `test_monitor_digest_output_key_set` — call `build_monitor` with
a minimal cfg. Assert `digest_agent.output_key == "monitor_digest"`.

---

### Step 7 — G09: observe polling loop fills `app` field

**File:** `src/kage/observe.py`

In `_observe_loop`, before creating `ObserveEvent`, query the frontmost app.

**Import strategy:** Add `NSWorkspace` as a module-level import in `observe.py`
with a non-macOS guard (the same guard already used there for PyObjC imports).
Do NOT use a local `from AppKit import NSWorkspace` inside the loop body —
local imports cannot be patched by monkeypatch at test time.

Pattern to follow (already exists in observe.py for other PyObjC imports):
```python
try:
    from AppKit import NSWorkspace as _NSWorkspace
except ImportError:
    _NSWorkspace = None
```

Then in `_observe_loop`:
```python
try:
    fi = _NSWorkspace.sharedWorkspace().frontmostApplication()
    app_name = fi.localizedName() or ""
    bundle   = fi.bundleIdentifier() or ""
except Exception:
    app_name, bundle = "", ""
```
Pass `app=app_name, bundle=bundle` to `ObserveEvent`.

**Test:** `test_observe_poll_fills_app` — because `_NSWorkspace` is now a
module-level name in `kage.observe`, it CAN be patched:
```python
monkeypatch.setattr("kage.observe._NSWorkspace", FakeNSWorkspace)
```
where `FakeNSWorkspace.sharedWorkspace()` returns a fake app object with
`localizedName() == "Xcode"` and `bundleIdentifier() == "com.apple.dt.Xcode"`.
Assert the written JSONL event has `"app": "Xcode"`.

---

### Step 8 — G08: `check_mcp_health` stdio liveness check

**File:** `src/kage/monitor.py`

For stdio arms, replace the `shutil.which` check with a real process spawn
and JSON-RPC `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}` ping.
Read one line of stdout. Mark healthy if a valid JSON response arrives within
the 3s timeout; degraded if exit code non-zero; timeout if no response.

**Test:** `test_check_mcp_health_stdio_dead_process` — mock
`asyncio.create_subprocess_exec` to return a process that exits immediately
with code 1. Assert status is `"degraded"` not `"healthy"`.

---

### Step 9 — G10: `read_observe_log` multi-day file iteration

**File:** `src/kage/observe.py`

Replace the hardcoded `today + yesterday` logic with a loop.
`timedelta` is already imported — no new import needed.

Correct formula (no off-by-one):
```python
days_back = int(hours / 24) + 1
for i in range(days_back):      # NOT range(days_back + 1) — that reads one extra file
    day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
    files.append(kage_dir / f"{day}.jsonl")
```
Remove the separate `if hours > 12` block.

**Test:** `test_read_observe_log_multi_day` — write JSONL files for today,
yesterday, and 2 days ago in tmp dir. Monkeypatch the kage_dir path. Call
`read_observe_log(hours=60)`. Assert events from all 3 files are returned.

---

### Step 10 — G06: Librarian rate limiting

**File:** `src/kage/librarian.py`

**Architecture note:** Librarian's queue drain is agent-driven — the ADK
`LlmAgent` follows the `_LIBRARIAN_INSTRUCTION` prompt and calls
`get_staging_queue()` itself. There is no Python-level for-loop to cap with
`[:max_items]`. The cap must go INSIDE `get_staging_queue()`:

```python
def get_staging_queue(limit: int = 20) -> list[dict]:
    # existing query, add: LIMIT ?
    ...
    rows = conn.execute("SELECT ... ORDER BY priority DESC, created_at ASC LIMIT ?", (limit,)).fetchall()
```

Expose the default via config. There is no separate "wrapper" function —
`librarian.run(cfg)` calls `_run_once_impl` which calls `build_librarian`.
The cap cannot be injected at that level without session state. The simplest
correct approach: have `get_staging_queue` read from `runtime.config.data`
itself for the limit, the same way other functions read config:
```python
def get_staging_queue(limit: int | None = None) -> list[dict]:
    if limit is None:
        limit = runtime.config.data.get("librarian", {}).get("max_items_per_run", 20)
    # existing query with: ... ORDER BY priority DESC, created_at ASC LIMIT ?
    rows = conn.execute("SELECT ... LIMIT ?", (limit,)).fetchall()
```

**CLI behavior note:** `kage librarian queue` calls `get_staging_queue()` with
no arguments. After this change, the CLI will show at most 20 items (was
previously unbounded). This is the desired behavior, but document it in the
commit message.

Add `time.sleep` similarly: add `time.sleep(cfg.get("librarian", {}).get("call_delay_s", 0.5))`
inside `distill_and_judge` (reading from `runtime.config.data`), after the
`_litellm_target` call returns.

**Test:** `test_librarian_respects_max_items` — populate staging queue with
25 items. Call `get_staging_queue(limit=20)`. Assert only 20 items returned
(no mock of distill_and_judge needed — this tests the DB layer directly).

---

## Success criteria

- [ ] `uv run pytest -q` green (480+ tests, no regressions)
- [ ] `kage scout run` deposits Tier 1 items into `kage librarian queue`
- [ ] `kage monitor status` shows real Scout last-run timestamp
- [ ] `kage librarian run` on fresh install does not crash (priority column)
- [ ] `kage scout bootstrap` followed by `kage librarian run` works end-to-end
      without manual intervention

---

## What does NOT change

- No new CLI commands (unless a gap test forces it)
- No new dependencies
- No schema changes beyond the priority column move
- No change to the sensitive vault (P01 — separate cycle)
- `_PII_PATTERNS` regex list stays as-is

---

## Correction log seed

*Each cloud correction of Qwen3's output goes here during the build:*

```
(empty — build not yet started)
```

---

## Cold review checklist (mandatory before PR)

- [ ] Pitch cold review (subagent) — before any code
- [ ] Code cold review (cloud inline) — after each step
- [ ] Consolidated cold review (subagent) — before PR

*Track count: v3, 2 cold reviews (subagents, 2026-06-28). 4 BLOCKERs + 10 WARNs resolved across v2 + v3. Ready for implementation.*
