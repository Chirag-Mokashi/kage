# kage — Fictional-AI Design Reference

> **Status:** Stage 0 enrichment / parking-lot material. This is a DESIGN
> REFERENCE for the post-v1 personalization layer — not a locked blueprint
> decision. Nothing here is committed to the architecture.
>
> **Purpose:** kage's north-star metaphor is JARVIS (and other fictional
> AIs). This file turns that vibe into a concrete keep/kill catalog so the
> metaphor produces design decisions, not cargo-cult tropes.
>
> *Last updated: 2026-06-01.*
>
> *Companion docs:*
> - [blueprint.md](blueprint.md) — the canonical Stage 0 planning state
> - [architecture.md](architecture.md) — visual system map

---

## How to read this file

Fiction is written for **drama**, not for good assistant design. Much of
what makes JARVIS delightful on screen — constant banter, omnipresence,
talking in every scene — directly **violates kage's locked `Silent` and
`Invisible` characteristics.** So a fictional behavior is only useful once
it has been filtered:

```
   SCENE / BEHAVIOR → which of the 10 characteristics? → IMPLEMENT / ADAPT / REJECT
```

The **REJECT / "what NOT to build"** column is the high-value output. If you
copy JARVIS uncritically you build Clippy with a British accent.

The 10 locked characteristics (see [blueprint.md](blueprint.md)):
`Seamless · Transparent · Aware · Local · Silent · Broker · Adoptable ·
Controlled · Invisible · Modular`.

---

## Keep/kill catalog — MCU JARVIS (Iron Man 1 & 3)

### A · Context-aware surfacing + on-the-fly analysis
*Generates the right view for the engine work (component view + live duty
cycle / brake temp / torque); runs a simulation to diagnose; "knew WHICH
fact to check" (fixed-wing, SR-71 altitude record).*
- **Maps to:** `Aware` + the context engine.
- **Verdict:** **IMPLEMENT** the kernel — surface what's relevant to the
  current task and run analysis proactively. **REJECT** the holographic UI
  itself (flash; UX is not the moat). *The magic is relevance, not the screen.*

### B · Proactive monitoring + early warning
*Notices ice build-up before Tony does; recommends not pushing higher.*
- **Maps to:** `Aware` + `Silent`.
- **Verdict:** **IMPLEMENT.** "Notice the problem before you do" covers the
  user's gap. Watches quietly, speaks only when it matters.

### C · Interrupt prioritization / attention management
*Inbound missile while Tony is busy flying; retargeting alert; quick-boot
handles survival-critical items first; controlled fall at 2% power.*
- **Maps to:** `Silent` + `Controlled`.
- **Verdict:** **IMPLEMENT** — the keystone behavior (see Synthesis #1).

### D · Norm-awareness + step-tracking
*Flight pre-check / virtual walk-around; IM3 safety briefing + tracking the
injection steps one by one.*
- **Maps to:** `Aware` (knows the standard procedure) + awareness-over-control.
- **Verdict:** **IMPLEMENT.** Surface the standard procedure the user would
  otherwise forget. Anti-nag rule applies — except live-critical values (see F).

### E · Provisional, collaborative recommendations
*Exoskeleton offered as "base solution, not final"; renders the suit to
Tony's proposed specs; incorporates his improvements.*
- **Maps to:** `Aware` + the draft-and-confirm flagship.
- **Verdict:** **IMPLEMENT** "offer a provisional starting point, then
  iterate." **ADAPT** the speculative leap ("flew high → suggest planetary
  travel") — goal-inference over-reaches easily; keep it rejectable, never assumed.

### F · Constraint awareness + graceful degradation
*Knows the OLD arc reactor's capacity; states limits up front; flags battery
drain from flight; at 2% does a controlled gradual fallback; repeats the
power warning.*
- **Maps to:** `Aware` + `Controlled` + `Local`.
- **Verdict:** **IMPLEMENT.** kage knows its OWN real limits (local-model
  capacity on 24GB, API / cost / rate limits, context window) and degrades
  gracefully. **Note:** the repeated power warning is the **anti-nag
  EXCEPTION** — re-surfacing is correct when a value is critical *and* changing live.

### G · Terse intent from shorthand
*Keyword-level commands ("hulk — news / footage") expand into a full search,
grounded in context.*
- **Maps to:** `Seamless` + activation-energy reduction.
- **Verdict:** **IMPLEMENT.** A keyword + the user's context should be enough;
  no carefully-worded query required. Lower input friction = lower starting cost.

### H · Pattern recognition / cross-referencing
*Spots the similarity between the bombs while analysing the crime scene.*
- **Maps to:** `Aware` + the context engine (linking across data).
- **Verdict:** **IMPLEMENT.** Connect current data to past / related data.

### I · Modular add-on, not core integration
*Hulkbuster is bolted ON TOP of the HUD as a separable tool — deliberately
NOT integrated into the core, to avoid "unnecessary complications."*
- **Maps to:** `Modular` (the characteristic, dramatized).
- **Verdict:** **IMPLEMENT.** Validates an existing kage decision: new
  capabilities and the personal layer PLUG IN as MCP-style tools; they never
  bake into the core. JARVIS makes the same call kage already made.

### J · Durable invariant protocols
*After JARVIS's "death," his memories scatter but the protocols are never
lost; priority is to protect the protocol.*
- **Maps to:** `Local` + kage's sacred invariants (always-confirm-writes,
  privacy partitioning).
- **Verdict:** **IMPLEMENT.** Core rules survive crashes / restarts — they're
  invariants, not optional state. On-brand with local-first.

---

## Synthesis

**1 · The interrupt-threshold model (keystone).** Resolves the open question
of *how much kage is allowed to push the user* given `Silent` / `Invisible`.
JARVIS is **silent by default while monitoring continuously, and speaks ONLY
when (a) priority crosses a threshold** (incoming missile) **or (b) a
live-critical value is changing** (power at 2%). Not "proactive vs silent" —
*silent baseline + threshold-triggered interrupt.*

**2 · JARVIS's "intelligence" is mostly contextual relevance.** "Knew which
fact to check," "keyword → finds everything," "spotted the bomb pattern" — all
retrieval-of-the-right-thing-for-the-context, i.e. exactly what kage's
project-partitioned context engine is for. The metaphor quietly validates the
central bet: *JARVIS is a context engine with a charming voice.*

---

## Cautions

- **Don't fall in love with the screen.** The auto-generated holographic UI
  is the most cinematic and the least important. UX is not the moat; the
  behavior (right info, right moment) is everything.
- **Calibrate the threshold far below JARVIS.** Every scene above is a
  real-time, life-or-death cockpit. kage operates at a desk. Same
  interrupt-threshold model, *much* higher and quieter threshold — importing
  JARVIS's interrupt frequency would make kage feel frantic.

---

## Backlog

- [ ] Broaden beyond JARVIS for free anti-patterns: HAL 9000 (trust/control
  failure), Samantha / *Her* (over-attachment), TARS / *Interstellar*
  (`Controlled` dramatized via adjustable honesty/humor settings).
- [ ] Fold confirmed IMPLEMENT behaviors into the personal-layer design when
  Stage 0 closes and that layer is taken up.
