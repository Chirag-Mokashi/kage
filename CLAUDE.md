# CLAUDE.md — kage

*Entry point for any Claude Code session in this repo. Lightweight orientation only — the canonical planning state lives in [docs/blueprint.md](docs/blueprint.md).*

*Last updated: 2026-06-08 (implementation reality sync)*

---

## Who I Am

- **Name:** Chirag Mokashi
- **Program:** Northeastern University — Masters in Applied AI
- **Hardware:** MacBook Pro M5 Pro, 24GB unified memory
- **GitHub:** Chirag-Mokashi
- **Email:** school@example.com

## What kage Is (current framing — nested, all three true)

**kage** (Japanese — "shadow") is defined at three nested levels:

- **COMPLEMENT (identity)** — the part of me that I am not. Disciplined self complementing the hedonistic self. Two personalities, one life. Invisible diligence.
- **MEDIATOR (role)** — a second layer of myself between intent and the world. Tools and devices are arms. kage is the brain. I am the person.
- **BROKER (mechanism, v1)** — local-first personal context broker between me and my cloud AI stack. Project × identity partitioned memory. Privacy-preserving multi-vendor routing.

**One-sentence:** kage is a COMPLEMENT that takes the form of a MEDIATOR operating as a BROKER. Use whichever level fits the conversation.

**What kage is NOT:**
- Not a Claude replacement
- Not "yet another personal AI" (that workspace layer is Odysseus's job; kage is the broker above it)
- Not an aspirational version of me / a proxy / a substitute for the human self
- Not a home automation hub or device manager
- Not cloud-dependent
- Not vendor-specific

**Trigger keyword:** `okiro` (Japanese — "wake up")

## Audience (locked Session 5)

- **Primary user:** Chirag (me). Daily-driven utility.
- **Primary audience for the work** (code, docs, ADRs): engineers who'd want to read kage and extend it. Optimize for code readability, clean ADRs, modular architecture.
- **Secondary audience:** research community (for deferred paper paths).
- Reconciles Adoptable + Engineering Credential as different "adoption" surfaces.

## The 10 Core Characteristics (locked Session 4)

```
   Seamless · Transparent · Aware · Local · Silent ·
   Broker · Adoptable · Controlled · Invisible · Modular
```

Every design decision must be checked against this list. Operational definitions in `docs/blueprint.md`. The single-word North Star: **Seamless** — kage acts invisibly; the only hard problem is adoption.

## Operating Value: Jugaad (above the 10) — locked 2026-06-10

**jugaad** (जुगाड़) — kage's *spirit*, sitting above the 10 characteristics (those are system properties; this is the lens for WHAT kage reaches for). Frugal, resourceful ingenuity under constraint: extract maximum capability from what you already have; route *around* artificial constraints (paywalls, missing APIs, double-billing) using existing resources rather than paying to remove them. Canonical example: drive the subscription web UI you already pay for instead of paying again for the API.

**Guardrail (inseparable from jugaad):** jugaad governs WHAT we reach for and HOW we route around constraints — *never how we build*. The workaround is resourceful; the implementation stays clean, tested, and complete. Jugaad is resourceful in *what*; **Complete over fast** governs *how*. They check each other.

## Current State

**Working CLI exists.** The repository is no longer purely Stage 0 planning: `src/kage/cli.py` implements the headless local broker thin slice and several follow-on cycles.

Current implemented surface:
- local markdown source of truth under `~/.kage/memory`
- SQLite FTS5 index and project partition filter
- ChromaDB chunk/vector index with `kage reindex`
- `remember`, `import`, `recall`, `ask`, `list`, `forget`, `status`, `doctor`
- local Ollama answering by default
- cloud answering via named providers (`claude`, `openai`, `gemini`, `groq`, `perplexity`, plus user config)
- black-box and unit tests in `tests/test_cli.py`

The long-term blueprint still matters for direction, but docs that say "no code yet" or "Stage 1 has not started" are historical/stale unless explicitly marked current. For implementation truth, inspect `README.md`, `src/kage/cli.py`, and `tests/test_cli.py`.

## Canonical Docs (where the real planning lives)

| File | What it is |
|---|---|
| [docs/blueprint.md](docs/blueprint.md) | **Read this for strategic context.** The detailed long-term planning state. Some status language is historical; current implementation may be ahead of it. |
| [docs/cycle-1-pitch.md](docs/cycle-1-pitch.md) | Historical v0.1 thin-slice pitch. Useful for original scope, not a complete description of current code. |
| [docs/architecture.md](docs/architecture.md) | ⚠️ LEGACY (Session 1) — superseded by blueprint.md §4 (Odysseus substrate). See banner in file. |
| [docs/ROADMAP.md](docs/ROADMAP.md) | ⚠️ LEGACY (Session 1) — superseded by cycle-1-pitch.md + blueprint.md. See banner in file. |
| [docs/competitor-flowcharts.md](docs/competitor-flowcharts.md) | Engine-level comparisons with prior art |

For a fresh coding session: read `README.md`, then `src/kage/cli.py`, `tests/test_cli.py`, and `docs/blueprint.md` for strategic context.

## Strategic Anchors (stable across sessions)

- **Build approach:** EXTEND PewDiePie's Odysseus (MIT) as the substrate, in kage's OWN repo (NOT a fork). kage = the headless broker layer above it. (OpenJarvis retired as substrate Session 13; kept only as a design reference.)
- **Dual goal:** Ship kage AND learn industry SDLC by mimicking real-team practice.
- **SDLC starter pack:** Shape Up cycles · GitHub Flow · ADRs · Conventional Commits · README/ROADMAP/CHANGELOG · GitHub Actions CI · pre-commit · semver.
- **Local stack:** Qwen3 14B Q4_K_M via Ollama (direct), Docker sandbox, ChromaDB vector index (derived — markdown files are the memory source of truth).
- **Cloud relationships:** Claude (reasoning), Perplexity (research), Gemini (Workspace), Cosmos (deep research). (Antigravity rejected as substrate #26 — optional client only.)
- **Repo:** github.com/Chirag-Mokashi/kage — kage's OWN repo (live on GitHub); extends Odysseus (MIT), not a fork.

## Operating Rules

- **Default coding workflow:** inspect first, make scoped changes when asked, run relevant tests, and report clearly.
- **Suggest, don't execute.** Chirag approves and runs everything. Never act autonomously.
- **All write actions require explicit user confirmation** (every agent, every flow).
- **When a decision needs to be made — stop, discuss, decide together.**
- **Do not treat the repo as planning-only.** Implementation work is active; keep docs and code aligned.
- **No Mermaid in new docs** — ASCII / Unicode box-drawing characters only (renderer-independent).
- **Bold recommendation first.** Lead with the conclusion + argument. Never bury opinion at the end. Save neutral menus for true value-driven choices.
- **Complete over fast.** The original 3-week build plan is deprioritized. Real goal: become a better AI engineer through depth while still shipping useful slices. **Push back if Chirag is rushing.**
- **Awareness over control.** When designing UX or routing, the user is *aware* of what's running but does NOT have to steer it. Status is a transparency layer, not a control surface.
- **Options over suggestions.** Wherever a decision is presented, surface options explicitly. Don't make silent choices.
- **Memory auto-loads** across sessions (see `~/.claude/projects/-Users-mokashi-Projects-kage/memory/`) — durable preferences and project state persist there.

## Implementation Workflow (HARD GATE — never skip)

Locked 7-step split for ALL implementation work. The roles do **NOT** collapse:

- **Cloud (the session model) PLANS and REVIEWS only.**
- **Local (Qwen3 via `kage ask`) WRITES all code and tests.**
- **Local RUNS tests** (`uv run pytest` via Bash).

Per step, in order:

```
1. PLAN code     → cloud
2. WRITE code    → local (Qwen3)
3. REVIEW code   → cloud      ← NEVER skipped
4. PLAN tests    → cloud
5. WRITE tests   → local (Qwen3)
6. REVIEW tests  → cloud      ← NEVER skipped
7. RUN tests     → local
```

**THE GATE:** I never write implementation code or tests myself with Edit/Write. The instant I do, three roles collapse into one, the review step has nothing independent to check, and the learning signal is destroyed. If I catch myself about to edit `cli.py` / `test_cli.py` directly — **STOP**. That is the exact failure mode this rule exists to prevent. (Planning stays on cloud deliberately: reasoning is local's known weak class, so routing it to local produces predictable noise, not insight.)

**MISTAKE LOG (mandatory, after every step):** every cloud correction of local's output is recorded via `kage remember --project kage-corrections`, in the format:

> *"Correction log — `<feature>` Step N (date): Local made X errors: … **Pattern:** …"*

Bidirectional — log cloud-introduced bugs too. **This log is the deliverable; the code is the byproduct.** It is the Layer 6 fuel and the entire reason the split exists. See `feedback_dev_workflow.md` in memory.

## Two Handoff Modes

This file and `docs/blueprint.md` serve different purposes when handing context to another AI tool (personal Claude, Cosmos, etc.):

```
   CLAUDE.md            Lightweight orientation. Who, what, current
                        stage, pointers. Use for quick onboarding of
                        a fresh tool.

   docs/blueprint.md    Substantive brainstorm material. Full state,
                        layer designs, audits, open questions, session
                        log. Use when you want another AI to engage
                        deeply with the planning.
```

## Context Files (legacy)

The `Context/` folder contains the original master-context files from before formal planning began. Preserved for historical reference but **superseded by `docs/blueprint.md`**. Do not treat them as the source of truth.

---

*If you're a Claude session reading this: skip to `docs/blueprint.md` for the real state. This file is the front door, not the house.*
