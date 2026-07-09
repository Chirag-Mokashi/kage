# Cycle 7 Pitch — Privacy Gate Out (v0.7)

*Written: 2026-06-10*
*Status: DRAFT — pending Chirag approval.*

---

## Problem

kage currently sends retrieved memory chunks to cloud providers with zero
filtering. Every `kage ask --provider groq` ships your notes — all of them,
unredacted — to an external API. Notes containing Aadhaar numbers, PAN cards,
API keys, passport numbers, or anything tagged to a sensitive project leave the
machine silently.

The broker is realised when kage can switch freely between models and no content
is lost or leaked in the switch. That requires two things: (1) context is
preserved and correctly reassembled for whichever provider receives the query,
and (2) sensitive content is gated so a switch to a less-trusted provider does
not accidentally expose data the previous provider was never sent. Layer 3e is
the gate that makes switching safe. Without it, routing is unsafe — the right
answer might reach the user but the wrong data might reach the provider.

---

## Scope

One gate inserted at `_call_cloud()`. Two ways to mark content sensitive.
One audit trail. No cloud call happens without explicit user authorisation.

---

## Design

### The Disclosure Pipeline

```
   Query arrives (CLI or MCP)
        │
        ▼
   Layer 3b  — partition filter (project × identity × state)
   [existing] "Can this memory be retrieved at all?"
        │
        ▼
   Layer 3e  — disclosure gate  ← THIS CYCLE
   "Can this memory be dispatched to this cloud provider?"
        │
        ├─► PERMIT  → show dispatch summary, ask user, send on approval
        └─► BLOCK   → withheld notice, fall back to Ollama
        │
        ▼
   _call_cloud() / Ollama
```

### Two Ways to Mark Content Local-Only

**1. Per-note flag at save time**

```bash
kage remember "my Aadhaar is XXXX XXXX XXXX" --local
kage remember "passport renewal notes" --local
```

Stored as `local_only: true` in the note's markdown frontmatter and in
the `memories` SQLite table. Can also be added to an existing note:

```bash
kage forget <id>  # re-save with --local if needed
```

**2. Project-level rule in config**

```json
{
  "local_only_projects": ["health", "finance", "personal-docs", "credentials"]
}
```

Any note tagged to a listed project is automatically gated — no per-note
flag needed. New notes saved to those projects get `local_only: true` set
automatically on write.

Both mechanisms can coexist. A note is local-only if EITHER applies.

### Regex Detection (Stage 3 Tier A — v1)

Before dispatch, the assembled context is scanned for known PII patterns.
Any match → the note is treated as local-only for this dispatch, user notified.

```
  INDIAN IDENTITY DOCUMENTS
  ─────────────────────────────────────────────────────────────────────────
  Aadhaar          \b\d{4}[\s-]\d{4}[\s-]\d{4}\b           1234 5678 9012
  PAN card         \b[A-Z]{5}[0-9]{4}[A-Z]\b               ABCDE1234F
  Passport (IN)    \b[A-Z][0-9]{7}\b                        A1234567
  Voter ID (IN)    \b[A-Z]{3}[0-9]{7}\b                     ABC1234567
  Driving licence  \b[A-Z]{2}[0-9]{2}[\s-]?[0-9]{4,11}\b   MH01 2011012345
  GSTIN            \b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b
  IFSC code        \b[A-Z]{4}0[A-Z0-9]{6}\b                 SBIN0001234
  Vehicle reg (IN) \b[A-Z]{2}[\s-]?\d{2}[\s-]?[A-Z]{1,2}[\s-]?\d{4}\b

  CONTACT INFORMATION
  ─────────────────────────────────────────────────────────────────────────
  Email address    \b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b
  Phone (IN)       \b(\+91[\s-]?)?[6-9]\d{9}\b              +91 98765 43210
  Phone (intl)     \+[1-9]\d{1,14}\b                        +1-555-123-4567
  Indian PIN code  (?i)\bpin\s*(?:code)?\s*[:=]?\s*[1-9][0-9]{5}\b   pin: 560001

  FINANCIAL
  ─────────────────────────────────────────────────────────────────────────
  Credit/debit card \b(?:\d{4}[\s-]?){3}\d{4}\b             4111 1111 1111 1111
  UPI ID           \b[a-zA-Z0-9._-]+@[a-zA-Z]+\b            chirag@okaxis
  CVV              (?i)cvv\s*[:=]\s*\d{3,4}                 cvv: 123

  CREDENTIALS AND KEYS
  ─────────────────────────────────────────────────────────────────────────
  Password field   (?i)(password|passwd|pwd|secret)\s*[:=]\s*\S+
  OpenAI key       \bsk-[A-Za-z0-9]{20,}\b                  sk-abc123...
  Google key       \bAIza[A-Za-z0-9_-]{35}\b
  GitHub PAT       \bghp_[A-Za-z0-9]{36}\b
  GitHub OAuth     \bgho_[A-Za-z0-9]{36}\b
  AWS access key   \bAKIA[0-9A-Z]{16}\b
  Bearer token     (?i)bearer\s+[A-Za-z0-9\-._~+/]+=*
  JWT token        \beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b
  SSH private key  -----BEGIN [A-Z ]+ PRIVATE KEY-----
  .env secret      (?i)(SECRET|TOKEN|KEY|PASS)\s*=\s*\S{8,}

  NETWORK AND SYSTEM
  ─────────────────────────────────────────────────────────────────────────
  IPv4 address     \b(?:\d{1,3}\.){3}\d{1,3}\b              192.168.1.1
  IPv6 address     \b([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b
  MAC address      ([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}   AA:BB:CC:DD:EE:FF

  LOCATION
  ─────────────────────────────────────────────────────────────────────────
  GPS coordinates  -?\d{1,3}\.\d{4,},\s*-?\d{1,3}\.\d{4,}  12.9716, 77.5946
```

Pattern list is extensible — add custom entries to `~/.kage/config.json`
under `"pii_patterns": [{"name": "my-id", "pattern": "..."}]` without
code changes. The built-in list above is the default baseline shipped with v0.7.

Detection is local-only (regex runs on-device, never sends data to scan it).
Full NER cascade (Presidio + Qwen3-14B redactor) deferred to v2.

### Gate Behaviour — Ask Before Cloud, Notify What's Withheld

Two combined UX modes (B + C):

**Case 1 — Some notes withheld, rest can proceed:**
```
[kage] Preparing to send context to groq.
  · 4 notes matched your query
  · 1 withheld (local_only: personal-docs project)
  · 3 notes will be included

Proceed with partial context? [y/N]
```

**Case 2 — All notes withheld:**
```
[kage] All retrieved context is local-only.
  · 3 notes matched — all withheld (health project)
  · Answering with local Ollama only (no cloud call).
```
→ Falls back to Ollama silently. No prompt needed.

**Case 3 — PII detected mid-context:**
```
[kage] PII detected in 1 note before dispatch to openai.
  · Pattern matched: Aadhaar (note: 20260601T...)
  · Note withheld. Remaining 2 notes will be sent.

Proceed? [y/N]
```

User says N at any prompt → Ollama fallback, no cloud call made.
Per-session memory: approval for a given provider in a session is remembered
so the prompt does not re-fire for every query (opt-in, `--always-ask` to
override).

### Gate Placement — before _call_cloud() in both paths

The gate runs in `_ask()` (CLI) and `kage_ask()` (MCP) immediately before
calling `_call_cloud()`. Both entry points gate independently — no bypass
possible regardless of which surface the query arrives from.

```
  CLI:  kage ask → _ask() → [3e gate] → _call_cloud() → provider
  MCP:  kage_ask → [3e gate] → _call_cloud() → provider
```

Local Ollama path is exempt — data never leaves the machine.

### Audit Log

Append-only JSONL at `~/.kage/audit.jsonl`. One record per dispatch attempt.

```json
{
  "ts": "2026-06-10T14:32:01+05:30",
  "provider": "groq",
  "project": "kage",
  "notes_retrieved": 4,
  "notes_withheld": 1,
  "withheld_reasons": ["local_only:personal-docs"],
  "pii_detected": [],
  "user_approved": true,
  "outcome": "dispatched"
}
```

Queryable via `kage status --audit` (last N dispatches). No crypto in v1 —
Ed25519 hash-chain deferred to v2.

### Config Schema (JSON v1)

```json
{
  "local_only_projects": ["health", "finance", "personal-docs"],
  "pii_patterns": [],
  "require_approval": true,
  "session_remember_approval": true
}
```

`require_approval: false` disables the ask prompt (not recommended — turns
off the C gate, keeps B notification only).

---

## Implementation Order

1. Add `local_only` field to `memories` table schema + markdown frontmatter
2. Add `--local` flag to `kage remember` → sets `local_only: true` on save
3. Add `local_only_projects` to config schema + auto-flag notes on save
4. Write `_pii_scan(text) → list[match]` — regex patterns, extensible
5. Write `_disclosure_gate(chunks, provider) → (allowed, withheld, pii_hits)`
   — combines local_only flag + project rules + PII scan
6. Insert gate into `_call_cloud()` before dispatch
7. Implement B+C UX — withheld notice + approval prompt with session memory
8. Implement Ollama fallback when gate blocks all context
9. Append to `~/.kage/audit.jsonl` on every gate decision
10. Add `kage status --audit` to show last N dispatch records
11. Update `kage status` — show local-only note count
12. Update `kage doctor` — validate `local_only_projects` config + audit log writable
13. Tests (see below)

---

## Tests

- `--local` flag sets `local_only: true` in frontmatter + DB
- Notes in `local_only_projects` are auto-flagged on save
- `_disclosure_gate` withholds local_only notes from context
- `_disclosure_gate` withholds PII-matched notes (Aadhaar, PAN, API key)
- `_pii_scan` correctly matches all 6 pattern types
- `_pii_scan` returns empty list on clean text
- Gate blocks entire dispatch when all notes are withheld, falls back to Ollama
- Approval prompt fires before cloud call (Case 1 + Case 3)
- No prompt fires when all withheld (Case 2 — Ollama fallback, silent)
- Session approval memory suppresses re-prompt for same provider
- Audit log entry written for every gate decision (dispatched + blocked)
- MCP `kage_ask` path also goes through gate (no bypass via MCP)
- `kage doctor` flags missing `local_only_projects` key in config
- `kage status` shows local-only note count

---

## What This Unlocks

- kage is a true broker: cloud tools see the minimum slice, not everything
- Personal identity documents (Aadhaar, PAN, Passport) never reach cloud APIs
- Sensitive projects (health, finance) stay local regardless of provider used
- Audit trail: "what did kage send to Groq last Tuesday?" is answerable
- MCP clients (Claude Code, future tools) are gated — no bypass via MCP
- Foundation for Layer 4 auto-routing: the router can now safely switch
  providers knowing 3e will gate each one correctly

---

## What Is NOT In This Cycle

- Identity-level dispatch rules — needs Layer 3a first
- Presidio / NER cascade (Stage 3 Tier B + C) — v2
- MODIFY policy outcome — v2 (redact-and-send vs. full block)
- Ed25519 hash-chained audit — v2
- Risk-adaptive confirmation UX (high/med/low risk tiers) — v2
- Rego / Cedar policy engine — only if JSON hits limits
- State partition dispatch rules — needs Layer 3a first

---

## Deferred to Blueprint Backlog

- Per-provider token budget enforcement (Stage 2 minimization — #3d hand-off)
- Cross-provider trust tiers (Groq vs. OpenRouter vs. OpenAI policy defaults)
- Chunk-level redaction (currently note-level gate only)
- `kage audit` as a first-class command with filtering + export
