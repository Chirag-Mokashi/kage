# kage — Stage 0 Blueprint

> **Status:** Stage 0 (planning / blueprinting). We are NOT yet building.
> Stage 1 (implementation) starts only when this blueprint is locked end-to-end.
>
> **Purpose of this file:** Single source of truth for the kage project state.
> Open this at the start of any session to re-enter with full context.
>
> *Last updated: 2026-05-21, end of Session 1 (planning).*
>
> *Companion docs:*
> - [architecture.md](architecture.md) — visual system map
> - [ROADMAP.md](ROADMAP.md) — cycle-by-cycle execution plan
> - [competitor-flowcharts.md](competitor-flowcharts.md) — engine comparisons

---

## 1 · North Star

kage exists at three nested levels of identity. All three are true simultaneously; each answers a different question.

### Identity (WHO / WHY) — kage is a COMPLEMENT

kage is the part of you that you are not. The user is the human self — hedonistic, creative, social, present in the moment. kage is the disciplined self — organization, follow-through, awareness, memory, monitoring. **Two personalities, one life. Complementary, not competitive.**

The product is **invisible diligence**. Things simply work without you trying harder. kage does not replace the person. It covers what the person cannot cover alone.

### Role (WHAT) — kage is a MEDIATOR

kage is a **second layer of yourself** that sits between your intent and the world. You express intent naturally. kage understands that intent through context and memory. kage identifies what fulfills it — which AI tool, which device, which document — and acts on your behalf.

**The tools and devices are arms. kage is the brain. You are the person.**

### Mechanism (HOW, v1) — kage is a BROKER

kage is a **local-first personal context broker** between you and your cloud AI stack (Claude, Perplexity, Gemini, Antigravity, plus local Qwen). Memory partitions by project × identity. Queries route across vendors with selective context disclosure. Privacy preserved by design.

### One-sentence summary

> **kage is a COMPLEMENT that takes the form of a MEDIATOR operating as a BROKER.**

Use whichever level fits the conversation: complement when explaining purpose, mediator when explaining function, broker when explaining v1 mechanism.

### v1 scope (2026 ship target)

Broker-functional. Single-device M5 Pro. Text-first interaction. The COMPLEMENT and MEDIATOR identities exist conceptually in v1 but operationally constrained to what a broker can do.

### v2+ horizon (2-5 year)

Mediator extends to the full local-network device ecosystem — secondary displays, smart home devices, IoT, ambient compute. Voice as first-class input. Multi-device mesh with zero-config discovery. Truly ambient operation. The complement identity becomes fully expressed.

**This roadmap is the 2026 surface of that vision** — getting from "nothing" to a real working v1.0 that demonstrates the core thesis: *mediation through context, not device management*.

### Audience (locked Session 5, 2026-05-28)

```
   Primary USER:          Chirag (you)
                          Daily-driven utility. One-person system.
                          "Does it actually help me?"

   Primary AUDIENCE       Engineers who would read kage's code
   for the WORK:          and want to extend it.
                          "I want to fork this and make it mine."
                          Optimizes documentation, code structure,
                          ADRs, conventional commits.

   Secondary AUDIENCE:    Research community.
                          For deferred paper paths (personal-scale
                          access control instantiation, consequence-
                          aware model routing).
```

**Reconciliation with Adoptable characteristic:** *Adoptable* (locked Session 4) = Chirag adopting kage daily, frictionlessly. *Engineering credential* (Session 5) = engineers reading the code and respecting it. Different surfaces; both true simultaneously.

**What the engineering-audience lock does NOT mean:**
- NOT "kage is a product for engineers to use" — it's a product for Chirag to use, with code an engineer would respect.
- NOT "we publish a polished SDK" — premature for v1.
- NOT "we ignore daily ergonomics" — friction for Chirag still matters.

---

## 2 · What kage IS (and is not)

### kage IS

A **complement, mediator, and broker** — at three levels of abstraction.

**Complement characteristics (defining identity):**
1. **Disciplined self** — handles organization, follow-through, awareness, memory, monitoring that the user would otherwise neglect
2. **Invisible diligence** — operates without ceremony; user notices outcomes, not mechanism
3. **Complementary not competitive** — never replaces the user's intelligence, originality, or judgment; covers what the user cannot cover simultaneously

**Mediator characteristics (operational role):**
4. **Intent understanding** — interprets natural input via context and memory
5. **Context ownership** — memory lives locally, never leaves the machine wholesale
6. **Selective fulfillment** — routes intent to whatever fulfills it (tool / model / device / document) with the minimal context that fulfillment requires
7. **Silent execution** — acts without ceremony; confirms only when consent is needed

**Broker properties (v1 — single-device, text-first):**
8. Project-partitioned memory — every memory belongs to one or more projects (kage, Quantum-AI, LLM-Research, Personal, …)
9. Identity-partitioned memory — Personal accounts and NEU accounts isolated
10. 2-D partition matrix — memories live at the intersection (project × identity)
11. Dynamic context retrieval — per query: detect active project + identity, retrieve relevant slice
12. Per-query context assembly — compose context fresh per query, not pre-bundled
13. Local-first execution — all memory + retrieval + assembly happens on M5 Pro
14. Multi-vendor router — sends query + context to Qwen / Claude / Perplexity / Gemini
15. MCP server interface — Claude Code, Cursor, etc. can query kage
16. Privacy / selective-disclosure — per-tool allowlists, redaction, audit log

**v2+ properties (architecture-ready in v1, NOT v1-shipping):**
17. Voice-first interaction (LiveKit pipeline)
18. Multi-device mesh (Zyre discovery + MQTT messaging)
19. Action substrate (`actions/` layer) — smallest executable units, permission-bounded per agent
20. Device-aware intent routing — picks the device(s) that fulfill the intent
21. Overnight dreaming pass — consolidation + verification (when locked from May 25 brainstorm)

### kage IS NOT

- Not a Claude replacement
- Not yet another single-agent local AI (OpenJarvis is that)
- Not vendor-specific
- Not a chatbot
- **Not an aspirational version of you. Not a proxy. Not a substitute for the human self.**
- **Not a home automation hub or device manager.** Home Assistant manages devices. kage mediates between you and devices through intent understanding and deep personal context. Different problem.
- **Not fully ambient in v1.** v1 ships broker-functional, single-device, text-first. Ambient operation lives in v2+.

The cloud tools stay. The devices stay. kage makes them work together as arms of a single intent.

---

## 3 · The Defensible Differentiator

**Important framing (recalibrated Session 4 after Cosmos Q2 finding):** kage's defensibility lives at the **product and engineering level**, not as an academic abstraction. Bhatt et al. 2025 (Microsoft Research, arXiv:2509.14608, "Enterprise AI Must Enforce Participant-Aware Access Control") already formalizes 2-D access-control matrices as bipartite graphs over documents × entities, with biclique-based safe-sharing regions for enterprise multi-user RAG. **kage does not claim to invent that abstraction.** kage applies it to a domain — *single-user multi-identity personal AI* — that the academic literature does not yet address, with three novel engineering contributions.

**Four real differentiators (genuinely novel):**

```
   1. First-of-kind SHIPPED personal-AI with state-aware
      identity partitioning                              ★ product novelty

   2. Three-state semantics (scoped/baseline/pending)
      for project-empty memories                         ★ genuinely novel
                                                           — not in any of
                                                           the 4 academic
                                                           papers surveyed

   3. Identity-as-cluster-of-accounts (many-to-one),
      reflecting real personal-account topology
      (Personal = {chirag@, mokashi.ch@gmail},
       NEU = {mokashi.ch@neu, research-email@})         ★ genuinely novel
                                                           for personal AI

   4. Multi-modal memory layer with Confidence-Gated     ★ novel combination
      Learning, constraint encoding, and identity-         (promoted Session 7)
      aware retrieval. Composed of locked elements:
        • Five typed memory types (#46) — Core /
          Procedural / Semantic-system-of-record /
          Semantic-vocabulary / Episodic-provisional
        • Confidence-Gated Learning principle —
          observe-confirm-graduate flow
        • Constraint encoding via Consequences field
          (#48) with Reconsideration Trigger (#51)
        • Identity-aware retrieval (Layer 3b hard
          identity wall + project state-aware spillover)
        • Privacy-by-architecture (not by DP budgets)
        • Three-mode user support (#47) — pure local /
          hybrid Notion mirror / Notion-canonical
      Each element exists in some shipping system; the
      COMBINATION is absent from current personal-AI
      products (verified across Cosmos Q1-Q5, Q7, Q E v2,
      Agent OS audit, and product landscape review).
```

**Supporting differentiators (shared with prior art but absent from current personal-AI products):**

```
   4. Local-first execution + cross-tool brokering    ◐ rare combination
   5. Context engine + multi-vendor router as ONE     ◐ no shipped product
   6. Per-query dynamic context assembly              ◐ vs. static buckets
   7. Identity-aware selective disclosure             ◐ enterprise pattern
                                                        applied to personal
```

**Academic ancestry (acknowledged — to be cited in ADR at Stage 1):**

| Paper (year) | Contribution kage builds on |
|---|---|
| Bhatt et al. 2025 (Microsoft, arXiv:2509.14608) | Bipartite graph / adjacency matrix over documents × entities; biclique-based safe-sharing. Enterprise multi-user confidentiality. |
| Kumar 2026 (Silo/Pool/Bridge) | Multi-tenant RAG isolation patterns. Tenant-scoped retrieval. Identity propagation. |
| Syed et al. 2025 (Secure by Design) | RBAC/ABAC tagging + identity propagation for enterprise RAG. |
| Bassit & Boddeti — SecureRAG | FHE-based encrypted vector search + KP-ABE policy-based decryption. Cryptographic enforcement (orthogonal to kage's matrix-style partitioning). |

**Validated against May 2026 SHIPPED prior-art landscape** (Mem0, Letta, Plurality, OpenBrain, Digital Twin Playbook, OpenJarvis, Bedrock AgentCore, LangGraph, Cursor Rules, Claude Projects): no shipped personal-AI product implements the matrix at personal scale. Closest threat: **Plurality Network** (cloud broker with hand-curated buckets) — kage differentiates via local-first + state semantics + identity-as-cluster. Closest pattern: **OpenJarvis** (substrate; agents-above-memory) — kage layers partition matrix + state machine + routing on top.

**External validation (Google I/O 2026):** Gemini Spark is cloud-only, Workspace-only, no local model option, no identity-partitioning concept. Most recent enterprise entrant does not threaten the personal-scale wedge.

**Cosmos empirical retrieval validation (Session 4):** LoCoMo / LongMemEval / MemoryBench audit confirms hybrid lexical+dense+rerank > graph-only at single-user-scale, validating Layer 3c v1.0 design. SmartSearch 91.9% on LoCoMo without graph structure. Graph retrieval helps mainly on temporal/multi-hop questions (GAAMA +16.1pp on temporal). Defer-graph-to-v2 decision is empirically supported.

**Possible research-paper path (deferred to post-v1.0 ship):** The personal-scale instantiation of enterprise access-control abstractions — specifically state-aware partition semantics (`scoped`/`baseline`/`pending`) and identity-as-cluster modeling — may be publishable as a Master's-thesis-adjacent contribution. Cosmos Q2 audit shows the gap in the literature (no academic paper addresses single-user multi-identity personal AI in this framework). Worth revisiting after v1.0 ships with real usage data.

---

## Core Characteristics (locked Session 4 — 2026-05-23)

kage is defined by ten characteristics. Every layer design, UX decision, and trade-off must be checked against this list.

| # | Characteristic | Operational definition |
|---|---|---|
| 1 | **Seamless** | kage acts invisibly in the background. The user notices outcomes (recalled context, smart routing) but not the mechanism. The friction-to-value ratio approaches zero. |
| 2 | **Transparent** | Every action, decision, route, and stored item is inspectable. Logs are complete, accessible, and never hidden. "What did kage do today?" always has a full answer. |
| 3 | **Aware** | The user always knows what is running: which model, which task, local vs. cloud. Status is ambient (menu bar pill, optional HUD) but never absent. |
| 4 | **Local** | Memory, retrieval, and decision logic live on the user's hardware by default. Cloud is a deliberate, visible escalation — never a hidden default. |
| 5 | **Silent** | kage does not interrupt unless action is required from the user. Notifications are scarce, intentional, and dismissible by design. |
| 6 | **Broker** | kage owns identity, context, and memory; cloud tools own intelligence and generation. kage never duplicates what existing tools do well — it makes them work together. |
| 7 | **Adoptable** | Onboarding is frictionless and daily activation cost is near zero. If kage is hard to start using, it doesn't get used. Adoption is treated as the *only* true product problem. |
| 8 | **Controlled** | Every write action requires explicit user confirmation. Defaults bias toward caution. Reversibility (forget, retag, undo) is built in. |
| 9 | **Invisible** | UX is ambient, not foreground. kage's surface area is menu bar + inbox review + okiro trigger — never a window competing for attention. |
| 10 | **Modular** | Built layer-by-layer, understood layer-by-layer. Each layer has a clear contract, locked separately, swappable when better alternatives emerge. |

These characteristics are locked. Definitions can be sharpened but the ten-word list is fixed.

---

## Locked Principles (Session 4)

Six principles to apply at every planning altitude, alongside the SDLC starter pack:

### 1. Transparency as core characteristic
Everything kage does is accessible — logs, agent decisions, routing choices, what was read, what was stored. No black boxes. The user does not have to look at it daily, but if they ever ask "what did kage do today?" the full answer is there with no restrictions.

### 2. Awareness over control
The user does NOT manually switch models or steer routing. kage routes intelligently. But the user is always aware of what is running — local or cloud, which model, what task. The status display is a *transparency* layer, not a *control* surface. **This modifies the planned Layer 4 (multi-vendor router) UX:** the 0.60 threshold concept stands but routing always emits visible audit signals.

### 3. Options over suggestions — everywhere
Wherever kage presents a decision, it presents options. It does not assume. It does not make choices silently. Human preference for awareness and choice is baked into every interaction layer.

### 4. Build for now, architect for 3 years out
Hardware limitations today are not permanent. AI silicon (Apple NPU, custom inference chips) means what requires cloud fallback today runs locally in 2-3 years. Architectural decisions should remain valid as compute gets 4× cheaper. **Local-first gets stronger over time, not weaker** — that's the secular tailwind.

### 5. Complete over fast
The original 3-week build plan is **deprioritized**. kage will be built completely and correctly, however long it takes. The goal is not to ship fast — the goal is to understand every layer deeply, because the real objective is becoming a better AI engineer through the process of building it. **Always push back when rushing.** Stage 0 (planning) has no deadline; Stage 1 (implementation) uses Shape Up cycles but cycles are variable-scope, fixed-time, never extended for arbitrary deadlines.

### 6. Bold recommendation first
Every planning response leads with the recommendation, then the reasoning. Never bury the conclusion. This is the operating mode in this and every subsequent session.

---

## Locked Principles — Round 2 (Session 5, 2026-05-28)

Seven additional principles. All operate at the same altitude as the Session-4 Locked Principles above. Together: 13 locked principles guide every design decision.

### 7. Blank Slate Boot
At first boot, kage's **runtime** knows NOTHING. No assumed preferences, no presumed patterns, no pre-loaded judgments about the user. Memory store empty. Routing rules at defaults. Learning at zero. **Humility of the blank slate is the feature, not a limitation.** Boots like a child newly arrived in the world — aware it knows little, curious, asks before assuming. The moment kage assumes, it begins being wrong in ways hard to correct.

**Scope clarification (Session 5, Tension #4 resolution):** This principle applies to kage's *runtime* (Stage 1+), NOT to the planning AI sessions used during Stage 0 design. Planning sessions deliberately load CLAUDE.md, blueprint.md, and memory entries — that's how they do their job. kage's runtime is a different system, and a different stage. The two should not be conflated.

### 8. Adaptation
kage does not break when the environment changes. It adapts at three levels:
- **Tools** — new APIs, models, capabilities appear. kage notices, evaluates, surfaces suggestion.
- **User** — preferences shift over time. kage tracks drift and adjusts without being told.
- **World** — landscape of what is possible changes. kage stays current so user does not have to.

**New things do not break it. New things interest it.** Adaptation is the primary design posture toward novelty.

### 9. Honesty (TARS reference — Interstellar)
Honesty as foundation, not as dial. kage reports what it actually assessed, including uncomfortable truths. It never lets comfort override accuracy. It does not drift toward telling the user what they want to hear. The sandbox makes honesty possible — kage can try things because failure is contained.

### 10. Testing Protocol
Three to five iterative AI-driven test rounds before human review. Round 1 generates tests based on intended behavior. Each subsequent round is informed by previous failures, sharpening on weak points. Then human review catches the 1% AI systematically misses (behavioral coherence, "does it feel right"). Every round produces a log: what was tested, what failed, what was fixed, what was promoted. This log becomes the quality baseline for every future build cycle. **Development discipline, not runtime behavior.**

### 11. Capability
Do not pre-assign capability limits before testing. You cannot know real percentages until you have seen the system run. Artificial constraints before testing are guesses dressed up as planning. **Ship at full capability within current scope.** Let testing define the actual ceiling. Constraints and calibration come AFTER observation, not before.

**Resolution of 0.60 threshold tension** (locked Session 5):
The originally-locked "Confidence threshold for routing: 0.60" (Session 1, pre-planning notes) is rewritten under this principle:
```
   0.60 is the v1 STARTING BASELINE — a cold-start default
   for the period before usage data accrues.
   
   NOT a fixed constraint. NOT a final value.
   
   Post-launch calibration target: learned threshold per
   query type, per identity, from observed routing-outcome
   data. The default is a placeholder for the no-data period.
```
Consistent with Capability + Blank Slate Boot + Adaptation + Raising/Nurturing. Connects to deferred Consequence-Aware Routing research path.

### 12. Raising / Nurturing
kage is not deployed. It is **germinated**. Stage 0 = selecting the seed. Stage 1 initiation = the moment of germination — first boot, first discovery, first observation logged. From that moment, kage is not a finished product. **It is something becoming.** You do not program preferences into it. You create conditions for the right behaviors to emerge through exposure to you.

### 13. Self-Discovery
On first boot kage should: test what is actually available before assuming anything; self-discover connected accounts, tools, MCPs; run basic protocol checks silently; report what it found; **never ask for something it could have checked itself.** Test before asking. Failure from day one is data, not a problem.

---

## Deferred Principles (pending Layer 6 design)

### Confidence-Gated Learning — DEFERRED
*To be locked when Layer 6 (Learning) is designed.* The principle as currently articulated:
- Below threshold: kage watches silently, notes pattern as hypothesis
- Above threshold: kage surfaces suggestion ("I noticed you tend to X. Should I treat as preference?")
- User confirms → soft rule. Soft rules always override-able.
- **Nothing graduates from observed to learned without explicit user confirmation.**

**Why deferred:** Learning has accreted across 10 separate planning touchpoints (Layer 6 T1/T2/T3, Confidence-Gated Learning, Consequence-Aware Routing, Phased Learning Model, Librarian's taste capture, Personal STT Correction Learner, Overnight Dreaming Pass, Adaptation Principle, etc.). Designing the principle in isolation risks under-constraining the layer that implements it. Better to design Layer 6 first, then extract a unified learning principle that captures what we built.

Note: this principle **supersedes** the earlier "Correction-Driven Personalization" framing from the May 24 handoff doc — same idea, sharper articulation. Only the Confidence-Gated version persists.

---

## 4 · The 7-Layer Architecture (decomposed)

```
   Layer 1: TRIGGER / INTERFACE   ╳ Universal (CLI + MCP + UX)
   Layer 2: INTERNAL AGENTS       ◐ Like OJ (Librarian + Monitor opt-in)
   Layer 3a: ACTIVE CONTEXT DETECT★ UNIQUE (cascade + bootstrap)
   Layer 3b: PARTITION FILTER     ★ UNIQUE (project × identity matrix)
   Layer 3c: HYBRID RETRIEVAL     ◐ From Mem0 (vector/graph/episodic)
   Layer 3d: TIERED ASSEMBLY      ◐ From Letta (hot/recall/archival)
   Layer 3e: PRIVACY/DISCLOSURE   ◐ Strong layer; mostly emergent
   Layer 4:  MULTI-VENDOR ROUTER  ◐ Standalone tools exist; not bundled
   Layer 5:  MEMORY STORAGE       ◐ From OJ (FAISS+BM25 substrate)
   Layer 6:  LEARNING (T1)        ◐ Prompt-only first; DSPy later
   Layer 7:  MCP SERVER (out)     ╳ Standard delivery channel

   ★ unique to kage   ◐ borrowed/shared   ╳ universal
```

**Only Layers 3a and 3b are starred.** They are where engineering effort concentrates and where competitive moat lives. The rest are commodity layers wired correctly.

---

## 5 · Layer-by-Layer Status

### Layer 1 — Trigger / Interface

**Status:** Outline only.
- CLI (`kage ask`, `kage memory add`, etc.)
- MCP server (in) — for external tools to query kage
- Menu bar (Mac-native) — status display
- `okiro` keyword as wake trigger
- (Detailed design deferred to its turn)

### Layer 2 — Internal Helper Agents

**Status:** Architecture choice locked.
- **Decision:** Hybrid (Option C) — small internal helpers + external via MCP
- **Internal agents:** Librarian (memory maintenance, hourly) + Monitor (optional, opt-in observation)
- **External agents:** Claude Code, Cursor, etc. via MCP
- **Rejected alternatives:** Option A (pure broker, no proactive behavior) · Option B (full OJ-style agent system, muddies engine focus)

### Layer 3a — Active Context Detection ★

**Status:** Designed and locked. v1 scope clear.

**v1 detection logic — priority cascade (6 levels):**
For each query, kage resolves both `active_project` and `active_identity` by trying in order:
  1. Explicit flag (`--project X --identity Y`)
  2. Editor file path (`~/Projects/X/…`)
  3. Active calendar event (macOS Calendar API)
  4. Terminal cwd
  5. Sticky last-active (state, derived from prior resolution — not a signal)
  6. Fallback to "personal" identity, no project

**v1 signals (4 sources — inputs to the cascade):**
- Explicit CLI flag (user-driven)
- Editor file path (via small editor plugin)
- Active calendar event (via macOS Calendar API)
- Terminal cwd (via shell hook)

Note: Sticky last-active is **state**, not a signal — it's the previous cascade resolution carried forward. The fallback at rank 6 is the floor when no signal resolves.

**Setup / Bootstrap (first-run wizard) — aligned with Self-Discovery Principle (Locked Principle #13):**
1. Detect Google accounts on machine (Chirag has 4)
2. **Auto-suggest identity groupings from domain heuristics** (e.g., `*@neu.edu` → NEU identity; `*@gmail.com` → Personal identity). Present groupings; user confirms or reassigns. **Never ask user to assign from a blank slate** — always auto-detect first, surface findings, let user override.
3. Auto-discover projects on disk + offer pinning each project to an identity
4. Save config

**Pattern:** auto-detect → present findings → user confirms. Satisfies Self-Discovery + Blank Slate Boot + Awareness over control + Options over suggestions.

**Identity model — many-to-one:**
- An identity = logical grouping of 1+ accounts
- Personal identity ← {chirag@, mokashi.ch@gmail}
- NEU identity ← {mokashi.ch@neu, research-email@}
- Memory tagged by (project, identity); ingestion auto-resolves source → identity

**Automation Pattern A in v1:** Reactive context-switching watches the 4 signals; auto-flips active (project, identity); shows status pill.

**Automation Patterns B/C/D/E shapes (deferred to v2, but v1 design accommodates):**
- B (unified aggregation): data model uses identity_id not account_id
- C (cross-identity search): search API takes scope parameter
- D (deeper OS signals): signal sources are pluggable interface
- E (account-aware writes): all writes go through confirmation gate

**Privacy / consent framework (7 principles):**
1. Local-only, no exfiltration
2. macOS handles consent prompts (we don't reinvent them)
3. Per-signal opt-in (granular toggles in config)
4. Inspection commands (`kage signals show`, `kage state`)
5. Default minimal (only no-permission signals on by default)
6. Pause & reset commands
7. Audit log of every context-change

**Engineering details:** Deferred to Stage 1. Approximate v1 cost noted (~1 cycle for Layer 3a alone) — to be revisited at Stage 1.

### Layer 3b — Partition Filter ★ (THE WEDGE)

**Status:** Designed and locked. v1 scope clear.

**Save philosophy — wall, not firehose:**
- Default: nothing enters queryable memory unless user explicitly saves
- No background scraping in v1 (calendar/email auto-ingest = opt-in v2 only)
- Save triggers: `kage remember`, voice "okiro save that", menu bar, hotkey ⌘⇧S

**Two write flows (Flow 3 from earlier proposal deleted with wall approach):**
- **Flow 1 — Direct save (CLI / voice / menu bar):** user triggers save → suggested tags via Layer 3a → confirm/edit/discard
- **Flow 2 — Session inbox (markdown-file batch):** candidates flagged during session accumulate in `~/.kage/inbox/<date>.md` → reviewed at session end via `kage inbox review` → each item walked through with suggested tags

**Tag schema (locked):**
```
projects:    [list of project names]       can be empty
identities:  [list of identities]           must be non-empty (≥1)
state:       'scoped' | 'baseline' | 'pending'
             - defaults to 'scoped' when projects is non-empty
             - user-chosen when projects is empty
```

**Three-state semantics for project-empty memories:**

| State | Meaning | Filter behavior |
|---|---|---|
| `scoped` | project list is non-empty | returned when active project ∈ memory.projects |
| `baseline` | project-empty by design (identity-wide preference/fact) | always returned for matching identity |
| `pending` | not yet assigned to a project; in triage | never returned in queries until tagged |

**Filter logic (locked) — hard identity wall + project state-aware spillover:**
```
Given active (P, I), return memory M if:
    I ∈ M.identities                          (HARD identity wall — inviolable)
    AND (
      P ∈ M.projects                          (exact scoped match)
      OR (M.projects = [] AND M.state = baseline)  (baseline spillover)
    )

NEVER returns:
    - memories with I ∉ M.identities          (privacy)
    - pending memories                         (in triage)
    - cross-identity in v1                     (Pattern C, v2)
```

**Save-time prompt UX:**
```
"<memory text>"

Suggested tags:
  projects:   [<resolved from Layer 3a>]
  identities: [<resolved from source / cascade>]

Identities (multi-select):
  [p] Personal only
  [n] NEU only
  [b] both Personal + NEU

[If projects = []]   State:
  [B] baseline   (always returns for matching identity queries)
  [P] pending    (sits in inbox until assigned a project)
  [A] assign     (give a project now — type project name)

[Enter] save    [e] edit fields    [d] discard
```

**Defaults minimize prompting:**
- When all three (project, identity, state) can be resolved unambiguously by Layer 3a + source, save proceeds with a single confirm
- Prompt expands only when project-empty (forces state choice) or ambiguous source

**Re-walk scenarios under locked B+:**
```
M1  "kage repo structure"      projects:[kage]      ident:[P]    state:scoped
M2  "I prefer terse"           projects:[]          ident:[P,N]  state:baseline
M3  "Quantum circuit results"  projects:[quantum]   ident:[NEU]  state:scoped
M4  "Sarah is advisor"         projects:[]          ident:[NEU]  state:baseline
M5  "Lung-project notes"       projects:[llm-rsrch] ident:[NEU]  state:scoped
M6  "Cmd+Del = trash"          projects:[]          ident:[P,N]  state:baseline
M7  "Back pain"                projects:[]          ident:[P]    state:pending
```

Query `(kage, Personal)` returns: M1 (exact), M2 (baseline spillover), M6 (baseline spillover). Blocks M3/M4/M5 (identity wall), M7 (pending).

**Wedge re-confirmed against 2026 prior art:**
- Mem0: user/agent/run hierarchy — no identity dimension, no state model
- Letta: per-agent only
- Plurality: hand-curated buckets, 1-D, cloud
- OpenJarvis: per-agent memory
- Cursor Rules: per-repo, 1-D
- Claude Projects: per-project, manual, 1-D

kage's 2-D matrix + asymmetric walls + three-state schema + auto-suggested tagging = absent from current landscape.

**Cross-cutting deferred to subsequent layers / cycles:**
- Cross-project references (memory tagged with multiple projects) — supported by schema; UX deferred
- Identity-shared writes — supported via multi-identity tag at save time
- Retagging / corrections — `kage memory retag <id>`, batch operations — Stage 1 detail
- Audit log of retags / state changes — emerges from Layer 3e

**Engineering details:** Deferred to Stage 1. Approximate v1 cost noted (~1 cycle for Layer 3b alone — schema, filter logic, save-time prompt, inbox flow) — to be revisited at Stage 1.

### Layer 3c — Hybrid Retrieval

**Status:** Designed (PROPOSED, not yet locked). Awaiting Cosmos research validation and resolution of open sub-decisions.

**Role in pipeline:**
After Layer 3a resolves `(active_project, active_identity)` and Layer 3b filters memory to "what this query may see," Layer 3c finds the most relevant N memories within the allowed pool. The search engine inside kage.

**Proposed v1.0 shape:**
```
BM25 (lexical)            ──┐
FAISS (dense vector)       ──┼─► RRF score fusion ──► Cross-encoder
LightRAG query-side          │   (k=60, N retrievers)  re-ranker
  dual-level keyword       ──┘                          (top-50 → top-10)
  split (1 LLM call/query)
                                                            │
                                          ┌─────────────────┘
                                          ▼
                                   Layer 3d (assembly)
```

**Components (PROPOSED):**

| Component | Choice | Source |
|---|---|---|
| Lexical retrieval | BM25 | Inherited from OpenJarvis substrate |
| Dense retrieval | FAISS | Inherited from OpenJarvis substrate |
| Query expansion | LightRAG-style dual-level keyword split (low-level entities + high-level themes) | Stolen from LightRAG paper; query-side only, no graph required |
| Score fusion | Reciprocal Rank Fusion (RRF), k=60 | Industry default |
| Re-ranking | Dedicated cross-encoder (bge-reranker-v2-m3 as default, mxbai-rerank-v2-base as swap-in) | Stage 0 altitude — model choice swappable behind interface |
| Edge provenance | EXTRACTED / INFERRED / AMBIGUOUS tags on retrieved items | Stolen from Graphify |

**Deferred to v1.5:**
- Episodic immutable journal (Graphiti concept)
- Bi-temporal facts table (when-true vs. when-recorded)
- Lightweight entity linking (LightRAG concept, no graph)

**Deferred indefinitely (v2.0+):**
- Graph edges via Kuzu (only if retrieval quality demands it)
- Community detection / GraphRAG-style summaries (likely never — wrong scale)

**Audit findings supporting these choices:**

| Repo | Verdict | What kage steals |
|---|---|---|
| Graphify (safishamsi) | Reference, not dependency | Edge provenance tagging (EXTRACTED/INFERRED/AMBIGUOUS). v2 feeder for codebase projects. |
| Graphiti (Zep) | Reference, not dependency | Episodic journal concept + bi-temporal facts. For v1.5. |
| GraphRAG (Microsoft) | Skip | Architectural mismatch with personal scale; ingest LLM cost is brutal on local Qwen3. |
| LightRAG (HKU) | Steal query-side keyword split only | Dual-level retrieval at query time (cheap). Defer the graph half. |
| Cognee (topoteretes) | Reference, not fork | Closest architectural cousin. Lacks 2-D partition matrix + state machine + identity inheritance. Steal: filesystem layout `/user_uuid/dataset_uuid/`, principal/permission model, 4-verb broker API. |

**Open sub-decisions awaiting lock:**
1. RRF as fusion method (vs. DBSF / weighted / LTR) — leaning lock RRF
2. Cross-encoder re-ranker model selection (bge-reranker-v2-m3 vs. mxbai-rerank-v2-base vs. Qwen3-as-judge) — leaning bge-v2-m3
3. Whether to include re-ranker in v1.0 at all, or defer to v1.5
4. Cosmos research integration (see Section 8)

### Cross-cutting — Ingest Pipeline Philosophy

**Status:** PROPOSED (not yet locked). Direction agreed; sync/async split needs final tweaking.

**The question:** When a memory enters via Layer 3b's wall flow, what work is synchronous (blocks the save) vs. asynchronous (background queue)?

**Proposed: hybrid — cheap things synchronously, expensive things asynchronously.**

```
┌────────────────────────────┬──────────────────────────────────────┐
│ Synchronous (save returns) │ Asynchronous (background queue)      │
├────────────────────────────┼──────────────────────────────────────┤
│ • Text + metadata stored   │ • Entity extraction (LLM)            │
│ • Identity + project tags  │ • Relationship inference (LLM)       │
│ • State (scoped/baseline/  │ • Dual-level keys (if eager pre-     │
│    pending)                │    computed instead of query-time)   │
│ • Embedding computed (no   │ • Graph edge updates (v1.5+)         │
│    LLM, just encoder pass) │ • Stale-fact invalidation passes     │
│ • BM25 tokens indexed      │ • Entity dedup / merge               │
│ • Episodic journal entry   │ • Optional: LLM-generated summary    │
├────────────────────────────┼──────────────────────────────────────┤
│ Latency: < 200ms           │ Latency: seconds to minutes after    │
│                            │   save; runs when CPU idle           │
└────────────────────────────┴──────────────────────────────────────┘
```

**Memory lifecycle states:**
```
pending  ─►  tagged  ─►  indexed  ─►  analyzed
(inbox)      (3b save) (sync done) (async done)
                            │            │
                            ▼            ▼
                       retrievable   retrievable
                       via BM25 +    via graph,
                       FAISS         entities, etc.
```

A memory becomes **retrievable** as soon as it's `indexed`. Graph-retrievable when `analyzed`. Layer 3c uses whatever's available at query time.

**Open sub-decisions:**
- Exact placement of dual-level keyword extraction (eager at ingest vs. lazy at query time) — leaning query-time
- Whether to expose lifecycle state in the menu bar / inbox UI

**Cosmos Q5 validation (Session 4):** The hybrid sync-cheap / async-expensive split matches the "production compromise" pattern Cosmos identified across shipped systems. Specifically:
- **Validates kage's wall save** (Layer 3b decision #16) against ChatGPT's anti-pattern: 96% of ChatGPT memories are system-created unilaterally; 28% contain GDPR-defined personal data; persisted *interpretations*, not transcripts. kage explicitly inverts this.
- **Structurally aligned with Claude Code's pattern**: hybrid loading, plain-text auditable artifacts, no mandatory pre-indexing for everything. kage extends with FAISS+BM25 retrieval.
- **Matches "Pattern C — eager indexing + lifecycle ops"** in the sync column: embeddings + BM25 tokens computed at save time; lifecycle ops (deprecate/retag/forget) supported.
- **No structural changes to PROPOSED ingest pipeline.** Hybrid sync/async is the right call.

### Layer 3d — Tiered Assembly

**Status:** Designed and locked (directional). Session 7. Validated against Cosmos Q J (MemGPT/Letta, Zep/Graphiti, MIRIX, Mem0, GRAVITY, ECoRAG, ClawVM, SPL evidence).

**Role in pipeline:** After Layer 3c returns ranked memories, Layer 3d assembles them into prompt-shaped context within the target agent's token budget. Hands off to Layer 3e (privacy gate) before Layer 4 dispatch.

**3-tier residency × 5-type schema (orthogonal dimensions):**

Every memory has TWO orthogonal attributes:

```
   TIER (Layer 3d residency status)        TYPE (memory schema #46)
   ────────────────────────────────         ─────────────────────────
   • HOT  — always in context               • Core
   • WARM — retrieved per query             • Procedural
   • COLD — deep storage, on demand only    • Semantic-system-of-record
                                            • Semantic-vocabulary
                                            • Episodic-provisional

   Typical mappings:
   • Core memory       → typically HOT
   • Semantic-vocab    → HOT if frequently used, else WARM
   • Procedural        → WARM (retrieved when applicable)
   • Semantic-SOR      → WARM (decisions retrieved per query)
   • Episodic          → WARM when recent → COLD with age
```

**Assembly flow per query (locked):**

```
   1. Layer 3c hands kage: ranked list of relevant memories
      (typed + provenance-tagged)

   2. Layer 3d allocates token budget for target tool:
      • Reserve output budget FIRST (first-class constraint)
      • Then allocate: HOT (deterministic) + WARM (Layer 3c output)
      • System prompt + user query/history fill remaining space

   3. Format per memory type (type-aware rendering, mandatory):
      • Decisions: "X (because Y, consequences Z)"
      • Episodic: with timestamps + structured event fields
      • Procedural: numbered step lists
      • Facts: with validity date ranges (Graphiti pattern)
      • Glossary: inline definitions on first reference

   4. Compose final ordered context:
      • HOT first (Core memory frames the rest)
      • WARM second (query-relevant, in rank order)
      • User query last

   5. Hand off to Layer 3e (privacy gate)
```

**Overflow strategy (locked) — CASCADE, not recursive summarization:**

When relevant memory > available budget, kage applies in order:

```
   Step 1: Top-K select by Layer 3c reranker score
   Step 2: Extractive compression of TAIL items (lower-ranked)
           with evidence-sufficiency check (ECoRAG pattern)
   Step 3: Only drop items that fail rank AND compression
           threshold

   Recursive summarization is EXPLICITLY REJECTED — Cosmos Q J
   evidence: MemGPT DMR 35.3% (recursive summarization) vs 93.4%
   (paging + retrieval). Compression beats truncation: ECoRAG
   on 1000 docs uses 659 tokens for 35.51 EM, vs full RAG at
   127,880 tokens with near-zero performance.
```

**Cross-tool budget normalization (locked) — multi-resolution rendering:**

HOT tier stays constant across target tools (kage's foundation is consistent). WARM tier degrades fidelity per target window size (ClawVM pattern):

```
   Target tool        WARM rendering level
   ─────────────────  ──────────────────────────────────────────
   Claude 200K        Level 1 — Full structured rendering
   Gemini 1M          Level 1 — Full structured rendering
   Qwen3 32K          Level 2-3 — Compressed structured / fields
   Heavy constraint   Level 4 — Pointer references ("memory:ep:X
                                available on demand")
```

**Type-aware rendering — empirically validated:**

GRAVITY benchmark evidence (Cosmos Q J): structured entity-event-topic anchors yield +5.7% on LoCoMo vs +1.3% for unstructured summary in same prompt slot — **net +4.4 percentage points from structure alone**. Validates kage's type-aware rendering as mandatory, not optional.

**Deferred to Stage 1 engineering:**

- Exact HOT budget percentage (starting heuristic: 15%, calibrate post-launch from real usage)
- Specific type-rendering templates (direction locked, format details deferred)
- Compression model for the cascade tail (local Qwen via Layer 4 router — Layer 4 design)

### Layers 3e, 4, 5, 6, 7

**Status:** Not yet designed. Layer 3e next-up (Session 8+).

---

## 6 · SDLC + Process Decisions (locked)

### Build methodology — Shape Up
- ~2-week cycles
- Each cycle: pitch (problem + appetite + solution sketch) → build → retrospective
- Fixed time, variable scope (cut features, not extend cycles)
- **Stage 0 (planning) has no time pressure** — locked Session 4. Original "3-week build plan" deprioritized in favor of completeness. Shape Up cycles apply to Stage 1 only.

### Git workflow — GitHub Flow
- Branch per feature → PR → self-review or Claude-review → merge to `main`
- Even solo, write PR descriptions explaining what + why

### Documentation discipline
- **ADRs** (Architecture Decision Records) — one markdown file per significant decision in `docs/adr/`
- **Conventional Commits** — `feat:`, `fix:`, `chore:`, `docs:` etc.
- **README + ROADMAP + CHANGELOG** at repo root

### Release / operations
- Semantic versioning (start 0.1.0)
- GitHub Actions CI on every PR (lint + test) from PR #1
- Pre-commit hooks (auto-format + lint)

### Visual practice
- Mermaid disallowed (renderer-dependent); ASCII / Unicode box-drawing characters as default for diagrams in repo docs
- Style C: containment box for system + external column for outside actors
- Living architecture doc at `docs/architecture.md` updated session-to-session

---

## 7 · Strategic & Identity Decisions (locked)

| # | Decision | Date |
|---|---|---|
| 1 | Local model: Qwen3 14B Q4_K_M via Ollama | pre-session |
| 2 | Sandbox: Docker | pre-session |
| 3 | Cloud fallback: Claude Sonnet 4.6 | pre-session |
| 4 | OpenJarvis (Stanford SAIL) audited — verify Stanford provenance, Apache 2.0, 8 agents, highly active | Session 1 |
| 5 | kage framing: **personal context broker** (NOT "yet another personal AI") | Session 1 |
| 6 | Core differentiator: **context engine** (project-partitioned, identity-aware, dynamic retrieval). Routing is downstream, not upstream. | Session 1 |
| 7 | Repo strategy: **Fork OpenJarvis on GitHub as `kage`**, stay close to upstream | Session 1 |
| 8 | Dual goal: ship kage **AND** learn industry SDLC by doing it the way a real team would | Session 1 |
| 9 | Dual portfolio: own repo + upstream PRs to Stanford SAIL OJ | Session 1 |
| 10 | UX is NOT a defensible differentiator — restrict competitive comparison to core engine logic | Session 1 |
| 11 | Visual format: ASCII/Unicode flowcharts in repo docs (no Mermaid dependency) | Session 1 |
| 12 | Layer-by-layer planning workflow: each round = one layer, refine until locked | Session 1 |
| 13 | Stage 0 (now) = blueprint planning · Stage 1 (later) = implementation engineering | Session 1 |
| 14 | Internal agents architecture: Option C (hybrid — Librarian + opt-in Monitor inside, external via MCP) | Session 1 |
| 15 | Layer 3a: 4 signals, 6-level priority cascade (calendar event ranked between editor file path and terminal cwd; sticky is state not signal), bootstrap wizard, many-to-one identity model, 7 privacy principles | Session 1 |
| 16 | Layer 3b save philosophy: **wall, not firehose** — nothing enters memory unless explicitly saved. Background scraping = opt-in v2 only. | Session 2, 2026-05-21 |
| 17 | Layer 3b write path: **2 flows only** — Flow 1 (direct save: CLI/voice/menu bar/hotkey) + Flow 2 (session inbox markdown-file batch review). | Session 2 |
| 18 | Layer 3b tag schema: `projects[]` (can be empty) + `identities[≥1]` + `state ∈ {scoped, baseline, pending}`. | Session 2 |
| 19 | Layer 3b filter logic: **hard identity wall** (inviolable) + **project state-aware spillover** — `scoped` returns on exact project match; `baseline` returns for matching identity; `pending` never returns. Cross-identity = Pattern C, v2. | Session 2 |
| 20 | Layer 3b save-time prompt: identities multi-select + state choice when project-empty + confirm/edit/discard. Defaults minimize prompting; expand only on ambiguity. | Session 2 |
| 21 | **Core Characteristics locked** — ten one-word characteristics define kage: Seamless, Transparent, Aware, Local, Silent, Broker, Adoptable, Controlled, Invisible, Modular. Operational definitions in dedicated section above. | Session 4, 2026-05-23 |
| 22 | **Six new operating principles locked** — (1) Transparency as core, (2) Awareness over control, (3) Options over suggestions everywhere, (4) Build for now / architect for 3 years out, (5) Complete over fast — 3-week plan deprioritized, push back on rushing, (6) Bold recommendation first. | Session 4 |
| 23 | **Stage 0 has no time pressure.** Original 3-week build plan deprioritized. Shape Up cycles apply to Stage 1 only. Real goal of build = becoming a better AI engineer through depth. | Session 4 |
| 24 | **Gemini Spark (Google I/O 2026) validates kage's moat.** Spark is cloud-only, Workspace-only, no local model, no identity partitioning. Most recent enterprise entrant does not threaten kage's wedge. | Session 4 |
| 25 | **MCP as distribution standard (Google I/O 2026).** Gemini Spark routes via MCP. Layer 7 (MCP server out) priority increases — may need to be earlier in cycle plan than originally placed. To revisit when designing Layer 7. | Session 4 |
| 26 | **Substrate decision: Option A-prime locked.** OJ remains kage's substrate (BaseAgent / AgentRegistry / FAISS+BM25 memory backends). kage adopts the **open AGENTS.md / SKILL.md spec** (cross-vendor, not Antigravity-proprietary) for agent definitions and writes a thin SKILL.md → OJ BaseAgent loader. **Antigravity 2.0 is REJECTED as substrate** — closed-source, Google-OAuth-gated, Gemini-3.5-Flash-only, ToS-restrictive, 92% free-tier cut in 5 months, 4 days old at audit with active stability issues. Antigravity remains an optional client surface (Stage 3+ maybe). Audit findings: `Antigravity's harness wins on authoring ergonomics ONLY — markdown vs Python subclass; loses on every other dimension that matters for kage (local-model story, memory pluggability, headless trigger, license, cost, stability). Authoring win is captured for free by reading the open AGENTS.md/SKILL.md spec ourselves.` | Session 4 |
| 27 | **Differentiator recalibrated (Cosmos Q2 finding).** The (project × identity) 2-D matrix abstraction is **NOT academically novel** — Bhatt et al. 2025 (Microsoft Research, arXiv:2509.14608) formalizes documents × entities as bipartite graph with bicliques for enterprise multi-user access control. kage cites this as ancestor. **kage's defensibility repositioned at three product/engineering novelty points:** (1) first-of-kind shipped personal-AI with state-aware identity partitioning, (2) three-state semantics (scoped/baseline/pending), (3) identity-as-cluster-of-accounts (many-to-one). Practical wedge (no shipped product does this at personal scale) still holds, validated by both repo audit and Gemini Spark gap. Research-paper path (personal-scale instantiation of enterprise abstractions) flagged as possible but deferred to post-v1.0. | Session 4 |
| 28 | **Ingest pipeline validated (Cosmos Q5 finding).** Hybrid sync-cheap / async-expensive ingest pipeline (decision in Section 5 Layer 3b) matches the "production compromise" pattern shipping systems converge on. ChatGPT's eager implicit extraction is explicitly REJECTED as anti-pattern (rejected item #31). One v2 consideration added: optional per-state TTL on `pending` memories (parked #15.5), inspired by GitHub Copilot Memory's 28-day expiry pattern adapted to kage's state machine. No structural changes to PROPOSED ingest pipeline. | Session 4 |
| 29 | **Identity & audience locked (Session 5, 2026-05-28).** (a) **Nested framing locked**: kage is a COMPLEMENT (identity / why) that takes the form of a MEDIATOR (role / what) operating as a BROKER (mechanism / how, v1). All three are true simultaneously. Use whichever level fits the conversation. (b) **Audience split locked**: Primary user = Chirag (daily-driven utility). Primary audience for the work (code/ADRs/docs) = engineers who'd want to extend kage. Secondary audience = research community for deferred paper paths. Reconciles Adoptable (Session 4) with Engineering Credential (May 25 brainstorm) — different surfaces of "adoption." | Session 5 |
| 30 | **7 new Locked Principles (Session 5)** — Blank Slate Boot, Adaptation, Honesty (TARS), Testing Protocol, Capability, Raising/Nurturing, Self-Discovery. Total of 13 Locked Principles now (6 from Session 4 + 7 from Session 5). One additional principle (Confidence-Gated Learning) **deferred** to Layer 6 design session. The earlier "Correction-Driven Personalization" framing (May 24 handoff) is **superseded** by the deferred Confidence-Gated Learning concept. | Session 5 |
| 31 | **Capability Principle 0.60 resolution (Session 5)** — the originally-locked "Confidence threshold for routing: 0.60" (pre-session notes) is rewritten as a v1 STARTING BASELINE / cold-start default. Not a fixed constraint. Post-launch calibration target: learned threshold per query type, per identity, from observed routing-outcome data. Consistent with Capability + Blank Slate Boot + Adaptation + Raising/Nurturing. Connects to deferred Consequence-Aware Routing research path. | Session 5 |
| 32 | **Learning recognized as cross-cutting concern (Session 5)** — learning has surfaced in 10 separate planning touchpoints (Layer 6 T1/T2/T3, Confidence-Gated Learning, Consequence-Aware Routing, Phased Learning Model, Librarian's taste capture, Personal STT Correction Learner, Overnight Dreaming Pass, Adaptation Principle, plus). All deferred to a dedicated Layer 6 design session that will unify them. **NOT yet promoted to "fourth differentiator"** — that elevation is deferred until Layer 6 is designed. Note as architectural priority. | Session 5 |
| 33 | **Layer 4 routing pattern locked (direction)** — **Pattern 5 (pre-classification)** as v1 default. kage decides which model BEFORE generating (sub-second classification), executes single round-trip, shows user a visible model badge. Pattern 2 (cached local fallback) explicitly **rejected** (jarring UX). Patterns 1 (speculative execution), 3 (streaming handoff), 4 (asynchronous escalation) deferred as v2+ candidates once data shows where friction lives. Detailed mechanics (classifier logic, confidence signal, cost-ceiling enforcement, failure-mode handling, audit log schema) deferred to Layer 4 design session. | Session 5 |
| 34 | **Distillation Harness added as major Layer 6 design candidate (Session 5)** — Chirag-proposed pattern: route per-query via Pattern 5, but ALSO run query on local even when escalating to cloud, store (query, local_resp, cloud_resp, feedback) pairs, run overnight LoRA fine-tune on accumulated pairs. Local quality rises over time → confidence threshold can rise → cloud usage falls. Strengthens "Learning as 4th differentiator" case but not yet promoting. Cosmos queries A/B/C/D queued (personal-scale distillation prior art, LoRA on Apple Silicon feasibility, privacy-preserving distillation, catastrophic forgetting mitigation). Privacy posture options under discussion: explicit-tag-only / cloud-routed-only / all-queries-opt-out — to be resolved at Layer 6 design. | Session 5 |
| 35 | **Tension #1 resolved (Session 5): Self-Discovery Principle compatible with Layer 3a Bootstrap Wizard.** Both items stay as-is. Refinement: Step 2 wording made explicit — auto-suggest identity groupings via domain heuristics, present findings, user confirms or reassigns; never ask from a blank slate. Pattern: auto-detect → present findings → user confirms. Satisfies Self-Discovery + Blank Slate Boot + Awareness over control + Options over suggestions simultaneously. | Session 5 |
| 36 | **Tension #2 resolved (Session 5): drop the 4-week number from Deployment Philosophy.** May 24 brainstorm doc proposed "Target: four weeks to a living, breathing system" for the 5 essential elements. This conflicts with locked "Complete over fast" (no arbitrary deadlines). **Resolution:** when integrating the May 24 Deployment Philosophy, DROP the 4-week number entirely. Keep the 5 essential elements as the v1.0 ship target. Map to "minimum 2 Shape Up cycles, possibly more — however many needed." Cycle boundaries are sacred; scope flexes; time and quality never. "Push back on rushing" applies whenever anyone suggests compressing scope or skipping rigor to hit a date. | Session 5 |
| 37 | **Briefer deferred to v1.5 (Session 5).** Briefer agent (daily PA-style briefing — calendar, email, project status) was a candidate for v1 essentials per the JARVIS framing. **Deferred to v1.5** with structural reason: Briefer depends on tool integrations (Calendar, Gmail, Teams, Meet) that don't exist in v1. Building Briefer before its dependencies is premature. v1 ships infrastructure-only essentials; v1.5 builds the role-playing agents once their tool substrates are in place. | Session 5 |
| 38 | **External tool relationship framing locked (Session 5).** kage's BROKER role with external tools: USE what exists, DON'T rebuild what's already free/good. MCP-first where supported (Claude Code, Cursor, emerging tools). Direct integration for tools without MCP (Perplexity API, Gemini, Cosmos). kage's job is DISCOVER → ROUTE → COORDINATE → not DUPLICATE. When new tools ship, kage evaluates (Adaptation Principle) and slots in if better. This is the BROKER level made operational; ties Free Tools Philosophy + Adaptation Principle + Awareness over control + Layer 4 routing + Layer 7 MCP exposure. | Session 5 |
| 39 | **Layer 6 REFRAMED — memory-layer learning, NOT weight-based distillation (Cosmos Q A/B/C/D convergence, Session 5).** Original "Distillation Harness with LoRA fine-tuning" approach is REJECTED for v1 and v2 based on: (a) Q B — Apple Silicon 24GB unified memory is high-risk for 14B QLoRA (PyTorch MPS 4GB tensor limit, near-capacity instability, no Unsloth-equivalent); (b) Q C — privacy is complex (DP budget management, LoRA rank-memorization tradeoff, StolenLoRA adapter extraction risk); (c) Q D — production personal-assistant systems (Cursor, Cognee, EMG-RAG, MIRIX) DO NOT fine-tune base weights; they encode personalization in memory/rules/RAG layers; (d) Q A — the technical pattern is well-trodden (Proxy-KD, Alpaca, Vicuna), no novelty to recover. **New approach**: multi-modal memory-layer learning — context exemplars + editable rules (Cursor pattern) + schema-grounded facts (Cognee pattern) + per-identity preference deltas + system-of-record isolation. LoRA path deferred to v3+ research only. | Session 5 |
| 40 | **Layer 4 router refinements (Cosmos Q E v2 informed, Session 5).** Pattern 5 (pre-classification) stays locked as v1 default. ADD: framework-style failure handling — structured exceptions per tool, timeout policies (skip/retry/extend), graceful degradation (cloud fail → local-teacher fallback per OJ pattern). ADD: per-identity / per-project default permission policies to reduce approval fatigue. Inherits OpenJarvis tool architecture (internal + direct API + MCP adapter) directly. | Session 5 |
| 41 | **Layer 7 MCP server out — priority CONFIRMED HIGH (Cosmos Q E v2).** Validates Session 4 #25. MCP is de-facto distribution standard in 2026 — adopted by Anthropic, OpenAI, Google DeepMind/Gemini, Microsoft Copilot Studio. ~8,060 valid MCP servers across 6 markets. kage publishes (project × identity)-partitioned memory as MCP server; signs server + registers only on verified registries (Anthropic official) to avoid the ~50% invalid-listing problem. | Session 5 |
| 42 | **Three industry gaps identified as kage differentiator opportunities (Cosmos Q E v2).** (1) Discovery / registry trust at scale — ~50% of MCP listings invalid; hosts don't verify. kage adds per-identity tool allowlists + signed verification + project-level scoping. (2) Approval fatigue — per-tool confirmation is brittle; auto-run modes risky. kage adds identity-aware default policies + Confidence-Gated Learning of approval patterns. (3) Non-uniform failure semantics — products lack shared cross-tool fallback standard; frameworks have it. kage inherits framework-grade resilience (retry/timeout/skip per tool category) as unified failure layer. All three: concrete differentiator surfaces beyond the engine-level novelties. | Session 5 |
| 43 | **OpenJarvis tool architecture inherited as direct substrate (Cosmos Q E v2 detailed).** OJ provides: 7 internal tool categories (reasoning/math/code execution/web search/file I/O/memory/inference delegation), direct API tools (Google/Tavily/Brave for web search), MCP adapter (external MCP server → Tool), TOML spec for tools/connectors/channels, EventBus for component plug-in, 25+ data sources, 32+ messaging channels, interchangeable memory backends, sensitive-data scanner, prompt-injection detection, SSRF allowlist validation, sandboxed code execution, scrubbing pipeline, trace eligibility controls, local-teacher fallback. **kage inherits all of this by forking OJ; extends with identity partitioning + state machine + memory-layer learning subsystem.** | Session 5 |
| 44 | **CoT preservation rule for any future context distillation (Cosmos Q A finding, Session 5).** If kage ever stores teacher responses as retrievable exemplars (Layer 6 memory-layer learning), MUST preserve full reasoning trace, not just final answer. Evidence: DistillGuard MATH-500 dropped 68.4→31.4 when CoT removed during distillation — >50% degradation from cutting reasoning. Layer 6 design constraint. | Session 5 |
| 45 | **Tension #4 resolved (Session 5): Blank Slate Boot Principle scope clarified.** Principle applies to kage's RUNTIME (Stage 1+), NOT to the planning AI sessions used during Stage 0 design. Planning sessions load CLAUDE.md / blueprint.md / memory entries by design — that's how they help design kage. kage's runtime is a different system and a different stage. Wording in §"Locked Principles" #7 updated to make scope explicit. No architectural change required. | Session 5 |
| 46 | **Five Memory Types locked for kage's memory schema (Session 5, Agent OS-validated).** Independent confirmation from Oleg Kupshukov's "Agent OS" handbook (the YouTube creator's solution to cross-AI context loss) that the right memory schema has five typed components. kage adopts the SAME structure as locked memory types, with kage automating the capture that Agent OS does manually: **(1) CORE memory** = always-in-context (project/identity overview, current state, "what NOT to do" prohibitions — Agent OS "Project Context"); **(2) PROCEDURAL memory** = how-to / workflow patterns (Agent OS "Workflow"); **(3) SEMANTIC system-of-record memory** = authoritative decisions including the constraint-encoding "Consequences" field that records what becomes FORBIDDEN by each decision (Agent OS "Decisions Log"); **(4) SEMANTIC vocabulary memory** = entity definitions, disambiguations (Agent OS "Glossary"); **(5) EPISODIC provisional memory** = observed patterns awaiting graduation to formal types via Confidence-Gated Learning principle (Agent OS "Working Insights"). All five composed with kage's existing (project × identity) partition matrix from Layer 3b. kage automates capture; user confirms/edits/discards (Awareness over Control + Confidence-Gated Learning). Structure is locked; engineering details deferred to Layer 5 (memory storage) + Layer 6 (learning) design sessions. | Session 5 |
| 47 | **Three-mode user support locked (Session 6, 2026-05-28). Agent OS coexistence strategy.** kage supports a continuum of inspection/storage modes: **Mode 1 — Pure kage local**: `~/.kage/memory/` markdown files; no external dependencies; privacy-first. **Mode 2 — Hybrid**: kage local + Notion mirror (read-mostly, optional write-back) for users who want inspection/sharing layer. **Mode 3 — Notion-canonical**: kage auto-maintains the user's existing Agent OS-style Notion pages via Notion MCP — kage adds automation on top of their existing setup. v1 ships Mode 1; Modes 2 and 3 added when Notion connector is wired (v1.5+). Strategic framing: kage doesn't compete with Notion; kage automates what Agent OS does manually. | Session 6 |
| 48 | **Consequences-field-as-detection-signal locked for Layer 6 design (Session 6).** kage's Confidence-Gated Learning must detect not just "we decided X" moments but the constraint-defining "and therefore Y is off-limits" moments. Linguistic signals to watch for: "we chose X, so don't propose Y anymore" · "X is our default. Other approaches off the table" · "X is the rule. Y was considered and rejected because Z" · "From now on, X — never Y." When detected, kage extracts a constraint field separately from the choice, storing as system-of-record SEMANTIC memory with both Decision and Consequences populated. Layer 6 design constraint: capture constraints, not just facts. Why: vector retrieval over text returns facts but not constraints; kage's memory needs to encode behavioral consequences for retrieval to be useful. | Session 6 |
| 49 | **Layer 3c (Hybrid Retrieval) FULLY LOCKED (Session 7).** Final v1 composition: BM25 (OJ substrate) + Granite Embedding 311M R2 at native 768d for dense (Apache 2.0, see #50) + FAISS for ANN index + LightRAG query-side dual-level keyword split (1 LLM call/query) + RRF score fusion (k=60) + bge-reranker-v2-m3 for re-ranking (Apache 2.0, see #51) + Graphify-style edge provenance tags (EXTRACTED/INFERRED/AMBIGUOUS) + hybrid sync/async ingest pipeline. Total memory budget: ~1.0-1.5GB for retrieval stack, fits comfortably alongside Qwen3-14B Q4_K_M on M5 Pro 24GB. All components Apache 2.0. Layer 3c is the first FULLY-LOCKED layer of kage's retrieval pipeline. | Session 7 |
| 50 | **Embedding model: Granite Embedding 311M R2 (replaces jina-embeddings-v3, Session 7).** Cosmos Q7 originally recommended jina-embeddings-v3 as default, but post-Cosmos license verification revealed jina-v3 is CC BY-NC 4.0 (non-commercial). Granite Embedding 311M R2 is Apache 2.0 (IBM Research), 311M params, 768d native, MTEB-v2 Retrieval Avg 65.2 (slightly higher than jina-v3 in the relevant comparison), 200+ languages. Trade-off: no Matryoshka truncation, but native 768d at MTEB 65.2 is already smaller than jina at 1024d and competitive on quality. License preservation outweighs the Matryoshka feature. | Session 7 |
| 51 | **Re-ranker: bge-reranker-v2-m3 (MemReranker not viable for v1, Session 7).** Cosmos Q3 originally recommended MemReranker-0.6B for agent memory, but post-Cosmos verification: (a) MemReranker-0.6B is NOT publicly downloadable — only available via Memos hosted API, which violates kage's local-first principle; (b) MemReranker-4B IS downloadable (Apache 2.0 confirmed) but bf16 weights are 8.83GB — too heavy alongside Qwen3-14B + Granite on 24GB unified memory; (c) jina-reranker-v3 is CC BY-NC, rejected for license reasons. Fall back to bge-reranker-v2-m3: Apache 2.0, ~500MB, ~4 MAP-point gap vs MemReranker-0.6B on agent-memory benchmarks but fits memory budget cleanly. **v1.5 upgrade paths flagged:** (a) if MemReranker-0.6B is released publicly (HF Discussions request pending), swap is trivial behind SentenceTransformer interface; (b) MemReranker-4B Q4-quantized (~2.5GB) is a v1.5/v2 engineering project once quality preservation is validated. **Constraint Reconsideration Trigger applies** (see #52): if quality demonstrably blocks v1 use cases, revisit. | Session 7 |
| 52 | **Constraint Reconsideration Trigger pattern locked (Session 7).** Safety net for the 4th differentiator's constraint encoding to prevent over-restriction failure mode. **The pattern:** every constraint encoded in Consequences MUST include the rationale's PREMISES (the "because Y" portion). When the Adaptation Principle detects a premise has materially changed (new tools available, scale shift, user behavior drift, new evidence), kage SURFACES the constraint for reconsideration — does NOT silently enforce. This makes constraint encoding a hypothesis-under-current-conditions, not a verdict. Specific operational rules: (a) every Consequences entry has WHY field; (b) periodic premise-validity checks (kage's background workers re-evaluate active constraints); (c) when reconsideration is triggered, kage surfaces with current evidence and asks user to confirm, modify, or revoke; (d) user can always force-reconsider via `kage reconsider <decision>` command. This reconciles Honesty + Adaptation + Confidence-Gated Learning + Awareness over Control simultaneously. | Session 7 |
| 53 | **4th Differentiator promoted (Session 7).** "Multi-modal memory layer with Confidence-Gated Learning, constraint encoding, and identity-aware retrieval" is added as differentiator #4 in §3. Composed of six locked elements (5 memory types #46, CGL principle, Consequences with Reconsideration Trigger #48 + #52, identity-aware retrieval Layer 3b, privacy-by-architecture, three-mode user support #47). Validated by absence-from-shipping-products across Cosmos Q1-Q5, Q7, Q E v2 + Agent OS audit. **Academic novelty NOT claimed** — Bhatt et al. 2025 (#27) is acknowledged ancestor for the matrix abstraction; the 4th differentiator's claim is product/engineering combination novelty at personal scale. Honest framing maintained. Cosmos Q F null retrieval doesn't disturb the case (tool failure, not novelty evidence). Research-paper-path #18.5 remains deferred post-v1.0 ship. | Session 7 |
| 54 | **Layer 3d 3-tier × 5-type orthogonal model locked (Session 7, Cosmos Q J-validated).** Every memory has TWO orthogonal attributes: TIER (HOT/WARM/COLD residency) and TYPE (Core/Procedural/Semantic-SOR/Semantic-Vocab/Episodic per #46). HOT is deterministic per (active_project, active_identity) — constant across queries for user-trust predictability. WARM is per-query, populated by Layer 3c output. COLD is invisible by default, retrieved only on explicit reference. Validated against Letta/MemGPT (3-tier), Zep/Graphiti (3-tier graph hierarchy), MIRIX (typed-without-tier — kage composes both), Mem0 (selective retrieval). | Session 7 |
| 55 | **Layer 3d overflow strategy: CASCADE (Session 7, Cosmos Q J-validated).** When relevant memory > available budget, kage applies in order: (1) top-K select by Layer 3c reranker score, (2) extractive compression of TAIL with evidence-sufficiency check (ECoRAG pattern), (3) only then drop. **Recursive summarization explicitly REJECTED** based on MemGPT DMR evidence (35.3% recursive summarization vs 93.4% paging+retrieval with GPT-4 Turbo). ECoRAG evidence: 1000 docs → 659 tokens with 35.51 EM, vs full RAG 127,880 tokens near-zero. | Session 7 |
| 56 | **Layer 3d multi-resolution rendering for cross-tool budget scaling (Session 7, Cosmos Q J-validated).** HOT tier stays CONSTANT across target tools (kage's foundation is consistent — user-trust property). WARM tier degrades fidelity per target window size (ClawVM pattern): Level 1 full structured (Claude 200K, Gemini 1M) → Level 2-3 compressed structured / structured fields (Qwen 32K) → Level 4 pointer references ("memory:ep:X available on demand") under heavy constraint. Per SPL `USING MODEL` clause and ClawVM multi-resolution representations. **Type-aware rendering** mandatory per all tiers, validated by GRAVITY +4.4 percentage point benchmark advantage over unstructured summary in same prompt slot. | Session 7 |

---

## 8 · Open Questions / Pending Layers

### Pending — to be designed in subsequent sessions

1. ✓ **Layer 3c — Hybrid retrieval shape** — LOCKED Session 7 (#49-52)
2. ✓ **Layer 3d — Tiered assembly shape** — LOCKED Session 7 (#54-56)
3. **Layer 3e — Privacy / disclosure mechanics** (allowlist schema, redaction rules, audit format) — **next up**
4. **Layer 4 — Multi-vendor router** (signal sources for routing decisions: cost, capability, privacy, latency)
5. **Layer 5 — Memory storage** (on-disk layout, FAISS + BM25 + graph + episodic, partition tags)
6. **Layer 6 — Learning T1** (preferences + entities + implicit feedback)
7. **Layer 7 — MCP server out** (endpoints, schema, auth)
8. **Layer 1 — Trigger / Interface detail** (CLI shape, menu bar, okiro)
9. **Layer 2 — Helper agents detail** (Librarian responsibilities, Monitor scope)

### Pending — cross-cutting

- Cycle 1 pitch (what's the first shippable scope)
- Repo strategy detail: how to organize `src/` to keep kage code separable from upstream OJ for clean sync
- Engagement plan with OJ team (lurk Discord, plan upstream PRs)
- Eval / testing strategy (per-layer, per-agent)
- **Ingest pipeline philosophy** — direction proposed (hybrid sync/async); sync/async split awaiting final tweaks

### Pending — Cosmos research (to be initiated)

**Status as of Session 5 (2026-05-28):** Q1, Q2, Q5 delivered + integrated. Q3, Q4, Q7 delivered + processed (stage for Layer 3c lock). Q6 not yet run. Plus 4 new Layer-6 distillation queries (A/B/C/D) added Session 5.

Original questions identified during Session 3:

1. ✓ **Personal AI memory layer benchmarks 2025-2026** — DELIVERED, integrated (validates Layer 3c)
2. ✓ **Multi-tenant / partitioned RAG literature 2024-2026** — DELIVERED, integrated (decision #27 recalibration)
3. ✓ **Cross-encoder re-rankers for personal AI 2025-2026** — DELIVERED, staged (overturned reranker pick → MemReranker)
4. ✓ **Beyond RRF: score fusion methods 2024-2026** — DELIVERED, staged (RRF validated, no change)
5. ✓ **Lazy vs. eager extraction in production agent memory** — DELIVERED, integrated (decision #28)
6. ⏳ **Ingest pipeline cost on consumer hardware** — NOT YET RUN (lower priority)
7. ✓ **Embedding models for personal-scale local AI** (NEW Q7) — DELIVERED, staged (jina-embeddings-v3 pick)

Session-5 additions (Layer 6 distillation harness):

A. ⏳ **Personal-scale knowledge distillation prior art** — does any existing system distill from cloud LLM to local LLM on a single user's data? Novelty assessment.
B. ⏳ **LoRA fine-tuning on Apple Silicon (M-series) 2024-2026** — practical feasibility for Qwen3-14B-Q4 on 24GB unified memory. Tooling, timing, quality.
C. ⏳ **Privacy-preserving distillation patterns 2024-2026** — DP-SGD on LoRA, selective distillation, memorization risks, mitigations.
D. ⏳ **Catastrophic forgetting in personalized LoRA 2024-2026** — rehearsal strategies, modular adapters, evaluation methodology.

---

## 9 · Parked / Deferred Decisions

Items deliberately set aside — either deferred to a later cycle, conditional on outcomes, or awaiting external signals.

### Deferred to v2 (after v1.0 ships)

| # | Item | Notes |
|---|---|---|
| 1 | Pattern B — Unified per-identity aggregation (4 accounts → 2 views) | v1 design accommodates the shape |
| 2 | Pattern C — Smart cross-identity search | v1 search API takes scope parameter |
| 3 | Pattern D — Deeper OS signals (Chrome profile, Mail.app, Focus mode) | v1 signal sources are pluggable |
| 4 | Pattern E — Account-aware writes with confirmation | v1 has trivial confirmation gate in place |
| 5 | Voice modality (Wispr Flow integration as kage input) | text-first in v1 |
| 6 | Multi-device / hub-and-spoke (mobile thin-clients) | single-device M5 Pro for v1 |
| 7 | Observational learning (screen/IDE watch) | opt-in only, deferred for privacy |
| 8 | Learning Tier 2 — DSPy programmatic optimization | v1 is T1 prompt-only |
| 9 | Skill marketplace integration (OJ's agentskills.io) | not core to context engine |
| 10 | Additional MCP connectors beyond Google (Notion, GitHub, etc.) | Google-only in v1 |
| 11 | Cross-device sync | single-device in v1 |
| 12 | Übersicht HUD widget (always-visible desktop) | menu bar suffices for v1 |
| 13 | Mac menu bar polish (icons, animation, $ spend display) | basic status pill in v1 |
| 14 | Bridge agent (cloud-fallback specific to Claude) | original notes; superseded by router |
| 15 | Morning briefing opening line style | content question, defer |
| 15.5 | Optional per-state TTL on `pending` memories (auto-archive after N days if not promoted to scoped/baseline) | Inspired by GitHub Copilot Memory's 28-day expiry pattern but adapted to kage's state machine. NOT a blanket expiry — only on `pending` state. Defer to v2 (Cosmos Q5 finding, Session 4). |
| 16 | News topics for morning briefing | content question, defer |

### Deferred — research / thesis path

| # | Item | Notes |
|---|---|---|
| 17 | Learning Tier 3 — LoRA fine-tuning of Qwen3 on personal traces | research/thesis only; not on v1.0 path |
| 18 | Calibrated routing (replace hardcoded 0.60 threshold with learned cost-aware router) | research-flavored; would align with Stanford IP-Watt; potential paper |
| 18.5 | **Personal-scale instantiation of enterprise access-control abstractions** (Session 4) | Cosmos Q2 confirms academic gap: state-aware partition semantics (scoped/baseline/pending) + identity-as-cluster modeling at single-user scale is absent from literature. Worth revisiting as a thesis-adjacent paper after v1.0 ships with real usage data. |

### Deferred — conditional on signal

| # | Item | Condition |
|---|---|---|
| 19 | 30B local models | only if 14B shows quality limits in v1 use |
| 20 | NativeOpenHands promotion to write | only when coding agents are mature |
| 21 | Time Machine backup setup | needs external drive (logistics) |
| 22 | Monetization / commercialization architecture | foundation first |

### Rejected — not on roadmap

| # | Item | Reason |
|---|---|---|
| 23 | Option A — Pure broker (no internal agents) | loses proactive helpers (Librarian) |
| 24 | Option B — Full OJ-style agent system inside kage | muddies broker positioning |
| 25 | Option E — kage as user's primary chat interface (replace cloud tools) | rebuilds too much solved UX |
| 26 | C4 model architecture diagrams (Structurizr / PlantUML) | overkill for current stage |
| 27 | Letta-style memory-inside-agent paradigm | different paradigm; kage is broker not agent |
| 28 | Mermaid as default visual format in repo docs | renderer-dependent; ASCII/Unicode chosen |
| 29 | Fork-and-detach (cut "Forked from" badge) | loses upstream sync benefit; mostly cosmetic |
| 30 | Vendor OJ inside kage repo as submodule | unclear divergence makes this premature |
| 31 | **Eager implicit extraction (ChatGPT Memory style)** | Cosmos Q5 evidence: 96% of ChatGPT memories created unilaterally by the system; 28% contain GDPR-defined personal data; 52% psychological inferences persisted without explicit consent. kage's wall save philosophy (decision #16) is the deliberate inverse. **NO implicit extraction in v1. NO silent inference of user traits.** Background sources stay opt-in for v2 only. |

---

## 10 · Session log

### Session 1 — 2026-05-21 (planning)

**Done:**
- Audited OpenJarvis source (verified Stanford SAIL provenance, 8 agents, far more complete than original notes assumed)
- Reframed kage from "personal AI" to "personal context broker"
- Discovered the core differentiator: context engine (project × identity matrix), with routing/MCP/privacy as downstream
- Locked dual goal (ship + learn SDLC)
- Adopted SDLC starter pack (Shape Up + GitHub Flow + ADRs + CC + CI + pre-commit + semver)
- Researched 2026 competitive landscape (Mem0, Letta, Plurality, OpenBrain, DTP, OJ, plus academic/enterprise tools)
- Established visual practice (ASCII/Unicode flowcharts, Style C)
- Switched to layer-by-layer blueprint workflow
- Locked Layer 2 (hybrid agents architecture, Option C)
- Designed Layer 3a end-to-end (detection cascade, bootstrap, identity model, automation patterns A-E, privacy framework)
- Created this blueprint doc

**Memory saved (10 entries):**
- User priorities (portfolio + distinctiveness alongside utility)
- kage ↔ OpenJarvis relationship
- kage long-term vision (2-5 year invisible plumbing)
- Dual goal: ship + learn SDLC
- Core differentiator: context engine
- UX is not a differentiator
- Polls: prefer multi-select + multi-question
- Push opinion, don't list neutrally
- Visual format: ASCII/Unicode not Mermaid
- Proactively educate on platform/tools
- Stage 0 / blueprint altitude

**Next session resume point:**
- Open this file (docs/blueprint.md), confirm context loads cleanly
- Begin **Layer 3c — Hybrid retrieval shape** design
- Layer-by-layer workflow continues: design, side-by-side competitor coverage, lock, move on
- Estimated: 5-7 more layer-design sessions to complete Stage 0 blueprint, then Cycle 1 pitch, then Stage 1 implementation begins

### Session 2 — 2026-05-21 (planning, continued)

**Done:**
- Layer 3a audit + cleanup: cascade promoted to 6 levels with calendar event ranked third; sticky last-active reclassified as state (not signal)
- Layer 3b — Partition Filter designed end-to-end:
  - Save philosophy: **wall**, not firehose (no background scraping in v1)
  - Two write flows (Flow 1 direct + Flow 2 session inbox); Flow 3 deleted
  - Tag schema: `projects[] + identities[≥1] + state ∈ {scoped, baseline, pending}`
  - Filter logic: hard identity wall + project state-aware spillover
  - Save-time prompt UX (identities + state when project-empty)
  - Three-state model resolves project-empty leak concern
- Blueprint updated; decisions #16-20 added; pending list re-numbered

### Session 3 — 2026-05-22 (Layer 3c design)

**Done:**
- Layer 3c — Hybrid Retrieval designed in PROPOSED state:
  - Full menu of retrieval families surfaced (lexical, dense, hybrid, graph, episodic, structured, re-ranking, query expansion, active/iterative)
  - Three rounds of audit on prior-art repos:
    - Round 1: Graphify (codebases only, v2 feeder concept), Graphiti (good concepts, heavy LLM dependency), GraphRAG (skip — wrong scale)
    - Round 2: Cognee (architectural cousin; reference don't fork), LightRAG dual-level keys (steal query-side half only)
  - v1.0 shape proposed: BM25 + FAISS + LightRAG dual-level split + RRF fusion + cross-encoder re-ranker + Graphify-style provenance tags
  - v1.5 deferred: episodic journal, bi-temporal facts, lightweight entity linking
  - v2.0+ deferred: graph edges (Kuzu), community detection
- Cross-cutting ingest pipeline philosophy designed in PROPOSED state:
  - Hybrid: cheap things synchronously, expensive things asynchronously
  - Memory lifecycle: pending → tagged → indexed → analyzed
- Cosmos research brief drafted (6 questions, priority #1/#2/#5)

**Open / not-yet-locked:**
- RRF vs. DBSF vs. weighted fusion
- Cross-encoder model selection (bge-v2-m3 vs. mxbai-v2 vs. Qwen3-as-judge)
- Whether re-ranker is in v1.0 or deferred to v1.5
- Sync/async split tweaks for ingest pipeline
- Cosmos research integration

**Next session resume point:**
- Bring back results from Cosmos run + personal-Claude brainstorm
- Reconcile findings against the PROPOSED Layer 3c shape in this blueprint
- Lock Layer 3c, write ADR for ingest pipeline, then move to Layer 3d (Tiered Assembly)

### Session 5 — 2026-05-28 (serious revisit phase begins)

**Done:**
- **Priority 1 — Identity & audience locks:**
  - Nested framing locked: COMPLEMENT (identity) → MEDIATOR (role) → BROKER (mechanism, v1). All three true simultaneously.
  - Audience split locked: Chirag primary user; engineers primary audience for the work; research community secondary.
  - Rewrote §1 (North Star) and §2 (What kage IS / IS NOT) with the nested framing.
- **Priority 2 Round 2a — 7 new locked principles + Capability resolution:**
  - Locked: Blank Slate Boot, Adaptation, Honesty (TARS), Testing Protocol, Capability, Raising/Nurturing, Self-Discovery (13 locked principles total now).
  - Deferred: Confidence-Gated Learning (to Layer 6 design session — supersedes earlier "Correction-Driven Personalization").
  - Capability resolution: 0.60 threshold reframed as v1 starting baseline / cold-start default, post-launch learned calibration.
- **Priority 2 Round 2b — partial:**
  - ✓ Tension #1 (Self-Discovery vs Layer 3a Bootstrap) — resolved; Step 2 wording refined.
  - ✓ Tension #2 (4-week target vs Complete over fast) — resolved; 4-week number dropped from Deployment Philosophy.
  - 🟡 Tension #3 (Librarian taste capture) — partially parked; promoted to dedicated Layer 2 design session.
  - ⏳ Tension #4 (Blank Slate scope clarification) — not yet resolved.
- **Cosmos Q3 / Q4 / Q7 results processed and staged for Layer 3c lock:**
  - Q3 (rerankers): MemReranker-0.6B default; jina-reranker-v3 fallback; bge-v2-m3 demoted.
  - Q4 (fusion): RRF validated, no change.
  - Q7 (embeddings): jina-embeddings-v3 default at 256-d via Matryoshka.
- **Layer 4 routing direction locked:** Pattern 5 (pre-classification) as v1 default. Patterns 1/3/4 deferred. Pattern 2 rejected.
- **Distillation Harness added as Layer 6 major candidate:** Chirag-proposed pattern (run query on both local + cloud when escalating, use pairs as training data for overnight LoRA fine-tune of local model). 4 new Cosmos queries queued (A/B/C/D).
- **External tool relationship framing locked:** kage's BROKER role with external tools — USE what exists, MCP-first where supported, direct integration otherwise, kage DISCOVERS / ROUTES / COORDINATES (does NOT duplicate).
- **Briefer agent deferred to v1.5:** depends on tool integrations (Calendar, Gmail, etc.) not yet built.
- **Agent architecture exploration promoted to dedicated Layer 2 design session.**
- **Cosmos Query E v2 fired** (tool integration patterns in shipping personal AI systems 2024-2026).
- **Decisions #29-38 added** (10 new locks/decisions this session).

**Pending Cosmos results (to integrate next session):**
- A: Personal-scale knowledge distillation prior art
- B: LoRA fine-tuning on Apple Silicon (M-series) feasibility
- C: Privacy-preserving distillation patterns
- D: Catastrophic forgetting in personalized LoRA
- E v2: Tool integration patterns in shipping personal AI systems

**Pending revisits not yet handled:**
- Tension #4 (Blank Slate scope) — small, can resolve quickly next session
- Priority 3: Architecture revisits including wall-philosophy vs graph-memory question
- Priority 4: Layer 3c full lock (now informed and ready, awaiting structured-revisit completion)
- Priority 5: Layer-by-layer continuation (3d, 3e, 4, 5, 6, 7) + Layer 1+2 detail
- Cycle 1 pitch (after Stage 0 complete)
- May 24/25 mobile brainstorm integration backlog (Section principles + Deployment Philosophy + parked items + Cosmos queue items)

**Next session resume point:**
- Open `docs/blueprint.md`. Confirm context loads.
- Process pending Cosmos results (A/B/C/D/E v2) when they arrive.
- Resolve Tension #4 (Blank Slate scope).
- Move to Priority 3 (architecture revisits — wall vs graph + others).
- Then Priority 4 (Layer 3c lock — already informed).
- Then Layer 2 dedicated agent-architecture design session (uses Query E v2 results + OJ source audit).

### Session 6 — 2026-05-28 (Cosmos completion + Agent OS integration)

**Done:**
- Resolved Tension #4 (Blank Slate scope clarification) — decision #45
- All 11 Cosmos queries delivered and processed (Q1-Q5, Q7, QA/B/C/D/E v2)
- Major Layer 6 reframe: memory-layer learning, NOT weight-based distillation (decision #39). LoRA fine-tuning rejected for v1/v2 based on Q A/B/C/D convergence.
- Layer 4 router refinements (#40) — framework-style failure handling added
- Layer 7 MCP server out — priority CONFIRMED HIGH (#41) based on widespread MCP adoption
- Three industry differentiator opportunities identified (#42) — registry trust, approval fatigue, failure semantics
- OpenJarvis tool architecture inherited as direct substrate (#43)
- CoT preservation rule locked for any future context distillation (#44)
- **Agent OS integration:** Oleg Kupshukov's "Agent OS" handbook reviewed — manual Notion-based solution to cross-AI context loss. Strong validation of kage's market thesis (engineers are solving this by hand because no automatic solution exists).
- **Five Memory Types locked (#46)** based on Agent OS pattern: Core / Procedural / Semantic system-of-record / Semantic vocabulary / Episodic provisional. kage automates capture; user confirms.
- **Three-mode user support (#47)** locked: pure kage local / hybrid kage+Notion mirror / Notion-canonical with kage as automation engine. Strategic positioning: kage doesn't compete with Notion.
- **Consequences-field-as-detection-signal (#48)** locked for Layer 6 design. kage must detect constraint-defining moments, not just decisions.
- Decisions #39 through #48 added (10 new locks).

**Pending Cosmos integration → DONE.** All 11 queries processed.

**Pending revisits:**
- Priority 3: architecture revisits (most absorbed by Cosmos batch; differentiator promotion question remains)
- Priority 4: Layer 3c full lock (fully informed, ready to lock)
- Priority 5: layer-by-layer continuation (3d, 3e, 4, 5, 6, 7)
- Layer 2 dedicated agent-architecture session (uses Q E v2 + OJ source audit)
- Cycle 1 pitch (after Stage 0 complete)
- Integrate Agent OS patterns into Layer 5 + Layer 6 design when those sessions happen

**Next session resume point:**
- Open `docs/blueprint.md`. Confirm context loads.
- Address remaining Priority 3 question: should "Learning + multi-modal memory + identity partitioning" be promoted to 4th differentiator NOW (strengthened significantly by Agent OS validation + Cosmos convergence)?
- Then Priority 4: lock Layer 3c with verified Cosmos picks.
- Then Layer-by-layer through Layers 3d, 3e, 4, 5, 6, 7.
- Then Cycle 1 pitch.

### Session 7 — 2026-05-29 (Layer 3c lock + 4th differentiator promotion)

**Done:**
- License verification on Cosmos-recommended models surfaced two real issues:
  - jina-embeddings-v3 is CC BY-NC 4.0 (non-commercial) — REJECTED
  - MemReranker-0.6B is API-only via hosted Memos service — REJECTED (violates local-first)
  - MemReranker-4B is downloadable, Apache 2.0, but 8.83GB bf16 — too heavy for v1
- Granite Embedding 311M R2 swapped in as default embedding model (Apache 2.0, decision #50)
- bge-reranker-v2-m3 confirmed as v1 reranker (Apache 2.0, decision #51)
- MemReranker-0.6B HF Discussions request pending (user-initiated) — if released publicly, swap-in candidate for v1.5
- MemReranker-4B Q4-quantized flagged as v1.5/v2 engineering project (quality validation needed)
- Layer 3c FULLY LOCKED (decision #49): BM25 + Granite + FAISS + LightRAG dual-level + RRF + bge-reranker + Graphify provenance + hybrid sync/async ingest
- Constraint Reconsideration Trigger pattern locked (#52) — addresses the over-restriction failure mode for constraint encoding
- 4th differentiator promoted (#53) — "Multi-modal memory layer with CGL, constraint encoding, identity-aware retrieval" added to §3
- §3 (Defensible Differentiator) updated to four real differentiators
- Cosmos Q F (4th differentiator novelty check) returned null retrieval — tool failure, not novelty evidence; doesn't disturb the case
- Cosmos Q I (rerankers / MLX search) returned null retrieval — same tool issue; recommendation defaulted to bge from audited facts (matched our independent reasoning)

**Layer 3c is the FIRST fully-locked layer of kage's retrieval pipeline.**

**Layer 3d also locked at directional altitude (Session 7 continuation):**
- 3-tier × 5-type orthogonal model (decision #54)
- CASCADE overflow strategy — recursive summarization rejected (decision #55)
- Multi-resolution cross-tool rendering — HOT constant, WARM scales (decision #56)
- Cosmos Q J returned real evidence after two prior null runs; validated the design with three refinements (orthogonal type×tier, cascade overflow, multi-resolution rendering)
- Type-aware rendering empirically validated (+4.4 pp from structure alone per GRAVITY benchmark)

**Pending (background, non-blocking):**
- MemReranker-0.6B HF Discussions response — if positive, v1.5 swap
- MemReranker-4B quantization quality validation — v1.5/v2 engineering project
- Cosmos tool reliability — track whether subsequent queries retrieve documents

**Pending revisits / design work:**
- Layer 3d (Tiered Assembly) design — next-up
- Layer 3e (Privacy / Disclosure) design
- Layer 4 (Multi-Vendor Router) design — Pattern 5 already locked directionally
- Layer 5 (Memory Storage) design — 5-type schema locked #46, needs operational design
- Layer 6 (Learning) dedicated design session — memory-layer learning, NOT LoRA
- Layer 7 (MCP Server out) design — priority HIGH per #41
- Layer 1 + Layer 2 detail
- Layer 2 dedicated agent-architecture session (Q E v2 + OJ source audit)
- Cycle 1 pitch
- Integrate Agent OS coexistence patterns into Layer 5 + Layer 6 design

**Next session resume point:**
- Open `docs/blueprint.md`. Confirm context loads.
- Layer 3c is locked. Move to Layer 3d (Tiered Assembly) design.
- After 3d → 3e → 4 → 5 → 6 → 7 → 1+2 detail → Cycle 1 pitch.

### Session 4 — 2026-05-23 (brainstorm integration + new principles)

**Done:**
- Reviewed personal-Claude brainstorm document (`Context/kage-brainstorm-session-may2026.md`)
- Locked the **10 Core Characteristics** with operational definitions
- Locked **6 new operating principles**: Transparency as core, Awareness over control, Options over suggestions, Build for now / architect for 3 years, Complete over fast (3-week plan deprioritized), Bold recommendation first
- Added decisions #21-25 covering new locks + Gemini Spark validation + MCP-as-distribution-standard signal
- Updated CLAUDE.md to surface the 10 characteristics as kage's identity card and add new operating rules
- Added memory entries for durable preferences ("complete over fast", "bold recommendation first" strengthened, "transparency as core")

**Deferred to in-session brainstorm (Tier 2 from brainstorm doc):**
- ~~Antigravity 2.0 as build harness — replaces OJ substrate?~~ **RESOLVED Session 4 → Option A-prime (decision #26).** OJ stays as substrate; adopt open AGENTS.md/SKILL.md spec; reject Antigravity runtime.
- App-launch as native kage capability — new Layer 0 or Layer 1 skill?
- Google-tools observation/logging loop — new layer or extension of Layer 6 (Learning T1)?
- Revisit Layer 7 (MCP server out) priority — promote to earlier cycle?
- Define what kage observes from Google tools and how it logs that
- SKILL.md loader scope ("how thin is thin?") — depth of integration between markdown spec and OJ BaseAgent registry
- Cross-tool portability angle — implications of SKILL.md format being readable in Claude Code / Cursor / Antigravity etc.

**Open from previous sessions (still unresolved):**
- Layer 3c lock (RRF vs alternatives, re-ranker choice, re-ranker in v1.0 or v1.5, sync/async tweaks)
- Cosmos research integration (when results arrive)

**Next session resume point:**
- Brainstorm Tier 2 technical reframings in order: Antigravity-2.0-as-harness, then app-launch, then Google-tools observation, then Layer 7 priority
- Lock Layer 3c (still PROPOSED — needs final discussion on the 4 open sub-decisions)
- Then Layer 3d (Tiered Assembly)
