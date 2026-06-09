# kage

**Local-first personal context broker** — your notes, surfaced into your cloud AI, on your machine. Nothing leaves your Mac unless you send it.

> **Status:** working local CLI, currently beyond the original v0.1 thin slice. kage can save/import notes, search them with SQLite FTS5 plus optional ChromaDB semantic search, answer with local Ollama, and call named cloud providers. See [docs/blueprint.md](docs/blueprint.md) for the long-term roadmap and the cycle pitch docs for historical build context.

## Dev setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync            # create the venv + install kage and its deps
uv run kage init   # set up ~/.kage/ (config, memory store, index)
uv run kage --help # see all commands
```

## What it does now

| Command | What it does |
|---|---|
| `kage init` | Scaffold `~/.kage/` — config, markdown memory store, SQLite index, ChromaDB directory. Safe to re-run. |
| `kage remember "<text>" --project X` | Save a note as markdown + indexes, confirmed before write. |
| `kage import <folder> --project X` | Bulk-add `.md` / `.txt` notes; embeddings are deferred to `kage reindex`. |
| `kage recall "<query>" --project X` | Hybrid recall: SQLite FTS5 plus ChromaDB semantic search when embeddings are available. |
| `kage ask "<question>" --project X` | Answer from recalled notes using local Ollama by default. |
| `kage ask "<question>" --cloud --provider openai` | Answer from recalled notes through a named cloud provider. |
| `kage reindex` | Embed pending chunks, or rebuild chunk/vector indexes with `--force`. |
| `kage list` / `kage forget` | Browse and delete saved notes. |
| `kage status` / `kage doctor` | Show state, model/provider status, and health checks. |

Memory lives as plain `.md` files you can read, grep, and git. SQLite and ChromaDB are derived indexes; they can be rebuilt from markdown.
