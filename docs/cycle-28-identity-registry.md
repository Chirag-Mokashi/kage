# Cycle 28 — Identity Registry + Account-Scoped Arms (v3, PLAN — two cold reviews incorporated)

*Status: PLAN (cloud-authored 2026-07-03; v2/v3 cold-review fixes 2026-07-03). Awaiting Slice 1 start.*
*Discipline: 7-step dev-workflow gate. Local writes code/tests; cloud reviews every slice.*
*Related: [[project_identity_algorithm_separation]], [[project_two_pass_gate_vision]]*

> **v3 changelog (cold review #2, adversarial vs real code):** No new blockers. Five warns fixed:
> (W1) D3 now explicitly states detection fix AND merge are both in Slice 4 and both required — implementing
> one without the other silently breaks family dispatch. (W2) `mail_arm.scpt` code block now restores the
> `ponytail:` comment (3s = connection teardown, not query time). (W3) T11 specifies `asyncio.run()` +
> handler monkeypatch + exact assertion. (W4) `add-account` command semantics fully specified in Slice 2.
> (W5) D5 read-only guard comment corrected — "caller logs" was false; guard now explicitly calls `_write_audit`.
> NITs: `id` field dropped (YAGNI); "gitignored" → "outside repo tree"; per-query file-read ceiling noted
> in D3 with `ponytail:`; merged-dict stale `identity` field noted as a future-trap comment.
>
> **v2 changelog (cold review #1, adversarial vs real code):** Three blockers fixed:
> **B1 (detection wall):** `_detect_arms` filters `arm['identity'] == identity` — arms pinned to
> `personal` are invisible to `family`. Fix: `_detect_arms` accepts an arm if `arm['identity'] == identity`
> **OR** the active identity's registry entry has `arm_overrides[arm_name]`. Design section D3/D5 updated.
> **B2 (subprocess API):** D4 showed `subprocess.run(cmd.split() + extra)` — wrong. Real function is
> `asyncio.create_subprocess_exec(*shlex.split(cmd), ...)`. D4 and Key Facts §2 corrected.
> **B3 (AppleScript syntax):** Compound `whose name contains X or email addresses contains {X}` is
> invalid AppleScript. `name` is also the display name, not the email string. Fixed to
> `email addresses contains target_account` (sole predicate, no braces). Key Facts §3 and D4 corrected.
> Warns also addressed: T9 now specifies monkeypatch of a synthetic write-arm; D2 acknowledges the
> safe-default risk window; D4 explicitly notes injection safety from list-args exec.

---

## Why

Chirag maintains five email accounts for **algorithm hygiene** — not just data privacy.
Mixing a YouTube history trained on career videos with one trained on music/entertainment
collapses a deliberate wall he built by hand. kage inherits that wall. Today it partially
enforces it (identity matching on arm dispatch), but:

1. **No persistent registry.** Identity metadata lives scattered in `config.json` arm
   entries (`"identity": "personal"`). There is no single source of truth for what
   identities exist, what class they belong to, or which accounts they own.

2. **Arms are statically bound to one identity.** The gmail arm today is permanently
   wired to identity `personal`. When active identity is `family`, there is no way for
   kage to read `family@example.com` — even though `family` is a legitimate
   identity with its own Gmail account.

3. **No class enforcement.** kage has no concept of a `read-only` identity — an identity
   that kage may *read* for context (fetch calendar, fetch inbox) but must *never* act as
   (no writes, no sends, no calendar creates). The family account must stay read-only.
   Today there is no wall.

4. **Algorithm contamination risk.** If kage ever acts as the wrong identity — career
   research under the fun account or vice versa — it trains the recommendation engine
   against Chirag's intention. This is the exact failure mode the Cycle 28 wall prevents.

---

## What Cycle 28 IS / is NOT

**IS:**
- A standalone `~/.kage/identities.json` registry (same pattern as `sensitive.json`)
- Two identity classes: `normal` (read+write) and `read-only` (read only; never act-as)
- `kage identity list/show/set-class/add-account` CLI
- `arm_overrides` per identity: same arm definition, different account param at dispatch
- Account-scoped gmail arm dispatch — `family` active → arm reads `family@example.com`
- A read-only enforcement wall: write-permitted arms are blocked when class is `read-only`

**IS NOT:**
- Automatic identity detection from query content (kage never guesses; `kage use` is explicit)
- Quarantine class / burner identity management (deferred indefinitely — personal concern)
- Browser arm full scoping (stubbed; browser arm is dormant for read-only enforcement)
- Any kind of encryption, token management, or OAuth flow
- A change to the existing arm config in `config.json` (arms stay as-is; registry overlays)

---

## Key Facts from Reading the Code

These code seams directly shape the implementation:

### 1. Arm detection and dispatch (`src/kage/arms.py`)

```
_detect_arms(question, identity) → list[str]
  ├─ reads: runtime.config.data['arms']
  ├─ filter: arm['identity'] == identity AND arm['enabled'] AND arm['permission'] == 'read'
  │          AND keywords match
  └─ ⚠ BLOCKER 1 (fixed in D3/D5): arms pinned to 'personal' are invisible to 'family'.
       _detect_arms must ALSO accept an arm if the active identity's registry entry has
       arm_overrides[arm_name] — covering the "same arm, different account" case.

_call_arm(arm_name, question, identity) → str | None
  ├─ arm = runtime.config.data['arms'][arm_name]   ← static config lookup
  ├─ transport = arm.get('transport', 'stdio')
  └─ handler(arm_name, arm, question, identity, timeout)
```

**Seam:** `arm` dict passed to handler is mutable. Merging `arm_overrides` from the
registry into it before the handler call requires no handler signature change.

### 2. Shell handler subprocess call (`_call_arm_shell`, `arms.py:96`)

```python
cmd = arm_cfg.get('command', '')
proc = await asyncio.create_subprocess_exec(
    *shlex.split(cmd),
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

It is `asyncio.create_subprocess_exec` with `shlex.split`, not `subprocess.run` with
`cmd.split()`. To pass the account address as a positional arg, append it after the
expanded cmd args:

```python
extra = [arm_cfg['account']] if arm_cfg.get('account') else []
proc = await asyncio.create_subprocess_exec(
    *shlex.split(cmd), *extra,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

Using `create_subprocess_exec` with a list (not `shell=True`) prevents shell injection —
the account address goes as a literal argv, never interpreted by a shell.

### 3. mail_arm.scpt — current limitation

```applescript
-- reads: (messages of inbox whose read status is false)
-- "inbox" = Mail.app's unified inbox, not account-scoped
```

To scope to a specific account, osascript must receive the account address as `argv[0]`
via `on run argv`, then select the account by its `email addresses` property (a list of
strings). `name` is the display name (e.g. "Chirag Mokashi"), not the email address —
do not filter on `name`. AppleScript `whose` does not support compound `or` predicates;
use `email addresses contains target_account` as the single predicate.

### 4. Active identity (`src/kage/context.py` or `cli.py`)

```
_resolve_context() → {"identity": "personal", "project": "kage", ...}
```

The active identity label is available at dispatch time. The registry lookup
`get_identity(label)` → identity record (with class + arm_overrides) is a read at
call time, not import time.

### 5. No circular imports

`identity.py` must not import `cli.py`. It can import `runtime` (for `config.home`).
Pattern: same as `gate.py` — lazy `from kage import runtime` inside functions.

---

## Design Decisions

### D1 — Registry format: `~/.kage/identities.json`

```json
{
  "identities": [
    {
      "label": "personal",
      "class": "normal",
      "accounts": [
        "personal-a@example.com",
        "personal-b@example.com"
      ],
      "arm_overrides": {
        "gmail":    {"account": "personal-a@example.com"},
        "calendar": {}
      }
    },
    {
      "label": "school",
      "class": "normal",
      "accounts": ["school@example.com"],
      "arm_overrides": {
        "gmail": {"account": "school@example.com"}
      }
    },
    {
      "label": "family",
      "class": "read-only",
      "accounts": ["family@example.com"],
      "arm_overrides": {
        "gmail": {"account": "family@example.com"}
      }
    }
  ]
}
```

- `label` must match the identity string used in `kage use` and in `arm['identity']` in config; all lookups are by label
- `class` is one of: `"normal"` | `"read-only"` (the only two in V1)
- `arm_overrides[arm_name]` is a partial dict merged into the arm config at dispatch time
- `accounts` is informational in V1 (for display); enforced by arm scoping, not by a filter

### D2 — Two classes only

```
normal    — read + write. Full arm dispatch including calendar-write arm.
read-only — read only. kage may FETCH from this identity's arms (inbox/calendar read),
            but NEVER execute a write-type action (calendar create, draft send).
```

Enforcement point: `_detect_arms` checks `active_class(identity)`. If `read-only`, any
arm whose `permission` key in config is not `"read"` is excluded. In V1 all arms are
`"read"`, so this is a forward-looking guard — the calendar-write arm (Cycle 26) is
the first write-permission arm that would be blocked.

Quarantine is intentionally absent. Burner identity is Chirag's personal concern; kage
holds no registry entry for it and takes no action on its behalf.

**Safe-default risk window:** `active_class(label)` returns `"normal"` when the label is
absent from the registry. Before Slice 2 bootstraps `identities.json`, even `family`
defaults to `normal` — the read-only wall does not exist yet. This is acceptable because
the bootstrap runs as part of the same cycle and the risk window is one local operation.
If `identities.json` is corrupted or missing after bootstrap, the wall silently disappears.
Acceptable for V1 (no auto-recovery). Document bootstrap as a required setup step.

### D3 — Detection fix + arm_overrides merge at dispatch

**Detection fix (BLOCKER 1) — BOTH changes are in Slice 4; implement together or family dispatch is silently broken.**

`_detect_arms` currently accepts an arm only if `arm['identity'] == identity`. Arms pinned
to `personal` are invisible to `family`. Fix: an arm is accepted if EITHER condition holds:

```python
arm['identity'] == identity                              # existing: static pin
OR identity_arm_overrides(identity, arm_name) != {}      # new: registry has an override
```

Both still require `arm['enabled']`, `arm['permission'] == 'read'`, and keyword match.
Arms pinned to `personal` remain invisible to `family` unless `family`'s registry entry
has `arm_overrides[arm_name]` — which is exactly the registry's job to declare.

**Override merge in `_call_arm` — required alongside the detection fix:**

```
1. arm = runtime.config.data['arms'][arm_name]             (base config)
2. overrides = identity_arm_overrides(identity, arm_name)  (from identities.json)
3. merged = {**arm, **overrides}                           (override wins)
4. handler(arm_name, merged, question, identity, timeout)
```

The handler receives `merged`. Note: `merged['identity']` is still `"personal"` (the static
config value) even when dispatching for `family` — `arm_overrides` only carries `account`,
not `identity`. Handlers do not read `arm_cfg['identity']` (they use the function's own
`identity` parameter for audit logging). Do not read `merged['identity']` in future handlers.

`identity_arm_overrides(identity_label, arm_name)` → dict (empty if not found).
Missing registry or missing arm name → `{}` → no override → backward compatible.

# ponytail: O(n_arms) identities.json reads per query (one per arm in detect + one per arm in call).
# With 3 arms this is ~6 reads; ceiling: grows linearly with arm count. Upgrade path: cache
# load_identities() for the lifetime of the request (pass it in, don't re-read per arm).

### D4 — Account parameter plumbing (gmail arm, osascript)

`_call_arm_shell` appends `arm_cfg.get('account', '')` as an extra positional arg
if non-empty. The real subprocess API is `asyncio.create_subprocess_exec` (not
`subprocess.run`) — append after the `shlex.split(cmd)` expansion:

```python
extra = [arm_cfg['account']] if arm_cfg.get('account') else []
proc = await asyncio.create_subprocess_exec(
    *shlex.split(cmd), *extra,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

Using `create_subprocess_exec` with a list argument (no `shell=True`) means the
account address is passed as a literal argv — no shell interpolation, no injection risk.

`mail_arm.scpt` gains an `on run argv` handler. Filter accounts by the `email addresses`
property (a list of strings) — NOT by `name` (which is the display name, e.g.
"Chirag Mokashi", not the email address). AppleScript `whose` does not support
compound `or` predicates; use a single predicate:

```applescript
on run argv
    set target_account to ""
    if (count of argv) > 0 then set target_account to item 1 of argv

    if not (application "Mail" is running) then
        tell application "Mail" to launch
        delay 4
    end if

    -- ponytail: 3s is connection teardown time, not query time. The inner block
    -- completes instantly; Mail.app's Gmail sync keep-alive holds the connection open
    -- for ~2 min without this timeout. Do not lower this value.
    with timeout of 3 seconds
        tell application "Mail"
            set output to ""
            try
                if target_account is not "" then
                    set acct to first account whose email addresses contains target_account
                    set unread_msgs to (messages of inbox of acct whose read status is false)
                else
                    set unread_msgs to (messages of inbox whose read status is false)
                end if
                set total to count of unread_msgs
                if total > 10 then set total to 10
                repeat with i from 1 to total
                    set msg to item i of unread_msgs
                    set output to output & subject of msg & " | " & sender of msg & linefeed
                end repeat
            end try
            if output is "" then return "No unread messages."
            return output
        end tell
    end timeout
end run
```

Fallback: if `target_account` is empty (override absent), behavior is identical to today
(unified inbox). Backward compatible — the arm continues working for `personal` identity
even if the registry doesn't exist yet.

### D5 — Read-only enforcement

`_detect_arms` adds one check (after keyword match):

```python
from kage import identity as _identity
...
and not (_identity.active_class(id_label) == 'read-only'
         and arm.get('permission') != 'read')
```

In V1 all arms are `permission: read`, so this guard never fires. It is the seam for
when the calendar-write arm (or any future write arm) is added.

`_call_arm` adds a complementary guard (defense in depth). The ask-flow caller does not
log blocked attempts, so the guard must write to the audit log itself:

```python
from kage import identity as _identity
if _identity.active_class(identity) == 'read-only' and arm.get('permission') != 'read':
    _privacy._write_audit({'type': 'arm_blocked', 'arm': arm_name,
                           'reason': 'read-only identity', 'identity': identity,
                           'ts': datetime.now().astimezone().isoformat(timespec='seconds')})
    return None
```

---

## Non-goals (explicitly deferred)

- **Quarantine class / burner identity** — out of scope indefinitely; Chirag manages burner-account manually
- **Browser arm account scoping** — browser arm uses a shared Playwright MCP process with a single profile; multi-profile browser sessions require a separate browser process per identity (complex, deferred to a dedicated cycle)
- **Automatic identity inference** — kage must never guess which identity a query belongs to; `kage use` is the only switch
- **Write arm account scoping** — calendar-write arm (Cycle 26) uses EventKit which reads the active macOS calendar identity; full multi-account write scoping deferred
- **Validation that account strings are real/reachable** — registry is a thin JSON file; Mail.app will surface the error if the account doesn't exist

---

## Implementation Slices

```
Slice 0  PLAN (this doc) + cold review
Slice 1  identity.py — registry CRUD (load/save/list/get/set-class/add-account)
         + active_class() + identity_arm_overrides()
Slice 2  CLI: kage identity list/show/set-class/add-account
         + ~/.kage/identities.json bootstrap with personal/school/family
         add-account semantics: appends email to accounts[] for named label;
         saves; does NOT touch arm_overrides; exit 1 if label not found
Slice 3  read-only enforcement in _detect_arms + _call_arm (guard, forward-looking)
Slice 4  account-scoped dispatch: _call_arm merges arm_overrides;
         _call_arm_shell passes account arg; mail_arm.scpt updated
```

Per 7-step gate: each slice goes plan (cloud) → write code (local) → review (cloud)
→ plan tests (cloud) → write tests (local) → review tests (cloud) → run tests (local).

---

## Test Plan

Tests live in `tests/test_cli.py` alongside all existing tests. No new test files.
All PII values in tests are synthetic (no real account addresses).

**Home isolation:** `identity.py` reads `~/.kage/identities.json` via `runtime.config.home`,
same pattern as `gate.py`. Tests that exercise file I/O must monkeypatch `runtime.config`
to a `tmp_path`-backed `Config` object — the same `_save_home(monkeypatch, tmp_path)`
helper already used in existing gate/sensitive tests.

| # | Test | Covers |
|---|------|--------|
| T1 | `test_identity_registry_load_missing_file` | missing identities.json → `{"identities":[]}` | 
| T2 | `test_identity_registry_load_valid` | loads identities.json, returns list with expected fields |
| T3 | `test_identity_class_normal` | `active_class("personal")` → `"normal"` |
| T4 | `test_identity_class_read_only` | `active_class("family")` → `"read-only"` |
| T5 | `test_identity_class_unknown_defaults_normal` | label not in registry → `"normal"` (safe default) |
| T6 | `test_identity_arm_overrides_present` | `identity_arm_overrides("family", "gmail")` → `{"account": "...@synthetic.test"}` |
| T7 | `test_identity_arm_overrides_missing_arm` | no override for arm → `{}` |
| T8 | `test_identity_arm_overrides_missing_identity` | identity not in registry → `{}` |
| T9 | `test_detect_arms_read_only_blocks_write` | write-permission arm excluded from _detect_arms when class is read-only; requires injecting a synthetic arm with `"permission": "write"` into `runtime.config.data['arms']` via monkeypatch (no real write-arm exists yet) |
| T10 | `test_detect_arms_read_only_allows_read` | read-permission arm NOT excluded when class is read-only |
| T11 | `test_call_arm_merges_overrides` | merged arm_cfg passed to handler contains account from arm_overrides; call via `asyncio.run(cli._call_arm(...))` (per existing arm test pattern); monkeypatch the handler to capture the `arm_cfg` arg; assert `arm_cfg.get('account') == expected_account` |
| T12 | `test_call_arm_read_only_blocks_write` | _call_arm returns None when class is read-only + arm has write permission |
| T13 | `test_identity_list_cli` | `kage identity list` prints labels + classes |
| T14 | `test_identity_show_cli` | `kage identity show personal` prints account list + overrides |
| T15 | `test_identity_set_class_cli` | `kage identity set-class family normal` → persisted |
| T16 | `test_identity_add_account_cli` | `kage identity add-account personal new@synthetic.test` appends to `accounts[]` for that label, saves, does NOT touch `arm_overrides`; assert account in registry; error if label not found (exit 1) |
| T17 | `test_identity_set_class_invalid_cli` | `kage identity set-class x quarantine` → exit 1 |

---

## Files Changed

```
new      src/kage/identity.py           registry CRUD + class + override helpers
changed  src/kage/arms.py               Slices 3+4: read-only guard + override merge
changed  src/kage/cli.py                Slice 2+: kage identity subcommands
changed  ~/.kage/mail_arm.scpt          Slice 4: on run argv + account scoping
new      ~/.kage/identities.json        Slice 2: bootstrap (gitignored; personal data)
changed  tests/test_cli.py              T1–T17
```

`~/.kage/identities.json` lives **outside the repo tree** and can never be committed,
same as `sensitive.json`, `allowlist.json`, and `privacy_queue.jsonl`. It contains real
account addresses.

---

## Egress / Privacy Check

No new cloud egress path is introduced. `identity.py` is a pure local file reader.
`arm_overrides` values are account addresses that go only to the local subprocess
(osascript argv). The `account` field never enters the cloud prompt. No gate change needed.

The read-only wall makes the privacy posture *stricter*, not looser.

---

## Composability Check (10 characteristics)

- **Seamless** — arm dispatch gains account scoping silently; user does nothing different
- **Transparent** — `kage identity list` shows the registry; audit log already records identity per arm call
- **Local** — identities.json is local, gitignored, no cloud path
- **Controlled** — `kage use family` is the only switch; no auto-detect
- **Modular** — `identity.py` is a new standalone module; no circular imports
- **Silent** — read-only enforcement fails silently (returns None); no noisy errors

---

*v3 — 2026-07-03. Cold reviews #1 and #2 complete. Zero open blockers. Ready for Slice 1.*
