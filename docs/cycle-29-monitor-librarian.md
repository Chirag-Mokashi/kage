# Cycle 29 — Monitor→Librarian Pipeline + Librarian HITL + Scout Gate (v2, PLAN — one cold review incorporated)

*Status: PLAN (cloud-authored 2026-07-05; v2 cold-review fixes 2026-07-05). Ready to build.*
*Discipline: 7-step dev-workflow gate. Local writes code/tests; cloud reviews every slice.*
*Related: [[project_cycle29_plan]], [[project_agent_testing_playbook]], [[feedback_dev_workflow]]*

> **v3 changelog (cold review #2, adversarial vs real code):** Two new blockers fixed:
> **B1** Timestamp in deposit content body defeats SHA256 dedup — every digest cycle deposited a
> new item regardless of state change. Fixed: header is now `"## Monitor context snapshot"` (no
> live timestamp); `created_at` is already stored as a DB column. T3 rewritten accordingly.
> **B2** T1/T2/T3 would crash because `read_pipeline_state()` calls `_connect()` internally —
> tests that only mock `_read_active` hit a real DB. Fixed: pitch now specifies monkeypatching
> `monitor.read_pipeline_state` to return a fixed dict for T1/T2; T3 uses the `mon_env` fixture
> for real DB dedup testing.
> Two warns also addressed: **W1** `hours_since_scout_run` None→"never" guard now explicit in D1;
> **W2** T10 split into T10/T11, downstream tests renumbered to T12–T15, total count updated to ≥15.
> NIT N1 (delete-action note_json has no title/body) noted in D5.
>
> **v2 changelog (cold review #1, adversarial vs real code):** Six blockers fixed:
> **B1** `deposit_to_queue` signature corrected — has `reason` param between `source` and `project`;
> Key Facts #3 and D1 step 5 updated to show correct 5-arg signature and keyword-arg call.
> **B2** `_read_state_json()` does not exist — replaced with `read_pipeline_state()` (the DB-backed
> function at monitor.py:61) in D1 step 2.
> **B3** Key Facts #2 now shows complete end of `_digest_impl()` including `_maybe_trigger_learn`
> (line 747); insertion point for deposit call is between `_write_state_json` and `_maybe_trigger_learn`.
> **B4** T4 updated to also mock `_maybe_trigger_learn` (it calls subprocess; test would fail without mock).
> **B5** D1 step 3 now explicitly names the JSONL field as `r["findings"]` (not `content` or any other key).
> **B6** D5 now specifies that the approval prompt loop must be inside the `from kage import librarian as _lib`
> scope in `librarian_run()`.
> Five warns also addressed: W7 circular-import reasoning corrected (monitor has no existing librarian import;
> new import is unidirectional and safe); W8 D3 insertion point clarified (`_emit_ctm_note` is the adjacent
> function); W9 CLI display spec now says `json.loads(item["note_json"])` explicitly; W10 D7 now writes to
> `scout_runs` DB table (not `~/.kage/state.json` which is the context file); W11 T10 patch target
> corrected to `kage.librarian.write_note`.

---

## Why

Three agents are live — Monitor (eyes), Scout (research hands), Librarian (memory hands) —
but they don't talk. Kaggle judges score multi-agent architecture; the current system has
none visible. Separately, two hard bugs broke the Librarian HITL promise:

1. **Monitor never deposits to Librarian.** `_digest_impl()` writes a `.md` file and stops.
   No structured context flows from Monitor's observations into Librarian's memory pipeline.
   Judges see three isolated agents, not a system.

2. **Librarian's approval queue is invisible.** After `kage librarian run`, items move into
   `approval_queue`. But `kage librarian queue` shows the *staging* queue (wrong table). There
   is no `list_pending_approvals()` function. The user has no way to discover what needs their
   decision — IDs are unknowable without raw SQLite access. HITL is broken by design.

3. **Scout runs without user approval.** `kage scout run` dispatches immediately to the cloud
   (Qwen3 + OpenRouter) with no confirm prompt. User explicitly: "Scout should always run
   after I tell it to, not before, not after. Gated by user permission only."

---

## What Cycle 29 IS / IS NOT

**IS:**
- A `_deposit_context_snapshot()` function in `monitor.py`, called at end of `_digest_impl()`
- Structured markdown deposits from Monitor to Librarian's staging queue (source="monitor")
- A new `list_pending_approvals()` function in `librarian.py` (queries `approval_queue WHERE decision IS NULL`)
- Reworked `kage librarian queue`: two sections — awaiting approval (full detail) + staging backlog (counts)
- Reworked `kage librarian run` CLI: after processing, surfaces pending approvals with inline [a]/[r]/[s] prompt
- A `--yes / -y` flag on `kage scout run` and a blocking confirm prompt without it

**IS NOT:**
- AX-based identity inference (reading active Mail account from Accessibility tree — deferred to v2)
- Identity-switch tracking via `kage use` event log (no such log exists today)
- Raw AX event forwarding to Librarian (too noisy; snapshot only)
- Orchestrator (brain) — that is a future agent; this cycle wires only Monitor→Librarian
- Librarian inline cloud calling during approval (the judge already ran; approval just writes)
- Any changes to Monitor's launchd plists or observe cadence

---

## Key Facts from Reading the Code

### 1. Where active project/identity lives (`src/kage/context.py`)

`context._read_active()` reads `runtime.config.state_path` → JSON `{"identity": "...", "project": "..."}`.
This is set by `kage use` and is the only ground truth for active context. Monitor can import and call it.

### 2. Where `_digest_impl()` ends (`src/kage/monitor.py:741`)

```python
(monitor_dir / f"{today}.md").write_text(digest)     # line 741
_write_state_json({                                    # line 742
    "last_updated": datetime.now(timezone.utc).isoformat(),
    "digest_preview": digest[:200] if digest else "",
})                                                     # line 745

_maybe_trigger_learn(Path(runtime.config.home))        # line 747 — last statement
```

The insertion point for the Monitor deposit call is **between `_write_state_json(...)` (line 745)
and `_maybe_trigger_learn(...)` (line 747)**. Insert `_deposit_context_snapshot(...)` there.

### 3. `deposit_to_queue()` signature (`src/kage/librarian.py:174`)

```python
def deposit_to_queue(content: str, source: str, reason: str = "",
                     project: str | None = None, identity: str | None = None) -> str:
```

SHA256[:16] dedup: identical content is silently idempotent. Returns staging item id (always str).
**Critical:** `reason` is the third positional arg — always pass `project` and `identity` as keyword
arguments to avoid silently assigning the project string to `reason`.

### 4. `approval_queue` schema (`src/kage/librarian.py:61`)

```
id                TEXT PRIMARY KEY
staging_id        TEXT                (FK → staging_queue.id)
note_id           TEXT
action            TEXT                ('promote' | 'delete' | 'move' | 'merge')
reason            TEXT
sanitized_preview TEXT
note_json         TEXT                (JSON: {title, body, tags, project, identity, ...})
created_at        TEXT
decided_at        TEXT
decision          TEXT                (NULL = pending; 'approved' | 'rejected' = decided)
```

`note_json` holds the full proposed note — title, body, tags, project, identity.
This is what needs to be shown to the user in `kage librarian queue`.

### 5. `kage librarian queue` current implementation (`src/kage/cli.py:1821`)

```python
items = _lib.get_staging_queue(status=status)   # ← wrong table for approvals
for item in items[:10]:
    preview = (item.get("content", "") or "")[:80].replace("\n", " ")
    typer.echo(f"  {item['id'][:8]}  {item['source']:<10}  {preview}")
```

Shows staging_queue items (raw content, 80-char truncated). Approval queue never shown.

### 6. `kage librarian run` current implementation (`src/kage/cli.py:1785`)

```python
result = _lib.run(cfg)
typer.echo(result)
```

Prints whatever `run()` returns (a string). No post-run approval surfacing.

### 7. No Scout launchd plist (verified)

`launchctl list | grep -i scout` → empty. No plist to remove. Only need to add the gate
in the CLI command.

### 8. `kage scout run` current flow (`src/kage/cli.py`)

Calls `scout.run(mode="run")` with no confirmation gate. Cloud tokens consumed immediately.

---

## Slice 1 — Monitor → Librarian pipeline

**Goal:** After each digest cycle, Monitor deposits a structured session-context snapshot
into Librarian's staging queue. Identity-stamped. Project-stamped. Not raw AX noise.

### What the deposit contains

```markdown
## Monitor context snapshot

**Active project:** {project or 'none'}
**Active identity:** {identity}

### Recent activity (AX observer summary)
{last 3 observation findings, max 600 chars total}

### Pipeline state
- Scout last run: {hours_since_scout_run}h ago  (or: never)
- Librarian queue depth: {librarian_queue_depth} pending
- Memory notes: {memory_count} total
```

This is a snapshot — not the full 300-word digest (that's for human reading). Librarian
receives structured facts with correct project/identity labeling.

### Implementation steps

**D1 — `monitor.py`**: Add `_deposit_context_snapshot(digest_summary: str) -> None`:

1. `from kage.context import _read_active` — read `{identity, project}`.
2. Call `read_pipeline_state()` (existing function, `monitor.py:61`) for `hours_since_scout_run`,
   `librarian_queue_depth`, `memory_count`. Guard the None case:
   `hours_display = f"{state['hours_since_scout_run']}h ago" if state.get("hours_since_scout_run") is not None else "never"`.
3. Read last 3 observation entries from today's JSONL, extracting `r["findings"]` field
   from each record (not `r["content"]` or any other key). Fall back to `digest_summary[:600]`
   if the JSONL is missing or empty.
4. Format the structured markdown block (template above). **Do not include a live timestamp
   in the content body** — the `created_at` DB column records deposit time. The content header
   is `"## Monitor context snapshot"` (no timestamp). Without this, every call produces a
   unique hash and SHA256 dedup never fires.
5. `from kage.librarian import deposit_to_queue` — call with keyword args:
   `deposit_to_queue(content, source="monitor", project=active.get("project"), identity=active.get("identity"))`.
   Do NOT pass `project` or `identity` positionally — the third positional is `reason`.

**D2 — `monitor.py` `_digest_impl()`**: Insert `_deposit_context_snapshot(digest[:600] if digest else "")`
**between `_write_state_json(...)` (line 745) and `_maybe_trigger_learn(...)` (line 747)**.

Circular import note: `monitor.py` has no existing import of `librarian`. The new `from kage.librarian
import deposit_to_queue` is a new unidirectional dependency (monitor → librarian). Safe because
`librarian.py` does not import `monitor.py`. Use a local import inside `_deposit_context_snapshot`
to match the pattern of `_maybe_trigger_learn`'s local imports.

### Test plan (Slice 1)

Mock pattern for T1/T2: monkeypatch `monitor.read_pipeline_state` (return fixed dict with
`hours_since_scout_run=2.5`, `librarian_queue_depth=1`, `memory_count=42`) AND
`monitor._read_active` (return `{"identity": "personal", "project": "kage"}`). Also monkeypatch
`monitor.deposit_to_queue` (or `kage.librarian.deposit_to_queue`) to capture calls. Do NOT
let `read_pipeline_state()` hit the real DB — its internal `_connect()` call will fail in
unit test context without a DB fixture.

- T1: `_deposit_context_snapshot("summary")` (with above mocks) calls `deposit_to_queue` with
  `source="monitor"`, `project="kage"`, `identity="personal"`.
- T2: Snapshot content (captured from `deposit_to_queue` mock call) contains
  `"Active project:"`, `"Active identity:"`, `"Pipeline state"`, and `"2.5h ago"`.
- T3: (integration — uses `mon_env` fixture for real DB) Call `_deposit_context_snapshot("same")`
  twice with mocked `read_pipeline_state` and `_read_active` returning identical dicts.
  Query `staging_queue WHERE source='monitor'` — assert count == 1 (dedup fired).
- T4: `_digest_impl()` calls `_deposit_context_snapshot()` — monkeypatch `_write_state_json`,
  `_deposit_context_snapshot`, AND `_maybe_trigger_learn` (it calls subprocess; must be mocked);
  assert `_deposit_context_snapshot` is called once.

---

## Slice 2 — Librarian HITL fix

**Goal:** User can always see what's awaiting approval and act on it with one command.
Two changes: (a) new function in `librarian.py`, (b) reworked CLI commands in `cli.py`.

### New function `list_pending_approvals()` in `librarian.py`

```python
def list_pending_approvals() -> list[dict]:
    """Return approval_queue items with decision IS NULL, newest last."""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT aq.id, aq.action, aq.reason, aq.note_json, aq.sanitized_preview, "
        "aq.created_at, sq.source AS source "
        "FROM approval_queue aq "
        "LEFT JOIN staging_queue sq ON sq.id = aq.staging_id "
        "WHERE aq.decision IS NULL ORDER BY aq.created_at ASC"
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
```

Each returned dict: `{id, action, reason, note_json (raw JSON string — must json.loads() before dict access), sanitized_preview, created_at, source}`.

### Reworked `kage librarian queue` (in `cli.py`)

Replace the current single-table display with two sections:

```
=== Awaiting your approval (N items) ===

  [abc12345]
  Title:   ...json.loads(item["note_json"]).get("title", "")...
  Body:    ...json.loads(item["note_json"]).get("body", "")[:200]...
  Reason:  ...librarian's reason...
  Source:  scout    Action: promote
  Created: 2026-07-05T14:32:00
  → kage librarian approve abc12345
  → kage librarian reject abc12345

=== Staging backlog (N pending items) ===
  scout: 3   monitor: 1   user: 0
```

Approval section uses `list_pending_approvals()`.
Staging section uses `get_staging_queue(status="pending")` — counts by source only
(no content preview).

### Reworked `kage librarian run` (in `cli.py`)

After `typer.echo(result)`, call `list_pending_approvals()`. If non-empty:

```
─── 1 item awaiting your approval ───
  [abc12345] promote — "Title here"
  Reason: ... (one line)
  Body excerpt: ... (100 chars)
  [a]pprove / [r]eject / [s]kip:
```

For each pending item in order. `a` calls `_lib.write_note(approval_id)`, `r` calls
`_lib.reject_approval(approval_id, "")`, `s` skips (leaves in queue for later).

### Implementation steps

**D3 — `librarian.py`**: Add `list_pending_approvals()` after `request_approval()` (ends ~line 523),
before `_emit_ctm_note` (~line 526).

**D4 — `cli.py` `librarian_queue()`**: Replace `items = _lib.get_staging_queue(status=status)`
with two-section output. Remove the `--held` flag (simplify: approvals section covers the
important case; held items are edge case, demote to `--held` sub-option only if needed).

**D5 — `cli.py` `librarian_run()`**: The approval prompt loop must be **inside** the
`from kage import librarian as _lib` scope in `librarian_run()`. After `typer.echo(result)`,
call `_lib.list_pending_approvals()`. For each pending item, call `json.loads(item["note_json"])`
to get title/body, then print with inline `[a]/[r]/[s]` prompt via `typer.prompt()`.
Response `"a"` → `_lib.write_note(item["id"])`; `"r"` → `_lib.reject_approval(item["id"], "")`; `"s"` → continue.
Note: delete-action items have `note_json={"note_id":..., "action":"delete"}` with no title/body —
`.get("title","")` returns `""`, which is acceptable to display as blank.

### Test plan (Slice 2)

- T5: `list_pending_approvals()` returns only rows where `decision IS NULL`.
- T6: `list_pending_approvals()` returns `[]` when all decisions are set.
- T7: Returned dicts include keys: `id`, `action`, `reason`, `note_json`, `source`, `created_at`.
- T8: `librarian_queue` CLI output (mocked `list_pending_approvals()` returning 1 item)
  contains "Awaiting your approval" and shows the approval id, title, approve command.
- T9: `librarian_queue` CLI output (mocked `get_staging_queue()` returning 2 items with
  sources scout/monitor) contains "Staging backlog" with counts.
- T10: `librarian_run` CLI (monkeypatch `kage.librarian.run`, `kage.librarian.list_pending_approvals`
  returning 1 item with valid `note_json`, `typer.prompt` returning `"a"`) →
  `kage.librarian.write_note` called once with the item's id.
- T11: Same setup but `typer.prompt` returns `"s"` → `kage.librarian.write_note` never called,
  `kage.librarian.reject_approval` never called.

---

## Slice 3 — Scout gate

**Goal:** `kage scout run` never fires without explicit user confirmation.

### Implementation steps

**D6 — `cli.py` `scout_run()`**: Add `yes: bool = typer.Option(False, "--yes", "-y")`.
Without `--yes`, print:

```
Scout will run now. This uses cloud tokens (~5min, OpenRouter).
Proceed? [y/N]:
```

Abort on anything other than `y` / `yes` (case-insensitive).

**D7 — `cli.py` `scout_run()`**: On confirmed run, the `scout_runs` table already records every
run via `INSERT INTO scout_runs (created_at, notes_fetched, mode)`. No additional state write
needed — `kage scout status` can read `last_approved_run` from `scout_runs WHERE mode='run' ORDER BY
created_at DESC`. Do NOT write to `~/.kage/state.json` (that is the context active-state file,
owned by `context.py`; writing to it corrupts identity/project state).

No launchd plist to remove (confirmed: none registered).

### Test plan (Slice 3)

- T12: `scout_run(yes=False)` with `typer.prompt()` mocked to return `"n"` → `scout.run()`
  never called.
- T13: `scout_run(yes=False)` with prompt mocked to return `"y"` → `scout.run()` called once.
- T14: `scout_run(yes=True)` → `scout.run()` called without any prompt interaction.

---

## Acceptance Criteria

Cycle 29 ships when:

- [ ] `kage monitor digest` → a new "monitor" item appears in `kage librarian queue` staging backlog
- [ ] `kage librarian queue` shows both sections: approvals (with full detail + commands) + staging counts
- [ ] `kage librarian run` → after processing, any new approvals are shown inline with [a]/[r]/[s] prompt
- [ ] `kage scout run` (without `--yes`) prints confirm prompt; `N` aborts; `y` proceeds
- [ ] All three slices have passing tests (≥14 new tests: T1–T4 + T5–T11 + T12–T14)
- [x] One cold review pass completed (subagent vs real code seams; 6 BLOCKERs + 5 WARNs fixed in v2)
- [ ] PR merges green CI

---

## Implementation Order

Slices are independent — no cross-slice dependencies. Recommended order:

```
Slice 3 (Scout gate)   — smallest; 3 tests; sanity check first
Slice 2 (HITL fix)     — no new external deps; 6 tests
Slice 1 (Monitor dep)  — last; touches two files; 4 tests
```

---

## Out of Scope (parked)

- AX-based identity inference from Accessibility tree (Layer 2 of Monitor, post-Kaggle)
- `kage use` event logging (would require a separate events table in kage.db)
- Orchestrator agent (brain — post-Kaggle)
- Scout→Librarian→Orchestrator feedback loop (deferred to post-Kaggle)
- Fixing "Scout not run in 48h" miscalibration in Monitor alert (deferred — unrelated to this cycle)
