# kage — Session Decisions & Vision Principles
*Mobile brainstorm session — 24 May 2026*
*Upload to Claude Project knowledge base alongside blueprint.md*
*Status: Decisions locked. Vision principles captured. Philosophy NOT yet explored — see kage-philosophy-pending.md*

---

## Context of This Session

This session was conducted on mobile before returning to laptop for layer-by-layer blueprint completion. Purpose was high-level vision clarification, strategic thinking, and locking principles that inform every remaining layer design. No code written. No layers formally locked. Principles established that must inform all subsequent sessions.

---

## Why kage — The Name Decision — Locked

kage means shadow in Japanese.

The name was not chosen for aesthetics. It was chosen because shadow is the most accurate description of what the system does.

A shadow is not a copy. It is not a lesser version. It is the part of you that covers everything you cannot be simultaneously. It moves when you move. It exists because you exist. It goes where your attention is not.

More precisely — kage is the alternate personality of the user. The user is the human self — hedonistic, creative, social, present in the moment. kage is the disciplined self — the one that handles every essential activity a person is supposed to diligently maintain but often does not. Organization, follow-through, awareness, memory, research, monitoring.

The shadow does not replace the person. It covers what the person cannot cover alone.

That is what the name means. That is what the system must be.

---

## What kage Is — Locked Framing

**kage is a complement.**

Not a proxy. Not an assistant. Not an aspirational version of you.

The part of you that you are not — diligent, organized, persistent, tireless — running quietly so the part of you that you are — curious, creative, social, intelligent — can operate without friction or guilt.

Two personalities. One life. Complementary, not competitive.

**The product is invisible diligence.** The user should not feel managed. Things should simply work out. Effortlessly effective without trying harder.

---

## The Privacy Goal — Locked

kage exists in part because every major AI company runs on the same model: your data improves their model, their product captures more of your data. That loop is the product.

kage opts out of that loop entirely.

- All memory and context stays local on M5 Pro
- Nothing leaves unless explicitly routed by user
- Especially important for original research and early-stage ideas
- Local-first is not just a design choice — it is a deliberate stance

**Risk to be aware of:** The window to build local-first alternatives is approximately 18-36 months before platform-native AI (Apple, Google, Microsoft) becomes sticky enough to remove the felt need for kage among general users. Building now is time-sensitive for this reason.

---

## The Free Tools Philosophy — Locked

Do not build what already exists for free. Exploit the open source landscape aggressively.

- Study and steal patterns from everything available
- OpenJarvis fork already executes this correctly
- Mem0, LightRAG, Cognee — open source, study deeply
- r/LocalLLaMA, Hugging Face papers, LangChain blog — free signal sources
- Philosophy: listen to a hundred, act on what you think is best

The goal is not originality for its own sake. The goal is effectiveness.

---

## Build Sequence Decision — Locked

**Complete all layers in Stage 0 blueprint before any Stage 1 implementation begins.**

Only when the blueprint is fully locked does build begin. This session confirmed that decision stands.

Remaining layers to design on laptop:
- 3c — Hybrid retrieval (PROPOSED, needs locking)
- 3d — Tiered assembly
- 3e — Privacy and disclosure
- 4 — Multi-vendor router
- 5 — Memory storage
- 6 — Learning T1
- 7 — MCP server out
- Layer 1 and 2 detail

---

## Deployment Philosophy — Locked

**Basic elements first. Additional features strictly later.**

Essential at launch — without these the whole system fails:
- Local model running and routing correctly
- Memory storing and retrieving accurately
- Identity and project partition walls working
- MCP connections live (Gmail, Calendar, Notion)
- okiro trigger firing full sequence

Additional features — strictly deferred:
- Voice integration
- Agent creation tools
- Morning briefing full build
- Übersicht HUD
- Advanced learning layers

**Target: four weeks to a living, breathing system that starts understanding from day one.**

---

## The Blank Slate Boot Principle — Locked

kage initiates knowing nothing.

No assumed preferences. No presumed patterns. No pre-loaded judgments about the user.

It boots like a child newly arrived in the world — aware it knows very little, curious, asking before assuming.

The moment it assumes, it begins being wrong in ways that are hard to correct. The humility of the blank slate is the feature, not a limitation.

---

## The Adaptation Principle — Locked

kage does not break when the environment changes. It adapts.

At three levels:
- **Tools** — new APIs, models, capabilities appear. kage notices, evaluates, surfaces suggestion.
- **User** — preferences shift over time. kage tracks drift and adjusts without being told.
- **World** — landscape of what is possible changes. kage stays current so user does not have to.

New things do not break it. New things interest it.

Adaptation is the primary design posture toward novelty.

---

## The Confidence-Gated Learning Principle — Locked

kage observes everything. It does not act on everything.

- Below threshold — watches silently, notes, holds as hypothesis
- Above threshold — surfaces suggestion only: *"I have noticed you tend to do X. Should I treat that as a preference?"*
- User confirms — only then does it become a soft rule
- Soft rules can always be overridden without friction

**Nothing graduates from observed to learned without explicit user confirmation.**
**The system earns trust incrementally. It never assumes it.**

This principle exists because early hard-coded behaviors are the failure mode of every personal AI that starts feeling wrong over time. Gray area is intentional. Slow and accurate beats fast and wrong.

---

## The Honesty Principle — Locked

Reference: TARS from Interstellar. Honesty not as a dial — as a foundation baked in from day one.

kage reports what it actually assessed, including uncomfortable truths.
It never lets comfort override accuracy.
It does not drift toward telling you what you want to hear.
The sandbox makes honesty possible — it can try things because failure is contained.

---

## The Testing Protocol — Locked

Three to five iterative AI-driven test rounds before human review.

- Round 1 — AI generates tests based on intended behavior. Runs. Gets results.
- Round 2 — Analyzes failures. Generates sharper second set targeting weak points specifically.
- Rounds 3-5 — Each round informed by previous. Tests sharpen. Edge cases surface.

Then human review:
- Not to redo AI work
- To catch what AI systematically misses — behavioral coherence, does it feel right, does anything seem off in a way hard to articulate but obvious to someone who knows the goal
- AI covers 99%. Human catches the 1% that matters most.

Every round produces a log. What was tested, what failed, what was fixed, what was promoted. This log becomes the quality baseline for every future build cycle.

---

## The Capability Principle — Locked

Do not pre-assign capability limits before testing.

You cannot know what the real percentages are until you have seen the system run. Artificial constraints before testing are guesses dressed up as planning.

Ship at full capability within current scope. Let the testing define the actual ceiling. Constraints and calibration come after observation, not before.

---

## The Raising / Nurturing Framing — Locked

kage is not deployed. It is germinated.

Stage 0 is selecting the seed — understanding what it needs before it goes in the ground.
Stage 1 initiation is the moment of germination — first boot, first discovery, first observation logged.

From that moment it is not a finished product. It is something becoming.

You do not program preferences into it. You create conditions for the right behaviors to emerge through exposure to you. Your genuine feedback is what it grows toward.

---

## The Self-Discovery Protocol — Locked

On first boot kage should:
- Test what is actually available before assuming anything
- Self-discover connected accounts, tools, MCPs
- Run basic protocol checks silently
- Report what it found
- Never ask for something it could have checked itself

Test before asking. Failure from day one is data, not a problem.

---

## The Librarian's Real Job — Updated

Previously framed as memory maintenance. Updated framing from this session:

**The Librarian's job is taste capture.**

Not just what code was written — but what was changed, what was rejected, what was rewritten. The delta between first attempt and final version is where the user's standards live. That signal must be captured from day one.

---

## Division of Labor — Locked

| Human supplies | kage supplies |
|---|---|
| Intelligence | Diligence |
| Original ideas | Organization |
| Taste | Follow-through |
| Judgment in novel situations | Continuous awareness |
| Real relationships | Adaptation |
| Genuine curiosity | Memory |

Neither complete without the other. Together — one person operating at full capacity.

---

## Strategic Awareness — Noted

- Competitive landscape must be monitored continuously — not just at build start
- If a better free tool ships that covers something kage was going to build — use it, do not rebuild it
- The moat is the combination and the local-first stance, not any individual component
- Platform-native AI (Apple, Google, Microsoft) is the real competitive threat — not other personal AI tools
- Time window to establish kage as a working system: approximately 18-36 months

---

## What This Session Did NOT Decide

- Philosophy — not explored, not concluded. See kage-philosophy-pending.md
- Remaining blueprint layers — to be completed on laptop
- Cycle 1 pitch — after blueprint complete
- Voice output engine — parked until after Antigravity setup
- News topics for morning briefing — before first okiro run
- Morning briefing opening line — before first okiro run

---

*Session closed: 24 May 2026 — Mobile*
*Next session: Laptop — resume at Layer 3c, complete remaining layers*
*Open both this file and blueprint.md at session start*
