# kage — State of the System & Horizon

*Created: 2026-07-01. A reading snapshot of where kage is on main @ v0.22.0, what
"v1" means, and what kage can still become. Companion to the security track in
[security-audit-2026-07-01.md](security-audit-2026-07-01.md) (that one is being
fixed via [cycle-23-gate-hardening.md](cycle-23-gate-hardening.md)).*

*This doc is the CAPABILITY / DIRECTION reading. It changes nothing; it's a map.*

---

## The one-line status

> kage has **fully shipped the BROKER** (its v1 *mechanism*) — all 16 broker
> properties in blueprint §2 are implemented. What it has NOT built is the part
> that makes it a **MEDIATOR / COMPLEMENT** — its actual *identity*. Everything
> today is **pull** (you ask, it answers). The identity is **push** (it covers
> the gap you'd otherwise neglect). That gap is the roadmap.

---

## Smoke test — GREEN (2026-07-01)

`init` / `remember` / `recall` / `list` / `status` / `doctor` all pass. Ollama +
qwen3:14b up; openai / gemini / groq keys live; MCP server + audit log healthy.

**One real gap:** `pyobjc-framework-ApplicationServices` is not installed, so
**Monitor's macOS Accessibility (AX) daemon cannot run on this machine** — the
observe pipeline is dark until that dependency lands.

---

## What's shipped (through Cycle 22, v0.22.0)

```
   CORE ENGINE          remember / recall / forget / import / reindex
                        markdown source-of-truth + SQLite FTS5 + Chroma vectors
                        recursive chunking + bge-reranker retrieval
   PARTITIONING         identity × project 2-D matrix; scoped/baseline/pending
                        hard identity wall; kage use / where (manual context)
   CONVERSATION         kage chat REPL + slash commands; stateful sessions
   PRIVACY (3e)         disclosure gate; reversible PII masking; sensitive vault
   ROUTING              multi-vendor router; keyword task-class classification
   INTERFACES           MCP server (4 tools); arm routing (shell/stdio/sse)
                        gmail + browser + calendar arms
   AGENTS (ADK)         Scout (research) · Librarian (curate) · Monitor (observe)
                        pipeline plumbing G01-G10
   LEARNING             kage learn — ProTeGi prompt learning from corrections
   QUALITY              599 tests / 10 files / CI green · MIT licensed
```

All 16 v1 **broker** properties from blueprint §2 are done.

---

## When can you ship "v1.0"?

**Functionally, you're already there.** v1.0 is a labeling call, not a build call.
The only blueprint-listed v1 item never built is `kage test` (#98) — the
local-vs-cloud benchmark harness — and that one genuinely needs real usage/
correction data first (which `kage learn` now generates), so it's better as v1.1.

Honest path to *calling* it v1.0:

| Task | Effort |
|---|---|
| Fix gap-tracker doc (G01-G10 are done in code, still say OPEN) | ~10 min |
| Update CLAUDE.md header (says v0.20.0) | ~30 s |
| Backfill missing semver tags (v0.13, v0.16–v0.21) | ~5 min |
| (optional) `kage test` harness | ~1 cycle → defer to v1.1 |

Recommendation: **ship v1.0 without `kage test`.** Build the benchmark from real
correction data afterward.

---

## What more kage can be — the horizon

Reading the blueprint's final goals through the Jarvis reference produces the
SAME three gaps either way. This is not "add features" — it's closing the
distance from BROKER (shipped) to the identity kage was defined as.

```
   BROKER  ────────────►  MEDIATOR  ────────────►  COMPLEMENT
   (shipped, v1)          (v1.5)                    (v2+)

   the 3 gaps that move kage rightward:
   ┌────────────────────────┬──────────────────────┬─────────────────┐
   │ 1. Auto-context (3a)    │ knows WHERE you are   │ Aware           │
   │ 2. Push / interrupt     │ SPEAKS when it matters│ Silent+Controlled│
   │ 3. Agent loop           │ plans + EXECUTES      │ Mediator        │
   └────────────────────────┴──────────────────────┴─────────────────┘
```

### Near — finishes v1's own thesis

- **Layer 3a auto-context cascade** — the blueprint's own "★ BUILD, kage-unique."
  Today `context.py` is only explicit-arg → sticky (`kage use`) → `personal`
  fallback. NO git-repo or cwd inference. Adding it means kage stops needing to be
  steered — it's what makes *Aware* real. **Highest-leverage unbuilt v1 piece.**
- **`kage test` harness (#98)** — now has fuel (correction logs from `kage learn`).

### Mid — crosses into MEDIATOR (v1.5)

- **The interrupt-threshold model** — the Jarvis *keystone* (see below). Monitor
  already *watches*; it has no way to *speak*. A single push channel (macOS
  notification arm) + a threshold gate ("silent baseline; interrupt only when
  priority crosses OR a live-critical value is changing") turns kage from a diary
  into a complement. Calibrate FAR below JARVIS's cockpit frequency.
- **Interactive agent loop** — today `_detect_arms` is single keyword → one arm.
  Plan-then-execute (retrieve → call arms → synthesize) is what "a second layer
  between intent and the world" actually requires.
- **Safety Copilot pattern** — before risky arm actions, surface preconditions +
  what could go wrong. Risk-tiered, not nagging.

### Far — COMPLEMENT fully expressed (v2+)

Voice-first (LiveKit), multi-device mesh, action substrate, device-aware routing,
overnight consolidation pass. All architecture-ready; none v1.

---

## The Jarvis lens (from docs/jarvis-design-reference.md + memory)

The reference's own filter: *a fictional behavior is useful only after* asking
which of the 10 characteristics it maps to, then IMPLEMENT / ADAPT / REJECT. The
high-value output is the REJECT column ("don't build Clippy with a British
accent"). Behaviors marked **IMPLEMENT** that kage has NOT yet built:

| Jarvis behavior | Maps to | Built? |
|---|---|---|
| A · context-aware surfacing + on-the-fly analysis | Aware + context engine | partial (Scout researches; no "surface for current task") |
| B · proactive monitoring + early warning | Aware + Silent | partial (Monitor digests; no early warning) |
| **C · interrupt prioritization (the keystone)** | Silent + Controlled | **NO — no push channel at all** |
| D · norm-awareness / step-tracking | Aware | no |
| E · provisional, collaborative recommendations | draft-and-confirm | partial (Librarian HITL) |
| F · constraint awareness + graceful degradation | Aware + Controlled + Local | partial (doctor, router fallback) |
| G · terse intent from shorthand | Seamless | partial (okiro, ask) |
| **Safety Copilot** (pre-risk briefing; Mark 45 / Extremis) | COMPLEMENT diligence | **NO** |

**Synthesis #1 (the keystone):** JARVIS is *silent by default while monitoring
continuously, and speaks ONLY when (a) priority crosses a threshold or (b) a
live-critical value is changing.* Not "proactive vs silent" — **silent baseline +
threshold-triggered interrupt.** This is the single biggest missing behavior and
it resolves the tension between kage's `Silent`/`Invisible` locks and being a
useful complement.

**Synthesis #2:** JARVIS's "intelligence" is mostly *contextual relevance* —
"knew which fact to check," "keyword finds everything." That's exactly the
project-partitioned context engine kage already has. The metaphor validates the
central bet: JARVIS is a context engine with a charming voice.

**Cautions (don't cargo-cult):** don't fall in love with the holographic screen
(UX is not the moat); calibrate the interrupt threshold FAR below JARVIS —
kage is at a desk, not a cockpit; importing JARVIS's interrupt frequency would
make kage feel frantic.

---

## Doc debt noticed (cheap, not security)

- `docs/gaps/gap-tracker.md` — all 10 entries say `OPEN`; the code has every fix
  (verified). Never updated after Cycle 17 merged.
- `CLAUDE.md` header still says "Cycle 20 merged — v0.20.0" (now v0.22.0).
- `cli.py:1711` ponytail's "(Cycle 22)" forward-reference is stale/wrong
  (Cycle 22 shipped as `kage learn`; the context-blinding fix is Cycle 23).
- Missing semver tags: v0.13, v0.16–v0.21.
- `pyobjc-framework-ApplicationServices` not installed → Monitor AX daemon dark.

---

## Suggested sequence after Cycle 23 (security) lands

1. Doc-debt cleanup + tag v1.0 (fast, closes the "is it v1?" question).
2. **Layer 3a auto-context** — the highest-leverage unbuilt v1 piece; makes
   *Aware* real.
3. **Push / interrupt channel** — the Jarvis keystone; turns Monitor's watching
   into a complement.
4. Interactive agent loop → full MEDIATOR.

(Kaggle deadline is July 6 — freeze scope, ship the submission, then start #2.)
