# kage

**kage** (Japanese — "shadow") is a local-first personal context broker between you and your AI stack.

It sits silently between your intent and every AI tool you use — managing your memory, gating what leaves your machine, and routing queries to the right model. It is not a chatbot. It is not a Claude replacement. It is the invisible layer that makes every AI tool you already use smarter and safer.

kage is defined at three nested levels, all simultaneously true:

```
  COMPLEMENT  The disciplined part of you that the hedonistic part is not.
              Invisible diligence operating in the background.

  MEDIATOR    A second layer between your intent and the world.
              Tools and devices are arms. kage is the brain.

  BROKER      Local-first context broker between you and your cloud AI stack.
              Project × identity partitioned memory. Privacy-preserving routing.
```

---

## Current state — v0.7

kage ships as a headless CLI and MCP server. The full UI layer (via Odysseus integration) is in progress.

```
  ┌─────────────────────────────────────────────────────────────┐
  │  SURFACE                                                    │
  │  CLI (kage)                    MCP (stdio → any client)    │
  │  remember · recall · ask       kage_recall · kage_ask      │
  │  import · list · forget        kage_remember · kage_status │
  │  status · doctor · reindex                                  │
  └───────────────────────┬─────────────────────────────────────┘
                          │
  ┌───────────────────────▼─────────────────────────────────────┐
  │  LAYER 3e — PRIVACY GATE                                    │
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
  │  LAYER 3b — RETRIEVAL                                       │
  │  SQLite FTS5 + ChromaDB vectors · RRF fusion               │
  │  project partition filter · semantic + keyword hybrid      │
  └───────────────────────┬─────────────────────────────────────┘
                          │
  ┌───────────────────────▼─────────────────────────────────────┐
  │  LAYER 1 — MEMORY STORE                                     │
  │  Markdown source of truth  (~/.kage/memory/)               │
  │  SQLite index · ChromaDB chunk store · local_only flag     │
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

---

## Commands

```
kage remember "<text>"              Save a note. Add --project X to partition it.
                                    Add --local to mark it never-sent-to-cloud.

kage recall "<query>"               Hybrid search: FTS5 + semantic (if Ollama running).
                                    Add --project X to scope the search.

kage ask "<question>"               Answer from your notes using local Ollama.
kage ask "<question>" --cloud       Route to your default cloud provider.
kage ask "<question>" --cloud \
  --provider groq                   Route to a specific named provider.

kage import <folder>                Bulk-import .md / .txt files.
kage reindex                        Build / rebuild the vector index.
kage list                           Browse saved notes.
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
│   └── kage.db       ← SQLite FTS5 index (derived)
├── chroma/           ← vector index (derived, requires Ollama embed)
├── config.json       ← providers, routing rules, privacy config
└── audit.jsonl       ← append-only cloud dispatch log
```

Notes are partitioned by project. A note in project `kage` is invisible to a query scoped to project `health`. Identity and project are the two axes of memory isolation.

---

## Privacy gate (Layer 3e)

Every cloud dispatch goes through a disclosure gate. Nothing reaches an external API without passing three checks:

```
  1. local_only flag    Was this note explicitly saved as local-only?
  2. project rule       Is the note's project in local_only_projects config?
  3. PII scan           Does the note contain Aadhaar, PAN, API keys,
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
    },
    "openrouter-reason": {
      "type": "openai-compat",
      "api_key_env": "OPENROUTER_API_KEY",
      "base_url": "https://openrouter.ai/api/v1",
      "chat_path": "/chat/completions",
      "model": "nvidia/nemotron-3-ultra-550b-a55b:free"
    }
  }
}
```

Override the model per provider via `providers.<name>.model`. Swap providers per query with `--provider <name>`.

---

## MCP server

kage exposes four tools over stdio MCP, usable from Claude Code, Odysseus, or any MCP client:

```
kage_recall(query, project, limit)      Search memory — read-only, always available
kage_ask(question, provider, project)   Answer from memory, gate runs automatically
kage_remember(text, project, local)     Save a note — requires mcp_allow_writes: true
kage_status()                           Store snapshot
```

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
  Cycle 8   kage chat + streaming      Conversational interface, stateful turns
  Cycle 9   kage as MCP client         kage calls Gmail, files, web, git itself
  Cycle 10  Layer 4 auto-routing       Intent → model selection, automatic
  Cycle 11  Agent loop                 Multi-step planning and execution
```

After Cycle 9, external UIs (Odysseus, Claude Code) become optional rendering surfaces. kage calls the tools directly; the UI just shows the result.

---

## Design principles

Ten characteristics locked in Session 4, checked against every design decision:

```
  Seamless · Transparent · Aware · Local · Silent ·
  Broker · Adoptable · Controlled · Invisible · Modular
```

The single-word north star: **Seamless** — kage acts invisibly. The only hard problem is adoption.

---

## Repo

```
src/kage/
├── cli.py            Main CLI + all broker logic
└── mcp_server.py     MCP server (FastMCP, stdio)

tests/
└── test_cli.py       227 tests, 100% line coverage

docs/
├── blueprint.md      Long-term architecture and planning state
├── cycle-7-pitch.md  Privacy gate design (most recent cycle)
└── ...               Historical cycle pitches and research
```

Built by [Chirag Mokashi](https://github.com/Chirag-Mokashi) — MS Applied AI, Northeastern University.
