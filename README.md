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

## Current state — v0.9

kage ships as a headless CLI and MCP server. The full UI layer (via Odysseus integration) is in progress.

**Honest status:** today kage is a *context-gated forwarder with a hard identity wall* — it retrieves your notes, enforces the identity × project partition before any note reaches retrieval, gates what may leave your machine, and forwards a single grounded query to the model *you* select. The full *broker* behavior (automatic model routing, active context detection, conversational interface) is on the roadmap below — designed, not yet shipped. The BROKER level above describes the direction; this section describes what runs today.

```
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
  │  local_only flag · project rules · PII scan (29 patterns)  │
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

  PASS → user sees a summary of what will be sent, approves, cloud is called
  FAIL → note withheld, user notified, Ollama answers instead
```

Every dispatch decision is written to `~/.kage/audit.jsonl`. Session approval memory means you are not re-prompted for every query to the same provider.

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
  Cycle 8   Retrieval quality          SHIPPED — recursive chunking + bge-reranker
  Cycle 9   Identity axis (THE WEDGE)  SHIPPED — identity × project wall, real data
  Cycle 10  kage chat + streaming      Conversational interface, stateful turns
  Cycle 11  kage as MCP client         kage calls Gmail, files, web, git itself
  Cycle 12  Layer 4 auto-routing       Intent → model selection, automatic
  Cycle 13  Agent loop                 Multi-step planning and execution
```

After Cycle 11, external UIs (Odysseus, Claude Code) become optional rendering surfaces. kage calls the tools directly; the UI just shows the result.

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
├── cli.py            Main CLI + all broker logic
└── mcp_server.py     MCP server (FastMCP, stdio)

tests/
├── test_cli.py       273 tests, ~100% line coverage
└── eval_retrieval.py Retrieval eval harness (MRR, recall@k, identity wall invariants)

docs/
├── blueprint.md      Long-term architecture and planning state
├── cycle-9-pitch.md  Identity axis design (most recent cycle)
└── ...               Historical cycle pitches and research
```

Built by [Chirag Mokashi](https://github.com/Chirag-Mokashi) — MS Applied AI, Northeastern University.
