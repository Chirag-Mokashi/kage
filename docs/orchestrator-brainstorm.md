# kage Orchestrator — Brainstorm Notes

*Status: BRAINSTORM — initial pass complete 2026-07-02. NOT a cycle pitch; direction only, still being shaped.*
*Name: TBD ("Orchestrator" for now). Trigger word: `okiro`.*
*Scope note: **calendar-write is a SEPARATE cycle** — deliberately excluded from this doc. The orchestrator will one day dispatch to a calendar-write arm, but that arm is designed elsewhere.*

---

## One-liner

kage's coordinating brain — the layer that turns your shorthand (a glance, a half-sentence) into resolved, executed action, running your redundant daily rounds like a personal assistant, using whatever tools are available.

## What it is

- An **Orchestrator** (supervisor / "Chief-of-Staff" pattern) that sits **above** the worker agents (Scout, Librarian, Monitor) and the arms. It coordinates; it is not itself a worker.
- Architecturally it is the **deferred "Orchestrator"** from the Layer 2 plan and the "agent loop / mediator" endgame — now made concrete.
- `okiro` is the **wake trigger** (the word you say). The Orchestrator is the thing it wakes.

## The goal (locked 2026-07-02)

> kage is the disciplined **HITL layer between me and the world** — it runs my redundant daily rounds like a personal assistant (mail across accounts, news, repos, projects, feeds), understands what I *mean* against my private partitioned memory, and drives **whatever tools are available** to keep me oriented and organized. It proposes and orients automatically; it mutates state only with my approval. It is the **COMPLEMENT** doing the disciplined routine I'd otherwise skip (the "morning newspaper").

## Positioning / moat

- NOT "private context vs the web." kage's arms already reach Google and anything else; kage can drive **any** available tool. The moat is that kage is the only thing that knows **what *I* mean** by a request — it resolves referents ("which Apple, which project") against partitioned memory.
- kage sits at the **intersection nobody occupies**: *know-what-I-see* + *run-my-rounds* + *act-through-my-own-tools* + **local, can't be acquired and switched off.**
- kage is the brain on top; all tools sit underneath.

## Governance — the autonomy line (already kage's locked rule)

> **kage proposes, orients, and fetches automatically. It mutates state only with my approval.**

- **Automatic (no approval):** read / orient / fetch / maintain — Scout news+repos, Monitor observe+digest, Librarian distill, reindex, opening the daily circuit. (Reversible, low-stakes.)
- **Approval-gated:** add/delete memory, promote a staged note, act on my behalf, any write. (Irreversible / mutating.)
- Approval UX = an **"Evidence Pack"**: compress *what it wants to do + why* into a sub-15-second nod.

## Architecture

```
             ┌──────────────────────────────────────────┐
   okiro  →  │   THE ORCHESTRATOR  (the "brain")          │  plan · dispatch · aggregate · HITL
             │   resolve intent → plan → execute → revise │
             └──────────────┬───────────────────────────-┘
        dispatches to        │   (workers don't talk to each other)
   ┌──────────┬──────────────┼───────────┬──────────────┐
  Scout    Librarian      Monitor      Arms          Layer 4 router
 (research)(memory HITL) (observe)  (mail/web/…)   (query→model)
   ── existing workers ──            ── existing tools ──
```

- Pattern: **orchestrator-worker / supervisor** (≈70% of production multi-agent systems).
- Internal shape: **Planner-Executor** (plan upfront → execute steps → revise on feedback) + **calibrated/tiered HITL**.
- ADK fit: a root/coordinating agent with the workers as sub-agents (Scout is already a SequentialAgent — composes).
- Scale: only 3 workers → well under the ~8-agent fragility threshold. Safe.

## The disambiguation thesis (canonical example)

Input: *"Apple wasn't in that project."*
1. **Resolve referents** — "that project" → active project (`kage use`); "Apple" → which Apple? disambiguated against *that project's* memory.
2. **Read intent** — correct a note? update memory? go research it?
3. **Plan tools** — memory write (Librarian) · research (web arm) · both.
4. **Assemble context** — pull the right memory to ground the action.
5. **Execute** — across whatever tools fit, on approval.

Steps 1/2/4 (resolve · intent · context-assembly) are the unique value — nobody else has the partitioned memory to do them.

## The daily circuit (the "rounds" it ushers me through)

- **Mail** — across accounts (Gmail + Outlook/NEU). Open the native surface; I read it.
- **Current / industry** — Google News, GitHub repos, what could affect me.
- **Projects** — e.g. kage, HSI — kept apart by the **identity × project partition** (this is *why* that partition exists).
- **Downtime feeds** — Instagram, YouTube, TED — relevant, not random.
- Principle: kage is an **usher, not a summarizer** — it opens the surfaces I already know how to read; it does not try to summarize my inbox.

## Autonomy ladder (build bottom-up)

```
   3. PROACTIVE   notices context, offers action unprompted   ← later
   2. SUGGESTED   I glance; kage surfaces "want me to…?"       ← soon
   1. TRIGGERED   I hotkey "act on this"; propose; I approve   ← FIRST
```

## Interaction model / inspiration

- Copy the proven **Raycast / Gemini "select + act"** mechanic: hotkey → grab the focused item → propose a contextual action → I approve. But **locally, through my own tools** (Google shipped the same interaction in the cloud — validation, not competition).
- kage's opening vs Raycast: Raycast's AI is *conversational, not action-oriented.* kage is the **action layer** on top of the frontmost-context idea.
- Generalized "Circle to Search" — but the action is context-appropriate across my arms, grounded in my private memory.

## What already exists (reuse — jugaad)

- **Scout** = daily news + repo scan. **Monitor** = observer (knows what I'm doing, AX daemon). **Librarian** = memory curation that already proposes automatically + mutates only on approve/reject.
- Arms (mail/web/browser), Layer 4 router, MCP client (Cycle 11), streaming (Cycle 10), the `okiro` keyword.
- → The "automatic tier" is *partly running today.*

## What's missing to build

1. **The `okiro` conductor** — the human-facing daily circuit.
2. **The intelligence layer** — context/utterance → resolved action (the "which Apple, which project" brain).
3. **Approval-gated write arms** — first crossings from *suggest* to *execute*. (Calendar-write = **separate cycle**, not here.)

## Landscape takeaways (research 2026-07-02)

- Market split into three tiers that don't unify: **briefing** (Reclaim/alfred_/Google — bland, cloud), **chief-of-staff** (Lindy/Ohai — proactive but cloud + credit-per-action + permission-hungry + brittle on complex), **screen-context** (Screenpipe/Highlight — passive memory, no action).
- **Rewind** (screen-context leader) was acquired by Meta Dec 2025 and its capture killed → validates local-first ownership ("can't be acquired and switched off").
- **MCP** is now the Linux-Foundation standard → "drive anything available" gets cheaper because kage already speaks it.

## Pull candidates (don't build)

- **MCP ecosystem** broadly — kage is already a client; pull tools as arms.
- **Screenpipe** (open-source, local 24/7 screen memory) — heavier fallback for "what am I looking at" if Monitor's AX proves too coarse. (Lean: AX is lighter + more scoped; Screenpipe is a fallback.)
- **Khoj / Goose** — reference architectures for local automation + MCP-first runtime, not to adopt wholesale.

## Non-goals / scope boundaries (v1)

- **No UI** — leverage the native apps already on the Mac.
- **No voice, no notifications, no all-day ambient mode** — all deferred.
- **No calendar-write here** — separate cycle.
- **No autonomous mutation** — anything that changes state is approval-gated, always.

## Still open — to brainstorm (initial pass only)

- Positioning: is the "intersection nobody occupies" framing right for v1, or too grand?
- Screen sensing: Monitor AX vs pulling Screenpipe — when is fuller screen memory worth it?
- How the circuit **advances** (keypress wizard? watch me switch away? time?).
- The intelligence layer's **resolution mechanism** — how it actually pins "which Apple, which project" (retrieval? active context? an LLM disambiguation step?).
- First surface to prove the loop (Mail beachhead was discussed).
- Where the proactive rungs (2, 3) start earning their place.

## Research sources

- Orchestration patterns: augmentcode.com/guides/swarm-vs-supervisor · decodethefuture.org/en/multi-agent-systems-explained
- Chief-of-staff pattern: bbinto.medium.com/building-my-own-ai-chief-of-staff
- HITL / calibrated autonomy: myengineeringpath.dev/genai-engineer/human-in-the-loop
- Plan-and-execute: langchain.com/blog/planning-agents
- Screen context: github.com/screenpipe/screenpipe · shadow.do/blog/ai-that-reads-your-screen-on-mac-2026
- Select + act: android.gadgethacks.com (Gemini "Select from screen") · raycast.com
- Open-source assistants: github.com/khoj-ai/khoj · vellum.ai/blog/best-open-source-personal-ai-assistants
- Competitor limits: zapier.com/blog/lindy-review · get-alfred.ai/blog/best-ai-chief-of-staff-tools
