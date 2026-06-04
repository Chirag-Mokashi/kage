# CLAUDE.md — kage

*Entry point for any Claude Code session in this repo. Lightweight orientation only — the canonical planning state lives in [docs/blueprint.md](docs/blueprint.md).*

*Last updated: 2026-06-04 (Session 14)*

---

## Who I Am

- **Name:** Chirag Mokashi
- **Program:** Northeastern University — Masters in Applied AI
- **Hardware:** MacBook Pro M5 Pro, 24GB unified memory
- **GitHub:** Chirag-Mokashi
- **Email:** mokashi.ch@northeastern.edu

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

## Current Stage

**Stage 0 (blueprinting)** — designing the system layer-by-layer. No code yet.

Stage 1 (implementation) begins only when the Stage 0 blueprint is locked end-to-end and a Cycle 1 pitch is written.

Progress: Layers 1 (designed), 2 (arch), 3a–3e, 4, 5 locked. Substrate = Odysseus (extend, own repo). Remaining: Layer 6 (Learning), Layer 7 (MCP-out), Layer 2 detail + the Cycle 1 pitch.

## Canonical Docs (where the real planning lives)

| File | What it is |
|---|---|
| [docs/blueprint.md](docs/blueprint.md) | **Read this for substantive context.** The detailed planning state. North Star, 7-layer architecture, locked decisions, session log, all open questions. Self-contained. |
| [docs/cycle-1-pitch.md](docs/cycle-1-pitch.md) | **The live Cycle 1** — v0.1 thin-slice pitch (what we build first). |
| [docs/architecture.md](docs/architecture.md) | ⚠️ LEGACY (Session 1) — superseded by blueprint.md §4 (Odysseus substrate). See banner in file. |
| [docs/ROADMAP.md](docs/ROADMAP.md) | ⚠️ LEGACY (Session 1) — superseded by cycle-1-pitch.md + blueprint.md. See banner in file. |
| [docs/competitor-flowcharts.md](docs/competitor-flowcharts.md) | Engine-level comparisons with prior art |

For a fresh Claude session: **start by reading docs/blueprint.md.** It contains the current state of everything.

## Strategic Anchors (stable across sessions)

- **Build approach:** EXTEND PewDiePie's Odysseus (MIT) as the substrate, in kage's OWN repo (NOT a fork). kage = the headless broker layer above it. (OpenJarvis retired as substrate Session 13; kept only as a design reference.)
- **Dual goal:** Ship kage AND learn industry SDLC by mimicking real-team practice.
- **SDLC starter pack:** Shape Up cycles · GitHub Flow · ADRs · Conventional Commits · README/ROADMAP/CHANGELOG · GitHub Actions CI · pre-commit · semver.
- **Local stack:** Qwen3 14B Q4_K_M via Ollama (direct), Docker sandbox, ChromaDB vector index (derived — markdown files are the memory source of truth).
- **Cloud relationships:** Claude (reasoning), Perplexity (research), Gemini (Workspace), Cosmos (deep research). (Antigravity rejected as substrate #26 — optional client only.)
- **Repo:** github.com/Chirag-Mokashi/kage — kage's OWN repo (live on GitHub); extends Odysseus (MIT), not a fork.

## Operating Rules

- **Suggest, don't execute.** Chirag approves and runs everything. Never act autonomously.
- **All write actions require explicit user confirmation** (every agent, every flow).
- **When a decision needs to be made — stop, discuss, decide together.**
- **Stay at Stage 0 altitude** until blueprint is locked. Conceptual decisions only; defer engineering specifics to Stage 1.
- **No Mermaid in new docs** — ASCII / Unicode box-drawing characters only (renderer-independent).
- **Bold recommendation first.** Lead with the conclusion + argument. Never bury opinion at the end. Save neutral menus for true value-driven choices.
- **Complete over fast.** Stage 0 has no time pressure. The original 3-week build plan is deprioritized. Real goal: become a better AI engineer through depth. **Push back if Chirag is rushing.**
- **Awareness over control.** When designing UX or routing, the user is *aware* of what's running but does NOT have to steer it. Status is a transparency layer, not a control surface.
- **Options over suggestions.** Wherever a decision is presented, surface options explicitly. Don't make silent choices.
- **Memory auto-loads** across sessions (see `~/.claude/projects/-Users-mokashi-Projects-kage/memory/`) — durable preferences and project state persist there.

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
