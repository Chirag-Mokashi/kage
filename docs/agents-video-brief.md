# kage Agents — Complete Video Brief

*Compiled 2026-07-05. Use to prepare the Kaggle submission video.*
*Everything in here is factual, verified from source. Omit what you don't need.*

---

## Big picture — the three agents as a system

kage has three standing ADK agents. Each has a distinct role, a distinct model tier, and a distinct write permission level:

```
  World (HN/arXiv/GitHub/Reddit/RSS)
        │
        ▼
  ┌─────────────────────────────────┐
  │  SCOUT  (Cycle 14, v0.14.0)    │  Fetches. Triages. Deposits to staging.
  │  local: Qwen3 14B (shortlist)  │  CANNOT write to permanent memory.
  │  cloud: OpenRouter/Claude      │  Writes: scout/YYYY-MM-DD.md + staging_queue
  └──────────────┬──────────────────┘
                 │ deposit_to_queue()
                 ▼
  ┌─────────────────────────────────┐
  │  LIBRARIAN  (Cycle 15, v0.16.0)│  Distills. Judges. Awaits human HITL.
  │  cloud: Claude (distill+judge) │  SOLE writer to permanent memory.
  │  local: not used               │  Writes: ~/.kage/memory/*.md (gated)
  └──────────────┬──────────────────┘
                 │ (approved items only)
                 ▼
  ~/.kage/memory/  ←  permanent memory (SQLite FTS5 + ChromaDB)
                 ▲
  ┌─────────────────────────────────┐
  │  MONITOR   (Cycle 16, v0.17.0) │  Observes. Summarizes. Sends to Librarian.
  │  observe: Qwen3 14B (every 5m) │  CANNOT write to permanent memory.
  │  digest:  cloud (07:00 daily)  │  Writes: monitor/*.md + staging_queue (Cycle 29)
  └─────────────────────────────────┘
```

The pipeline is **Scout → staging_queue → Librarian → (your approval) → memory**. Monitor watches all three plus system health and deposits its own summaries to Librarian (Cycle 29).

Total agent code: ~2,500 lines across 4 files (scout.py, librarian.py, monitor.py, observe.py).
Test coverage: 720 tests total in the repo; agent-specific: Scout 64, Librarian 37, Monitor 48.

---

## SCOUT

### What it is
Scout is kage's external intelligence gatherer. It runs as a two-stage ADK Workflow — a local Qwen3 shortlisting pass followed by a cloud integration pass — and produces a project-aware morning digest.

### What problem it solves
A software engineer can't monitor Hacker News, arXiv, GitHub trending, Reddit, and RSS feeds daily without spending an hour on it. Scout does this in a single `kage scout run` and filters to what's actually relevant to your current project.

### Architecture (2 ADK stages)

**Stage 1 — ScoutBroad (local Qwen3 14B)**
- Receives a numbered list of all fetched items (titles + snippets)
- Task: pick 5–8 items worth reading in full ("high ambiguity, potentially high-signal")
- Does NOT classify into tiers yet — just picks index numbers
- Output key: `shortlist_indices`
- No cloud cost at this stage

**Stage 2 — ScoutIntegrate (cloud: OpenRouter/Claude)**
- Receives an enriched corpus:
  - `=== FULL CONTENT ===` for shortlisted items (full README/article/body via Jina Reader)
  - `=== HEADLINES ===` for everything else (title + snippet only)
- Calls `scout_recall` tool (ADK FunctionTool) to check what's already in kage's memory
- Classifies all items into Tier 1 (Actionable) or Tier 2 (Good to Know)
- Writes a structured morning digest with per-Tier-1-item cards
- Output key: `report`

### Five data sources
1. **Hacker News** — front-page via Algolia API, top 30 items
2. **arXiv** — latest cs.AI submissions, top 20, via Atom API
3. **GitHub** — repos with >100 stars pushed in the last 7 days, top 20 via Search API (optional token for higher rate limits)
4. **Reddit** — configured subreddits (e.g. r/MachineLearning), 25 posts each; body trimmed to 3,000 chars to prevent context blowout
5. **RSS** — any RSS 2.0 feed in `~/.kage/config.json`, stdlib XML parse

Each source is isolated in its own `try/except` — one source failing never aborts the whole fetch. Every fetch is audit-logged.

### Seen-cache dedup
Scout maintains `~/.kage/scout/cache/seen.json` — a sorted JSON list of `url + content-hash` keys. Items in this set are skipped on the next run. The cache is updated only after a successful report write, so a crash mid-run doesn't lose previously-seen state. `kage scout bootstrap` seeds the cache without writing a report (run this once before first `run`).

### Deep-fetch enrichment (Cycle 20 addition)
For the shortlisted items, Scout fetches full content:
- GitHub: reads README via GitHub API, base64-decoded, truncated to 3,000 chars
- Reddit: uses the already-fetched `body` field (no extra request)
- All others: Jina Reader (`r.jina.ai/URL`) — converts any URL to clean markdown, capped at 5,000 chars (2,000 for arXiv)
- Failures return `""` (graceful fallback — item stays in headlines section)

### Privacy gate on Scout
`_pii_seam` is wired as `before_model_callback` on ScoutIntegrate. Before any cloud dispatch, it calls `_gate_text` on all content parts. The `scout_recall` tool also routes through `_disclosure_gate` — so memory results respect the same 3-layered gate (local-only hard block, identity wall, reversible PII masking) that guards all of kage's cloud egress.

### Scout → Librarian pipeline
After the digest is written, Scout scans the report's Tier 1 section and calls `deposit_to_queue()` for each bullet line, tagging source="scout" with the current active project. This is the automatic feed into Librarian's staging queue.

**Note:** The card format from ScoutIntegrate is `### [source] Title` headers, not bullet lines. The deposit loop in `run()` looks for `- ` bullet lines and currently matches Tier 1 bullets like `- [hn] Title — one sentence`. The loop is a best-effort pass — failures are swallowed silently to not break the run.

### CLI commands
```
kage scout bootstrap     # seed seen-cache (run once)
kage scout run           # full run: fetch + triage + deep-fetch + integrate + write digest
kage scout dry-run       # fetch + shortlist only, no write, no cloud cost
kage scout status        # cache size, last run date, token log summary
```
`kage scout run` now (Cycle 29) asks for confirmation before dispatching to cloud. `--yes` / `-y` skips the prompt for automation.

### Output artifacts
- `~/.kage/scout/YYYY-MM-DD.md` — the morning digest
- `~/.kage/scout/cache/seen.json` — the dedup cache
- `~/.kage/scout/log/YYYY-MM-DD.jsonl` — token/character log per run
- `staging_queue` rows (source="scout") — fed to Librarian

### Key design decisions
- **Why two-stage (local then cloud)?** Local shortlist cuts the cloud input by ~80% and costs nothing. Cloud only sees the items worth deep analysis.
- **Why Jina Reader instead of direct fetch?** Jina converts arbitrary web pages to clean markdown — no HTML parsing, no JS rendering. For arXiv PDFs it extracts text; for GitHub it gets prose above the fold.
- **Why `_CORPUS_CHAR_CAP = 100,000`?** Leaves ~6k token headroom in Qwen3's 32k context window. The cap is hit before context overflow; items are skipped (not truncated mid-line) with a round-robin across sources so no single source dominates.
- **Why project-aware?** ScoutIntegrate receives `{project}` injected into its instruction via session state and calls `scout_recall` with it. `kage use hsi` → Scout analyses through the HSI lens; `kage use kage` → kage lens.

---

## LIBRARIAN

### What it is
Librarian is kage's sole writer to permanent memory. It is an ADK `LlmAgent` with 10 tools that processes items from a two-table staging pipeline, runs a cloud-powered distill-and-judge pass on each, and surfaces PROMOTE decisions as approval requests that require explicit human sign-off before anything lands in `~/.kage/memory/`.

### What problem it solves
Without Librarian, memory would grow unbounded with garbage — ephemeral facts, duplicates, half-baked ideas. Librarian is the curation gate: every piece of information that reaches permanent memory has been judged durable, actionable, novel, and specific by a cloud model, and confirmed by you.

### The two-table pipeline

**Table 1: `staging_queue`**
- Receives deposits from Scout (`source="scout"`), Monitor (`source="monitor"`, Cycle 29), and manual `kage remember`
- Columns: `id`, `content`, `content_hash`, `source`, `project`, `identity`, `status`, `priority`, `created_at`, `decision`, `reason`, `reviewed_at`
- Status states: `pending` → `held` (awaiting approval) → `approved` or `discarded` or `rejected`
- Dedup is SHA-256 on content — same content always gets the same ID, even if re-deposited
- `priority` column lets Monitor bump high-signal items to front of queue

**Table 2: `approval_queue`**
- Created by `request_approval()` for PROMOTE-judged items
- Columns: `id`, `staging_id`, `note_id`, `action`, `reason`, `sanitized_preview`, `note_json`, `created_at`, `decided_at`, `decision`
- `decision IS NULL` = pending; `kage librarian queue` shows these
- `kage librarian approve <id>` calls `write_note()` → permanent memory
- `kage librarian reject <id>` closes the item, writes a correction note to `kage-corrections-librarian`

### The `distill_and_judge` pass (the brain)
Every staging item goes through `distill_and_judge(content, source)`:

1. **3e gate (unconditional):** `_gate_text` strips PII from content before cloud dispatch. Cannot be bypassed.
2. **Dedup candidate lookup:** FTS5 search on the item's title guess — passes only paths and recall counts (no note bodies) to bound egress.
3. **EPM (Error Pattern Memory):** If `kage learn --librarian` has been run, the learned rules prepend the system prompt.
4. **CTM (Contextual Teaching Memory):** Up to 3 recent approval precedents are fetched from `kage-ctm-librarian` and prepended above EPM as few-shot examples.
5. **Cloud dispatch:** Claude (or configured provider) receives the gated content + candidate paths + system prompt.
6. **Structured JSON response:** `dedup`, `contradiction`, `quality`, `reason`, `note`, `staleness`.
7. **JSON parse with code-fence fallback:** If the model wraps JSON in ```json fences, strips them and re-parses.

**Quality verdict routing:**
- `PROMOTE` → `request_approval()` → item appears in `kage librarian queue` as an approval card
- `HOLD` → item stays `pending` in staging, surfaces in queue display for manual review
- `DISCARD` → `discard_staging_item()` closes it out silently

**Dedup verdict:**
- `DISTINCT` → no action
- `DUPLICATE` → usually implies DISCARD; Librarian can also request approval with a merge note
- `SUPERSEDES` → `annotate_memory()` flags the old note with `superseded_by`

**Staleness:** If the distill response identifies existing notes that become stale, `annotate_memory()` flags them with `librarian_flag='stale'`.

### The write path (`write_note`)
When you run `kage librarian approve <id>`:

1. Reads `note_json` from `approval_queue`; guards against double-write (idempotent)
2. Merges `project/identity/source` from the staging row
3. Generates `mem_id` = slug + 8-char UUID hex suffix
4. **DB INSERT first** (before file write) — if file write fails, `kage reindex` finds a stale pointer and reports it; a ghost file (no DB row) would be permanently undetectable
5. Writes `~/.kage/memory/<mem_id>.md` with YAML frontmatter
6. Embeds via Ollama (`nomic-embed-text`) and upserts to ChromaDB — if Ollama is down, `needs_embed=1` stays set and `kage reindex` will embed on next run
7. Updates staging + approval row status to `approved`
8. Emits a CTM note to `kage-ctm-librarian` project for future few-shot injection
9. Writes to audit log

### Librarian's learning loop (Cycles 24 + 25)
Librarian is the only agent with two independent learning paths:

**EPM (Error Pattern Memory, Cycle 24):** Each rejection you make via `kage librarian reject` writes a correction note to `kage-corrections-librarian`. When 7+ corrections accumulate, `kage learn --librarian` (also auto-triggered by Monitor) distills the rejection patterns into rules and prepends them to `_DISTILL_SYSTEM`. Librarian gets better at *not* promoting things you reject.

**CTM (Contextual Teaching Memory, Cycle 25):** Each approval writes a CTM note to `kage-ctm-librarian`. `distill_and_judge` retrieves the 3 most recent CTM notes and injects them as few-shot examples *above* the EPM rules. Librarian learns what good promotions look like, not just what bad ones look like. Together EPM + CTM form the MemAPO dual-memory loop.

### Concurrency protection
Librarian holds both an in-process `threading.Lock` and a cross-process lockfile (`~/.kage/librarian.lock`). Reason: ChromaDB's `PersistentClient` is not multi-process safe. The lockfile checks for stale locks (PID-based) before blocking.

### CLI commands
```
kage librarian run               # ADK agent processes staging queue, requests approvals
kage librarian queue             # show pending approval cards (--held for held items)
kage librarian approve <id>      # write approved note to permanent memory
kage librarian reject <id>       # reject; logs correction for EPM learning
kage librarian locate <query>    # FTS5 search in permanent memory (pre-check)
kage librarian scan              # scan staging queue for sensitive patterns before approval
kage librarian status            # note count, queue depth, last run timestamp
```

### Cycle 29 addition: receiving from Monitor
Monitor's `_deposit_context_snapshot()` (added in Cycle 29) calls `deposit_to_queue()` with `source="monitor"` after each successful daily digest. This means Librarian now receives structured session context from Monitor automatically, completing the Monitor→Librarian pipeline arm. The Librarian queue now shows a "Staging backlog by source" section distinguishing scout items from monitor items.

### 10 tools wired as ADK FunctionTools
`get_staging_queue`, `locate_memory`, `distill_and_judge`, `deposit_to_queue`, `annotate_memory`, `stage_for_deletion`, `discard_staging_item`, `request_approval`, `write_note`, `get_catalog_stats`.

The instruction is explicit that Librarian never calls `_gate_text` directly — `distill_and_judge` owns the gate. Never deletes — only `stage_for_deletion` (you decide). Never writes without `request_approval` completing.

---

## MONITOR

### What it is
Monitor is kage's ambient observer. It is a two-pass ADK Workflow (MonitorObserve → MonitorDigest) that aggregates signals from your machine, your kage pipeline state, and your session history, and synthesizes them into a ≤300-word daily digest. It also runs a macOS Accessibility daemon (`observe.py`) that captures what apps you're using and what's in your focused window every 10 seconds.

### What problem it solves
You don't have time to check whether Scout ran today, whether Librarian has a backlog, whether Ollama is up, whether your Qwen3 model is responding slowly. Monitor does this for you and flags anomalies. It's the health + activity layer.

### Architecture

**observe.py — the AX daemon**
- Runs continuously via launchd every 5 minutes (`StartInterval=300`)
- Uses macOS Accessibility API (`pyobjc-framework-ApplicationServices`) to read:
  - Frontmost app name + bundle ID (via `NSWorkspace`)
  - Focused UI element's text value (via `AXUIElementCopyAttributeValue`)
  - Window title
  - Trigger type: `app_switch`, `window_focus`, `typing_pause`, `scroll_stop`, `visual_change`, `idle`
- Skips AFK periods (> 3 minutes since last input, via Quartz `CGEventSourceSecondsSinceLastEventType`)
- Strips PII from AX text via `_gate_text` before writing to disk
- Skips secure text fields (`AXSecureTextField`)
- Enables Electron AX API for VS Code, Notion, Slack, Antigravity (special `AXEnhancedUserInterface` flag)
- Heartbeat merge: consecutive events from the same app+window within 30 seconds are merged (extends `duration` rather than creating a new event)
- Output: `~/.kage/observe/YYYY-MM-DD.jsonl`, one JSON record per event

**MonitorObserve — local Qwen3 14B**
- Runs on the observe cadence (every 5 min via `kage monitor observe`)
- Has 11 tools (ADK FunctionTools):
  - `read_pipeline_state` — Scout last run, Librarian queue depth, memory count
  - `read_session_log` — last 24h of kage REPL turns (PII-gated)
  - `read_observe_log` — last 1h of AX events (PII-gated)
  - `check_mcp_health` — pings each registered arm (shell: `--help` exit code; stdio: MCP `initialize` handshake)
  - `read_system_metrics` — CPU, RAM, disk, Ollama up/down + latency, SQLite size, ChromaDB vector count
  - `read_command_history` — last 50 kage CLI invocations from audit log
  - `read_antigravity_ctx` — reads `.antigravity.md` workspace file + recent Antigravity MCP calls
  - `ping_kage_mcp` — calls kage's own MCP server via `_call_internal_arm` (satisfies Kaggle MCP criterion)
  - `write_alert` — inserts to `monitor_alerts` table (info / warn / error)
  - `set_item_priority` — bumps a staging_queue item's priority so Librarian drains it first
  - `scan_sensitive_patterns` — checks content against user-defined PII patterns in `~/.kage/sensitive.json`
- Output: appends to `~/.kage/monitor/observations-YYYY-MM-DD.jsonl`
- MonitorObserve has NO execution power — cannot approve, remember, send, or trigger anything beyond write_alert and set_item_priority

**MonitorDigest — cloud (OpenRouter/Claude)**
- Runs once daily at 07:00 (`StartCalendarInterval` launchd plist)
- Reads today's `observations-YYYY-MM-DD.jsonl` (up to 50,000 chars total)
- Processes all observation records in chronological order
- `_pii_seam` fires as `before_model_callback` — gates all MonitorObserve output before cloud sees it
- Writes a ≤300-word human-readable digest
- Output: `~/.kage/monitor/YYYY-MM-DD.md`

### Anomaly detection
MonitorObserve is instructed to detect and alert on:
- Librarian queue backlog (depth growing, oldest pending item age)
- MCP server down (via `check_mcp_health`)
- Ollama offline (via `read_system_metrics`)
- Scout not run in 48+ hours
- Disk > 90% full
- Non-obvious patterns: topic drift, model switch patterns, provider latency trends, project going cold

### Cycle 29: Monitor → Librarian deposit (`_deposit_context_snapshot`)
After each successful daily digest, `_digest_impl` calls `_deposit_context_snapshot(digest[:600])`. This deposits the digest summary to Librarian's staging queue with `source="monitor"`. The empty-digest guard (`if digest:`) and a `try/except` wrapper mean a cloud failure never prevents the digest file from being written. This completes the three-agent pipeline: Scout → Librarian → memory, Monitor → Librarian → memory.

### launchd integration
`kage monitor install` writes two plists to `~/Library/LaunchAgents/`:
- `dev.kage.monitor.observe` — `StartInterval=300` (every 5 minutes, runs `kage monitor observe`)
- `dev.kage.monitor.digest` — `StartCalendarInterval Hour=7 Minute=0` (daily at 07:00, runs `kage monitor digest`)

Logs go to `~/.kage/logs/monitor*.log` and `~/.kage/logs/monitor*.err`. `kage monitor uninstall` removes both.

### Auto-triggering Layer 6 learning
`_maybe_trigger_learn` runs after every digest:
- Counts total correction notes in `kage-corrections` project
- If 7+ new corrections since last learn run: fires `kage learn --all`
- Separately counts `kage-corrections-librarian` notes
- If 7+ new Librarian rejections since last: fires `kage learn --librarian`
- State persisted in `~/.kage/learn_state.json`

### CLI commands
```
kage monitor observe     # one MonitorObserve pass (local Qwen3 only)
kage monitor digest      # one MonitorDigest pass (cloud, reads today's observations)
kage monitor run         # observe then digest in sequence (full combined pass)
kage monitor last        # print most recent digest file
kage monitor status      # observation count today, last run timestamp, state.json preview
kage monitor install     # register both launchd plists (auto-start on login)
kage monitor uninstall   # remove both launchd plists
```

---

## The privacy layer — how it threads through all three agents

Every cloud dispatch across all three agents is gated by the same privacy stack:

```
content
  │
  ▼
two_pass_gate()        ← Cycle 27; B1 (structural) + B2 (content) passes
  │ local_only notes: hard block (never dispatched)
  │ identity wall:    identity mismatch: hard block
  │ PII masking:      [EMAIL_1], [API_KEY_IN_CONTEXT_1], etc. — reversible
  ▼
user-defined patterns  ← ~/.kage/sensitive.json (Cycle 19)
  │ regex substitution → [REDACTED_PII]
  ▼
dispatched to cloud
  │
  ▼
response
  │ PII tokens swapped back to real values in local context
  ▼
shown to user
```

Scout: `_pii_seam` before_model_callback + `_disclosure_gate` in `scout_recall`.
Librarian: `_gate_text` in `distill_and_judge` (Step A, unconditional first step).
Monitor: `_gate_text` in `read_session_log`, `read_observe_log`, `write_alert`, `read_antigravity_ctx`; `_pii_seam` before_model_callback on MonitorDigest.

---

## ADK specifics — how the agents use the framework

All three agents use **Google ADK** (Agent Development Kit) as the orchestration layer, driven via **LiteLLM** to route to any model.

**Workflow (Scout, Monitor):** DAG of agents connected by `edges=[(START, A), (A, B)]`. Sequential by default. kage uses `InMemoryRunner` — no persistent server, no gRPC. Session state flows between stages via `output_key` (e.g. `output_key="shortlist_indices"` → Scout stage 2 reads `sess.state["shortlist_indices"]`).

**LlmAgent (Librarian):** Single agent with tools registered as ADK `FunctionTool` (auto-wrapped from plain Python functions). The agent decides which tools to call based on its instruction. Runs via `runner.run_async()`, draining the event stream with `async for _ in ...`; output lands in session state, not in events.

**LiteLlm bridge:** `LiteLlm(model="ollama_chat/qwen3:14b")` for local; `LiteLlm(model="openai/...", api_key=..., api_base=...)` for cloud OpenRouter; `LiteLlm(model="anthropic/claude-...", api_key=...)` for Claude direct. The `_litellm_target()` function (shared pattern across all three agents) resolves kage's provider config (`~/.kage/config.json`) to LiteLLM's model string, api_key (from env var), and api_base (OpenRouter-style endpoint).

**before_model_callback:** Used in Scout (on ScoutIntegrate) and Monitor (on MonitorDigest) as the PII gate. Fires before every cloud LLM call on that agent — runs `_gate_text` on every content part in the request. This is ADK's hook for pre-processing the model's input.

**FunctionTool auto-wrapping:** Any plain Python function passed to `tools=[]` in `LlmAgent` is automatically wrapped as an ADK FunctionTool. The function signature becomes the tool's schema. This is how Monitor's `read_pipeline_state`, `write_alert`, etc. and Librarian's 10 tools are exposed — zero boilerplate.

**Session re-fetch pattern:** ADK's `InMemoryRunner.run()` mutates the session service's internal store, not the local `session` variable returned by `create_session`. All three agents re-fetch the session after the run: `runner.session_service.get_session(...)`. Without this, `sess.state` would be empty.

---

## Numbers you can cite

| Metric | Value |
|--------|-------|
| Total tests in repo | 720 |
| Scout tests | 64 |
| Librarian tests | 37 |
| Monitor tests | 48 |
| Scout source lines | 539 |
| Librarian source lines | 1,021 |
| Monitor source lines | 708 |
| observe.py lines | 249 |
| Total agent code | ~2,517 lines |
| Cycles that built them | Cycles 14, 15, 16, 17, 20, 24, 25, 29 |
| First agent shipped | Librarian (Cycle 15, v0.16.0, 2026-06-26) |
| Latest cycle | Cycle 29 (Monitor→Librarian pipeline, 2026-07-05) |
| Scout data sources | 5 (HN, arXiv, GitHub, Reddit, RSS) |
| Librarian tools | 10 |
| Monitor tools (observe) | 11 |
| Librarian learning systems | 2 (EPM + CTM) |

---

## Things that are intentionally NOT there (honest scoping)

- **Scout does not auto-run daily yet.** `kage scout run` is gated by a user confirmation prompt (Cycle 29). Automation via launchd is a future step.
- **Librarian does not read email or calendar directly.** Those are arm jobs (gmail arm, calendar arm). Librarian only reads what's in staging_queue.
- **Monitor's observe.py requires Accessibility permission.** Without it, app-switch events only (no AX text). The permission prompt is handled by macOS TCC.
- **observe.py's browser URL reading is a stub.** `_get_browser_url` returns None. ScriptingBridge + tab URL path need live validation — deferred post-July 6.
- **Monitor can only flag priority items** (via `set_item_priority`) — it cannot directly approve, reject, or write memory. That intentional constraint is stated in its instruction.
- **Librarian `write_note` needs full UUID, not 8-char prefix.** `kage librarian approve fb73962d` fails; needs `kage librarian approve fb73962d-d33f-49cc-9116-97daa8556ce7`. Known pre-existing issue.
- **Scout's deposit loop looks for bullet lines** but ScoutIntegrate's Tier 1 section uses `### [source] Title` header cards. The loop catches the `- [source] Title — why actionable` lines from the classification section, which ScoutBroad does emit. The header cards are the detailed analysis section below those.

---

## Talking points for the video

**On why three agents:**
"Scout knows about the world. Librarian knows about the past. Monitor knows about right now. They're three distinct epistemic roles — you can't collapse them."

**On the HITL philosophy:**
"Nothing enters permanent memory without you seeing and approving it. kage is a broker, not an autopilot. The agents aggregate, distill, and surface — you decide what sticks."

**On local-first model use:**
"Shortlisting and observation run on Qwen3 14B locally via Ollama. Cloud (Claude/OpenRouter) only runs for integration and digest — the expensive creative synthesis steps. This matters because it means most of the agent work happens without a cloud call."

**On privacy through the pipeline:**
"Every piece of content that any agent dispatches to the cloud goes through the same gate: local-only notes are hard-blocked, identity walls are enforced, and PII is masked with typed placeholders before dispatch and restored in the response. The gate is wired into the ADK callback hooks — it cannot be bypassed by agent tool calls."

**On the jugaad principle:**
"kage doesn't pay for news APIs — it reads Hacker News via Algolia's free search API and arXiv via the public Atom feed. It doesn't pay for a web scraper — it uses Jina Reader. It doesn't pay for email OAuth — it uses AppleScript driving Mail.app. Every arm is 'use what you already pay for'."

**On Cycle 29 completing the pipeline:**
"The last thing we built before the deadline was the Monitor→Librarian wire. Before Cycle 29, Monitor produced daily digests but they didn't go anywhere. Now the digest drops into Librarian's staging queue, Librarian judges it, and if it's worth keeping you get an approval card. The full loop is now closed."
