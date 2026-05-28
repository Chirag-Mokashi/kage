# kage — Mobile Brainstorm Notes
*Date: 25 May 2026*
*Status: RAW IDEAS ONLY — not locked, not decided*
*Purpose: Input material for main desktop brainstorming session with Cosmos search*
*Do not treat anything here as final. Every point is a question to explore.*

---

## How to Use This File

These are unrefined ideas captured during a mobile session.
Before any of these become decisions, they need:
- A full desktop brainstorming session
- Cosmos research validation where indicated
- Discussion with a stronger model
- Cross-checking against existing blueprint layers

---

## 1 · North Star — To Be Defined More Rigorously

- Goal: build something that makes a mark as an engineer
- Not consumer UX — engineering quality is the credential
- Engineers appreciate clean architecture, honest ADRs, novel ideas executed correctly
- Builders who look at kage and say "I want to extend this" — that is the target audience
- The 2-D partition matrix (project × identity) is the engineering credential — explore how to communicate this
- **Questions to brainstorm:**
  - What does "making a mark" look like concretely at end of two months?
  - GitHub repo? Blog post? Demo? Conference submission?
  - How do you write about kage so engineers immediately understand the novel idea?

---

## 2 · kage as Vendor-Agnostic AI Mediator

- Core problem to solve: cognitive overhead of managing an AI stack
- User expresses intent — kage decides which model handles it
- Model selection is kage's job, never the user's
- When a better model ships, kage evaluates, tests, slots it in automatically
- User finds out in morning briefing — one line — done
- Local models when sufficient, cloud when necessary — automatic
- **Questions to brainstorm:**
  - What signals does kage use to decide local vs cloud? (latency, confidence, task type, cost)
  - How does kage evaluate a newly released model without user involvement?
  - What does the uniform model interface look like in config.toml?
  - How does kage handle a model going down mid-task?
  - Cosmos search: what is the current state of automatic model routing in 2026?

---

## 3 · The Dreaming / Overnight Consolidation Pass

- Concept: kage runs a consolidation cycle while user sleeps
- Reviews day's interactions, identifies candidate memories
- Verifies each candidate using external tools (Cosmos, web search) before promoting
- Principle: incomplete information is more dangerous than no information
- Nothing gets written to long-term memory unless verified and complete
- Unverifiable information flagged, not stored
- Contradictions with existing memory surfaced explicitly
- User wakes up to morning briefing with proposed memories — confirms or discards
- Nothing written autonomously — kage proposes, user approves
- **Questions to brainstorm:**
  - What tools does kage have access to during overnight pass?
  - What does "verified" mean exactly — web search confirmation? Cross-source agreement?
  - How does kage handle research topics that are genuinely ambiguous or contested?
  - What format does the morning briefing use to present candidate memories?
  - How many candidates is too many to review in a morning briefing?
  - Cosmos search: Active Dreaming Memory (ADM) paper — read in full before session
  - Cosmos search: Sleep-Consolidated Memory (SCM) paper — read in full before session

---

## 4 · Multi-Device Architecture — M5 Pro + VivoBook

- M5 Pro: primary brain — reasoning, planning, user interaction — active during day
- VivoBook: overnight worker — dreaming pass, verification, Cosmos research
- M5 Pro hands off to VivoBook at night, preserves battery lifespan
- VivoBook returns results to M5 Pro at morning wake
- kage should be able to use VivoBook however it needs — full capability access
- **Questions to brainstorm:**
  - What are the VivoBook's actual specs? Can it run local models?
  - If VivoBook can't run Qwen3 14B — does overnight pass use cloud only? Cost implications?
  - What is the handoff protocol? How does M5 Pro know VivoBook finished?
  - What happens if VivoBook fails overnight — graceful degradation plan?
  - Does VivoBook need kage installed fully or just a lightweight worker node?
  - How does this connect to the Zyre/Pyre device discovery layer already in blueprint?
  - Cosmos search: current best practice for local network multi-device AI workload distribution

---

## 5 · soul.md — To Be Written on Desktop

- Concept locked but content NOT decided — needs full brainstorm session
- kage's personality, tone, communication style, behavioral rules
- **Points to brainstorm in desktop session:**
  - How does kage address the user? (name, no name, neutral?)
  - Tone during okiro morning briefing vs urgent alert vs casual query vs planning session
  - How does kage express uncertainty without being annoying?
  - How does kage present options vs make recommendations?
  - What does kage say on first boot — the blank slate moment?
  - What does kage say when it cannot do something?
  - Reference: TARS honesty model — how to implement without being cold
  - Reference: Clawdbot/Claudette soul.md pattern — read before writing kage's version
  - Should kage have a name it uses for itself or just respond as kage?

---

## 6 · Phased Learning Model

- Phase 1: user teaches explicitly — corrections, confirmations, manual input
- Phase 2: kage infers patterns from behavior — stops asking, starts predicting
- Phase 3: self-improvement — refines predictions over time without explicit teaching
- Transition from Phase 1 to 2 needs a confidence threshold — "seen this 10 times, treating as rule — confirm?"
- Nothing graduates from observed to learned without user confirmation (existing principle)
- **Questions to brainstorm:**
  - What is the right threshold for Phase 1 → Phase 2 transition?
  - How does kage surface a learned rule for confirmation without interrupting flow?
  - What happens when a learned rule turns out to be wrong — how does kage unlearn?
  - Phase 3 (LoRA fine-tuning on personal traces) — realistic timeline? Research territory?
  - How does the Librarian agent's "taste capture" role connect to this learning pipeline?
  - Cosmos search: current state of personalized fine-tuning on consumer hardware 2026

---

## 7 · The Verification Principle

- Principle to potentially lock: incomplete information is more dangerous than no information
- Research before acting — kage should not act on unverified data
- Tools available for verification: Cosmos, web search, cross-source checking
- Applies to: memory consolidation, routing decisions, morning briefing content
- **Questions to brainstorm:**
  - How does this principle interact with speed? Some tasks need fast answers, not researched ones
  - Is verification always required or only for long-term memory writes?
  - How does kage signal to user that something is unverified vs verified?
  - What sources count as "verified"? Single source? Multiple? Peer-reviewed only for research topics?

---

## 8 · Engineering Credential Strategy

- Target audience: engineers, not consumers
- What engineers appreciate: clean architecture, honest ADRs, novel ideas executed well, readable codebase
- The novel idea to communicate: 2-D partition matrix + vendor-agnostic routing as one system
- **Questions to brainstorm:**
  - Write-up strategy: blog post, README, or arXiv preprint?
  - Which part of kage is most publishable — the partition matrix? The consequence-aware routing?
  - How to document kage so an engineer can understand the architecture in 10 minutes?
  - Open source strategy: what to publish, what to keep private?
  - Timeline: when in the two-month build does documentation happen?

---

## 9 · Reference Material to Read Before Desktop Session

Papers identified as relevant — read these before the Cosmos session:

- **Active Dreaming Memory (ADM)** — counterfactual verification, dual-store memory, 83% success rate
- **Sleep-Consolidated Memory (SCM)** — multi-stage sleep cycle, dreaming pass, importance scoring
- **Breathing and Speech Planning (KTH)** — for Artificial Lung Capacity project
- **Speech Breathing in Virtual Humans (USC/Aston)** — capacitylung parameter implementation

Repos to clone before desktop session:

- Stanford OpenJarvis — fork substrate
- nazirlouis/ada_v2 — mDNS discovery, Socket.IO pattern
- FatihMakes/Mark-XXXIX — actions/ folder structure (reference only, CC BY-NC)
- LiveKit Agents — voice pipeline framework

---

## 10 · Cosmos Research Queue for Desktop Session

Run these before locking any decisions:

**Highest priority:**
- Personal AI memory layer benchmarks 2025-2026 — does graph retrieval beat hybrid at personal scale?
- LLM dreaming / autonomous memory consolidation — current production implementations
- Multi-device local AI workload distribution — current best practice
- Vendor-agnostic model routing — what exists, what is novel about kage's approach

**Medium priority:**
- Active Dreaming Memory and SCM papers — full read
- Zyre/Pyre current maintenance status
- MQTT vs alternatives for local personal AI 2026
- LiveKit current status — still best local voice pipeline?

**Lower priority:**
- LoRA fine-tuning on Apple Silicon M5 Pro — feasibility and cost
- Consequence-aware model routing — prior art landscape

---

*Session: Mobile, 25 May 2026*
*Next action: Open desktop, read this file alongside blueprint.md, run Cosmos searches, begin formal brainstorm session*
*Nothing in this file is decided. Everything is a question.*
