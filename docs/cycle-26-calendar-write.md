# Cycle 26 — Calendar-write: kage's first write arm (v0.26.0)

*Status: PITCH v3 — **BUILD-READY** (2026-07-02, cloud-authored). One cold review (subagent vs. real repo) + a live B1 spike. Scope: **CREATE-ONLY** (write-only access, proven on the machine). NOT built yet.*
*Brainstorm source: [orchestrator-brainstorm.md](orchestrator-brainstorm.md) + the 7 locked decisions (D1–D7).*
*Dev workflow: plan cloud → write local (Qwen3) → review cloud → plan tests cloud → write tests local → review tests cloud → run tests local.*

> **v3 changelog:** cold-review B1 was **resolved empirically** — a live spike showed EventKit **full access is NOT grantable** in kage's runtime context (write-only already set → macOS won't re-prompt → returns write-only; delete never ran). Full access also has a fragile TCC identity story for a CLI. So **v1 ships create-only** (write-only, proven), and `delete` + reschedule + undo-composition **defer to a later cycle** bundled with a signed-helper / stable-identity for full access. Also folded from cold review #1: dropped the `native` transport-handler framing (writes go via the `runtime.calendar` seam, never `_call_arm`); `doctor` gets a write-arm branch; audit via `_write_audit`/`runtime.config.audit_path`; `EventKitBackend` lazy-imports EventKit so `runtime.reset()` survives non-mac CI; malformed proposal → fail safe.

---

## North star

> Build kage's **first write arm** — *create* calendar events on macOS — and make it the **template every future write arm inherits**: a dumb, deterministic, HITL-gated primitive that *proposes* before it *executes*, with the intelligence living above it.

The calendar is the first surface; the **pattern** is the deliverable. Decoupled from the orchestrator (which calls this arm later).

## Proven / decided

- ✅ **Write-only `create` is proven** — Step-0 spike created a real event via EventKit write-only access, confirmed visible in Calendar.app.
- ⛔ **Full access is NOT grantable in this context** — B1 spike confirmed. `delete` (needs full access) is **deferred**.

## The decisions (as they apply to create-only v1)

- **D1 — Backend: EventKit via pyobjc, WRITE-ONLY access.** Not osascript (AppleScript calendar writes silently don't save). Not a Google MCP server (OAuth wall). Write-only is proven and already granted.
- **D2 — Scope: ONE primitive in v1 — `create`** (+ target a specific calendar). `delete`, reschedule, and undo-composition are **deferred to a future full-access cycle**. Every create is HITL-gated.
- **D3 — Mechanism: new minimal two-phase `propose → execute` path** in its own module, executed via the `runtime.calendar` seam. **NOT** an arm transport: not `register_arm`'d, not in `_TRANSPORT_HANDLERS`, never reaches `_call_arm` (writes are never auto-dispatched). Config carries `permission:'write'` (so `_detect_arms` can't fire it) + a `transport` label used only for `status`/`doctor` display.
- **D4 — Approval UX: queued / staged-artifact, Librarian-style.** Proposals persist as **human-readable markdown files** reviewable via CLI *and* existing surfaces (Antigravity/editor/filesystem). Inline card deferred.
- **D5 — Invocation: `kage calendar propose|queue|approve|reject`, structured input** (Typer subgroup). Pure deterministic executor; NL→fields is the orchestrator's job (deferred). A callable seam is what the orchestrator reuses.
- **D6 — Reversibility: deferred with `delete`.** Undo/reschedule = caller composing create+delete, which needs the deferred delete. For create-only v1, undo of a bad create = delete it manually in Calendar.app (rare — every create is pre-approved).
- **D7 — Check: seam + `FakeCalendarBackend` unit tests + one skipped live smoke.**

## Design

### Module + seam layout
- **New module `src/kage/calendar_write.py`** — two-phase arm: `propose_create()`, `get_queue()`, `approve()`, `reject()`, + proposal file I/O. Executes by calling `runtime.calendar` directly. **Not** wired into `arms.py` dispatch.
- **`CalendarBackend` seam** (injected via `runtime`, per Cycle 12 pattern):
  - `EventKitBackend.create(spec) -> event_identifier`. **Lazy-imports EventKit inside the method** (NOT at construction) so `runtime.reset()` — which runs on every import incl. Linux CI — never raises `ImportError`. Mirror observe.py's guarded-pyobjc pattern and the validated Step-0 probe.
  - `FakeCalendarBackend` (in `tests/fakes.py`) — records `create` calls, returns a synthetic id; no EventKit; CI-safe.
  - `runtime.calendar` holds the live backend; `runtime.reset()` sets `calendar = EventKitBackend()` (cheap ctor, no import).

### Proposal store (human-readable files)
One markdown file per proposal under `<KAGE_HOME>/calendar/proposals/<id>.md` (path via `runtime.config.home`, not hardcoded):
```markdown
---
id: 20260702T143210-a1b2c3
op: create
status: pending          # pending | executed | rejected
title: Work on HSI draft
start: 2026-07-09T14:00:00
end:   2026-07-09T15:00:00
calendar: NEU (school@example.com)
why: from the email you flagged — "HSI grant revisions due Friday"
created_at: 2026-07-02T14:32:10
event_identifier:        # filled after execute
---

# kage would create: "Work on HSI draft"
Thu Jul 9 · 2:00–3:00 PM · calendar: NEU
why: from the email you flagged — "HSI grant revisions due Friday"
```
Readable in any editor/Antigravity. `approve` updates `status` + `event_identifier` in place, then executes. **Malformed / hand-edited frontmatter → `approve` fails safe (error, never execute a half-parsed spec).**

### Config
```json
"calendar-write": {
  "enabled": true,
  "transport": "native",     // DISPLAY LABEL ONLY — not a dispatch key; arm is never register_arm'd
  "permission": "write",     // guarantees _detect_arms (read-only) never fires it
  "identity": "personal"
}
```

### `doctor` handling
`_check_arm_health` gets a branch for `permission=='write'` (or `transport=='native'`) that reports health via **EventKit authorization status** (e.g. "write-only ✓"), NOT a subprocess/MCP probe — otherwise the MCP fallback `KeyError`s and mis-reports the arm as "unreachable."

### CLI (`kage calendar` Typer subgroup — no name collision; `calendar` is only a config/arm name today)
```
kage calendar propose --title T --start S --end E --cal C [--why …]   # stage a create
kage calendar queue                                                   # list pending proposals
kage calendar approve <id>                                            # revalidate → execute → audit
kage calendar reject  <id>                                            # mark rejected
```

### Approve-time guarantees
- Revalidate before write: target calendar exists; `start` not in the past; proposal `status == pending`; frontmatter parses cleanly.
- **Single-use:** once executed, status flips; re-approve is a no-op/error.
- **Audit:** `_privacy._write_audit({...})` (→ `runtime.config.audit_path`) with `{type:'calendar_write', op:'create', proposal_id, status, event_identifier, success, ts}`, matching the existing iso `ts` format.

## Implementation order (each slice through the 7-step gate)

1. **Backend seam.** `CalendarBackend` + `EventKitBackend` (create-only, lazy-import EventKit) + `FakeCalendarBackend` + `runtime.calendar` wiring. Add `pyobjc-framework-EventKit` dep (mac-only; must not break Linux CI resolution — lazy import covers runtime, and the dep is marked so resolution still works).
2. **Two-phase core + proposal files.** `propose_create`, `get_queue`, `approve`, `reject`; readable markdown store; malformed-file fail-safe.
3. **CLI.** `kage calendar` Typer subgroup (`@_calendar_app.command(...)`, NOT Click).
4. **Guards + audit + doctor branch.** Approve-time revalidation, single-use, `_write_audit`, `_check_arm_health` write-arm branch.
5. **Tests.** `FakeCalendarBackend` unit tests (propose builds correct proposal; approve calls backend with right fields; reject writes nothing; revalidation incl. past-start; single-use; malformed→fail-safe; audit) + one `@pytest.mark.skipif(not macOS/EventKit)` live smoke (create a throwaway).

## Non-goals (v1)
- **`delete`, reschedule, undo** — deferred to a future full-access cycle (needs signed-helper identity).
- No NL parsing (orchestrator's job). No inline approval card (needs a UI). No orchestrator wiring. No recurring/all-day events (timed only). No editing arbitrary events.

## Ponytail ceilings (named, with upgrade paths)
- **Create-only** — delete/reschedule/undo wait on full access + a stable TCC identity (signed helper). Upgrade path: a dedicated full-access cycle.
- **TCC prompt handling** — arm handles `notDetermined → request` for write-only; clear message if denied.
- **Single-use guard is check-then-write, not atomic**; **proposal files are plaintext in `~/.kage`** — both acceptable for the single-user local model.

## Cold-review log
- **v1 → v2: cold review #1** (independent subagent vs. real repo, 2026-07-02) — B1 (unproven full-access/delete), W1 (doctor mis-report), W2 (decorative `native` transport), W3 (audit), N2 (lazy-import), N6/N7 (fail-safe + create-only guard). All folded in.
- **v2 → v3:** B1 resolved by live spike (full access not grantable) → scope cut to create-only. This is a *reduction* of the cold-reviewed create path (delete removed), so no new surface was introduced.
- **Cold review #2 (consolidated, pre-PR, 2026-07-02):** independent subagent over the whole built feature. PASS on gate/security (write path structurally cannot auto-fire — not registered, not in `_TRANSPORT_HANDLERS`, `_detect_arms` read-only filter holds), egress/3e (no cloud egress), circular-import fix, and state-machine core. Fixed 2 WARNs: `_write_proposal` made total (`.get`) to kill a duplicate-on-retry bug; newline-injection guard in `propose_create`. NIT accepted: the pitch's `calendar-write` config entry + `doctor` branch were intentionally dropped as unnecessary (arm is CLI/seam-only, never in the arms config → W1 moot). Feature PR-ready.
