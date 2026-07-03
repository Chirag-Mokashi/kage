# Cycle 27 — Two-Pass Privacy Gate (v3, PLAN — two cold reviews incorporated)

> **v3 changelog (cold review #2, adversarial vs real repo):** one NEW blocker + fixes to the v2 fixes.
> **B4 (new, highest-value):** `kage learn`/ProTeGi reads `kage-corrections` straight from SQLite (`learn.py:173-193`) and sends it to cloud ungated (`learn.py:216`) — but `kage-corrections` is in `_ALWAYS_LOCAL_PROJECTS` (`privacy.py:9-13`), hard-blocked everywhere else. An 11th egress path leaking the MOST-protected project. Inventory is now **11 sites**. Fix: gate `correction_texts` (one-way, no restore) before `_build_meta_prompt`.
> **B1 refinement:** the `ask` query and context MUST share one mapping (`existing_mapping=`) or the same value gets different placeholders in question vs context (incoherent). **B2 refinement:** the fix lives in `_call_arm` (`arms.py:212`, transport known), NOT `_select_tool` (`arms.py:89`); and `sse` is DORMANT — defense-in-depth, not an active leak. **B3 refinement:** vault anonymity is achieved by shimming vault patterns with a generic name (`{"name":"REDACTED"}` → `[REDACTED_N]`), zero `redact.py` change; daemon `str→str` paths (`librarian.py:347`, `pii.py:60`) emit a constant string, not via `substitute`. **C1:** daemon `_gate_text` signatures differ (`pii.py:55` no cfg; `librarian.py:331` takes cfg + reads `cfg["pii_patterns"]`) — Slice 2 must reconcile the extra-pattern source. **Restore ordering:** keep `restore()` OUTSIDE the `auto` provider-retry loop (`cli.py:1129-1149`) — add a test. Verified sound: two-contract design, `runtime.config.home` exists, retrieval+embeddings are LOCAL so post-retrieval query masking is safe, vault-first ordering safe against the `(?<!\[)` rematch guard.

# Cycle 27 — Two-Pass Privacy Gate (v2, PLAN — cold review #1 incorporated)

*Status: PLAN (cloud-authored, decisions locked with Chirag 2026-07-03). No code yet.*
*Discipline: 7-step dev-workflow gate. Local writes code/tests; cloud reviews every slice. Cold reviews before code + before PR.*
*Privacy-first cycle: real PII never enters the repo (code/tests/docs/commits use synthetic values only); the vault/allowlist/queue live in `~/.kage/`, never committed.*

> **v2 changelog (cold review #1, adversarial vs real repo):** three blockers fixed in text before code —
> **B1:** `kage ask` masks only context/arm_context today; the raw `question` leaks to cloud (`cli.py:1128`). The gate MUST treat the query as a masked fragment on the `ask` path (chat/mcp already do). **B2:** remote `sse` arm input (`arms.py:89` → `arms.py:63-66`) sends the raw query off-machine — added to inventory; v1 gates the query before `sse` dispatch (local transports exempt, on-machine). **B3:** vault hits leak the *label* today (`librarian.py:347` `[SENSITIVE:label]`, `pii.py:60` `SENSITIVE_{label}`) — vault Pass-1 hits now emit a FIXED anonymous placeholder; Slice 2 replaces both schemes. Plus concerns C1–C5 and nits folded into the sections below. Load-bearing: the vault-first ordering flip must happen at EVERY site (all are generic-first today: `cli.py:1095`, `mcp_server.py:117/212`, `pii.py:64`, `librarian.py:335+345`).

---

## Why

kage now handles real personal data (identity emails today; account numbers next). The disclosure gate (Layer 3e) currently:

- Runs a **single blanket pass** (`_PII_PATTERNS + vault_patterns`) — generic-first, so the vault is redundant for anything generic already catches, and there is **no vault priority**.
- Is **duplicated across ~8 call sites** (cli `ask`, cli `chat`, `mcp_server` ×2, `scout`, `librarian`, `monitor`, `observe`) — each re-implements `load_vault() + substitute()`. Divergence risk; violates the Cycle 12 "one egress sink" principle. **Corrected inventory (two cold reviews) = 11 sites.** Three egress paths were missing: (a) the raw **query** on the `ask` path (`cli.py:1128`, unmasked today = B1, LIVE); (b) **arm input** for a remote `sse` transport (`arms.py:89` builds `{'query': question}` → `arms.py:63-66` posts off-machine = B2, DORMANT); (c) **`kage learn`** ships raw `kage-corrections` to cloud from SQLite ungated (`learn.py:173-193, 216` = B4, LIVE, and it's an `_ALWAYS_LOCAL_PROJECTS` project). Consolidation must cover all three, or it preserves the leaks. The egress golden test asserts **11** sites funnel through the gate.
- Runs **two gate contracts**, not one (cold review C1): **round-trip** paths (`ask`/`chat`/`mcp`) thread a shared per-request mapping across fragments and `restore()` the cloud answer (Cycle 21); **one-way** daemon paths (`scout`/`librarian`/`monitor`/`observe`) run inside ADK `before_model_callback` seams that mutate `part.text` in place (`str→str`, no restore). The shared gate returns `(masked, mapping)`; daemon callers use `[0]` and ignore the mapping — the callback signature must not change.
- Has **no HITL, no allowlist, no skip-public, no memory of decisions** — so it re-redacts *everything* PII-shaped forever, including public info that came *from* the cloud (e.g. a generic GitHub email pulled via a web search). Pointless work, and no way to say "this one's fine."
- Ships a **stale/incorrect message** at `cli.py:1999-2000` claiming `ask`/`chat` don't apply the vault. They do (`cli.py:1087-1098`, `1683-1711`). Fix it.

Chirag's model: **two passes.** Pass 1 = known essentials (vault) auto-redacted, silent. Pass 2 = generic patterns catch anything new; a *new* hit is redacted-and-queued for a human decision (keep-hiding vs it's-public), and the decision is remembered so we never re-ask. Separates "my essential private info" (always hide) from "generic/public stuff" (ask once, usually skip).

## Non-goals (explicitly deferred)

- **Auto-identity detection/routing** — kage guessing which identity a query belongs to. A probabilistic router must NOT decide privacy boundaries. Identity stays explicitly set via `kage use`. (Future cycle.)
- **Identity registry + account-scoped arms** — that is Cycle B ([[project_identity_algorithm_separation]]), built after this gate is solid.
- **Query-provenance tracking beyond a source label** — we record where a hit came from (arm/notes/web) but don't build a full provenance graph.

## Locked decisions

- **D1 — one shared gate.** Consolidate the ~8 call sites into a single `two_pass_gate()` function everything routes through. One place to audit.
- **D2 — vault-first, anonymous placeholders.** Pass 1 (vault) runs before Pass 2 (generic), because Pass 1 is silent/auto and must consume vaulted values before the "new hit?" logic. All hits → anonymous typed placeholders (`[EMAIL_1]`, `[REDACTED_1]`); the vault **label never surfaces to cloud** (structural, regardless of label text).
- **D3 — fail-closed + async review queue.** A new (non-vaulted, non-allowlisted) hit is ALWAYS redacted immediately (never leak, never block) and logged to a review queue. `kage privacy review` lets Chirag decide per item: keep-hiding → vault, or public → allowlist. Decision remembered. Inline y/n prompt only in the `chat` REPL (the one place a human is present mid-run).
- **D4 — separate `~/.kage/allowlist.json`.** Mirror of the vault; `kage allow list/add/remove`. Vault = always-hide, allowlist = never-hide, kept independent.
- **D5 — fail-closed is universal** (falls out of D3). MCP + Scout/Librarian/Monitor daemons redact-and-queue with no prompt. Interactivity is an optional fast-path, never required for safety.
- **Queue dedup:** each distinct normalized value queued once; values already in vault or allowlist are never queued.
- **Un-allowlistable types:** high-value secrets (SSH/private keys, cards, AWS/API keys, JWT, bearer) are always redacted and CANNOT be allowlisted — no footgun.

## The three stores (all human-readable, all local, none committed)

```
~/.kage/sensitive.json   vault      — always hide (exists; Cycle 19)
~/.kage/allowlist.json   allowlist  — never hide (new)
~/.kage/privacy_queue.jsonl  queue  — pending new-hit decisions (new)
```

Queue entry (one JSON object per line):
```
{ "value": "<the raw hit>", "type": "Email", "placeholder": "[EMAIL_3]",
  "source": "arm:browser" | "notes" | "chat", "ts": "<iso>", "status": "pending" }
```
`value` is stored locally so `kage privacy review` can show what you're deciding on; the file never leaves the machine.

## The gate algorithm (`two_pass_gate(text, *, interactive=False, source="", existing_mapping=None)`)

Patterns applied **vault-first** (C5): `vault_pats + _PII_PATTERNS`, reversing today's generic-first order at every site. `redact.substitute` won't re-match placeholders (`redact.py` `(?<!\[)` guard), so a vaulted value consumed in Pass 1 can't re-hit in Pass 2 → no double-count.

```
1. Pass 1 — vault: shim vault patterns with generic name {"name":"REDACTED"} so
             substitute emits [REDACTED_N] — the user's LABEL is never in the mapping
             key or the cloud text (fixes B3, zero redact.py change). (silent)
2. Pass 2 — generic (_PII_PATTERNS): load allowlist+queue into sets ONCE per call (C4/perf).
   for each match not already consumed:
     - norm = value.strip().lower()          # defined normalization (C4)
     - if norm in allowlist              → leave cleartext (skip)
     - elif type in _UN_ALLOWLISTABLE    → redact (never queue)   # named constant (N3)
     - elif norm in vault or already queued → redact (dedup, no new entry)
     - else                              → redact + append to queue (status=pending)
                                            audit-log the queued event (N4)
3. return (masked_text, mapping)
```

**Fragment coverage (B1/B2/B4):** callers pass EVERY outbound fragment through the gate, threading `existing_mapping` so one shared map covers a request. On `ask` that includes the **query/`user_msg`** — and it MUST reuse the context's mapping (`existing_mapping=sub_mapping`) so the same value gets the same placeholder in question and context (coherence, B1 refinement). `kage learn` gates `correction_texts` before `_build_meta_prompt` (one-way, mapping discarded — the output is prompt-rules, no restore). Remote `sse` arm dispatch gates the query **in `_call_arm` (`arms.py:212`, where transport is known)**, not `_select_tool`; local `shell`/`stdio`/`browser` transports are on-machine and exempt.

**Two contracts (C1):** round-trip callers keep the mapping and `restore()` the answer (unchanged, Cycle 21) — and `restore()` stays OUTSIDE the `auto` provider-retry loop (`cli.py:1129-1149`) so a vault value can't round-trip to the next provider. One-way daemon callbacks do `part.text = two_pass_gate(part.text, ...)[0]` — mapping discarded, no restore, `str→str` shim preserved. Daemon `str→str` paths (`librarian.py:347`, `pii.py:60`) emit the constant `[REDACTED_N]` string directly, NOT via the round-trip `substitute` mapping. Slice 2 reconciles the differing daemon signatures (`pii.py:55` no cfg vs `librarian.py:331` cfg + `cfg["pii_patterns"]` extra-pattern source).

**Interactive semantics (C3):** the query is ALWAYS redacted first; an inline `chat` prompt only updates a store for *future* turns (→ vault or → allowlist) — it never un-masks or re-sends the in-flight request. Dedup is checked before prompting so the same value doesn't prompt twice.

**KAGE_HOME (C2):** new `allowlist.json` / `privacy_queue.jsonl` loaders resolve via `runtime.config.home`, NOT hardcoded `~/.kage` (the `load_vault()`/`learn.py home=` trap). `sensitive.load_vault()` should be migrated to the same in Slice 1.

## CLI surface (new)

- `kage privacy review` — list pending queue items (value, type, source, ts); for each: `[v]ault / [a]llow / [s]kip`.
- `kage allow list | add <label> <value> | remove <id>` — manage the allowlist.
- (fix) remove the stale note at `cli.py:1999-2000`; replace with an accurate one.

## Slices (each a PR through the 7-step gate)

0. **This pitch + cold reviews** (cold review #1 done; #2 optional pre-code). No code.
1. **`two_pass_gate()` core + stores** — the function (vault-first, fixed anonymous vault placeholder, `existing_mapping` threading), `allowlist.json` + `privacy_queue.jsonl` loaders **via `runtime.config.home`** (C2), `.strip().lower()` normalization + O(n)-scan `ponytail:` ceiling note (C4), `_UN_ALLOWLISTABLE` named constant (N3). Unit-tested in isolation with synthetic PII.
2. **Consolidate call sites (all 11)** — route every egress through `two_pass_gate()`: the 8 known + **`ask` query** with shared `existing_mapping` (B1) + **`sse` arm-input query in `_call_arm`/`arms.py:212`** (B2) + **`kage learn` correction_texts** (B4, one-way). Reverse generic-first→vault-first at each (`cli.py:1095`, `mcp_server.py:117/212`, `pii.py:64`, `librarian.py:335+345`). Shim vault patterns with generic `{"name":"REDACTED"}`; **replace** the label-leaking `librarian.py:347` (`[SENSITIVE:label]`) and `pii.py:60` (`SENSITIVE_{label}`) with the constant `[REDACTED_N]` string (B3). Reconcile daemon signatures + the `cfg["pii_patterns"]` extra-pattern source (C1). Keep `restore()` on round-trip paths and OUTSIDE the `auto` retry loop; daemon callbacks stay `str→str` shims. Extend Cycle 12 egress golden tests to assert all 11 paths funnel through the one gate and none bypasses it.
3. **`kage privacy review` + `kage allow`** — review UX (shows value, type, `source`, ts → `[v]ault/[a]llow/[s]kip`) and allowlist commands; inline y/n in `chat` (future-turns only, C3); audit queue/allow decisions (N4). Fix the stale note at `cli.py:1998-2001` (also wrongly claims scout/librarian are the only vault paths — N1). Add `privacy_queue.jsonl` to any commit-guard alongside `sensitive.json` (N2).
4. **Consolidated cold review + PR.**

## Testing (Step 5/7, synthetic PII only)

- **B1 regression:** `kage ask "...john@synthetic.test..."` → query reaches cloud masked (mirror the existing chat guard at `tests/test_cli.py:4416-4430`, which covers chat but NOT ask). **Coherence:** same synthetic email in question AND context → SAME placeholder (shared mapping).
- **B2:** a remote `sse` arm receives a masked query; a local `shell`/`stdio` arm receives the raw query (on-machine, expected).
- **B4:** `kage learn` with a synthetic-PII correction note → the meta-prompt sent to cloud contains no cleartext PII (gate applied before `_build_meta_prompt`).
- **Restore-loop:** `ask --auto` fallback across ≥2 providers → each provider receives masked text; `restore()` runs once, after the loop (no vault value re-sent to a later provider).
- **B3 anonymity:** no vault label (e.g. a synthetic `burner`-labelled value) ever appears in gate output — assert against ALL paths incl. `librarian` and `pii._gate_text`.
- Vault-first ordering: a vaulted value never appears as a queue entry (guards the concat-order flip).
- Fail-closed: non-interactive new hit → redacted + queued, output contains no cleartext PII.
- Allowlist: an allowlisted value passes through cleartext; removing it re-queues.
- Un-allowlistable: attempting to allowlist a private key / card is rejected.
- Dedup: `John@X.test` and `john@x.test` across two calls → one queue entry (normalization).
- KAGE_HOME: stores resolve under a `tmp_path` `runtime.config.home`, not the real `~/.kage`.
- Egress golden (extend Cycle 12): every egress path (10 sites) routes through `two_pass_gate()`; no path bypasses it.

## Cold-review log

- **Cold review #1 (DONE, 2026-07-03)** — independent subagent vs real repo. Found 3 BLOCKERS (B1 `ask` query unmasked; B2 `sse` arm-input egress; B3 vault-label leak on librarian/pii paths), 5 concerns (C1 two contracts, C2 KAGE_HOME, C3 resolve-immediately semantics, C4 dedup normalization + O(n) ceiling, C5 ordering-flip-at-every-site), 4 nits (N1 stale-note line/scope, N2 gitignore queue, N3 `_UN_ALLOWLISTABLE` constant, N4 audit decisions). All incorporated in v2 above. Verdict: direction sound; the inventory was the load-bearing gap.
- **Cold review #2 (DONE, 2026-07-03)** — independent subagent, adversarial. Found 1 NEW blocker **B4** (`kage learn` ungated egress of `kage-corrections`, an always-local project — the inventory's 11th site and highest-value catch). Verified B1 real (+ shared-mapping coherence req), corrected B2 fix location (`_call_arm` not `_select_tool`; path is dormant), corrected B3 mechanism (generic-name shim, daemon paths emit constant string not via `substitute`). Verified sound: two-contract design, `runtime.config.home` exists, retrieval/embeddings local (query masking safe post-retrieval), vault-first ordering safe. Flagged restore-outside-retry-loop + load stores into a set once/call. All incorporated in v3. **Verdict: inventory now 11 sites; B1/B2/B4 fixes specified against real code; ready for Slice 1.**
