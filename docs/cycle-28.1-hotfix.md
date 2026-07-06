# Cycle 28.1 — Write-Wall Hotfix (v0.28.1)

*Status: PITCH v2 — 1 cold review done (subagent, against repo at HEAD; verdict APPROVE WITH EDITS — all 9 findings incorporated below). Ready for the 7-step gate.*
*Discipline: 7-step dev-workflow gate. Local (Qwen3) writes all code/tests; cloud plans + reviews.*
*Date: 2026-07-06. Source: Fable 5 full-codebase audit (post-v0.28.0).*

---

## Problem

The v0.28.0 audit found that **Cycle 28's identity-group invariant was wired into only
one of kage's three memory writers** (CLI `remember`/`import`). The other two writers
(MCP `kage_remember`, Librarian approve) still hand-roll identity tagging, producing a
wall bypass and silent data loss. Plus five smaller defects in observe/monitor/cloud/
calendar-write/registry, all found in the same audit.

Ranked findings:

| ID | Sev | Where | Defect |
|----|-----|-------|--------|
| B1 | HIGH | `mcp_server.py:51` | `kage_remember` skips the read-only check AND `active_group` — MCP clients can write as `family`/`burner` (when `mcp_allow_writes`), and notes tagged `personal-us` (label, not group) |
| B2 | HIGH | `librarian.py:663-666` | Librarian approve inserts the raw staging label into `memory_identities`. Reads resolve labels→groups, so a note tagged `personal-us` matches **no query from any identity, ever** — invisible-note data loss |
| B3 | MED | `observe.py:148, 226` | `SELECT … FROM sessions ORDER BY updated_at` — column doesn't exist; broad `except` swallows it; **every observation ever written is tagged `identity="personal", project=""`**. Blocks Cycle 29 Slice 1 (Monitor→Librarian context timeline) |
| B4 | MED | `monitor.py:160` | Health check uses `create_subprocess_shell(cmd + " --help")` — bypasses the `shlex.split`+`exec` pattern and interpreter blocklist that `arms.py` enforces on the same config values |
| B5 | LOW | `cloud.py:59-62` | Gemini API key in URL query string (leaks into proxies/logs); Gemini supports `x-goog-api-key` header |
| B6 | LOW | `identity.py:14-23` | Corrupt `identities.json` → empty registry → read-only wall silently OFF (fail-open on a security wall) |
| B7 | LOW | `calendar_write.py:169-171`; gate/identity/observe writers | `reject()` doesn't check status (executed proposal relabeled `rejected` while the event stays); PII-bearing files (`privacy_queue.jsonl`, `allowlist.json`, `identities.json`, `sensitive.json`, `audit.jsonl`, `observe/*.jsonl`) written with default perms |

**Root cause (B1/B2):** the write-identity invariant lives in call sites, not in a
chokepoint. Cycle 27 hardened egress by enumerating all 11 egress sites; Cycle 28
never enumerated the write sites.

## Appetite

1–2 days. This is a hotfix cycle: no new features beyond one `kage identity repair`
command and one `kage doctor` check (both are the runnable checks for the fix).
Version: **v0.28.1** (patch semver — behavior corrections, no new surface worth a minor).

## Solution — 5 slices

### Slice 1 — Write-identity chokepoint (fixes B1 + B2, prevents the class)

New function in `identity.py` (the ONE place the write invariant lives):

```python
class ReadOnlyIdentityError(ValueError):
    """Raised when a write is attempted as a read-only identity."""

def resolve_write_identity(label: str) -> str:
    """Group-resolve a label for tagging a memory write; raise if read-only.
    EVERY writer to memory_identities MUST route its tag through this.
    Built on get_identity directly (NOT active_class/active_group) so that
    RegistryCorruptError (Slice 4.2) propagates AS ITSELF — callers must
    distinguish 'you may not write' from 'the registry is unreadable'."""
    entry = get_identity(label) or {}     # RegistryCorruptError propagates
    if entry.get("class", "normal") == "read-only":
        raise ReadOnlyIdentityError(f"read-only identity '{label}' cannot write to memory")
    return entry.get("group", label)
```

**The write-site enumeration (per the new rule — cold review corrected v1's false
count of 2; grep finds FOUR INSERT sites into `memory_identities`):**

| # | Site | Tag source | Wire-in |
|---|------|-----------|---------|
| 1 | `cli.py:242` (inside `_save`) | caller-passed `identities` list | chokepoint lives here |
| 2 | `librarian.py:664` (inside `write_note`) | staging row label | resolve + error split below |
| 3 | `librarian.py:566` (`_emit_ctm_note`) | hardcoded `'personal'` | one-line `resolve_write_identity("personal")` — today safe only because `personal` happens to be canonical; make it invariant, not coincidence |
| 4 | `librarian.py:998` (rejection correction-log writer) | hardcoded `'personal'` | same one-liner |

Read paths: `store.allowed_note_ids` (group-resolved via `cli.py:296-298`) is the
active one. **Known dormant seam:** `librarian.locate_memory` (`librarian.py:145`)
filters `mi.identity = ?` with NO group resolution — inert today (every caller
passes `identity=None`) but a future caller passing a label recreates B2 on the
read side. Add a one-line comment at that filter pointing here; no code change.

Wire-in detail:

1. **`cli._save`** — resolve **once at the top of `_save`**
   (`identities = [resolve_write_identity(i) for i in (identities or ["personal"])]`)
   so the `identities:` frontmatter (`cli.py:223-227`) AND the DB insert
   (`cli.py:240-244`) both receive the group — resolving only at the INSERT would
   recreate the exact markdown/DB drift the repair command exists to fix. The
   existing explicit checks in `remember`/`import_` STAY — friendly CLI error
   before any work; `_save` is the belt-and-suspenders layer. `_save` lets
   `ReadOnlyIdentityError` propagate; `remember`/`import_` never reach it, MCP
   catches it. (`_save` has exactly three callers — `cli.py:612`, `cli.py:659`,
   `mcp_server.py:51` — and `identities=None` → `["personal"]`; verified no caller
   breaks.)
2. **`mcp_server.kage_remember`** — wrap the `_save` call: catch `ReadOnlyIdentityError`
   → return `{"saved": False, "reason": "read-only identity cannot write"}`. (Group
   resolution now happens inside `_save`, so the `identities=[identity]` call is fixed
   for free.)
3. **`librarian.write_note` (the direct-INSERT path, `librarian.py:590`; called from
   `cli.py:1798`)** — before the `memory_identities` insert:
   `identity = _identity.resolve_write_identity(identity)`. **Error handling splits
   two ways (cold-review finding #2 — do NOT conflate):**
   - `ReadOnlyIdentityError` (genuine read-only identity) → mark the approval
     decision rejected with reason `"read-only identity"`, return False.
   - `RegistryCorruptError` (registry unreadable) → **abort leaving the approval
     row UNDECIDED** with a loud stderr error, return False. A transiently corrupt
     `identities.json` must never convert pending approvals into recorded
     rejections — that would also feed the EPM rejection-learning loop garbage.

**Repair for existing orphans** — new `kage identity repair`:
- Detect: `SELECT DISTINCT identity FROM memory_identities` → any tag where
  `active_group(tag) != tag` is an orphan tag.
- Repair (per orphan tag, atomic): `INSERT OR IGNORE INTO memory_identities(mem_id, identity)
  SELECT mem_id, :group FROM memory_identities WHERE identity = :tag` then
  `DELETE FROM memory_identities WHERE identity = :tag`. Also rewrite the
  `identities:` frontmatter list in each affected note's markdown (human-readable
  layer must match the DB — additive-layer principle). **Frontmatter rewrite must
  dedupe:** the PK `(mem_id, identity)` permits a note tagged with BOTH
  `personal-us` and `personal`; `INSERT OR IGNORE`+`DELETE` handles the DB, but a
  naive line-rewrite would leave `- personal` twice. (Chroma/FTS unaffected —
  neither carries identity.)
- Prints per-tag counts; `--dry-run` flag lists without changing.

**Doctor check (the invariant made runnable):** `kage doctor` gains one check —
"identity tags canonical": every distinct tag in `memory_identities` satisfies
`active_group(tag) == tag`. FAIL lists the orphan tags and points at
`kage identity repair`. (Convention: doctor = pass/fail health — this fits.)
**Corruption ordering (cold-review finding #5):** the check FAILs immediately on
`RegistryCorruptError` BEFORE evaluating tags — with `active_group` degrading to
`label` on corruption, tag evaluation would silently PASS while the registry is
unreadable, exactly when the wall is most in doubt.

### Slice 2 — observe.py context fix (fixes B3)

Replace BOTH broken `sessions ORDER BY updated_at` queries (`_observe_loop` and
`_AppSwitchObserver.handle_`) with the active-context resolver — the same source
every other kage operation uses:

```python
from kage.context import _resolve_context   # imports only runtime — no cycle
...
identity, project, _src = _resolve_context(None, None)
project = project or ""
```

- Extract the duplicated block into one `_active_context() -> tuple[str, str]` helper
  used by both call sites (it exists twice today; that duplication is how the bug
  shipped twice).
- Drop the `runtime.store.connect()` sessions query entirely — `kage use` state IS
  the active context; the sessions table was the wrong source even if the column
  had existed.
- **Test rule (new, from this bug):** any module executing SQL gets at least one test
  against a real `init_schema()` database — no monkeypatched connection. (observe.py
  no longer executes SQL after this fix, but monitor.py does; add the real-schema
  test there: `read_session_log` (`monitor.py:112`) against a real DB.)

### Slice 3 — Monitor health-check exec (fixes B4)

In `monitor.py` `check_mcp_health` (`monitor.py:147`) shell branch, replace
`create_subprocess_shell(cmd + " --help")` with the arms.py pattern. The snippet
goes **inside the existing `if cmd:` branch** (`monitor.py:157-158`) — keep that
guard, or empty/whitespace commands hit `IndexError` on `parts[0]` and report
`"list index out of range"` instead of `"no command"`:

```python
if cmd:                       # existing guard — PRESERVE
    parts = shlex.split(cmd)  # ValueError on unbalanced quotes → outer except (fine)
    if not parts or parts[0].rsplit("/", 1)[-1] in _SHELL_INTERPRETERS:
        result[name] = {"status": "blocked", "error": "interpreter", "latency_ms": 0}
        continue
    proc = await asyncio.create_subprocess_exec(*parts, "--help",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
```

Import `_SHELL_INTERPRETERS` from `kage.arms` (single source of truth; do NOT copy
the frozenset).

### Slice 4 — Small fixes (B5, B6, B7)

1. **Gemini key → header** (`cloud.py::_dispatch_gemini`): URL becomes
   `.../models/{model}:generateContent` (no `?key=`); pass
   `headers={"x-goog-api-key": key}` to `_post_json`.
2. **Registry fail-closed on corruption** (`identity.py`): distinguish the two
   failure modes —
   - `FileNotFoundError` → `{"identities": []}` unchanged (fresh install, wall
     legitimately absent — this MUST stay fail-open or the existing test suite,
     which mostly runs without an identities.json, breaks).
   - Any other error (bad JSON, perms) → `load_identities` raises new
     `RegistryCorruptError`; **`get_identity` propagates it** (this is what lets
     `resolve_write_identity` see corruption as corruption).
   - `active_class` catches it → returns **"read-only"** (fail-closed for the arm
     paths: corrupt registry blocks write-arms; read arms keep working).
   - `active_group` catches → returns `label`; `identity_arm_overrides` catches → `{}`.
     `kage identity list` surfaces the corrupt state with the underlying error
     instead of showing an empty registry.
3. **`reject()` status guard** (`calendar_write.py`): mirror `approve()` —
   `if p.get("status") != "pending": raise RuntimeError(f"proposal {id} is {status}, not pending")`.
4. **chmod 600 on PII-bearing files**: tiny best-effort helper `_chmod600(path)`
   (3 lines, `try/except OSError: pass`) homed in **`runtime.py`** — NOT `gate.py`
   (cold-review finding #8: identity/observe importing the privacy gate for a
   chmod adds coupling; runtime is already imported by every module). Applied
   after write in: `save_allowlist`, `append_queue`, `save_queue`, `sensitive.json`
   write site, `identity.save_identities`, `privacy._write_audit` (first-create
   only — NOT per append; it's called on every dispatch), `observe._write_event`
   (first-create only, same reason).

### Slice 5 — Tests + workflow amendment

Tests (all written by local per the gate):
- Slice 1: `resolve_write_identity` unit tests (normal→group, read-only→raises,
  unknown→label); `_save` rejects read-only tag; MCP `kage_remember` as read-only
  identity returns `saved: False`; MCP save as `personal-us` lands tagged `personal`;
  Librarian `write_note` with read-only staging identity → decision rejected, no note
  row; `write_note` with `personal-us` staging identity → note tagged `personal` and
  **findable from a `personal` query** (the end-to-end invisible-note regression test);
  `write_note` under corrupt registry → approval row stays UNDECIDED (not rejected);
  `_emit_ctm_note` + rejection-log writer route through the chokepoint;
  `kage identity repair` migrates an orphaned tag + frontmatter (incl. the
  dual-tag dedupe case); doctor check PASS/FAIL both directions + FAIL on corrupt
  registry before tag evaluation.
- Slice 2: `_active_context()` honors `kage use` state; falls back to
  `personal`/`""` with no state file. Monitor `read_session_log` real-schema test.
- Slice 3: interpreter command → `blocked`; command with shell metacharacters
  (`echo hi; touch /tmp/x`) does NOT execute the second command (assert file absent).
- Slice 4: Gemini dispatch URL contains no key + header does; corrupt
  `identities.json` → `active_class` returns read-only + `remember` blocked;
  `reject()` on executed proposal raises; written files have mode 600.
- **Restore-coverage golden tests** (closes the audit's near-miss): for `chat`,
  MCP session, and MCP single-shot paths — fake cloud returns text containing the
  placeholder; assert the final user-visible answer contains the real value.
  (`ask` already has one; this makes it symmetric with the egress golden tests.)

Estimated new tests: ~30. Target: 720 → ~750, all green.

Workflow amendment (CLAUDE.md, cold-review section) — two rules, both paid for
by this cycle's bugs:

> **Invariant enumeration rule:** when a cycle changes a shared invariant (identity
> tagging, gate coverage, audit format …), the pitch MUST contain the enumerated
> list of ALL call sites of that seam (grep output pasted into the doc), and the
> cold review checks the list, not the diff — and the reviewer INDEPENDENTLY
> re-runs the grep rather than trusting the pitch's list (this pitch's own v1
> enumeration was wrong: it claimed 2 write sites, grep finds 4). (Cycle 27 did
> this for 11 egress sites and egress is clean; Cycle 28 didn't for the write
> sites — of 4, 2 broke outright and 2 were safe only by coincidence.)

> **Real-schema test rule:** any module that executes SQL has at least one test
> against a real `init_schema()` database — monkeypatched connections cannot catch
> schema drift (observe.py `updated_at` shipped broken at both call sites).

**The write-site enumeration for THIS cycle lives in Slice 1** (four INSERT sites
plus one dormant read seam). Instructive note for the doc trail: pitch v1 claimed
two write sites "verified by grep" — the cold review found four. The enumeration
rule only works if the review independently re-runs the grep; that step is now
part of the rule.

## Rabbit holes

- **Do NOT refactor Librarian to call `cli._save`** — its direct-INSERT path exists
  deliberately (custom mem_id slugs, tags column, single-chunk convention). Route
  only the *identity tag* through the chokepoint, not the whole write.
- **Do NOT add a migrations framework** for the repair — it's one UPDATE-shaped fix
  with a dry-run flag, not Alembic.
- **Do NOT make `observe.py` re-read state.json per keystroke-pause event** — per
  event is fine (it's one small file read every ≥10s; measure only if it shows up).
- **Fail-closed scope stays at identity.py** — do not generalize a "fail-closed
  config" framework across modules in this cycle.

## No-gos

- No delete/reschedule for calendar (still gated on signed-helper identity).
- No Orchestrator work (that's its own cycle; this hotfix must stay small).
- No new PII patterns or gate changes beyond chmod.

## Ship checklist

1. Branch `cycle-28.1-write-wall` off main.
2. 7-step gate per slice; slices 1+2 are security-critical → subagent cold review
   on code AND tests; slices 3–5 cloud-inline review.
3. One consolidated subagent cold review of the whole diff before PR.
4. `kage identity repair --dry-run` then `repair` on the live store; paste output
   into the PR.
5. CHANGELOG + README (identity repair command, doctor check) + this doc status
   flip; CLAUDE.md workflow amendment in the same PR.
6. CI green → merge → tag v0.28.1.
