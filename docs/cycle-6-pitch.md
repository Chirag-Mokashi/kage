# Cycle 6 Pitch — MCP Server Out (v0.6)

*Written: 2026-06-09*
*Status: DRAFT — pending Chirag approval.*

---

## Problem

kage's memory is trapped inside the CLI. Every tool that could benefit from it —
Claude Code, future Antigravity 2.0, Cursor — has no way to access it. When a
development session switches tools (Claude NEU hits its monthly limit → switch
to Groq or Antigravity), the context built up in kage stays dark. The broker
cannot broker if it has no outbound channel.

MCP (Model Context Protocol) is the de-facto standard for exposing tools and
memory to AI agents in 2026 — adopted by Anthropic, OpenAI, Google, Microsoft.
kage needs to speak it.

---

## Scope

One new command: `kage mcp serve`.

Four MCP tools exposed:

```
kage_recall   — search kage memory (project-partitioned, read-only)
kage_remember — save a note to kage memory (write-gated, user-confirmable)
kage_ask      — route a question through kage (local or cloud provider)
kage_status   — snapshot of active project, memory count, model config
```

stdio transport. localhost-only. Read-only by default (`kage_remember` off
unless `"mcp_allow_writes": true` in config). Project partition respected on
every call — an MCP client cannot access memories outside its declared project
scope.

---

## Design

### Transport and registration

```
   Claude Code / Antigravity 2.0 / Cursor
            │
            │  spawns subprocess via stdio
            ▼
   kage mcp serve
   (Python MCP SDK — `mcp` package)
            │
            ├─► kage_recall(query, project?)  → ranked notes
            ├─► kage_remember(text, project?) → saved / rejected
            ├─► kage_ask(question, provider?, project?) → answer + sources
            └─► kage_status()                → store snapshot
```

Registration in Claude Code — `.mcp.json` at project root (project scope,
committed to repo so teammates inherit it automatically):

```json
{
  "mcpServers": {
    "kage": {
      "type": "stdio",
      "command": "kage",
      "args": ["mcp", "serve"]
    }
  }
}
```

Or add globally (all projects) via CLI:
```bash
claude mcp add kage --scope user -- kage mcp serve
```

Antigravity 2.0 uses the same stdio convention — same registration pattern,
different config path (TBD post-June 18). No code change needed to support
both; MCP is the abstraction.

### Tool schemas (MCP)

```
kage_recall
  input:  query (str), project (str | null), limit (int = 5)
  output: list of { id, title, excerpt, score, project }

kage_remember
  input:  text (str), project (str | null)
  output: { saved: bool, id: str | null, reason: str }

kage_ask
  input:  question (str), provider (str | null), project (str | null)
  output: { answer: str, sources: list[str], provider: str }

kage_status
  input:  (none)
  output: { memory_count: int, projects: list[str], model: str, disk_free: str }
```

### Partition enforcement

Every tool call goes through the same `_search` / `_config` path the CLI uses.
The `project` parameter on each tool maps directly to the `-p` flag. No new
logic — the MCP layer is a thin JSON-in / JSON-out wrapper over existing
functions.

### Write gate

`kage_remember` is disabled by default. To enable:

```json
{ "mcp_allow_writes": true }
```

in `~/.kage/config.json`. When disabled, `kage_remember` returns
`{ "saved": false, "reason": "writes disabled — set mcp_allow_writes in config" }`.
This satisfies the read-only-by-default decision (#83) without hard-coding it.

---

## Implementation Order

1. Add `mcp[cli]` to dependencies in `pyproject.toml`
2. Scaffold `kage/mcp_server.py` — `FastMCP` instance, register 4 tools
3. Wire `kage_recall` → `_search()` + format output as tool result
4. Wire `kage_status` → reuse `status` internals, return dict
5. Wire `kage_ask` → `_call_cloud()` or local path, return answer + sources
6. Wire `kage_remember` → `_remember_core()` behind write gate
7. Add `mcp serve` subcommand to `cli.py` → starts the server via stdio
8. Register in project-level `.claude/mcp.json` (committed to repo)
9. Tests: mock MCP client calls each tool, assert correct JSON shape and
   partition behaviour (project filter respected, write gate enforced)
10. Update `kage doctor` to check MCP server importable + config readable

---

## Tests

- `kage_recall` returns notes filtered to declared project
- `kage_recall` with no project returns notes from all projects
- `kage_remember` returns write-disabled message when gate is off
- `kage_remember` saves correctly when gate is on
- `kage_ask` routes to local when no provider specified
- `kage_ask` routes to named provider when specified
- `kage_status` returns correct memory count and project list
- MCP server starts and responds without error (`mcp dev` inspector smoke test)

---

## What this unlocks immediately

- Claude Code can query kage memory inline during any coding session
- Antigravity 2.0 (post-June 18) can access kage via MCP if it supports stdio
- kage becomes the API key vault + router — MCP clients delegate cloud calls
  through kage rather than needing their own keys
- Development sessions survive provider switches: context lives in kage,
  not in any one tool's session memory

---

## What is NOT in this cycle

- Identity dimension (Layer 3b) — project partition only, no identity wall yet
- Per-tool disclosure budgets (Layer 3e) — all retrieved context passes through
- Auto-routing (Layer 4) — provider still explicit or from config default
- MCP server IN (external tools writing TO kage) — read-mostly first
- Permission Broker — separate design surface, post-MCP-stable
- Daemon / background MCP process — on-demand launch only (kage mcp serve
  is spawned by the client, exits when client disconnects)

---

## Deferred from this cycle to blueprint backlog

- MCP server registry signing (Anthropic official registry — #41 note)
- Per-identity tool allowlists (#42)
- Token-auth hardening for non-localhost clients (v1.5)
- Antigravity 2.0 specific config path (`~/.antigravity/`) — evaluate
  post-June 18 once 2.0 MCP support is confirmed
