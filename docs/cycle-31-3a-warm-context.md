# Cycle 31 — Layer 3a: Active Context Detection as a Warm-Context Tier

*Status: SHIPPED — v0.31.0 (2026-07-09). Built via the 7-step gate across 6 slices (warm.py → kernel producers → rich resolver → S-render bar/M1 masking → budget/output-buffer reservation → miss-metric). PITCH: THREE cold reviews (subagent, Opus) before build: #1 REVISE (3 blockers), #2 REVISE (verified B1 sound; caught the still-undercounted enumeration + non-implementable Librarian consumer + `kage use` gap), #3 APPROVE WITH EDITS (enumeration closed; build-ready). EXECUTION: Slice 4 (security-critical M1 masking) got an independent Opus review of the plan AND the implemented code — both APPROVE(-WITH-EDITS). Whole-feature consolidated cold review after all 6 slices: APPROVE-WITH-EDITS (one real fix — missing `ts` on new audit events — applied; 3 remaining findings were documentation/awareness nits, no code change needed). Final state: 926 tests passing (up from 791 at cycle start), 0 regressions.*
*Dev workflow: 7-step gate. Cloud plans + reviews; local (Qwen3 via `kage ask`) writes all code + tests; local runs. Pitch cold-review = Opus subagent; code/test review = Sonnet inline.*
*Date: 2026-07-09. Depends on: Cycle 29.1 (num_ctx — the real 16384 window this budgets against), Cycle 30.2 (`guard`), Cycle 28 (identity registry).*

> **v2 changelog (cold review #1, REVISE):** B1 — `guard.neutralize()` fence (~38 tok/call) can't be the 60-tok bar → new fenceless `guard.sanitize_fact()`. B2 — `.kage` is ambient disk state, not a declaration → **`.kage` resolves PROJECT ONLY**. B3 — "14 callers untouched" contradicts the feature → freeze old resolver, move warm consumers to rich. + M1 egress order, M2 observe gate-strip, M3 injection enumeration added, N1 13 not 14, N2 generalized writer, N3 real-schema test, N4 findings handling.
>
> **v3 changelog (cold review #2, REVISE — verified B1 SOUND at `guard.py:58-64`):**
> - **NEW-1 (MAJOR)** — the injection enumeration *still* omitted **`mcp_server.kage_ask` (`:77`)**, a third answer-path. Fixed: enumerated + **explicitly deferred** (MCP clients are agents, not the human-at-a-running-start; MCP ask stays cold by design, stated).
> - **NEW-2 (BLOCKER)** — Librarian `write_note` confirm-on-inferred is **not implementable**: it runs at approval time (no interactive surface), takes identity from the staging row via `resolve_write_identity` (`librarian.py:645-666`), and forcing resolution there re-opens the 28.1 fail-closed class. Fixed: **dropped as a consumer.** Real rich consumers = `ask` + `remember` (+ `chat`, flagged).
> - **NEW-3 (MAJOR, elevated)** — `kage use` (`cli.py:572-583`) does ZERO registry validation; 3a makes declared identity the trusted root, so a typo mints a phantom write partition (28.1 through the front door). Fixed: **`kage use` must validate against the C28 identity registry** (reject unknown / confirm-create) — added as a hard dependency + slice-3 step.
> - **NEW-4 (MINOR, REVERSED at build time 2026-07-09)** — `chat` (`cli.py:1858`) ignores sticky today (defaults `--identity personal`). v3 proposed wiring rich to fix this; **build-time decision: keep it.** Identity is declared-only and must never be auto-inferred/switched (the two-axis invariant); *deciding* whether content belongs under a different identity is exactly the Librarian's future HITL job (confirm/move), not the resolver's or `chat`'s. So `chat` passes its default-`"personal"` identity through `_resolve_context_rich` unchanged (truthy arg → declared, sticky never consulted) — only the *project* axis infers, for the bar. This also dissolves a build-time cold-review finding: with identity behavior identical flag-on/flag-off, the byte-identical-OFF guarantee holds trivially, no special-casing needed. See `[[project_identity_correction_is_librarian_job]]` (memory).
> - **NEW-5 (MINOR)** — `sanitize_fact` drop-on-injection false-positive ceiling named (ponytail).
> - **NEW-6 (MINOR)** — `atomic_write_json` uses a **unique per-writer tmp name** so atomicity is real, not accidental-via-reader-try/except.
> - Residuals: freeze-test asserts **byte-identical** output across all 3 branches; `where` stays frozen as an explicit decision (the bar shows inferred, `where` reports declared).

---

## North star

kage today is **steered, not aware**: `context.py` resolves `(identity, project)` from explicit flag → sticky `kage use` → `personal` fallback. There is no *detection* — the two designed signals (calendar, cwd) were never built, and there is no warm state. Every query starts cold.

**3a makes `Aware` real** (the blueprint's own ★, and the first of the three BROKER→MEDIATOR gaps). It is the **warm working-memory tier**: a tiny, TTL'd, identity-tagged set of derived world-facts — loaded at first touch, refreshed on expiry, evicted on switch — that lets kage answer from a running start instead of cold. It is the slab the Jarvis keystone (push/interrupt) is later built on; this cycle lays the slab, not the house.

**Named ancestor (honest framing, per the Bhatt-et-al. precedent):** this is the **Letta/MemGPT RAM-tier pattern** — main context = RAM, archival = disk, managed allocation — *applied at personal scale, over kage's own arms, with identity partitioning none of the memory frameworks have.* We are not inventing the tier; we are the first to assemble it from a personal broker's real sensors.

## The model: demand paging, not eager loading

```
   BOOT (first invocation)  →  resident kernel: now · tz · day-part · next-calendar · resume-pointer
   FIRST REFERENCE to a project/identity  →  PAGE FAULT → load that partition's warm facts
   SWITCH away  →  evict (summarize into resume-pointer first)
   MOST invocations  →  read warm.json, refresh only EXPIRED facts, write back  (≈ 0 latency)
```

**The warm tier is derived state — so v1 needs no daemon.** Like the vector index: markdown is truth, `warm.json` is a disposable cache rebuildable from scratch, living at `~/.kage/state/warm.json` (a NEW path + subdir — see §Machinery; the shipped writer is *generalized*, not reused verbatim). Persistence between invocations is the *file*, not a resident process — dissolving the scope conflict with the deferred daemon (#80/#103): v1 stays per-invocation as locked, and still behaves like RAM. The real daemon, when it lands, only refreshes the same file faster.

**Concurrency (cold-review completeness):** two `kage` invocations can race on `warm.json`. Writes are atomic (tmp + `os.replace`, last-writer-wins), and because every fact is a disposable cache entry with its own validity window, a lost write is self-healing — the next invocation re-refreshes the expired fact. No lock needed; the ceiling (last-writer-wins may drop a concurrent refresh) is acceptable and named. `ponytail:` last-writer-wins on warm.json; ceiling = a racing refresh is dropped, self-heals next invocation; upgrade = advisory flock if it ever matters.

## What a warm fact IS — validity windows for the mutable few, plain TTL for the rest

Each fact carries a **validity window** *only where a state-change must stay auditable* — the ~2 mutable facts (timezone on travel, active project). Zep/Graphiti beats plain-TTL 63.8% vs 49% on temporal retrieval by modelling `valid-from → superseded-at`; but `superseded_at` is dead weight for `now`/day-part/queue-depth. One code path, optional field, populated only for the mutable two.

```json
{
  "key": "timezone",
  "value": "America/New_York",
  "identity": "personal",
  "valid_from": "2026-07-09T08:00:00-04:00",
  "ttl_seconds": 3600,
  "provenance": "macos-location",
  "superseded_at": null
}
```

**Write discipline — the 4-op primitive (Mem0 steal):** a refresh does NOT blind-append. It compares the new fact to the resident one → exactly one of **ADD / UPDATE / DELETE / NOOP**. Unchanged past TTL → NOOP + bumped `valid_from`. Changed value → UPDATE: stamp `superseded_at` on the old (mutable facts only), ADD the new (India→Boston TZ closed out, not deleted — auditable). Unresolvable → DELETE.

## The kernel — every fact has a shipped producer (jugaad inventory, cold-review-verified)

**Assembly cycle, not build cycle.** All rows below VERIFIED against code by cold review #1 except the two corrected:

| Warm fact | Producer (shipped) | Status |
|---|---|---|
| now / timezone / day-part | macOS `TZ` (Location Services, on-device — never egressed) | ~1 line |
| next calendar event | `arms._call_arm('calendar', …)` (`arms.py:214`) | import |
| mail deadlines / flagged | `arms._call_arm('gmail', …)` | import |
| pending approvals | `librarian.list_pending_approvals()` (`librarian.py:527`), `get_staging_queue()` (`:126`) | import |
| scout freshness / queue depth | `monitor.read_pipeline_state()` (`monitor.py:61`) | import |
| machine state (RAM, battery) | `monitor.read_system_metrics()` (`monitor.py:236`) | import |
| frontmost app (SOFT signal) | `monitor.read_observe_log()` — **gate-stripped, NOT raw** (`_gate_text` at `monitor.py:156`); fine, but see echo-chamber note | import |
| capability state | `doctor` + `monitor.check_mcp_health()` (`monitor.py:160`) | refactor-share |
| interrupt seeds | **`monitor_alerts` table (`monitor.py:42`) + `write_alert()` gated + `_gate_text`-stripped (`:346`)** — VERIFIED | reader (~10 lines) |

## Machinery — imports, with two honest corrections from cold review

- **Atomic writer:** `context._write_active` (`context.py:15`) hardcodes `runtime.config.state_path` AND uses a single fixed `.json.tmp` name — it is NOT reusable verbatim. Slice 1 extracts a generalized `atomic_write_json(path, data)` that uses a **unique per-writer tmp name** (pid/token, or `NamedTemporaryFile` in the same dir) so two racing `kage` invocations can't interleave bytes into one shared tmp before `os.replace` (NEW-6 — otherwise atomicity is only accidental-via-the-reader's try/except). Creates `~/.kage/state/`.
- **Identity registry** (C28) tags every fact; **`_write_audit`** satisfies privacy-principle-#7 (audit every context change); **`router._classify` + Layer 4** decide destination *before* dispatch (drives S-vs-M rendering for free).

## The two-axis cascade — identity is DECLARED (live action only), project may be INFERRED

The single most load-bearing rule. Failure costs differ by an order of magnitude: a wrong **identity** guess mistags *writes* (Cycle 28.1's wound) and shifts the 3e disclosure partition; a wrong **project** guess only weakens answers.

```
   IDENTITY  ←  LIVE USER ACTION ONLY:  --identity flag · kage use
                (NOT .kage — a file on disk is ambient state, not a live declaration; cold review #1)
   PROJECT   ←  within the resolved identity:  .kage marker (allow-gated) → cwd/git-branch → sticky → fallback → none
```

**Invariant:** *only a live user action may switch identity; every ambient/inferred signal — `.kage`, cwd, calendar, Focus — may only pick project inside the already-resolved identity.* This corrects both the Session-14 cascade (calendar at rank 2 resolved BOTH axes) and pitch v1 (which wrongly let `.kage` switch identity). A calendar "CS5200 lecture" event is inference → it may surface a project hint *in the bar*, never a silent identity move.

## Resolution: freeze the old resolver, move 4 consumers to a rich one (BLOCKER 3 fix)

Pitch v1 had this backwards. Correct design:

- **`_resolve_context` (the old 3-tuple) is FROZEN inference-free** — declared + sticky + fallback, exactly as today. This is what protects the read-only / echo-chamber callers *for free*: `observe.py:52` (tags observations — must never infer, or it closes a feedback loop: infer→tag→read→re-infer), the 3 `mcp_server` sites, `where`/`status`. A test asserts the old wrapper never infers. **`where` decision (residual):** it stays frozen and reports the *declared* context; the inferred project surfaces in the *context bar*, not in `where`. Explicit choice — `where` answers "what did I pin," the bar answers "what does kage think right now."
- **`_resolve_context_rich() -> Resolution`** (dataclass: per-axis `value, confidence, provenance`) is called by exactly **3 warm consumers** (cold review #2 cut the Librarian — NEW-2):
  1. `cli.py:1021` — `ask` (warm slice + rich)
  2. `cli.py:1858` — `chat` — **injection site NOT captured by the `_resolve_context` grep**; identity resolution is deliberately left unchanged (default `"personal"`, sticky never consulted — reversed NEW-4, build-time 2026-07-09); only the project axis infers, for the bar
  3. `cli.py:611` — `remember` (reads inference confidence → fires the Layer-3b save-time confirm prompt on low-confidence writes; interactive surface present)
  - **NOT Librarian `write_note`** — it runs at approval time (no interactive prompt surface), takes identity from the staging row via `resolve_write_identity` (`librarian.py:645-666`), and forcing resolution there re-opens the 28.1 fail-closed class. Librarian's writes keep their existing HITL + `resolve_write_identity` protection; 3a does not touch them.

**Consumer policy by confidence:** retrieval accepts any; **writes** on inferred context → confirm prompt (only where an interactive surface exists — `remember`); **disclosure (3e)** — inference may only ever *narrow* disclosure, never widen (fail-closed).

**`kage use` HARD DEPENDENCY (NEW-3):** because 3a promotes declared/sticky identity to the trusted root of the two-axis invariant, `kage use` (`cli.py:572-583`, today accepts any string) MUST validate the identity against the C28 registry — reject unknown, or confirm-create — before persisting it. A typo'd identity is otherwise a phantom write partition (the 28.1 wound through the front door). This is a slice-3 step, not optional.

**INVARIANT-ENUMERATION (paste, not memory) — BOTH cold reviews re-ran these:**
- **Resolution sites** — `grep -rn "_resolve_context" src/kage/*.py` → **13 call sites** (v1 miscounted as 14): `cli.py` 592/611/641/837/880/1021/1398 (7); `mcp_server.py` 22/45/77 (3); `observe.py` 52 (1); `scout.py` 273/520 (2). Only `611` (`remember`) and `1021` (`ask`) move to rich; the other 11 stay frozen.
- **Injection sites** (where a warm slice renders into a prompt) — **3, not 2** (cold review #2 caught the omission): `ask` (`cli.py:1021`), `chat` (`cli.py:1806`), **and `mcp_server.kage_ask` (`:77`, calls `_answer` at `:126` session / `_call_cloud` at `:247` stateless)**. Decision: **MCP ask is DEFERRED (stays cold) by design** — MCP clients are agents making programmatic calls, not the human at a running start; warm context is a human-session affordance. Stated explicitly so the omission is a decision, not a gap. The build's cold review MUST re-run BOTH enumerations and confirm MCP is still the only deferred injection site.

## Rendering — one generator, two consumers, budget-priced

Warm tier holds full fidelity in `warm.json`; only a curated **slice** enters any prompt (lost-in-the-middle bites 40–80k; 16k keeps us clear, but the slice stays tiny).

- **S-rendering (~60 tokens)** = the context-bar string, injected **adjacent to the question**, field order **stable→volatile** (prefix-cache stability; `now` rounded to 5-min buckets, last). *The string kage injects IS the string shown in the bar* — one generator, two consumers → Transparent for free. **This is only true because the bar uses `sanitize_fact()` (no fence), not `neutralize()` (see security).**
- **M (~300 tok)** = + resume pointer, day's calendar, pending count. Cloud can take S at first.
- **L** = only on explicit `kage context show`.

**Budget math (absorbs the 29.2 output-buffer candidate):** one shared pool — input+output share `num_ctx`. Reserve output:
`reserved_output (default 1500) + system + warm_slice + retrieved_context + history ≤ num_ctx`.
Trim input *before* dispatch if the estimate exceeds `num_ctx − reserved_output`; set `num_predict` so the model never writes into absent space; extend the 29.1 doctor headroom check to subtract `reserved_output`.

## Security — the honest version (guard does NOT compose for free)

1. **Injection (Cycle 30.2) — corrected.** Calendar titles / mail subjects are attacker-writable. But `guard.neutralize()` wraps ~38 tokens of `«UNTRUSTED-…»` fence per call — it cannot be the 60-token bar. **Two paths:**
   - **Local bar:** new `guard.sanitize_fact(text) -> (clean, findings)` = the sanitize half only (NFKC normalize + zero-width strip + injection-pattern scan) — cold review #2 VERIFIED this is a clean pure prefix of `neutralize()` at `guard.py:58-64`, no fence entanglement. If `findings` flags an injection attempt → **drop the fact** (don't render it) + `_write_audit`. `ponytail:` the `_INJECTION_PATTERNS` (`guard.py:30-39`) are broad — a legit calendar/mail title containing e.g. "you are now" gets silently dropped from the bar (audited, but an *awareness* regression, not a safety one). Ceiling accepted; upgrade = a tighter title-context allowlist if false-drops ever bite.
   - **Cloud egress:** the assembled warm slice joins the existing full `neutralize()` + `two_pass_gate` pass (see #3) — the fence is fine there, it's not user-facing.
2. **Identity leak:** every warm fact is identity-tagged; the S-renderer filters to the active identity — a school calendar title can never ride a personal-context prompt around the 3b wall.
3. **Egress ordering (M1) — pinned.** When an S/M rendering rides a *cloud* dispatch, the warm slice is assembled and threaded into the **same shared per-request mask map (Cycle 23 mask-at-dispatch) BEFORE `_answer` is called** — never appended after the gate pass. Assembly order: resolve → build warm slice → mask(query + context + warm slice, one map) → dispatch → restore. Stated as an invariant.
4. **Location = never egress:** timezone derived from Location on-device; kage reads the `TZ` string, never coordinates. Raw location (if ever read) joins the 3e hard-block class.
5. **Audit:** every context change + every dropped-injection fact writes `_write_audit`.

## The miss-metric — the learning sensor, built before the learning

Every `kage use` issued *after* an inferred resolution = a logged 3a miss → `kage-corrections` (the log `kage learn` already consumes). Inference hit-rate → a `kage status` line. v1 ships the sensor; the learned temporal-prior fallback (P(project | hour, weekday), simple counts, no ML) is v1.1 — but the fallback is written as a *function* now, not a literal, so it slots in without rework.

## Slices (build order)

1. **`warm.py`** — fact dataclass (optional validity window + provenance), `warm.json` store via new `atomic_write_json`, TTL refresh with the 4-op write. Pure logic. Test against a temp `warm.json`.
2. **Kernel producers** — wire shipped seams behind **fixed direct `_call_arm` calls (NOT `_detect_arms`** — keyword path is side-effecty; see ceiling), each TTL'd + `sanitize_fact`'d + identity-tagged. **REAL-SCHEMA RULE:** the `read_pipeline_state`/`list_pending_approvals` producers run SQL → test against a real `init_schema()` DB, not a mock.
3. **`_resolve_context_rich`** + two-axis split (identity = live-action-only; project inferable) + `.kage` **project-only** walk-up (allow-gated, ~40 lines stdlib, no dep) + confidence/provenance + **`kage use` registry validation** (NEW-3, reject unknown identity / confirm-create). **Freeze-test:** assert the old `_resolve_context` output is **byte-identical to today's** across all three branches (declared / sticky / fallback) — not merely "does not infer" (residual).
4. **S-renderer = context bar** (`sanitize_fact`, no fence), injected adjacent to question at BOTH injection sites (`ask`, `chat`); egress-order invariant (M1).
5. **Budget math + output-buffer reservation** + doctor extension.
6. **Miss-metric** + `kage status` line + `warm.alerts` reader (reserved seam, renders nothing yet).

## Deferred (leave the seam)

Learned temporal-prior fallback → v1.1 (written as a function now). Focus-mode signal → own research (note: **SSID moved Tier-1→Tier-2**, macOS gates it behind Location perm). M/L polish; alert-channel *rendering* → keystone cycle. Monitor auto-flip → daemon era (#80); file-as-daemon already accommodates.

## Known ceilings (ponytail)

- Warm slice is a len/4 token estimate, not a real count (shared with 29.1's tripwire).
- Cold-fault arm latency ~1–3s (osascript); amortized ~0 by TTL; stale-but-present served during refresh-in-flight rather than blocking.
- `.kage` precedence copies project-root-finder's model as a 40-line stdlib walk, not the library.
- `warm.json` last-writer-wins concurrency (see §Concurrency).

## Open decisions — RESOLVED by cold review #1

1. **Wrapper vs. signature change → WRAPPER, with the framing inverted (BLOCKER 3).** Freeze the old resolver inference-free; move the 4 enumerated consumers to rich; lock the freeze with a test. The risk isn't "two resolvers" — it's the old wrapper silently gaining inference and poisoning `observe.py:52` + read-only sites. The freeze-test bounds it.
2. **Validity windows → mutable-two only, plain TTL for the rest.** One code path, optional `superseded_at`.
3. **Calendar switch prompt → bar only, no prompt.** Awareness-over-control; per BLOCKER 2 it can't touch identity anyway; the miss-metric measures whether the inference was right.
4. **Enumeration → done.** 13 resolution call sites (none missed; count corrected) + a second injection-site enumeration (`ask`, `chat`); `observe.py:52` safety is the frozen inference-free wrapper, stated as the reason not a bespoke exception.
