# kage — Session Handoff
*Date: 2026-05-24*
*Purpose: Context continuity file. Upload at start of next Claude / Claude Code session to resume instantly.*

---

## Session Summary

This session was primarily a brainstorming and parking session — no Stage 0 layers were designed. All ideas below are parked for future phases. Stage 0 blueprint work (Layer 3c onward) resumes next session.

---

## Current Stage 0 Status

| Layer | Status |
|---|---|
| Layer 3a — Active Context Detection | Locked |
| Layer 3b — Partition Filter | Locked |
| Layer 3c — Hybrid Retrieval | PROPOSED — needs Cosmos research to lock |
| Layer 3d — Tiered Assembly | Not yet designed |
| Layer 3e — Privacy / Disclosure | Not yet designed |
| Layer 4 — Multi-Vendor Router | Not yet designed |
| Layer 5 — Memory Storage | Not yet designed |
| Layer 6 — Learning | Not yet designed |
| Layer 7 — MCP Server Out | Not yet designed |
| Layer 1 — Trigger / Interface detail | Not yet designed |
| Layer 2 — Helper Agents detail | Not yet designed |

**Resume point:** Layer 3c — bring Cosmos research results, reconcile against PROPOSED shape, lock it, then move to Layer 3d.

---

## Operating Rules — Reinforced This Session

- **Human review required before any file edit, markdown update, commit, or code change.** Claude suggests only, never executes.
- **Context window discipline:** generate a handoff markdown at 60-65% context usage. Never let a session close without capturing decisions.
- Each future thread should stay within 65-70% context limit. A smaller standing context file will be maintained in the Claude project to enforce this.

---

## New Design Principle Established

**Correction-Driven Personalization**

Every place the user overrides the system is a data point. kage should watch for overrides passively and learn from them — not from explicit configuration. Applies across: voice STT, email triage, calendar suggestions, memory tagging, briefing consumption patterns. No hardcoding. No explicit rule definition. The system learns from what the user *does*, not what the user *tells it*.

This should be added to the North Star section of `docs/blueprint.md` as a standing design principle.

---

## Parked Ideas — Voice / STT / TTS Phase

*Do not implement until kage reaches the voice design phase.*

### Personal STT Correction Learner
- Monitor agent (or lightweight companion) watches for STT output vs. manual correction delta
- Logs correction pairs: e.g. `car guy → kage`, `clause → Claude`, `cart gate → kage`
- Phase 1: personal correction dictionary — simple substitution layer on top of any STT engine
- Phase 2: Whisper fine-tune on local M5 Pro using accumulated correction corpus
- Phase 3: continuous learning — every new correction improves it
- NativeOpenHands screen observation is the natural capture mechanism
- Standalone buildable component — fits building blocks philosophy
- Potentially publishable independently

### Artificial Lung Capacity Module
- Standalone research project first, integrate into kage voice / TTS layer later
- A time-varying lung-state that constrains where emphasis occurs, how strong it can be, when sentences must end
- Modulates TTS the way real respiratory physiology modulates human speech
- **Repositioned as Claude Code learning project** — use this as the teaching vehicle for learning Claude Code workflows. Real problem, bounded scope, publishable output.
- Full prior research documented in: `Tell_me_something__How_does_an_AI_at_itsspeak_mimi.md`
- Integration target: kage voice layer TTS engine
- Makes kage's voice output more physiologically coherent than any other personal AI system

### Voice Phase Parked Items (Existing + New)
- Voice output engine — decide after Antigravity setup
- isair/jarvis vs OpenJarvis voice layer comparison
- Morning briefing opening line style
- Personal STT correction learner (above)
- Artificial lung capacity module (above)

---

## Parked Ideas — Intelligence / Routing Phase

*Do not implement until Stage 0 is complete and test infrastructure is designed.*

### Consequence-Aware Model Routing
**The novel claim:** Model selection determined by failure cost profile of each agent role — not task complexity or performance benchmarks.

- Monitor → `best_available` (cloud) — failure cost high, missed email unrecoverable
- Executor → `local_preferred` — failure cost medium, confirmation gate catches mistakes
- Librarian → `adaptive` — low stakes, local for routine, cloud for synthesis
- Bridge → `best_available` (cloud) — critical path

**Prior art landscape (honest assessment):**
- Skill-level routing EXISTS — SkillOrchestra (Salesforce + UW-Madison, Feb 2026)
- Self-modifying skill files EXISTS — Memento-Skills (April 2026), Skill Evolver
- Per-skill model declaration EXISTS — Hermes Agent GitHub issue #5508 (April 2026)
- **Failure-cost as primary routing signal — NOT FOUND in any system**
- **Consequence-aware assignment for personal AI agent roles — NOT FOUND**

**The defensible novel claim:** Consequence-aware model assignment where routing is determined by failure cost profile of each agent role, combined with a learning meta-agent that adjusts both skill content and model assignments based on observed failure consequences.

**Implementation plan (post Stage 0):**
- Stub in `config.toml` — inert at runtime, documents intent
- Test harness logs from day one: agent, model, outcome, correction applied
- Month 1: observe with threshold routing, log everything
- Month 2: manually apply failure-cost profiles to subset, compare outcomes
- Result: real 60-day personal usage dataset — stronger than any synthetic benchmark
- Target: arXiv preprint to establish timestamped prior art

**Status:** Parked. Revisit immediately after all 9 layers of Stage 0 are locked.

---

## Parked Ideas — Infrastructure Phase

### Overnight Automated Test Runner
- MacBook stays open on charge, scheduled jobs fire at night
- Results waiting in morning briefing for review
- No autonomous corrections — suggest only, human approves
- Applies to: lung capacity module testing, routing test harness, STT correction learner
- Design when kage test infrastructure phase begins

---

## Parked Ideas — Product Philosophy

### Building Blocks Architecture (2-Year Horizon)
- kage is the chassis. Each capability is a standalone component, perfected in isolation, then integrated.
- Components: routing, memory, voice, learning, context detection, STT correction, lung capacity
- Each component = its own Shape Up cycle, potentially its own repo, potentially its own paper
- Consequence-aware routing is one such standalone component — build it, test it, prove it, then integrate
- Add to North Star section of `docs/blueprint.md`

---

## Memory / Context Architecture — Decisions

### Librarian Owns Canonical Context
- `~/.kage/context/kage-master-context.md` is single source of truth
- Claude is always a reader, never the owner
- Librarian agent actively maintains the file after every planning session
- Solves the 28-day Claude memory cycle problem entirely
- Already noted in `kage-master-context.md` — reinforced this session

### Local Model Handles Simple Context Queries
- Long context file reads for simple factual retrieval → Qwen3 14B local, not Claude
- Claude is used for planning, reasoning, brainstorming only
- This is the routing intelligence goal — system decides which model is sufficient
- At launch: manual / threshold routing
- Post-deployment: learned router calibrated from real usage data

---

## Next Session Instructions

1. Open `docs/blueprint.md` — confirm full context loads
2. Run Cosmos research on the 6 pending questions (see blueprint Section 8)
3. Bring results back and reconcile against Layer 3c PROPOSED shape
4. Lock Layer 3c
5. Write ADR for ingest pipeline decision
6. Begin Layer 3d — Tiered Assembly design
7. Continue layer by layer until all 9 layers locked
8. **Only after Stage 0 complete:** revisit consequence-aware routing test harness design

---

*Session closed: 2026-05-24*
*Next session: Resume at Layer 3c lock — Cosmos results required*
*Context discipline: generate new handoff at 65% context usage*
