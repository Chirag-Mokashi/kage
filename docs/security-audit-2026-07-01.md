# kage — Security Audit & Hardening Reference

*Created: 2026-07-01. Source: adversarial trust-boundary audit of the Layer 3e
disclosure gate on main @ v0.22.0. Keep this open while Cycle 23 lands.*

*This is the READING doc. The build plan is [cycle-23-gate-hardening.md](cycle-23-gate-hardening.md).*

---

## The one-line honest summary

> The 3e gate is **functionally sound for its primary threat model** — a
> single-shot `kage ask` will not blind-send unmasked PII to the cloud. It is
> **not** forensically clean (audit reveals structure, chat history stores real
> values) and **not** cryptographically resistant (placeholders are reversible,
> the audit log is plain append-only text). Appropriate for a single-user local
> machine; would need hardening before any networked or multi-user exposure.

---

## Threat model (what the gate is actually defending)

```
   TRUSTED                          │  UNTRUSTED
   ────────────────────────────────┼──────────────────────────────
   ~/.kage/memory/*.md  (source)    │  cloud LLM providers (Claude,
   ~/.kage/indexes/*    (derived)   │    OpenAI, Gemini, Groq, …)
   ~/.kage/config.json  (secrets    │  remote SSE / stdio MCP arms
      referenced by env-var name)   │  MCP *clients* (Claude Code,
   the local Ollama model           │    Cursor, Antigravity)
   ────────────────────────────────┼──────────────────────────────
   Everything left of the line is   │  Anything crossing right MUST be
   assumed honest (single user,     │  blocked, masked, or explicitly
   own machine).                    │  user-approved.
```

The gate's job is the boundary crossing. The findings below are ranked by how
much they weaken that crossing **for the local single-user model kage actually
ships in** — not by abstract CVSS.

---

## Cold-review corrections (2026-07-01, after this audit)

The Cycle 23 pitch cold review verified these findings against code and adjusted two:

- **F1 is smaller than rated.** `pii_detected` already logs pattern *names*, not
  raw substrings (`pii.py:67-79`). The only reversible leak is `placeholder_labels`
  at `cli.py:1137` (three other write sites already log `[]`).
- **F7 surface is mostly closed.** `shell=True` is absent everywhere in `arms.py`
  and `shlex.split` neutralizes `;`/`|` chaining. Residual risk is interpreter
  smuggling (`bash -c "…"`), addressed at both `arms.py:92` and `:261`.
- **F2 fix redesigned.** "Store masked" was rejected — `session_turns` also feeds
  the trusted local model + display, which must see real values. Fix is now
  mask-at-dispatch (see pitch S1).
- **NEW — F13: the condensed query leaks unmasked (HIGH).** Not in the original
  audit; found by the pitch's 2nd cold review. `_condense_query` (`session.py:124-128`)
  splices the last assistant turn's REAL content into the string sent to the cloud
  as `question` (`_answer`, `cli.py:405-408`) — masked nowhere today. A follow-up
  like "what's their email?" splices a real address into a cloud request in
  cleartext. Fixed by Cycle 23 S1 (mask the condensed query with the shared mapping).
- **F5 is narrower than stated.** `restore()` is `str.replace`, so it only reverses
  a *verbatim* placeholder echo; non-verbatim reformatting is a known ceiling, not
  a full round-trip guarantee.
- **N4 — existing PII patterns aren't placeholder-safe.** `pii.py:32,34,35,43` use
  greedy `\S+`/`\S{8,}` that can swallow an adjacent `[LABEL_N]` placeholder,
  corrupting dispatch masking. Cycle 23 S5 fixes the existing patterns, not just
  new ones.

## Findings — ranked for the real threat model

### Fix now (Cycle 23)

| # | Finding | Where | Sev | Status |
|---|---------|-------|-----|--------|
| F2 | **Chat history stores restored real values.** After a cloud reply, `restore()` swaps placeholders → real values, and the *restored* text is written to `session_turns`. Later turns read it back; a destination switch can't un-leak what's already stored. In practice `_gate_conversation` then withholds those turns → progressive **context-blinding** in long PII-heavy sessions. | `cli.py:1699-1716`, `mcp_server.py:122-136`, `session.py:49-108` | HIGH | Known (B3); ponytail comment wrongly says "Cycle 22" fixes it — it does **not**, still open |
| F5 | **PII echo-back.** If the cloud model repeats a `[SSN_1]` placeholder in its answer, `restore()` swaps the real value back into the *stored + displayed* answer. Same root cause as F2. | `redact.py:60-64`, `cli.py:1699-1717`, `mcp_server.py:122-136` | MED | Implicit |
| F1 | **Audit log leaks placeholder structure.** `placeholder_labels` writes the numbered keys (`[EMAIL_2]`, `[CREDIT_DEBIT_CARD_1]`). Correlating these across requests + a leaked session map enables reverse-mapping. | `cli.py:1137`, `privacy.py:10-16` | HIGH* | Design gap |
| F7 | **Shell arm command injection.** `arm_cfg["command"]` from config runs via `subprocess.run(shlex.split(cmd))` with no allowlist / no metacharacter rejection. A compromised or fat-fingered config runs arbitrary commands. | `arms.py:88-103` | MED | Trust-in-config, undocumented |
| F3 | **MCP server has no auth / authz.** Any connected client can `recall`/`remember`/`ask` under *any* identity string; the audit records the *client-supplied* identity, not the caller. Fine for local stdio; a real hole the moment it's relayed over a network. | `mcp_server.py:16-268` | HIGH if networked / LOW if local-stdio | Implicit assumption, undocumented |
| F4 | **PII regex coverage gaps.** Non-ASCII emails, non-Indian passports, AMEX/Diners cards, DB connection strings, non-`eyJ` tokens all evade. Creates *false confidence* — gate reports "clean" on data it never recognized. | `pii.py:12-51` | HIGH | Partial docs |

\* F1 is HIGH by the auditor's rating; in the local single-user model its real
risk is lower (needs local read of both `audit.jsonl` *and* live process memory).
Cheap to fix, so it's in scope.

### Accept & document (parked, with reasons)

| # | Finding | Where | Sev | Why parked |
|---|---------|-------|-----|-----------|
| F6 | PII scan runs on whole note body, not the chunk actually sent. | `privacy.py:70-86` | MED | Observational only — real filtering is at dispatch-time `substitute()`. Not a leak. |
| F8 | Scout/Librarian `_pii_seam` may not see all ADK message contents (Jina-fetched article text could bypass). | `scout.py:70-73,278-285`, `librarian.py:369` | MED | Depends on ADK callback semantics; documented ceiling. Needs live ADK verification, not a code guess. |
| F9 | Audit log not tamper-resistant (plain JSONL, editable). | `privacy.py:13-16` | MED | Crypto signing is heavy; low value for single-user local. The log is observational, not itself a security boundary. |
| F10 | Session substitution map grows unboundedly. | `cli.py:1689` | LOW | Ponytail already notes it; only bites in extreme sessions. Cap+evict when it matters. |
| F11 | Config *could* hold plaintext keys if user hand-edits. | `cli.py:108-121` | LOW | Default design references env vars, not stored keys. Sound as-is; document the footgun. |
| F12 | No recursive check that placeholders aren't themselves flagged as PII. | `redact.py:27` | LOW | Theoretical; placeholders are designed unmatchable. |

---

## Root-cause clustering (why Cycle 23 groups the way it does)

```
   F2 + F5  ─── one root cause: "restore mutates what we STORE, not just
                what we DISPLAY."  Fix = store masked, restore at the
                display/return boundary only, with a per-session map that
                persists so placeholder numbering stays consistent.

   F1       ─── audit writes the reversible artifact (numbered keys) instead
                of a non-reversible summary (type counts).

   F7       ─── one missing validation at one call site.

   F3       ─── an undocumented trust assumption + audit mislabels who asked.

   F4       ─── open-ended; the user vault (`kage sensitive`) already exists
                for the long tail. Fix = close the common gaps + tell the
                truth about coverage, NOT chase every format.
```

---

## The MCP persistence wrinkle (important for the F2 fix)

The REPL keeps `session_sub_mapping` in a loop variable, so within one `kage
chat` it persists and placeholder numbering is consistent. **MCP does not** —
`_mcp_sess_map` is created fresh per `kage_ask` call (`mcp_server.py:117`, no
`existing_mapping`). So "store masked" without persisting the map means a later
MCP call re-numbers from `[EMAIL_1]` against *different* real values than the
`[EMAIL_1]` already sitting in stored history → **collision on restore**.

Therefore the F2 fix must persist the per-session `placeholder → real` map
locally (SQLite table or sidecar keyed by `session_id`). Real values in that map
live at the same trust level as the memory files (local plaintext) — the point
is only to keep them out of the *cloud-bound* history/context, which is achieved.

---

## Out of scope for security work (the broader horizon — separate track)

For context only. These are *capability* gaps, not security gaps, and follow
Cycle 23:

- **Layer 3a auto-context** — blueprint's "★ BUILD, kage-unique." Today
  `context.py` is explicit→sticky→fallback; no git/cwd inference. (Aware)
- **Push / interrupt model** — the Jarvis keystone (silent baseline +
  threshold-triggered interrupt). Monitor watches but kage has no way to speak
  up. (Silent + Controlled)
- **Interactive agent loop** — `_detect_arms` is single keyword→one arm, not
  plan-then-execute. (Mediator)

These are what move kage from BROKER (shipped) → MEDIATOR/COMPLEMENT (identity).

---

## Also-noticed doc debt (not security, cheap)

- `docs/gaps/gap-tracker.md` — all 10 entries say `OPEN`; the code has every fix
  (verified). Statuses never updated after Cycle 17 merged.
- `CLAUDE.md` header still says "Cycle 20 merged — v0.20.0" (now v0.22.0).
- The `cli.py:1711` ponytail's "(Cycle 22)" forward-reference is stale/wrong.
- `pyobjc-framework-ApplicationServices` not installed → Monitor AX daemon can't
  run on this machine.
- Missing semver tags: v0.13, v0.16–v0.21 never tagged.
