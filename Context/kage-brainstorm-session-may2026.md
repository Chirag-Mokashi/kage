# kage — Brainstorm Session
*Mobile session — May 2026*
*To be refined by a stronger model before merging into blueprint.md*

---

## Purpose of This Document

This file captures a raw mobile brainstorm session. It does not replace or edit the existing blueprint. It is an additive layer — new directions, new principles, new decisions — to be reviewed, refined, and merged into the canonical blueprint in a future session.

---

## North Star — Refined

**The word is: Seamless.**

kage should make life measurably better without you noticing it doing so. The only hard problem is adoption. Once activated, everything else runs invisibly.

The goal is not productivity for its own sake. The goal is: earn well, stay sharp in AI engineering, have enough freedom and money to live exactly how you want. kage is the discipline layer that compensates for a naturally pleasure-driven, hedonistic personality — it works so you don't have to be a different person.

> "I shouldn't notice it making valuable contributions, but the point is that it is. The only fact is the point where I activate it in my life — that should be my goal."

**Adoption is the product problem. Everything else is engineering.**

---

## Core Characteristics (One-Word)

- **Seamless** — you don't notice it working, but it is
- **Transparent** — everything accessible, no black boxes, ever
- **Aware** — you always know what is running
- **Local** — local-first, always
- **Silent** — no noise, no interruptions unless necessary
- **Broker** — connects your AI stack, owns nothing itself
- **Adoptable** — frictionless to activate, or it never gets used
- **Controlled** — you own every decision point
- **Invisible** — ambient, not in your face
- **Modular** — built in pieces, understood in pieces

These characteristics should be defined and locked before Stage 1 begins.

---

## New Design Principles (Locked This Session)

### 1. Transparency as a Core Characteristic
Everything kage does is accessible — logs, agent decisions, routing choices, what was read, what was stored. No black boxes. You don't have to look at it daily, but if you ever ask "what did kage do today?" the full answer is there with no restrictions.

### 2. Awareness Over Control
You do not need to manually switch models or control routing. kage routes intelligently. But you are always aware of what is running — local or cloud, which model, what it is doing. The status display is a transparency layer, not a control surface.

> "A human likes to be aware of what he is using."

### 3. Options Over Suggestions — Everywhere
Wherever kage presents a decision, it presents options. It does not assume. It does not make choices silently. Human preference for awareness and choice is baked into every interaction layer.

### 4. Build for Now, Architect for 3 Years Out
Hardware limitations today are not permanent. Moore's Law equivalent for AI silicon (Apple NPU, custom inference chips) means what requires cloud fallback today runs locally in 2-3 years. Architectural decisions should remain valid as compute gets 4x cheaper. Local-first gets stronger over time, not weaker.

### 5. Complete Over Fast
**The 3-week build plan is too aggressive and is hereby deprioritized.**
kage will be built completely and correctly, however long that takes. The goal is not to ship fast. The goal is to understand every layer deeply — because the real objective is becoming a better AI engineer through the process of building it.

> "Always push back if I am rushing. Tell me to take my time."

### 6. Bold Recommendation First
In all planning sessions — lead with the bold recommendation, then reasoning. Never bury the conclusion at the end.

---

## New Technical Decisions (This Session)

### Antigravity 2.0 as Build Harness
**Use Antigravity 2.0 as the agent orchestration layer for Stage 1** instead of building the agent harness from scratch. AGENTS.md and SKILL.md pattern means agents can be defined in markdown. This is a meaningful simplification to the existing plan.

### Antigravity Version Check — Manual, Outside kage
When switching to desktop, the Antigravity version check is done **manually by the user**. kage is not involved in this — it does not trigger it, log it, or automate it in any way. Completely outside kage's scope.

### App Launch as a Native Capability
kage can launch and interact with **any application on the Mac** — not hardcoded to Antigravity or any specific app. General capability. This is a system-level skill kage should develop early.

### Learning From Google Tools
kage should observe and learn from whatever Google tools are actively in use — Spark, Antigravity, Workspace. Not by watching the screen, but by reading what those tools are doing and logging it. Two things happen simultaneously: kage gets smarter about patterns and preferences, and the user stays current with the latest Google stack. The learning and the tool adoption are the same motion.

---

## Google I/O 2026 — Relevant Announcements for kage

### Immediately Actionable
- **Antigravity 2.0 + CLI** — available now. Use as build harness. AGENTS.md/SKILL.md agent definition pattern replaces custom orchestration code.
- **Gemini CLI → Antigravity CLI migration** — deadline June 18, 2026. If Gemini CLI is anywhere in the stack, migrate now.
- **Managed Agents API** — single API call spins up a fully provisioned agent with remote sandbox. Useful for cloud-side execution without infra setup.

### Watch Closely
- **MCP is now a distribution standard** — any tool that speaks MCP is visible to Gemini Spark's routing. kage's MCP server (Layer 7) is now more important, not less.
- **Android AppFunctions** — official Android API for apps to expose capabilities to agents. Relevant when kage expands to mobile.
- **WebMCP** — MCP extended to the browser layer. Origin trial in Chrome 149. Future integration point.

### Competitive Context
- **Gemini Spark** — cloud-only, Google Workspace-only, no local model, no identity partitioning. kage's local-first + 2-D partition matrix moat holds completely.
- **Android Halo** — agent status indicator in Android 17 status bar. Potential v2 mobile transparency layer. Watch for third-party API access before building custom.

---

## Blueprint Status (As of This Session)

```
Layer 3a + 3b     ✅ locked
Layer 3c          ⏳ designed, not locked — 3 open decisions remain
Layer 3d, 3e      ✖ not designed
Layer 4, 5, 6, 7  ✖ not designed
Layer 1, 2 detail ✖ deferred
Cycle 1 pitch     ✖ not written
Stage 1 (build)   ✖ has not started — should not start yet
```

**Do not start Stage 1 until the full blueprint is locked.** Approximately 4-5 design sessions remain before the blueprint is complete enough to begin building.

---

## Open Items — To Resolve in Next Session

1. Lock Layer 3c — resolve RRF vs other fusion methods, cross-encoder model selection, whether re-ranker is in v1.0 or v1.5
2. Begin Layer 3d — Tiered Assembly design
3. Define the full characteristics list formally and lock it
4. Define what kage specifically observes from Google tools (Spark, Antigravity, Workspace) and how it logs that
5. Revisit the confidence threshold routing (0.60) in light of the awareness-over-control principle — routing can stay automatic but must always be visible

---

*Session closed. To resume: read blueprint.md first, then this file. All decisions here are additive — nothing in blueprint.md has been changed.*
