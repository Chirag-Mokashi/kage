# Cycle 10 — Stateful Session Engine + Safe Model-Switching (v0.10)

*Status: SHIPPED v0.10.0 (`8071e3e`) — pitch v3 (cloud-authored, Opus, 2026-06-13). Two fresh-eyes reviews + design sessions.*

> **Roadmap position:** Cycle 8 (retrieval) and Cycle 9 (identity axis — the moat) are SHIPPED. Cycle 10 gives kage a **stateful session engine** — the step that turns it from a stateless forwarder into the "brain" — and lays the privacy foundation that reversible-redaction (Layer 3e v2) and auto-routing (Cycle 12+) both stand on. See [[project-mediator-vision]].

---

## Framing — what this cycle ships (and what it deliberately is NOT)

**The deliverable is the session ENGINE**: kage owning multi-turn conversation state, with the identity wall + disclosure gate holding across turns and across model switches, reachable over MCP. That engine is what external surfaces (Odysseus, Claude Code) render.

`kage chat` is **a local dev/debug cockpit over that engine — not a product surface, not kage's "face."** This preserves the locked **Silent / Invisible** characteristics: kage stays headless; the REPL is how *Chirag* drives and tests the engine, the way `kage doctor` is a tool, not a face. UX is explicitly not the moat and not claimed as one.

## Problem

Today every `kage ask` (CLI, [cli.py:1205](../src/kage/cli.py#L1205)) and every MCP `kage_ask` is **single-shot and stateless**. Follow-ups ("compare *it* to Y") can't work, the disclosure gate re-runs cold each time, and there is no session for the future Librarian / pending auto-promptor to watch ([[project-pending-promotion-vision]]).

As long as conversation state lives only in Odysseus or Claude Code, **kage is permanently a stateless backend and can never become the mediator** the vision requires. *Odysseus is scaffold only* — that is only true in code once kage owns the session.

**The moat, stated honestly (2026).** Multi-turn chat and mid-conversation model-switching are commodity (LibreChat's headline feature; Open WebUI does it too). PII redaction before cloud is *also* now commodity — Cherry Studio, Microsoft "PII Shield" (mask + reverse after response), Tonic.ai, and OpenAI's local Apache-2.0 Privacy Filter all ship it. So "we redact PII" is **not** a differentiator, and reversible redaction alone is not novel. kage's uncontested wedge is the **combination**: a per-**identity** partition wall + project soft-filter + per-destination disclosure gate, enforced **inside the one local broker that also owns conversation state and routes across vendors**. Competitors do multi-**user** isolation (RBAC between people); none does multi-**identity** disclosure for a single person inside a routing broker. Cycle 10 extends that wedge to a stateful, model-switching surface.

## Appetite

One cycle. Two theses — **stateful engine + safe model-switching** — after deferring live streaming (below). Local Ollama path is zero-API-cost. A **circuit-breaker** (de-scope ladder) is included for honesty about size.

## Solution

### 0. The keystone: pinned persona, switchable destination, safety by re-gating

> **(identity, project) are pinned at session open and immutable for its life. The model/destination is FREE to switch mid-conversation. Safety comes from the gate re-running on every turn and every switch — not from locking the destination.**

- **identity/project pinned** → `_allowed_note_ids` returns the same hard wall on every turn; a NEU session can never surface a personal note, even at turn 50. Switching *persona* mid-conversation is out of scope (a different, more dangerous thing).
- **destination switchable** → move local → groq → claude mid-conversation with context intact (the competitor norm). The leak this would normally cause is closed by re-gating, below.

Auto-routing (Cycle 12+) is just *kage choosing the destination for you*, protected by the identical re-gate machinery built here.

### 1. The gate runs over the *whole conversation, every turn* (the safety foundation)

Today `_disclosure_gate` ([cli.py:684](../src/kage/cli.py#L684)) scans only retrieved **note bodies** — a secret typed straight into chat ("my key is sk-…") would sail through. Cycle 10 extends it to gate the **full turn context** against the **current destination**:

- **Note provenance** — each turn records *which note IDs fed it* (in `session_turns`). On a switch to a more-exposed destination, any prior turn whose notes fail the gate for the new vendor is withheld from that vendor.
- **Conversation text** — the user's typed messages *and* model replies are PII-scanned (`_pii_scan`) too — catching typed/emitted secrets no note-provenance check would see.

Non-negotiable per Chirag: by ~v10 he talks to kage conversationally and must never manually flag sensitivity. **Cycle 10's gate behavior is withhold/block**; reversible redaction (mask-and-swap-back) is its own later cycle — see the seam in §6.

### 2. Session store — SQLite in `kage.db` (derived, not memory)

Sessions are **transient conversation state, not memory** — never markdown notes (markdown stays the source of truth for memory only). Two tables in the existing `~/.kage/indexes/kage.db`:

```
sessions(
  session_id   TEXT PRIMARY KEY,
  created_at   TEXT,
  identity     TEXT,            -- pinned
  project      TEXT,            -- pinned (nullable)
  destination  TEXT,            -- CURRENT dest: 'local' or a provider name (mutable)
  deleted      INTEGER DEFAULT 0
)
session_turns(
  session_id   TEXT,
  idx          INTEGER,         -- turn order
  parent_idx   INTEGER,         -- nullable; seam for future conversation branching/forking
  role         TEXT,            -- 'user' | 'assistant'
  content      TEXT,
  note_ids     TEXT,            -- JSON list: provenance for re-gating on switch
  destination  TEXT,            -- which dest answered this turn
  model        TEXT,            -- exact model id
  reason       TEXT,            -- why this model ('user-selected'; later 'auto-routed: …')
  tokens       INTEGER,         -- tokens consumed (best-effort)
  ts           TEXT,
  deleted      INTEGER DEFAULT 0,
  PRIMARY KEY (session_id, idx)
)
```

Connection exists via `_connect()`. Schema creation idempotent (Cycle 9 pattern). `deleted` makes `/clear` a **soft-delete** so the future Librarian can still read history. `parent_idx` is a one-column seam now so branching (a competitor norm) needs no migration later ([[feedback-future-proof-decisions]]).

### 3. Per-turn flow

```
  user message
      │
      ▼
  ① condense    — heuristic: short + leading pronoun + no proper noun → rewrite to a
                  standalone query using history; else use raw.  (_condense_query;
                  LLM-condense deferred behind seam)
  ② retrieve    — _search on the condensed query, scoped to pinned identity/project
  ③ gate        — _disclosure_gate over note provenance + full conversation text,
                  against the CURRENT destination (cloud destinations only)
  ④ assemble    — /api/chat messages array: system + last-N-by-token-budget history
                  + retrieved context + user turn  (structured roles, NOT a flat string)
  ⑤ answer      — buffered this cycle (Ollama /api/chat + cloud), behind an
                  Iterator-shaped seam so live streaming drops in later
  ⑥ append      — store the turn with parent_idx, note_ids, destination, model, reason, tokens
```

History bounded by a **token budget** (not raw turn count); old turns drop when prompt + retrieved notes would exceed the window. Summarization-compaction (`/compact`) deferred.

### 4. Model switching + re-gate (the safe-switch mechanism)

- **Cockpit:** `/use <provider>` (or `/use local`) changes the session's `destination`.
- **MCP:** pass a different `provider` on the next `kage_ask` call for the session.
- **On switch to a more-exposed destination:** re-run the gate over the *entire* conversation's provenance + text for the new vendor; anything that fails is withheld from that vendor's view of history. A **one-time approval prompt per provider** fires on first switch (reuses the session-approval memory at ~[cli.py:1248](../src/kage/cli.py#L1248)); after that the switch is seamless and the status line keeps you aware. A little friction here is acceptable for v1.

### 5. Model call — structured `/api/chat`, live streaming deferred

The `ask`/`chat` answer path moves to a structured **`/api/chat` messages array** (system/user/assistant turns) instead of flat-string concatenation — a *correctness* fix that prevents history role-bleed. The existing single-shot `ask` (`/api/generate`) path is left untouched to limit blast radius.

A dispatcher `_answer(...) -> Iterator[str]` wraps both Ollama `/api/chat` and cloud `_call_cloud` and, for this cycle, **yields once (buffered)**. The Iterator shape is the seam: live word-by-word streaming (Ollama `stream:true` delta handling + flush loop) drops into the local branch in a clean follow-up cycle, no caller changes. Deferred because, with `kage chat` reframed as a dev cockpit, live streaming is low-value polish, not a thesis.

### 6. Transparency (the locked characteristic, applied)

Every turn records and surfaces **which model · why · tokens**:
- Per-turn cockpit status line, e.g. `[groq · llama-3.3-70b · 412 tok · user-selected]`.
- Same fields appended to `~/.kage/audit.jsonl` and `session_turns`.
- `reason` is `user-selected` now; the auto-router (Cycle 12+) fills it with `auto-routed: images → multimodal`. Rich render is a later UI surface; Cycle 10 captures the *data*. "Clearly justified now, beautifully rendered later."

**Redaction seam:** §1's per-turn gate over full conversation text + structured withheld output is the foundation for Layer 3e v2 (turn "withhold" into "mask `<CARD_1>` → swap back locally"). That cycle should, jugaad-style, adopt OpenAI's free local Apache-2.0 **Privacy Filter** behind `_pii_scan` rather than hand-growing the 29-regex set ([[project-redaction-substitution-vision]], [[project-global-model-sourcing]]).

### 7. Surface — the engine, plus a cockpit

**The engine over MCP (`kage_ask` gains optional `session_id`)** is the real integration surface:
- `session_id=None` → today's stateless behavior (**fully backward-compatible**).
- `session_id="…"` → load prior turns, gate + answer, append. First use binds (identity, project); the `provider` param sets/switches destination and triggers re-gate.
- MCP returns **buffered** (streaming over stdio MCP deferred).

**`kage chat` — the local dev/debug cockpit** (not a product surface):
```
kage chat [--identity X] [--project Y] [--cloud --provider Z] [--limit N]
```
v1 commands:
```
/help  /?     List commands.
/exit  /quit  Leave (session persists in SQLite).
/new          Fresh session — the only way to change pinned (identity, project).
/use <prov>   Switch model/destination mid-session (triggers re-gate; /use local too).
/clear        Soft-delete this session's turns, keep pinned scope.
/scope        Show pinned identity · project · current destination + single-writer note.
/sources      Source notes behind the last answer.
/history      Print the turns carried so far.
```

## Implementation order (per dev workflow — test + cloud-review after each step)

1. **Session schema** — `sessions` + `session_turns` (with `parent_idx`/`note_ids`/`destination`/`model`/`reason`/`tokens`/`deleted`); idempotent. Test: round-trip; pinned (identity, project); soft-delete hides turns.
2. **Session store helpers** — `_session_create / _session_load / _session_append / _session_turns`; last-N **by token budget**. Test: append→load order; token-budget truncation.
3. **`_condense_query(history, question)`** — heuristic follow-up rewrite. Test: pronoun follow-up condensed; standalone passed through.
4. **`_answer` dispatcher** — Ollama `/api/chat` (buffered) + cloud buffered-yield, Iterator-shaped. Test: yields content; URLError path; structured messages array assembled correctly.
5. **Gate over conversation + provenance** — extend `_disclosure_gate`: scan full conversation text + note provenance vs current destination; structured withheld output (redaction seam). **Cloud review — highest blast radius.** Test: typed-secret in history blocked on cloud; local turn's note blocked when switched to cloud.
6. **Switch + re-gate** — `/use` (cockpit) + `provider` (MCP); re-gate full history; one-prompt-per-provider. Test: switch local→cloud re-gates; **no-leak-on-switch invariant** (a local-only note never reaches cloud across a switch).
7. **`kage chat` cockpit** — core loop (① – ⑥) + v1 commands + per-turn transparency status line. Test: multi-turn history carried; wall holds across turns; `/scope` `/sources` `/history` render.
8. **MCP `session_id`** — optional param; `None` = stateless (backward-compat regression test); session path carries history; provider switch re-gates.
9. **Eval + invariants** — extend `tests/eval_retrieval.py`: identity wall holds across a *multi-turn* session; no-leak-on-switch; no retrieval regression vs Cycle 9 (MRR 1.000).

## Circuit-breaker (if over budget — de-scope in this order)

Cut bottom-up, keeping the two theses (stateful engine + safe-switch) intact:

1. **First:** per-provider token-count parsing (each cloud API reports usage differently) → ship Ollama `eval_count`, cloud `tokens: null`, fill later.
2. **Then:** `/history` and `/sources` cockpit commands → defer.
3. **Then:** the `/use` *command*, keeping the provenance + re-gate *mechanism* (switching lands next cycle on a finished foundation).
4. **Never cut:** the gate-over-conversation + provenance foundation (§1), the session store, the no-leak-on-switch invariant. The cycle's reason to exist.

## Future-proof seams (deferred ≠ skipped)

- **Live streaming** → `_answer` is Iterator-shaped; later cycle fills the Ollama `stream:true` branch.
- **Reversible redaction (Layer 3e v2)** → §1 gate + structured withheld output is the foundation; adopt OpenAI Privacy Filter behind `_pii_scan`. Roadmap slot **TBD** ([[project-redaction-substitution-vision]]).
- **Automatic model routing** (Cycle 12+) → kage picks destination; same §4 re-gate; `reason` column pre-wired.
- **Conversation branching/forking** → `parent_idx` column already present.
- **LLM-condense** → heuristic now (frugal); upgrade behind seam.
- **History compaction** (`/compact`) → token-budget truncation now; summarizer into step ④.
- **Session browser** (`/sessions`, `/resume`) → SQLite already persists; v2 adds a listing.
- **Global model sourcing** → DeepSeek + cheap foreign providers already work via `openai-compat` config; no build needed ([[project-global-model-sourcing]]).

## Out of scope (explicit)

- **Live word-by-word streaming** — structured `/api/chat` + buffered this cycle; deltas deferred to a follow-up.
- **Reversible redaction / value-substitution** — its own cycle; Cycle 10 leaves the seam, does withhold/block.
- **Automatic model selection / multimodal auto-switch** — Cycle 12+ / v5–v6.
- **Streaming over MCP**, **conversation branching**, **history summarization**, **session browser/resume**, **export**, **mid-session persona (identity) switch**.
- **LLM-based condense** — heuristic only.
- **`kage chat` as a promoted product surface** — it is a dev/debug cockpit only.
- Any later mediator feature (MCP *client*, agent loop).

## Risks / rabbit holes

- **Follow-up retrieval quality** — heuristic condense may misjudge (e.g. "What about Rust?"). Mitigate: history still in the generation prompt; LLM-condense seam left.
- **Token blowup** — long sessions + per-turn note injection overflow the window. Mitigate: token-budget cap; test that prompt + notes + history fits.
- **Cross-destination leak on switch** — the core safety property. Mitigate: provenance + full-text re-gate on every switch; the no-leak-on-switch invariant test (step 6) is the proof.
- **`/api/chat` migration** — current code uses `/api/generate` (parses `response`); chat parses `message.content`. Mitigate: leave single-shot `ask` on `/api/generate`; only `chat` uses the new path.
- **Concurrent append** — CLI cockpit and MCP server are separate processes on one `kage.db`. v1 assumes **single-writer per session_id**; surfaced loudly in `/scope`, and `(session_id, idx)` PK rejects accidental collisions rather than corrupting.
- **MCP backward-compat** — `session_id=None` must behave exactly as today. Mitigate: explicit regression test.

## Decisions (locked 2026-06-13, with Chirag)

- **D1 — State ownership:** ✅ kage owns the session engine (becomes the brain). Clients render it.
- **D2 — Keystone:** ✅ (identity, project) pinned; **destination switchable**; safety via per-turn + per-switch re-gating, not immobility.
- **D3 — Session store:** ✅ SQLite in `kage.db` with provenance + transparency cols + `parent_idx` seam + soft-delete. Not markdown memory.
- **D4 — Gate scope:** ✅ scan the **full conversation, every turn** (typed text + replies + note provenance) vs the current destination. Withhold/block now; redaction next cycle.
- **D5 — Switching:** ✅ build manual switch (`/use`, MCP `provider`) + provenance + re-gate now; one-prompt-per-provider friction acceptable. AUTO selection deferred.
- **D6 — Model call:** ✅ structured `/api/chat` assembly NOW (role-bleed fix); **live streaming DEFERRED** behind the `_answer` Iterator seam (low-value polish once chat is a cockpit).
- **D7 — Surfaces:** ✅ engine over MCP `session_id` is the real integration; `kage chat` is a **dev/debug cockpit, not a product face** (preserves Silent/Invisible).
- **D8 — Follow-ups:** ✅ heuristic `_condense_query` for v1 (frugal); LLM-condense deferred.
- **D9 — Transparency:** ✅ capture + show model · reason · tokens per turn; rich render deferred.
- **D10 — Moat framing:** ✅ claim the **combination** (per-identity wall + per-destination gate + state ownership in one local broker), NOT "we redact PII" (now commodity).
- **D11 — Redaction slot:** ✅ Layer 3e v2 is its own cycle; roadmap slot decided later; Cycle 10 leaves the seam + notes the OpenAI Privacy Filter adoption.
