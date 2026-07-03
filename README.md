# kage

**kage** (Japanese — "shadow") is a local-first personal context broker between you and your AI stack.

It sits silently between your intent and every AI tool you use — managing your memory, gating what leaves your machine, and grounding answers in your own notes. It is not a chatbot. It is not a Claude replacement. It is the invisible layer that makes every AI tool you already use smarter and safer.

kage is defined at three nested levels, all simultaneously true:

```
  COMPLEMENT  The disciplined part of you that the hedonistic part is not.
              Invisible diligence operating in the background.

  MEDIATOR    A second layer between your intent and the world.
              Tools and devices are arms. kage is the brain.

  BROKER      Local-first context broker between you and your cloud AI stack.
              Identity × project partitioned memory. Privacy-preserving routing.
```

---

## Current state — v0.28.0

kage ships as a headless CLI and MCP server. The full UI layer (via Odysseus integration) is in progress.

**Honest status:** today kage is a *context-gated forwarder with a hard identity wall, stateful sessions, arm routing for live external data, three proactive agents, reversible PII masking, a prompt-learning layer, and a persistent identity registry*. It retrieves your notes, enforces the identity × project partition before any note reaches retrieval, gates what may leave your machine (including user-defined sensitive patterns in `~/.kage/sensitive.json`), holds multi-turn conversation state, and forwards a grounded query to the model *you* select (switchable mid-session, with the privacy gate re-run on switch). PII in notes is now *masked* before cloud dispatch — real values replaced with typed placeholders (`[EMAIL_1]`, `[API_KEY_IN_CONTEXT_1]`) and swapped back in the response — so notes are no longer withheld for containing sensitive data. Scout fetches external signals (Hacker News, arXiv, GitHub, Reddit, RSS), shortlists the most relevant via a local ADK stage, deep-fetches full content via Jina/GitHub API/Reddit body, and writes a project-aware morning digest to `~/.kage/scout/`. Librarian processes Scout's findings through a 3e-gated distill-and-judge pipeline and presents promotion requests for your approval — nothing reaches permanent memory without an explicit `kage librarian approve`. Monitor runs a macOS AX daemon that captures app-switch and typing-pause events every 5 minutes (local Qwen3) and synthesizes a daily digest at 07:00 (cloud). `kage learn` reads correction logs from `kage-corrections`, sends them to a cloud model using the ProTeGi pattern, and injects the generated rules into local Qwen3's system prompt — the local model gets better over time without weight updates. The identity registry (`~/.kage/identities.json`) tracks identity classes (`normal`/`read-only`), owned accounts, and per-arm overrides — enabling account-scoped arm dispatch (e.g. `kage use family` routes gmail to `family@example.com`) while enforcing that read-only identities cannot trigger write-permission arms.

```
  ┌─────────────────────────────────────────────────────────────┐
  │  SCOUT (proactive agent — runs independently)               │
  │  kage scout run / dry-run / bootstrap / status             │
  │  HN · arXiv · GitHub · Reddit · RSS                        │
  │  ADK Workflow: ScoutBroad (local) → deep-fetch → ScoutIntegrate (cloud) │
  │  Tier 1/2 triage · project-aware · ~/.kage/scout/          │
  └─────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────┐
  │  MONITOR (continuous watcher — cadence-split launchd)       │
  │  kage monitor observe / digest / run / install / status    │
  │  observe: AX daemon → observations-YYYY-MM-DD.jsonl (5min) │
  │  digest: cloud synthesis → YYYY-MM-DD.md (07:00 daily)     │
  └─────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────┐
  │  LIBRARIAN (memory curator — HITL approval gate)            │
  │  kage librarian run / queue / approve / reject / status    │
  │  staging queue → distill_and_judge (3e gate + LLM)         │
  │  PROMOTE / HOLD / DISCARD · human approves every write     │
  │  nothing enters ~/.kage/memory/ without kage librarian approve│
  └─────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────┐
  │  SURFACE                                                    │
  │  CLI (kage)                    MCP (stdio → any client)    │
  │  remember · recall · ask       kage_recall · kage_ask      │
  │  import · list · forget        kage_remember · kage_status │
  │  status · doctor · reindex · migrate                        │
  └───────────────────────┬─────────────────────────────────────┘
                          │
  ┌───────────────────────▼─────────────────────────────────────┐
  │  LAYER 3e — PRIVACY GATE                                    │
  │  Stage 1: identity wall (independent re-check)             │
  │  local_only flag · project rules · PII scan (31 patterns)  │
  │  approval prompt · session memory · audit log              │
  └───────────────────────┬─────────────────────────────────────┘
                          │
  ┌───────────────────────▼─────────────────────────────────────┐
  │  LAYER 3d — GROUNDED ASK                                    │
  │  context assembly · system prompt: answer ONLY from notes  │
  │  local Ollama default · named cloud providers              │
  └───────────────────────┬─────────────────────────────────────┘
                          │
  ┌───────────────────────▼─────────────────────────────────────┐
  │  LAYER 3b — RETRIEVAL + IDENTITY WALL                       │
  │  SQLite FTS5 + ChromaDB vectors · RRF fusion · reranker    │
  │  _allowed_note_ids(identity, project) → SQLite pre-filter  │
  │  Chroma where={"note_id": {"$in": allowed}}                │
  └───────────────────────┬─────────────────────────────────────┘
                          │
  ┌───────────────────────▼─────────────────────────────────────┐
  │  LAYER 1 — MEMORY STORE                                     │
  │  Markdown source of truth  (~/.kage/memory/)               │
  │  SQLite index · ChromaDB chunk store · local_only flag     │
  │  memory_identities · memory_projects (join tables)         │
  └─────────────────────────────────────────────────────────────┘
```

---

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Chirag-Mokashi/kage.git
cd kage
uv sync
uv run kage init
```

`kage init` scaffolds `~/.kage/` — config, markdown memory store, SQLite index, ChromaDB directory. Safe to re-run.

**Upgrading from v0.8 or earlier:** run `kage migrate` once to backfill identity metadata on existing notes.

---

## Commands

```
kage use <identity>[/project]       Set active context — honored by every surface.
kage use --clear                    Reset to fallback (personal / no project).
kage where                          Show resolved context + its source.

kage remember "<text>"              Save a note. --project X to partition it.
                                    --identity X to assign an identity (default: personal).
                                    --state to set scoped/baseline/pending explicitly.
                                    --local to mark it never-sent-to-cloud.

kage recall "<query>"               Hybrid search: FTS5 + semantic (if Ollama running).
                                    --project X to scope the search.
                                    --identity X to scope to an identity (default: personal).

kage ask "<question>"               Answer from your notes using local Ollama.
kage ask "<question>" --cloud       Route to your default cloud provider.
kage ask "<question>" --cloud \
  --provider groq                   Route to a specific named provider.
kage ask "<question>" \
  --identity neu                    Answer using only NEU identity notes.

kage import <folder>                Bulk-import .md / .txt files.
                                    --identity X to tag all imported notes.
kage reindex                        Build / rebuild the vector index.
kage migrate                        Backfill identity metadata on existing notes.
                                    --dry-run to preview without writing.
kage list                           Browse saved notes (filtered by --identity).
kage forget <id>                    Delete a note from memory + indexes.

kage status                         Snapshot: note count, model, RAM, disk.
kage status --audit                 Last N cloud dispatch records.
kage doctor                         Health checks: store, DB, Ollama, providers,
                                    privacy gate config, audit log.

kage mcp serve                      Start the MCP server (stdio transport).

kage arm auth                       One-time Google OAuth consent (for remote SSE arms).

kage scout run                      Fetch external signals, triage, and write today's digest.
                                    Requires prior bootstrap run to seed the seen-cache.
kage scout dry-run                  Fetch + triage only — print digest and discard (no write).
kage scout bootstrap                Seed the seen-cache without writing a report.
                                    Run once before the first kage scout run.
kage scout status                   Show cache size, last run date, token log summary.

kage librarian run                  Process pending staging items — distill, judge, queue for approval.
kage librarian queue                Show items awaiting your approval (--held for held items).
kage librarian approve <id>         Write an approved note to permanent memory.
kage librarian reject <id>          Reject an approval request (item stays in staging).
kage librarian locate <query>       Search permanent memory (pre-check before depositing).
kage librarian scan                 Scan the staging queue for sensitive patterns before approval.
kage librarian status               Show catalog stats: note count, queue depth, last run.

kage monitor observe                Run one observe pass (local Qwen3 only — no cloud).
kage monitor digest                 Synthesize today's observations into a digest (cloud).
kage monitor run                    Run observe then digest in sequence.
kage monitor last                   Print the most recent digest file.
kage monitor status                 Show observation count for today, last run timestamp.
kage monitor install                Install both launchd plists (observe every 5min, digest at 07:00).
kage monitor uninstall              Remove both launchd plists.

kage sensitive list                 Show all user-defined sensitive patterns in the vault.
kage sensitive add <label> <regex>  Add a new pattern to ~/.kage/sensitive.json.
kage sensitive scan                 Scan memory + staging queue against vault patterns.

kage learn                          Generate improved system prompt rules from kage-corrections
                                    (ProTeGi pattern — cloud reads logs, writes rules, stores in
                                    ~/.kage/learned_prompts.json). Reviews pending; use --accept.
kage learn --class code             Generate rules for one task class only.
kage learn --all                    Force relearn all 5 classes regardless of correction count.
kage learn --accept                 Accept and save pending generated rules to active prompts.
kage learn --accept --class code    Accept only the pending rules for a specific class.
kage learn --status                 Show active prompt version, date, correction count per class.
kage learn --rollback <class>       Roll back a class to its previous prompt version.
```

Arms are configured under `arms` in `~/.kage/config.json`. Each arm declares a
`transport` (`shell` for a local command, `stdio` for a local MCP process, `sse` for a
remote MCP server), an `identity`, and a `permission` (read-only enforced today). When a
question matches an arm's keywords, kage calls it and injects the live result as context —
falling back to memory-only if the arm is unavailable. Every arm call is recorded in the
audit log. The first shipped arm reads the local macOS Calendar (via `osascript`
querying Calendar.app — `icalbuddy` was the original transport but broke on macOS
16 / Darwin 25.x, so it was replaced with a bundled AppleScript):

```json
"arms": {
  "calendar": {
    "enabled": true,
    "transport": "shell",
    "command": "osascript ~/.kage/calendar_arm.scpt",
    "identity": "personal",
    "permission": "read"
  }
}
```

---

## Memory model

Memory lives as plain `.md` files under `~/.kage/memory/`. SQLite FTS5 and ChromaDB are derived indexes — rebuilt from markdown on demand. You can grep, git, and read your own notes with no kage running.

```
~/.kage/
├── memory/           ← source of truth (markdown, one file per note)
├── indexes/
│   └── kage.db       ← SQLite FTS5 index + identity/project join tables (derived)
├── chroma/           ← vector index (derived, requires Ollama embed)
├── config.json       ← providers, routing rules, privacy config
└── audit.jsonl       ← append-only cloud dispatch log
```

### Identity × project partition

Notes are partitioned on two axes:

- **Identity** — the hard wall. `personal` notes are invisible to a `--identity neu` query and vice versa. Default identity is `personal`. Pass `--identity neu` to scope to a different identity.
- **Project** — the soft filter within an identity. A note in project `kage` is invisible to a query scoped to project `health` *within the same identity*.

Three note states control how the project filter is applied:

```
  scoped    note belongs to specific project(s) — only returned when that project is active
  baseline  note has no project — returned for any query within the matching identity
  pending   note is not yet partitioned — never returned in search
```

The wall is a SQLite pre-filter (`_allowed_note_ids`) that runs before both FTS and vector search. Chroma never sees a note ID that the wall has blocked.

---

## Privacy gate (Layer 3e)

Every cloud dispatch goes through a disclosure gate. Nothing reaches an external API without passing checks in order:

```
  0. identity wall  Stage-1 re-check: is this note in the active identity?
                    (Independent second wall — defense in depth.)
  1. local_only     Was this note explicitly saved as local-only?
  2. project rule   Is the note's project in local_only_projects config?
  3. PII scan       Does the note contain Aadhaar, PAN, API keys,
                    passport numbers, email addresses, or 26 other
                    patterns across 6 categories?

  PASS → PII values substituted with placeholders before dispatch;
         real values swapped back into the cloud response before display
  FAIL → note withheld (local_only or identity mismatch), user notified
```

As of v0.21.0, notes containing PII are no longer withheld from cloud — they pass through with real values masked (`[EMAIL_1]`, `[API_KEY_IN_CONTEXT_1]`, etc.) and restored in the response. `local_only` and the identity wall remain hard blocks. Every dispatch decision is written to `~/.kage/audit.jsonl`. Session approval memory means you are not re-prompted for every query to the same provider.

Mark a note local-only at save time:
```bash
kage remember "my Aadhaar is XXXX XXXX XXXX" --local
```

Or by project in `~/.kage/config.json`:
```json
{ "local_only_projects": ["health", "finance", "personal-docs"] }
```

---

## Cloud providers

kage ships with five built-in providers and supports any OpenAI-compatible endpoint.

```bash
# Built-in providers — set the corresponding env var to enable
ANTHROPIC_API_KEY    → claude        (claude-sonnet-4-6 default)
OPENAI_API_KEY       → openai        (gpt-4o default)
GEMINI_API_KEY       → gemini        (gemini-2.0-flash default)
GROQ_API_KEY         → groq          (llama-3.3-70b-versatile default)
PERPLEXITY_API_KEY   → perplexity    (sonar-large-128k-online default)
```

Add any OpenAI-compatible endpoint (OpenRouter, Fireworks, Mistral, etc.) in `~/.kage/config.json`:

```json
{
  "cloud_provider": "openrouter-free",
  "providers": {
    "openrouter-free": {
      "type": "openai-compat",
      "api_key_env": "OPENROUTER_API_KEY",
      "base_url": "https://openrouter.ai/api/v1",
      "chat_path": "/chat/completions",
      "model": "openrouter/free"
    }
  }
}
```

Override the model per provider via `providers.<name>.model`. Swap providers per query with `--provider <name>`.

---

## MCP server

kage exposes four tools over stdio MCP, usable from Claude Code, Odysseus, or any MCP client:

```
kage_recall(query, project, limit, identity)    Search memory — read-only, always available
kage_ask(question, provider, project, identity) Answer from memory, gate runs automatically
kage_remember(text, project, local)             Save a note — requires mcp_allow_writes: true
kage_status()                                   Store snapshot
```

All search tools default `identity="personal"`. Pass `identity="neu"` to scope to a different identity.

**Claude Code** — add to `.mcp.json` in your repo root:
```json
{
  "mcpServers": {
    "kage": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/kage", "kage", "mcp", "serve"]
    }
  }
}
```

**Odysseus** — add via Settings → MCP Servers → Add Server:
- Transport: `stdio`
- Command: `uv`
- Args: `["run", "--directory", "/path/to/kage", "kage", "mcp", "serve"]`

---

## Local model

kage uses [Ollama](https://ollama.ai) for local inference and embeddings. Install Ollama, then:

```bash
ollama pull qwen3:14b           # answering model
ollama pull nomic-embed-text    # embedding model (for semantic search)
ollama serve                    # keep running while using kage
```

Set a different model in `~/.kage/config.json`:
```json
{ "model": "llama3.2:3b" }
```

---

## What is coming

kage today is a passive broker — it answers when called. The target is an active mediator — it orchestrates.

```
  Cycle 8    Retrieval quality          SHIPPED — recursive chunking + bge-reranker
  Cycle 9    Identity axis (THE WEDGE)  SHIPPED — identity × project wall, real data
  Cycle 10   Stateful sessions          SHIPPED — kage chat REPL, safe model-switching
  Cycle 10.5 Active context             SHIPPED — kage use / where, resolver, MCP wired
  Cycle 11   kage as MCP client         SHIPPED — arm routing + local shell arm (calendar)
  Cycle 12   Modularity                 SHIPPED — injectable seams, 25 modules, registries
  Cycle 13   Arms expansion             SHIPPED — gmail arm (osascript) + browser arm (Playwright MCP)
  Cycle 14   Scout agent                SHIPPED — proactive ADK Workflow, Tier 1/2 triage, project-aware
  Cycle 15   Librarian agent            SHIPPED — ADK LlmAgent, HITL approval gate, 3e-gated distill-and-judge
  Cycle 16   Monitor agent              SHIPPED — AX daemon, observe/digest ADK Workflows, launchd plists
  Cycle 17   Gap fixes                  SHIPPED — 10 structural gaps across scout/librarian/monitor/observe
  Cycle 18   Layer 4 router             SHIPPED — keyword task-class routing, config-driven routing table
  Cycle 19   Sensitive vault            SHIPPED — user-defined PII patterns (kage sensitive)
  Cycle 20   Monitor cadence + Scout deep fetch  SHIPPED — observe/digest cadence split, Scout two-stage fetch
  Cycle 21   Reversible PII masking             SHIPPED — substitute/restore gate, PII notes no longer withheld
  Cycle 22   kage learn (Layer 6)               SHIPPED — ProTeGi prompt learning, Monitor auto-trigger at N=7
  Cycle 23   Gate hardening                     SHIPPED — mask-at-dispatch, per-request map, audit type-counts
  Cycle 24   Librarian EPM (learn rejections)   SHIPPED — distills rejection patterns into the distill prompt
  Cycle 25   Librarian CTM (learn approvals)    SHIPPED — approved precedents as few-shot examples (MemAPO loop)
  Cycle 26   Calendar-write (first write arm)   SHIPPED — EventKit create-only, propose→approve→execute, HITL-gated
```

Cycle 23 (gate hardening) closed the HIGH-severity findings from the 2026-07-01 security audit (`docs/security-audit-2026-07-01.md`). The marquee fix is **mask-at-dispatch**: the condensed retrieval query, conversation history, and retrieved context are all masked through one shared per-request placeholder map and restored in the response — closing the condensed-query cleartext leak (F13). The audit log now emits `pii_type_counts` (typed tallies) instead of numbered placeholder labels, so it no longer leaks the placeholder structure (F1). No new capability — defense-in-depth only. Build plan: `docs/cycle-23-gate-hardening.md`.

Cycle 25 (CTM — Correct-Template Memory) closes the Librarian's dual-memory loop: after every approved `write_note`, `_emit_ctm_note` records the approved item as a precedent in `kage-ctm-librarian`. At distill time, `_retrieve_ctm` pulls the most recent approved precedents (recency-based, PII-gated) and injects them as few-shot examples above the rejection rules — so the Librarian's judgment is shaped by what you *accepted*, not only what you rejected.

Cycle 24 (EPM — learn from rejections) gave the Librarian the same Layer 6 learning engine `kage ask` uses. Each `kage librarian reject` writes a correction note to `kage-corrections-librarian`; `kage learn --librarian` distills those rejections into rules that prepend the distill prompt, and Monitor auto-fires the pass at 7+ new librarian corrections. The project is hard-blocked from cloud egress.

Cycle 22 added `kage learn` — a prompt-only learning layer. `learn.py` reads correction logs from the `kage-corrections` project via FTS, sends them to a cloud model using the ProTeGi meta-prompt pattern, and stores versioned rules in `~/.kage/learned_prompts.json`. At query time, `load_learned_prompt(task_class)` injects the active rules into local Qwen3's system prompt. Monitor now fires `kage learn --all` automatically when 7+ new corrections accumulate since the last run. Workflow: `kage learn` generates pending rules → `kage learn --status` to review → `kage learn --accept` to promote. `kage learn --rollback <class>` reverts to the previous version if a rule set degrades quality.

Cycle 21 made PII handling reversible. `redact.py` provides pure `substitute()` / `restore()` functions — PII spans are replaced with typed numbered placeholders (`[EMAIL_1]`, `[AADHAAR_1]`) before cloud dispatch and swapped back from the response before display. `_disclosure_gate` now returns a three-tuple `(allowed, withheld, pii_map)`; PII no longer causes notes to be withheld — they pass through masked. `local_only` and the identity wall remain unconditional hard blocks.

Cycle 20 split Monitor's cadence: observe (AX daemon, local Qwen3) runs every 5 minutes via a `StartInterval` launchd plist; digest (cloud) fires once daily at 07:00 via `StartCalendarInterval`. Scout gained a two-stage deep-fetch: ScoutBroad (local) shortlists by index number → `_fetch_full` enriches via Jina Reader / GitHub API README / Reddit body → ScoutIntegrate (cloud) works from full content, not headlines. Both `kage monitor observe` and `kage monitor digest` are now independent subcommands with their own try/except error reporting.

Cycle 19 added a user-defined sensitive pattern vault at `~/.kage/sensitive.json`. Add any regex via `kage sensitive add <label> <pattern>`; the vault extends the 29-pattern built-in PII table and can be scanned across memory and the staging queue. Patterns are validated at add time and stored with an id, label, and timestamp.

Cycle 18 added a Layer 4 keyword router — `router.py` classifies questions into five task classes (code, research, multimodal, reasoning, chat) by keyword match and returns an ordered list of provider candidates. The routing table is config-driven so you can override per task class in `~/.kage/config.json`.

Cycle 17 addressed 10 structural gaps (G01–G10) across scout/librarian/monitor/observe — missing guards, stale imports, test seam gaps.

Cycle 16 shipped Monitor — kage's third ADK agent. A macOS Accessibility daemon (`observe.py`) captures app-switch, typing-pause, scroll-stop, and idle events and appends timestamped JSON to `observations-YYYY-MM-DD.jsonl`. `build_monitor_observe` (local Qwen3) summarizes findings; `build_monitor_digest` (cloud) synthesizes the day's JSONL into a readable `~/.kage/monitor/YYYY-MM-DD.md`. `kage monitor install` registers both launchd plists with one command.

Cycle 15 shipped Librarian — kage's sole writer to permanent memory. Librarian runs as an ADK `LlmAgent` with 10 tools over a two-table staging pipeline (`staging_queue` → `approval_queue`). Every item deposited by Scout (or manually via `kage librarian`) passes through a 3e-gated `distill_and_judge` call: PII is scrubbed unconditionally, existing notes are checked for dedup and supersession, and the LLM judges PROMOTE / HOLD / DISCARD against five criteria (durability, actionability, novelty, specificity, contradiction). PROMOTE items surface in `kage librarian queue` awaiting your approval — nothing reaches `~/.kage/memory/` without `kage librarian approve`. Write order is DB-first, writes are idempotent, and a dual-lock prevents concurrent runs.

Cycle 14 shipped Scout — kage's first proactive behavior. Scout fetches public signals from five sources (HN, arXiv, GitHub, Reddit, RSS) on demand, classifies them into Tier 1 (Actionable) and Tier 2 (Good to Know) using a two-stage ADK Workflow, and writes a project-aware morning digest. ScoutBroad (local Qwen3) shortlists by index → deep-fetch enriches full content → ScoutIntegrate (cloud Claude) writes business-ruthlessness cards for Tier 1 items, consulting project memory via `scout_recall`. Scout finds. You decide. Librarian remembers.

Cycle 13 added two arms: a gmail arm (reads Mail.app via osascript, zero OAuth, privacy-gated) and a browser arm (Playwright MCP for headless web, stealth config). Arms are declared in `~/.kage/config.json` and routed by keyword; every call hits the audit log.

Cycle 12 dissolved the monolithic `cli.py` into 25 focused modules via injectable runtime seams — swapping `runtime.embed` or `runtime.cloud` now reaches every module at once, making backends genuinely swappable and arms/providers pluggable via registries. The egress golden tests lock the privacy moat: withheld note content is verified absent from every cloud payload.

---

## Design principles

Ten characteristics locked in Session 4, checked against every design decision:

```
  Seamless · Transparent · Aware · Local · Silent ·
  Broker · Adoptable · Controlled · Invisible · Modular
```

The single-word north star: **Seamless** — kage acts invisibly. The only hard problem is adoption.

Above the ten sits one operating value — **jugaad** (जुगाड़): frugal, resourceful ingenuity under constraint. Get maximum capability from what you already have; route *around* artificial constraints (paywalls, missing APIs, double-billing) rather than pay to remove them. The guardrail: jugaad governs *what* kage reaches for, never *how* it's built — the workaround is resourceful, the implementation stays clean, tested, and complete.

---

## Repo

```
src/kage/
├── cli.py          Typer commands + call-time forwarder shims (the entry point)
├── runtime.py      Live seam instances — swapping runtime.X reaches every module
├── http.py         Shared urllib helper (_post_json) — one place for headers/User-Agent
├── config.py       Config seam — derives paths from KAGE_HOME, re-reads on every access
├── store.py        Store seam — SQLite WAL connect, schema init, identity wall query
├── embed.py        Embedder seam — Ollama nomic-embed-text + OllamaUnavailable sentinel
├── vector.py       VectorIndex seam — ChromaDB collection + semantic search
├── cloud.py        CloudClient + ProviderRegistry — the single cloud egress sink
├── arms.py         Arm routing + ArmRegistry — shell / stdio / sse transport dispatch
├── privacy.py      Disclosure gate, PII scan, audit log, context assembly
├── retrieval.py    FTS5 + vector search, RRF fusion, bge-reranker
├── notes.py        Save / reindex / import — the write path
├── context.py      Active context resolver (kage use / where)
├── session.py      Session CRUD, turn gating, query condensing
├── chunk.py        Note chunking — pure text logic, no I/O
├── pii.py          PII patterns + scanner — pure, no I/O
├── scout.py        Scout agent — fetch (5 sources), two-stage deep fetch, ADK pipeline, report writer
├── librarian.py    Librarian agent — staging queue, distill_and_judge, HITL approval, memory write
├── monitor.py      Monitor agent — observe/digest ADK Workflows, cadence-split launchd plists
├── observe.py      macOS AX daemon — app-switch / typing-pause / idle event capture
├── router.py       Layer 4 keyword router — task-class classification, config-driven routing table
├── sensitive.py    Sensitive vault — user-defined regex PII patterns, vault CRUD, memory/queue scan
├── redact.py       Reversible PII masking — substitute() / restore(), pure functions, no I/O
├── learn.py        Layer 6 prompt learning — ProTeGi pattern, versioned learned_prompts.json
└── mcp_server.py   MCP server (FastMCP, stdio transport)

tests/
├── test_cli.py         418 tests — CLI commands + all seam behaviors
├── test_scout.py        64 tests — fetch layer, corpus, deep fetch, ADK pipeline, project injection
├── test_monitor.py      48 tests — observe pass, digest pass, cadence split, launchd plists, learn trigger
├── test_librarian.py    37 tests — schema migration, staging queue, distill_and_judge, HITL loop, EPM + CTM learning
├── test_learn.py        24 tests — load/build/run/save, FTS filtering, bullet extraction, librarian pass
├── test_router.py       18 tests — task classification, routing table, config override
├── test_seams.py        13 tests — seam contracts + registry functions
├── test_calendar_write.py  12 tests — propose/approve/reject, guards, fail-safe, injection, live EventKit smoke
├── test_redact.py        9 tests — substitute/restore round-trip, sequential safety, existing mapping
├── test_pii.py           8 tests — PII detection table + scanner
├── test_sensitive.py     8 tests — vault CRUD, pattern scan, integration with privacy gate
├── test_observe.py       2 tests — AX daemon event capture
└── fakes.py         Test doubles: FakeEmbedder, FakeVectorIndex, RecordingCloud, FakeConfig
                       (661 tests total across 12 test files)

docs/
├── blueprint.md             Long-term architecture and planning state
├── cycle-12-modularity.md   Modularity design — injectable seams, 25 modules
├── cycle-14-scout.md        Scout agent pitch — ADK design, source list, seen-cache
├── cycle-14-scout-v1.1.md   Scout v1.1 — Tier 1/2 triage, project-aware, GitHub stats
├── cycle-15-librarian.md    Librarian agent pitch — staging pipeline, HITL design, cold reviews
├── cycle-16-monitor.md      Monitor agent pitch — AX daemon, cadence split, launchd design
├── cycle-19-sensitive-vault.md  Sensitive vault pitch — user-defined patterns, vault schema
├── cycle-20-pitch.md        Cycle 20 pitch — Monitor cadence split, Scout two-stage deep fetch
├── cycle-21-redact.md       Reversible PII masking pitch — substitute/restore design, 3 cold reviews
├── cycle-22-layer6.md       Layer 6 kage learn pitch — ProTeGi pattern, learned_prompts.json schema
└── ...                      Historical cycle pitches and research
```

Built by [Chirag Mokashi](https://github.com/Chirag-Mokashi) — MS Applied AI, Northeastern University.
