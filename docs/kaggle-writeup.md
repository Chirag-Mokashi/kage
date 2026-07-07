# kage: A Local-First Multi-Agent Personal AI Broker

---

## The Problem

Every morning I wake up behind. Research happened while I slept. Relevant papers were published on arXiv, GitHub projects gained traction, Hacker News discussions moved. My calendar shifted. Emails arrived. And my AI tools — Claude, Gemini, Perplexity, whatever I reach for — have no idea. Each conversation starts from scratch. Each tool is a silo. I am the only one who holds the full picture, and I spend real time re-establishing context every day.

This is not a productivity problem. It is an architecture problem. The tools are powerful but stateless. The user carries all the context in their head. The gap between intent and execution is filled by manual re-explanation, copy-pasting between tools, and hoping the AI understands what you mean this time.

Existing solutions fall into two camps: cloud-dependent personal assistants that require trusting a third party with everything you know, or local tools too isolated to be useful across your stack. Neither solves the real problem: a privacy-preserving, context-aware broker layer that sits between you and your entire AI stack, makes every tool smarter, without re-explaining yourself or surrendering your data.

kage (Japanese — "shadow") is my answer to this problem. It has been in development for 29 cycles since June 2026, shipping as a headless CLI and MCP server with 773 tests across 13 test files. For this capstone — the **Concierge Agents** track — the focus is three internal agents, Scout, Librarian, and Monitor, that form a self-contained multi-agent pipeline: a concierge that researches while you sleep, curates what it learns, and briefs you each morning, answering a single question — **what did I miss, and what should I know right now?**

---

## Why Agents

An agent is the right primitive here because the problem is not a single query — it is a continuous, asynchronous process. Research happens overnight. Machine state changes throughout the day. Memory needs to be curated, not merely accumulated. No single prompt handles this. Specialization is required: agents with distinct roles, defined boundaries, and a shared memory substrate.

Multi-agent architecture also enforces a separation of trust a monolith cannot: the agent that reads the web is not the agent that writes to permanent memory; the agent that observes machine state has no write access without a human checkpoint. The pipeline enforces these boundaries by design, not convention.

The Google ADK was chosen as the orchestration layer for three reasons: it supports both local and cloud models via LiteLlm, its `Workflow` and `LlmAgent` primitives map cleanly to the distinct roles each agent plays, and the capstone required it. Importantly, ADK is the orchestration layer only — the model stack (Qwen3 14B local + Claude/OpenRouter cloud) is unchanged from the rest of kage.

---

## What is kage

kage is a local-first personal AI broker — a silent layer between you and your entire AI stack that holds your context, enforces your privacy, and routes every query to the right model. Memory lives as plain markdown files under `~/.kage/memory/`. SQLite FTS5 and ChromaDB are derived indexes rebuilt on demand. The source of truth is always the file, never the index.

The full system ships 29 modules: FTS5 + vector retrieval with bge-reranker, stateful sessions, MCP server (four tools), MCP client arm routing (shell / stdio / SSE), identity × project memory partitioning, reversible PII masking across 11 egress sites, a prompt-learning layer, and a live identity registry. Ten characteristics lock every design decision: Seamless · Transparent · Aware · Local · Silent · Broker · Adoptable · Controlled · Invisible · Modular.

**Kaggle concepts demonstrated:**

| Concept | How |
|---|---|
| Agent / Multi-agent (ADK) | Scout (`Workflow`), Monitor (`Workflow`), Librarian (`LlmAgent`) — three distinct ADK agents |
| MCP Server | `kage mcp serve` — four tools, stdio transport, registered in Antigravity and Claude Code |
| Antigravity | Built and demoed inside Antigravity IDE; kage MCP registered as a server |
| Security features | Two-pass privacy gate across 11 egress sites; identity wall; audit log; HITL write gate |
| Deployability | `kage monitor install` registers launchd plists; `okiro` startup sequence fires the full pipeline |
| Agent skills | Librarian's 10 FunctionTools; Scout's `scout_recall` FunctionTool; arm skills in `~/.kage/arms/` |

---

## The Three Agents

### Scout — Nightly Research Agent (567 lines, 70 tests)

Scout runs as two 1-node ADK `Workflow`s — ScoutBroad (`LlmAgent`, local Qwen3) and ScoutIntegrate (`LlmAgent`, cloud) — each executed by its own `InMemoryRunner`, with a deterministic Python deep-fetch pass between them. It runs nightly and writes a structured morning research report scoped to the user's active project.

**Stage 1 — ScoutBroad** runs entirely on Qwen3 14B via Ollama. It fetches from five independent sources, each in its own try/except boundary so one failure never stops the run:

- **Hacker News** — top 30 stories via the public API
- **arXiv** — AI/ML/CS category RSS, last 48 hours
- **GitHub Trending** — weekly trending repos with star counts
- **Reddit** — configurable subreddits (r/MachineLearning, r/LocalLLaMA, r/programming)
- **RSS** — user-configurable feed list in `~/.kage/config.json`

A seen cache (`~/.kage/scout/cache/seen.json`, SHA-1 keyed by URL + title hash) ensures no item is ever surfaced twice across runs. ScoutBroad receives the full corpus (up to 100,000 characters, round-robin balanced across sources) and returns the index numbers of the most relevant items.

**Stage 2 — ScoutIntegrate** runs on a cloud model via LiteLlm. It receives the shortlisted items and triggers a deep-fetch pass: GitHub READMEs are fetched via the GitHub API, Reddit posts via their JSON endpoint, and everything else via Jina Reader (`r.jina.ai/<url>`). The enriched corpus (up to 80,000 characters) is passed to ScoutIntegrate alongside the user's active project context retrieved via `scout_recall` — a FunctionTool that queries kage's own memory, gated through the privacy gate before dispatch.

The output is a structured markdown report with Tier 1 (Actionable) and Tier 2 (Good to Know) sections, each item carrying: tech relevance, kage relevance, competitors named, where in kage this matters, and a cycle candidate flag. Reports are written to `~/.kage/scout/YYYY-MM-DD.md`.

Scout deposits its output into Librarian's staging queue via `deposit_to_queue()`, using SHA-256 content hashing for idempotency — running Scout twice on the same content produces exactly one staging entry.

A `before_model_callback` (`_pii_seam`) wires the two-pass privacy gate into ScoutIntegrate's ADK invocation. Every cloud call is masked before dispatch.

### Librarian — Memory Gatekeeper (1,056 lines, 43 tests)

Librarian is an ADK `LlmAgent` with ten `FunctionTool`s. It is the **sole writer to permanent memory**. Nothing reaches `~/.kage/memory/` without passing through Librarian and receiving explicit human approval.

**The ten tools:**
1. `get_staging_queue` — reads pending items from `staging_queue`
2. `locate_memory` — FTS5 dedup check against existing notes
3. `distill_and_judge` — 3e-gated distillation + LLM judgment (PROMOTE / HOLD / DISCARD)
4. `deposit_to_queue` — idempotent re-queue for later retry
5. `annotate_memory` — add tags or flags to existing notes
6. `request_approval` — moves item to `approval_queue`, surfaces for HITL review
7. `write_note` — seven-step approved write: idempotency check → context merge → mem_id → DB INSERT → `.md` file → ChromaDB embed → CTM emit → audit log
8. `reject_approval` — records rejection, emits EPM correction note
9. `list_pending_approvals` — returns items awaiting human decision
10. `get_catalog_stats` — memory count, queue depth, last run timestamp

The pipeline runs as follows: Librarian reads the staging queue → calls `distill_and_judge` on each item (Pass 1: privacy gate, Pass 2: FTS5 dedup, Pass 3: CTM few-shot injection, Pass 4: cloud judge) → calls `request_approval` to surface for human review → the user runs `kage librarian approve <id>` or `kage librarian reject <id>`.

**The CTM loop (Cycle 25):** after every approved `write_note`, `_emit_ctm_note` records the approved item as a precedent in the `kage-ctm-librarian` project. At the next distillation pass, `_retrieve_ctm` pulls the most recent approved precedents (recency-based, PII-gated) and injects them as few-shot examples above the rejection rules. Librarian's judgment is shaped by what the user *accepted*, not only what they rejected.

**The EPM loop (Cycle 24):** each `kage librarian reject` writes a correction note to `kage-corrections-librarian`. `kage learn --librarian` distills those rejections into rules that prepend the distill prompt — Monitor auto-fires this pass when 7+ new rejections accumulate. Librarian improves without any weight updates.

A threading lock plus PID-based lockfile prevent concurrent runs. Write order is always DB-first — a ghost file with no DB row is permanently undetectable, so the DB write is never deferred.

### Monitor — Machine Observer (794 lines + 240 lines observe.py, 61 tests)

Monitor is a two-job ADK `Workflow` — `build_monitor_observe()` and `build_monitor_digest()` are separate pipeline builders so the two jobs run on independent launchd cadences. The fast local job never blocks on the slower cloud job.

**Observe job** — `StartInterval: 300` (every 5 minutes). An `NSWorkspaceDidActivateApplicationNotification` callback captures app-switches; a polling thread captures typing pauses, scroll stops, and idle periods. Events are captured via macOS Accessibility APIs (`kAXFocusedUIElementAttribute`), with three explicit guards:
- `AXSecureTextField` is skipped unconditionally — password fields are never read
- AFK periods > 180 seconds are skipped entirely
- Consecutive same-app events within 30 seconds are heartbeat-merged into a single event

Electron apps (VS Code, Notion, Antigravity) receive `AXEnhancedUserInterface = true` before the AX read to improve text extraction. Events are appended to `~/.kage/observe/observations-YYYY-MM-DD.jsonl`.

**Digest job** — `StartCalendarInterval: {Hour: 7, Minute: 0}` (07:00 daily). MonitorObserve (local Qwen3) reads today's JSONL and summarizes raw observations. MonitorDigest (cloud via LiteLlm) synthesizes the summary into a structured briefing: anomalies detected, patterns noticed, recommendations. A `before_model_callback` wires the two-pass privacy gate into MonitorDigest before any cloud dispatch.

The digest is written to `~/.kage/observe/digest-YYYY-MM-DD.md`. As of Cycle 29, `_deposit_context_snapshot(digest[:600])` deposits a summary into Librarian's staging queue with `source="monitor"` — the machine's own activity becomes part of permanent memory, gated by the same HITL approval process as Scout output.

Monitor also tracks pipeline health: Scout last run, Librarian queue depth, MCP server status, system metrics (CPU, RAM, Ollama latency, ChromaDB vector count). Alerts are written to `monitor_alerts`. `_maybe_trigger_learn` fires `kage learn --all` automatically when the corrections log crosses 7 new entries.

---

## Architecture

```
  Scout (two ADK Workflows, one Runner each)
    ScoutBroad     → Qwen3 14B (local, Ollama)
        ↓ deterministic Python deep-fetch
    ScoutIntegrate → Cloud via LiteLlm (OpenRouter / Claude)
        ↓ deposit_to_queue() — SHA-256 dedup, idempotent

  Monitor (ADK Workflow, cadence-split launchd)
    MonitorObserve → Qwen3 14B (local, every 5 min)
    MonitorDigest  → Cloud via LiteLlm (07:00 daily)
        ↓ _deposit_context_snapshot() — Cycle 29 pipeline

  staging_queue (SQLite)
        ↓ kage librarian run

  Librarian (ADK LlmAgent, 10 FunctionTools)
    distill_and_judge → gate + FTS5 dedup + CTM injection + cloud judge
        ↓ request_approval()

  approval_queue (SQLite)
        ↓ kage librarian approve <id>   [HUMAN IN THE LOOP]

  permanent memory
    ~/.kage/memory/   ← markdown source of truth
    ~/.kage/indexes/kage.db  ← SQLite FTS5 + identity/project joins
    ~/.kage/chroma/          ← ChromaDB vector index
```

Every cloud boundary — Scout's integrate stage, Librarian's judge pass, Monitor's digest, the chat REPL, the MCP server — passes through `gate.two_pass_gate()`: eleven egress sites, all gated.

---

## Security and Privacy

The two-pass privacy gate (`gate.py`, 168 lines) is structural, not optional:

**Pass 1 — Hard blocks (silent):** vault-defined sensitive patterns are checked first. User-defined regex patterns in `~/.kage/sensitive.json` are matched and values silently redacted before any further processing. Local-only notes (`--local` flag) never leave the machine under any circumstances. Identity walls are enforced — `personal` notes are invisible to `--identity neu` queries and vice versa.

**Pass 2 — Reversible PII masking:** 31 built-in patterns across 6 categories (national IDs, financial, credentials, contact, location, biometric) plus user-defined vault patterns are matched. Real values are replaced with typed placeholders (`[EMAIL_1]`, `[AADHAAR_1]`) before dispatch. kage swaps them back in the response. The cloud never sees actual PII.

Every dispatch decision is written to `~/.kage/audit.jsonl` with `pii_type_counts` (typed tallies, not raw values).

The identity registry enforces read-only identity classes — read-only identities cannot trigger write-permission arms. `identity.resolve_write_identity()` is the single chokepoint every memory writer routes through. `kage doctor` checks identity tag canonicality and fails loudly on corruption.

---

## MCP Integration

kage ships an MCP server (`mcp_server.py`, stdio transport via FastMCP) exposing four tools:

```
kage_recall(query, project, limit, identity)    — FTS5 + vector search, identity-gated, read-only
kage_ask(question, provider, project, identity) — grounded answer, privacy gate runs automatically
kage_remember(text, project, local)             — write-gated: requires mcp_allow_writes: true in config
kage_status()                                   — store snapshot: note count, model, disk, arms
```

`kage_remember` is write-gated by default. `kage_recall` is always read-only. Any MCP-compatible client — Antigravity, Cursor, Claude Code — connects via the project-level `.mcp.json`:

```json
{
  "mcpServers": {
    "kage": {
      "command": "uv",
      "args": ["run", "kage", "mcp", "serve"]
    }
  }
}
```

kage also acts as an MCP client — Calendar, Gmail, and Browser arms are invoked via shell/stdio/SSE transports and injected as live context. Every arm call is audited.

---

## What I Built and Learned

kage is at v0.29.0 — 29 shipped cycles, 773 tests across 13 test files, 29 modules. The three agents (scout.py + librarian.py + monitor.py + observe.py) total 2,657 lines, written across Cycles 14–16 and refined through Cycle 29.

The most important lesson: **the boundary between agents matters more than the agents themselves.** Scout depositing to staging rather than writing directly, Librarian being the sole memory writer, Monitor observing without acting — these boundaries are what make the system trustworthy. Violate one and the whole trust model breaks. This was confirmed empirically: Cycle 28.1 hotfixed a write-site bug where MCP's `kage_remember` and Librarian's `write_note` could tag notes with raw identity labels instead of canonical groups, making them permanently unreachable. The fix was one chokepoint function — but finding the bug required independently re-running the grep of all call sites, not trusting the pitch document's list.

Second: **local models for volume, cloud for judgment.** Qwen3 14B running locally handles fetching, filtering, observation processing, and FTS search at zero marginal cost and zero privacy exposure. Cloud only sees the shortlist — pre-filtered, deduped, and masked. This is not a cost optimization. It is a privacy architecture.

Third: **HITL is not a checkpoint, it is a training signal.** Every approval and rejection feeds the CTM and EPM loops. The human is not in the loop to catch mistakes — the human *is* the learning signal. Librarian improves through use, not fine-tuning.

---

## What's Next

The pipeline runs while you sleep. The next step is making it act when you wake up — calendar write, email draft, task creation — all gated through the same HITL approval process that governs memory today. kage already ships a calendar write arm (Cycle 26, EventKit create-only) as the template for future write arms.

The longer arc is kage as invisible infrastructure: memory and routing underneath every AI tool on your devices, preserving context across tools and time — without trusting a cloud you do not control. Today kage is a broker. The target is a mediator that orchestrates without being asked and stays silent unless it has something worth saying. That is the definition of Seamless.

---

*Built by Chirag Mokashi — MS Applied AI, Northeastern University*
*GitHub: https://github.com/Chirag-Mokashi/kage*
*Video: https://youtu.be/tZLuvQKmiG4*
