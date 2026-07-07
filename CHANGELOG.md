# Changelog

All notable changes to kage are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/) once kage reaches 1.0 (pre-1.0
minor bumps below are per-cycle, not strictly semver-load-bearing).

## [0.29.0] — 2026-07-07

Monitor's daily digest now feeds the Librarian directly — kage's own activity
becomes a memory candidate, not just Scout's research.

- **Added:** Monitor → Librarian pipeline (`_deposit_context_snapshot`) — the
  daily digest deposits a summary into Librarian's staging queue, gated by the
  same `kage librarian approve` checkpoint as Scout's findings (Cycle 29).
- **Fixed:** Librarian HITL approval flow — `list_pending_approvals` +
  inline approve/reject, closing a gap where pending items had no clean
  review path.
- **Changed:** `kage scout run` is now confirm-gated by default (`--yes` to
  skip), matching the caution already applied to other write-adjacent paths.
- **Fixed:** write-identity chokepoint (`resolve_write_identity()`) applied
  across all memory writers — previously only CLI callers routed through it;
  MCP `kage_remember` and Librarian's `write_note` could tag a note with a
  raw label instead of its canonical identity group, making it permanently
  unreachable. `kage identity repair` migrates any notes tagged before the
  fix; `kage doctor` gained an "identity tags canonical" check (Cycle 28.1).
- **Fixed:** Gemini key-in-header dispatch, calendar `reject()` guard,
  `chmod 600` on PII files, `observe.py` dead context tagging, Monitor
  shell-exec consistency.
- **Chore:** post-capstone hygiene — sanitized FTS5 queries in
  `locate_memory` (punctuated queries no longer raise
  `sqlite3.OperationalError`), approval-ID prefix matching in `write_note`,
  doc/gitignore cleanup.

## [0.28.0] — 2026-07-04

- **Added:** Identity Registry (`identity.py`) + `kage identity` CLI —
  CRUD over named identities, read-only identity class blocks write-permission
  arms, per-identity arm overrides (e.g. account-scoped Gmail/Calendar
  routing), identity groups (shared memory pool, distinct arm routing).
- **Fixed:** post-smoke-test hardening — arm timeout, read-only gate,
  identity-group edge cases.

## [0.27.0] — 2026-07-03

- **Added:** two-pass privacy gate (`gate.two_pass_gate()`) applied across
  all 11 egress sites — vault-value silent redaction (pass 1) + generic PII
  detection with allowlist/queue (pass 2). `kage allow` + `kage privacy
  review` CLI.

## [0.26.0] — 2026-07-03

- **Added:** calendar-write arm — kage's first WRITE arm. EventKit
  create-only (write access only), `propose → approve → execute` over
  human-readable markdown proposals, `kage calendar` CLI subgroup. Excluded
  from `_detect_arms`, HITL-gated, audited. Delete/reschedule deferred
  pending a signed-helper identity for full EventKit access.
- **Docs:** corrected 22 cycle-doc status lines to SHIPPED; fixed stale
  README/CLAUDE.md factual errors found in cold review.

## [0.25.0] — 2026-07-02

- **Added:** Librarian CTM learning — recent approved precedents injected
  as few-shot examples (MemAPO dual-memory loop).
- **Fixed:** asyncio shell-arm dispatch + `health_command` for osascript
  hangs.

## [0.24.0] — 2026-07-01

- **Added:** Librarian EPM learning — Librarian learns from its own
  *rejections*, distilling rejection patterns into its distill prompt.
- **Fixed:** hard-block `kage-corrections` from cloud egress.

## [0.23.0] — 2026-07-01

- **Fixed:** Layer 3e gate hardening — mask-at-dispatch. Condensed query +
  history + retrieved context now masked through one shared per-request map
  and restored in the response (closed the condensed-query cleartext leak);
  audit log emits `pii_type_counts` instead of placeholder labels.

## [0.22.0] — 2026-06-30

- **Added:** Layer 6 `kage learn` — ProTeGi prompt learning from the
  `kage-corrections` log; Monitor auto-triggers at 7+ new corrections.

## [0.21.0] — 2026-06-30

- **Added:** Layer 3e reversible PII masking before cloud dispatch —
  substitute-before-dispatch / restore-in-response; PII notes no longer
  withheld outright.

## [0.20.0] — 2026-06-29

- **Added:** Monitor cadence split — `observe` runs every 5 min (launchd
  `StartInterval`), `digest` runs 07:00 daily (`StartCalendarInterval`).
  Scout two-stage deep fetch (Jina / GitHub API / Reddit body).

## [0.19.0] — 2026-06-29

- **Added:** sensitive vault — user-defined regex PII patterns in
  `~/.kage/sensitive.json`; `kage sensitive list/add/scan`.
- **Fixed:** Scout/Librarian/Monitor pipeline gap fixes (10 structural gaps,
  G01–G10).

## [0.18.0] — 2026-06-29

- **Added:** Layer 4 multi-vendor router — keyword task-class routing
  (code/research/multimodal/reasoning/chat), config-driven table,
  `kage ask --auto`.

## [0.17.0] — 2026-06-29

- **Added:** Monitor agent (ADK `Workflow`) — macOS Accessibility (AX)
  daemon (`observe.py`) capturing app-switch/typing-pause events;
  `kage monitor observe/digest/run/install/uninstall/status/last`.
- **Fixed:** contextual API-key detection covering all current providers.

## [0.16.0] — 2026-06-26

- **Added:** Librarian agent (ADK `LlmAgent`) — 3e-gated distill-and-judge,
  HITL staging → approval pipeline, sole writer to permanent memory.

## [0.15.0] — 2026-06-25

- **Added:** Scout v1.1 — Tier 1/2 depth split, project-aware analysis,
  GitHub stats.

## [0.14.0] — 2026-06-25

- **Added:** Scout agent — proactive ADK pipeline (`ScoutBroad` local
  Qwen3 shortlists → `ScoutIntegrate` cloud writes digest), deterministic
  fetch across 5 public sources, `kage scout run/dry-run/bootstrap/status`.

## [0.13.0] — 2026-06-25

- **Added:** gmail arm (osascript/Mail.app, zero OAuth) + browser arm
  (Playwright MCP, headless stealth).

## [0.12.0] — 2026-06-19

- **Changed:** major modularity refactor — `cli.py` split into 16 modules
  behind injectable runtime seams; `ProviderRegistry` + `ArmRegistry`
  replace hardcoded dispatch; egress golden tests added.
- **Fixed:** UPI regex tightened (dropped false-positive IPv4 matches),
  privacy gate floor lowered to prefer over-withholding.

## [0.11.0] — 2026-06-16

- **Added:** MCP client + arm routing — `_detect_arms` keyword routing,
  `_call_arm` graceful fallback, audit log. Three transports: `shell`,
  `stdio`, `sse`. First live arm reads the local macOS Calendar via
  `osascript`/Calendar.app.

## [0.10.1] — 2026-06-16

- **Added:** active context — `kage use` / `where` + resolver, wired through
  CLI and MCP.

## [0.10] — 2026-06-14

- **Added:** stateful session engine + `kage chat` REPL, safe
  model-switching.
- **Fixed:** CI green; corrected Odysseus license fact (AGPL-3.0, not MIT);
  added kage's own MIT LICENSE.

## [0.9] — 2026-06-12

- **Added:** identity × project wall (Layer 3b) — the identity axis.
- **Added:** recursive chunking + bge-reranker retrieval (v0.8, bundled into
  this tag).

## [0.7] — 2026-06-10

First tagged release. Bundles the repo's genesis and the v0.1 thin slice:

- **Added:** local markdown source of truth, SQLite FTS5 index, project
  partition filter — `init`, `remember`, `recall`, `recall --pipe`, `list`,
  `forget`, `status`, `doctor`.
- **Added:** 3e disclosure gate (Layer 3e) — local-only notes hard-blocked
  before cloud dispatch.
- **Added:** CI (GitHub Actions, `uv sync` + `pytest`).
