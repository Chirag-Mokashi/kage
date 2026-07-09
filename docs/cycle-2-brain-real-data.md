# Cycle 2 Pitch — kage v0.2 (the brain + real data)

> **Status:** SHIPPED v0.2 (`1f35365`). Original pitch — appetite ~1 cycle.
> *Date: 2026-06-05.* Companion: [cycle-1-thin-slice.md](cycle-1-thin-slice.md) (shipped v0.1) · [blueprint.md](blueprint.md).

---

## Problem

v0.1 is a cabinet you fill by hand. It isn't *usable* — or honestly *testable* — until two things are true: it holds **real info**, and it can **do something with it**. Right now "testing" is taking a note out of the drawer and putting it back. Cycle 2 makes kage a thing you actually open: it **answers**, using **your** context.

## Foundations check (rests on stable decisions?)

Builds only on locked pieces: v0.1 (`recall`/FTS5, `remember`, markdown SoT #70, SQLite #71) + #1 (Qwen3-14B via Ollama) + #89 (kage talks to Ollama directly). Nothing here depends on deferred/volatile layers. ✓

## Solution

- **`kage ask "<question>" [-p project] [--cloud]`** — recall the relevant notes (reuse `recall`'s search) → assemble a prompt (system + your context + question) → send to **local Qwen3 via Ollama** → stream the answer. `--cloud` sends to **Claude** (Anthropic API, `ANTHROPIC_API_KEY`) instead, for Opus-quality when you want it. This is the unlock: testing becomes *"ask a real question, judge the answer,"* not round-tripping the drawer.
- **`kage import <folder> [-p project]`** — bulk-add `.md`/`.txt` files from a folder *you choose*: each file → one memory (project from `-p` or the folder name). Curated by *which folder you point at* (honors the wall's spirit — your selection — just batched). `--dry-run` previews first.
- **`doctor` + `status`** — the queued Ollama check lands now that the model exists: `doctor` verifies Ollama is reachable + the model is pulled; `status` shows the configured model. (Per the status-vs-doctor convention.)

## What's IN
local `ask` (Ollama) · `--cloud` to Claude · `import <folder>` (+`--dry-run`) · doctor Ollama check + status model line · config gains model + endpoint.

## NOT in v0.2 (deferred)
- **Smart auto-routing** (local-vs-cloud *decision*) — Layer 4, later. `--cloud` is a **manual** switch, not routing.
- **Selective disclosure (3e)** — `--cloud` sends full context to Anthropic (same as pasting into Claude today). The privacy gate is a later cycle.
- Semantic search · identity dimension · Mac control · multi-turn/REPL · "sync my Claude history" (no API + it's the firehose anti-pattern #31).

## Setup you'll do (like uv)
Install Ollama and pull the model: `ollama pull qwen3:14b` (or chosen tag). kage talks to it at `localhost:11434`. ~10 GB on your 24 GB M5 — fits.

## Rabbit holes to avoid
- Don't build routing — `--cloud` is a dumb manual flag.
- Don't build a REPL / multi-turn — `ask` is one-shot for v0.2.
- Don't over-engineer the prompt — a simple "here's my context, here's my question" template.
- **`--cloud` is the one cuttable piece** if the cycle runs long: local `ask` + `import` are the core.

## Done when
You `kage import` a folder of your real notes, then `kage ask` real questions and get useful, context-aware answers — and you reach for kage instead of pasting into Claude. Judge it honestly: local vs `--cloud` quality (that data informs the *next* cycle: is routing worth building?).

## Honest expectation
Local Qwen3-14B is **not** Opus (#68). It'll be a useful, private, context-aware helper for everyday things; for hard reasoning, `--cloud`. The *automatic* "use the right one" is Layer-4 routing — a later cycle, earned by this cycle's usage data.
