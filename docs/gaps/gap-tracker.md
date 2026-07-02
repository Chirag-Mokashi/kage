# kage Agent Gap Tracker

*Created: 2026-06-28. Source: post-Cycle-16 code review of scout.py, librarian.py, monitor.py, observe.py.*
*Update this file as each gap is fixed — change status and add the fix commit/PR.*

---

## Status legend

```
  OPEN      — not yet fixed
  IN FLIGHT — being worked on in current cycle
  FIXED     — merged, note the PR
```

---

## Gap list

*All 10 gaps FIXED in Cycle 17 (PR #23, merged to main). Verified present in code as of v0.25.0 (2026-07-02). Section detail below is retained as the original review record.*

| ID  | Agent     | Priority | Status | PR  |
|-----|-----------|----------|--------|-----|
| G01 | Scout     | HIGH     | FIXED  | #23 |
| G02 | Scout     | HIGH     | FIXED  | #23 |
| G03 | Scout→Lib | HIGH     | FIXED  | #23 |
| G04 | Librarian | MED      | FIXED  | #23 |
| G05 | Librarian | HIGH     | FIXED  | #23 |
| G06 | Librarian | LOW      | FIXED  | #23 |
| G07 | Monitor   | MED      | FIXED  | #23 |
| G08 | Monitor   | MED      | FIXED  | #23 |
| G09 | Observe   | MED      | FIXED  | #23 |
| G10 | Observe   | LOW      | FIXED  | #23 |

---

## G01 — Scout `_pii_seam` is a pass-through stub

**File:** [src/kage/scout.py](../../src/kage/scout.py)

**What it is:**
`_pii_seam` in scout.py is `return None`. ScoutIntegrate (cloud stage) has
`before_model_callback=_pii_seam` wired, but the function does nothing. The
real concern is `scout_recall` — it returns excerpts from personal memory notes
(`~/.kage/memory/*.md`). Those excerpts land in `llm_request.contents` as tool
results and go to the cloud model unredacted.

**Right fix:**
Replace the stub body with the same 4-line delegation used in monitor.py:
```python
def _pii_seam(callback_context, llm_request):
    if llm_request.contents:
        for content in llm_request.contents:
            if hasattr(content, "parts"):
                for part in content.parts:
                    if hasattr(part, "text") and part.text:
                        part.text = _gate_text(part.text)
    return None
```
Requires importing `_gate_text` from `kage.pii`.

**What it fixes:**
Personal memory excerpts returned by `scout_recall` are scrubbed before they
reach the cloud model. The 3e disclosure gate claim holds end-to-end in Scout.

---

## G02 — Scout never writes to `scout_runs` table

**File:** [src/kage/scout.py](../../src/kage/scout.py)

**What it is:**
Monitor's `read_pipeline_state` queries `SELECT created_at, notes_fetched FROM
scout_runs`. That table is never created or written by scout.py. The try/except
in monitor.py exists entirely to paper over this. Monitor always reports
`scout_last_run=None, scout_items_today=0` — the "Scout hasn't run in 48h"
alert condition is structurally unreachable.

**Right fix:**
At the end of `scout.run()`, after `_write_report()`:
```python
conn = runtime.store.connect()
conn.execute(
    "CREATE TABLE IF NOT EXISTS scout_runs "
    "(created_at TEXT, notes_fetched INTEGER, mode TEXT)"
)
conn.execute(
    "INSERT INTO scout_runs (created_at, notes_fetched, mode) VALUES (?, ?, ?)",
    (datetime.now().astimezone().isoformat(timespec="seconds"), len(items), mode),
)
conn.commit()
conn.close()
```

**What it fixes:**
Monitor can now read real Scout run history. The 48h staleness alert becomes
live. `read_pipeline_state` returns accurate data for the first time.

---

## G03 — Scout report never reaches Librarian's staging queue

**Files:** [src/kage/scout.py](../../src/kage/scout.py), [src/kage/librarian.py](../../src/kage/librarian.py)

**What it is:**
Scout writes its output to `~/.kage/scout/YYYY-MM-DD.md`. Librarian processes
`staging_queue`. Nothing in scout.py calls `deposit_to_queue`. The three-agent
pipeline (Scout → Librarian → Monitor) does not exist as running code — it is
three independent modules that happen to share a database.

**Right fix:**
After `_write_report()` in `scout.run()`, parse Tier 1 lines from the final
output and deposit each one:
```python
from kage.librarian import deposit_to_queue

in_tier1 = False
for line in final.splitlines():
    if line.startswith("## Tier 1"):
        in_tier1 = True
        continue
    if line.startswith("## Tier 2") or line.startswith("---"):
        break
    if in_tier1 and line.startswith("- "):
        deposit_to_queue(line.lstrip("- "), source="scout", project=project)
```

**What it fixes:**
Every Scout run automatically seeds Librarian's queue with Tier 1 items. The
pipeline flows end-to-end without manual intervention. This is the biggest
single plumbing gap in the three-agent system.

---

## G04 — Librarian falls back to wrong config key `default_provider`

**File:** [src/kage/librarian.py](../../src/kage/librarian.py) lines 373, 695

**What it is:**
Two places fall back to `cfg.get("default_provider", "claude")`. The actual
top-level key in `~/.kage/config.json` is `"cloud_provider"`, not
`"default_provider"`. The key doesn't exist so the lookup always falls through
to the hardcoded string `"claude"`. Works only if `ANTHROPIC_API_KEY` is set —
silently ignores the user's openrouter-free routing config.

**Right fix:**
Change both occurrences to match the pattern Scout and Monitor use:
```python
cfg.get("librarian", {}).get("cloud_provider", cfg.get("cloud_provider", "claude"))
```

**What it fixes:**
Librarian respects the user's default cloud provider. If openrouter-free is
configured as default, Librarian uses it instead of silently forcing Claude.

---

## G05 — `staging_queue.priority` migration split across two modules

**Files:** [src/kage/librarian.py](../../src/kage/librarian.py), [src/kage/monitor.py](../../src/kage/monitor.py)

**What it is:**
`staging_queue` is created in Librarian's `_apply_migrations`. The `priority`
column is added in Monitor's `_apply_migrations`. Librarian's
`get_staging_queue` queries `ORDER BY priority DESC, created_at ASC`. If
Monitor has never run, the column doesn't exist and Librarian crashes with
`sqlite3.OperationalError: no such column: priority` on the first queue fetch.

**Right fix:**
Move the `ALTER TABLE staging_queue ADD COLUMN priority` into Librarian's
`_apply_migrations`, right after the `CREATE TABLE staging_queue` block.
Wrap in try/except for idempotency (same pattern already used there). Monitor's
migration can stay as-is — it will no-op if the column already exists.

**What it fixes:**
Librarian runs on a fresh install without Monitor having been run first. The
order-of-operations crash is eliminated.

---

## G06 — Librarian: no rate limiting between cloud calls

**File:** [src/kage/librarian.py](../../src/kage/librarian.py)

**What it is:**
`distill_and_judge` makes one cloud API call per staging item with no pause.
50 pending items = 50 sequential cloud calls. Most providers rate-limit on
requests-per-minute; openrouter-free is capped at 200 req/day per model.
A large backlog can exhaust the daily quota in one run.

**Right fix (ponytail):**
Add `time.sleep(0.5)` after each cloud call in `distill_and_judge`, capping
throughput at ~120 req/min. Or expose `max_items` config so Librarian only
drains N items per run:
```python
items = get_staging_queue()[:cfg.get("librarian", {}).get("max_items_per_run", 20)]
```

**What it fixes:**
Librarian doesn't burn the day's quota on a large backlog. Graceful
throughput regardless of queue size.

---

## G07 — MonitorDigest has no `output_key` — fragile event scanning

**File:** [src/kage/monitor.py](../../src/kage/monitor.py)

**What it is:**
`_run_once_impl` reads the digest by scanning `runner.run()` events and
overwriting `digest` with every text part found — last text event wins. If
thinking traces, tool call echoes, or intermediate text fire after the real
digest, the captured output is wrong. Scout and Librarian both use
`output_key` + re-fetch from session state, which is the deterministic pattern.

**Right fix:**
Add `output_key="monitor_digest"` to `digest_agent` in `build_monitor`, then
read from re-fetched session state instead of scanning events:
```python
session = await runner.session_service.get_session(...)
digest = session.state.get("monitor_digest") or ""
```

**What it fixes:**
Digest capture is deterministic regardless of what ADK emits in the event
stream. Mirrors the Scout/Librarian pattern consistently.

---

## G08 — `check_mcp_health` non-shell path only checks binary existence

**File:** [src/kage/monitor.py](../../src/kage/monitor.py)

**What it is:**
For arms with `transport != "shell"`, health check does
`shutil.which(mcp_cmd.split()[0])` — returns `{"status": "healthy"}` if the
binary is in PATH. Does not check if the server is actually running. A crashed
stdio server reports healthy.

**Right fix:**
For stdio arms, attempt to start the process, send a JSON-RPC `initialize`
ping, and check for a valid response within timeout. For SSE arms, attempt an
HTTP GET to the configured endpoint URL.

**What it fixes:**
`check_mcp_health` becomes a real liveness check, not a "binary installed?"
check. MonitorObserve can actually detect a crashed MCP server and fire an
alert.

---

## G09 — `_observe_loop` polling events always have `app=""`

**File:** [src/kage/observe.py](../../src/kage/observe.py)

**What it is:**
The 10-second polling loop creates `ObserveEvent` with `app=""` — it reads AX
text and window title from the focused element but never queries which
application is frontmost. Only NSWorkspace app-switch events (fired when
switching apps) populate `app` and `bundle`. All "stayed in same app" events —
which is the majority of screen time — have an empty app field.

**Right fix:**
Query `NSWorkspace.sharedWorkspace().frontmostApplication()` in the poll loop:
```python
try:
    from AppKit import NSWorkspace
    app_info = NSWorkspace.sharedWorkspace().frontmostApplication()
    app_name = app_info.localizedName() or ""
    bundle   = app_info.bundleIdentifier() or ""
except Exception:
    app_name, bundle = "", ""
```

**What it fixes:**
Monitor's `read_observe_log` can answer "what was the user working in?" for
the full monitoring window. Currently all polling events are anonymous —
the bulk of screen time is invisible to Monitor.

---

## G10 — `read_observe_log` multi-day file coverage is wrong

**File:** [src/kage/observe.py](../../src/kage/observe.py)

**What it is:**
`read_observe_log` reads `today.jsonl` always, plus `yesterday.jsonl` if
`hours > 12`. If called with `hours=48`, it still only reads 2 files — the
timestamp cutoff is applied correctly but the file iteration never opens
files older than yesterday.

**Right fix:**
Compute days to look back from the hours parameter:
```python
days_back = int(hours / 24) + 1
for i in range(days_back + 1):
    day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
    files.append(kage_dir / f"{day}.jsonl")
```

**What it fixes:**
Callers requesting longer windows (hours=48, hours=72) get real data from
the correct number of daily files.

---

## Planned (not yet a cycle)

| ID  | Feature               | Notes |
|-----|-----------------------|-------|
| P01 | Sensitive vault       | `~/.kage/sensitive.json` + bootstrap scan + Monitor discovery + `kage sensitive review` CLI. Regex patterns for detection only; vault for exact-value redaction. Covers Indian documents (Aadhaar, PAN, UPI) + international. |
