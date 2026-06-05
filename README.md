# kage

**Local-first personal context broker** — your notes, surfaced into your cloud AI, on your machine. Nothing leaves your Mac unless you send it.

> **Status:** v0.1 (Cycle 1) — in active development. The thin slice: `remember` / `recall`, project-tagged, stored as plain markdown + SQLite, piped into your model. See [docs/cycle-1-pitch.md](docs/cycle-1-pitch.md) for scope and [docs/blueprint.md](docs/blueprint.md) for the full roadmap.

## Dev setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync            # create the venv + install kage and its deps
uv run kage init   # set up ~/.kage/ (config, memory store, index)
uv run kage --help # see all commands
```

## What it does (v0.1)

| Command | What it does |
|---|---|
| `kage init` | Scaffold `~/.kage/` — config, markdown memory store, SQLite index. Safe to re-run. |
| `kage remember "<text>" --project X` | Save a note (markdown + frontmatter), confirmed before write. |
| `kage recall "<query>" --project X` | Full-text search your notes; surface the best matches. |
| `kage status` / `kage doctor` | What's active / is everything healthy. |

Everything is local. Memory lives as plain `.md` files you can read, grep, and git.
