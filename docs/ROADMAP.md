# kage — Roadmap

> ⚠️ **SUPERSEDED — Session-1 legacy (2026-05-21).** Everything below predates the Odysseus substrate swap (#81) and the thin-slice pivot (#104). Its "Fork OpenJarvis," FAISS, Antigravity, and 7-cycle plan are **OUTDATED**. **Current truth:** [blueprint.md](blueprint.md) (all decisions) + [cycle-1-thin-slice.md](cycle-1-thin-slice.md) (the real Cycle 1 = v0.1 thin slice). This file will be rewritten when v0.1 ships and the real cadence is known.
>
> **Living document.** This is the working plan, not a contract. Updated at the end of each cycle based on what we learned. The full vision goes to v1.0; the *path* there is iterative.
>
> **Cadence:** Shape Up cycles, ~2 weeks each. Each cycle has a Pitch (written before) and a Retrospective (written after).
>
> *Last updated: 2026-05-21 (Session 1 — planning)*

---

## North Star (the long-term vision)

kage is the **invisible local context layer** between Chirag and the AI-saturated device ecosystem. The **core differentiator** is its **context engine** — project-partitioned, identity-aware, dynamic memory retrieval that decides what slice of context applies to any query in any context. Everything else (routing, MCP server, privacy, learning) is downstream infrastructure that consumes the context engine's output. 2-5 year horizon: ambient, multi-device, voice-first.

This roadmap is the **2026 surface** of that vision: getting from "nothing" to a real working v1.0 that demonstrates the context engine thesis.

---

## Where we are

**Phase 0 — Discovery & Planning** (current, ~1-2 sessions remaining)

Goal: enough decisions to write a real Cycle 1 pitch.

- [x] OpenJarvis audited (provenance, scope, license, agent inventory)
- [x] kage framing locked: local context broker + multi-vendor router (not "another assistant")
- [x] SDLC starter pack adopted (Shape Up · GitHub Flow · ADRs · CC · CI · pre-commit · semver)
- [x] Visual tracker established (`docs/architecture.md`)
- [x] Dual goal noted (ship kage + learn industry SDLC)
- [x] Learning model proposal (T1 prompt-only · explicit+implicit signals · per-identity scope) — pending final discussion
- [ ] Widen privacy / selective-disclosure mechanics
- [ ] Widen memory shape & storage
- [ ] Widen modality + proactivity (batchable)
- [ ] Compile **Discovery Doc** — single artifact capturing everything decided
- [ ] Write **Cycle 1 Pitch** — the first thing we build

---

## The build phases — overview

Each phase is one Shape Up cycle (~2 weeks). Cycles 1-3 = v0.1. Cycles 4-7 = v1.0. Each cycle ends with a working, shippable artifact, even if small.

| Cycle | Phase | Goal | Deliverable | Status |
|---|---|---|---|---|
| **1** | Foundation | Fork OJ, set up SDLC infra, get OJ running locally | `kage doctor` works on your M5 Pro | ⚪ planned |
| **2** | **★ Context engine v0** | Project-partitioned memory + dynamic retrieval + context assembly | Given a query, kage returns the right context slice from the right project | ⚪ planned |
| **3** | **★ Context engine v1** | Identity scoping + multi-project queries + relevance ranking | "What do I know about lung capacity research?" returns NEU-scoped, LLM-Research-tagged context | ⚪ planned |
| **4** | Router + interface | Minimal multi-vendor router + MCP server delivering assembled context | Claude Code in this repo can query kage for context; query goes to Qwen or Claude based on simple rules | ⚪ planned |
| **5** | Privacy layer | Per-identity allowlists, redaction, audit log | "What did kage share with whom this week?" report | ⚪ planned |
| **6** | Learning T1 | Preferences + entities + implicit learning feeds back into context engine | kage learns which memories were useful for which query types | ⚪ planned |
| **7** | okiro + UX + v1.0 polish | `okiro` trigger, menu bar status, confirmation system, public README | Tag `v1.0.0`, ROADMAP refreshed to v2.0 horizon | ⚪ planned |

**Estimated calendar:** 7 cycles × ~2 weeks = **~14 weeks (≈3.5 months)** from Cycle 1 start to v1.0. Includes buffer for cooldown weeks between cycles (Shape Up standard).

---

## Phase detail

> ⚠️ **STALE BELOW** — phase details written for the original cycle order. Cycle table above (with context engine at Cycles 2-3) is authoritative as of 2026-05-21. Will be rewritten next session after Chirag confirms the corrected high-level ordering.

### Cycle 1 — Foundation (~2 weeks)

*The unsexy but essential setup. Without this, every later cycle pays interest.*

- Fork `open-jarvis/OpenJarvis` → `Chirag-Mokashi/kage` (private)
- Clone locally to `~/Projects/kage`, replace current empty repo
- Set up SDLC infra:
  - `docs/adr/` folder + ADR template + ADR-001 (kage's strategic framing)
  - `.github/workflows/ci.yml` (pytest + ruff on every PR)
  - `.pre-commit-config.yaml` (ruff format + lint)
  - `README.md`, `ROADMAP.md` (this file), `CHANGELOG.md` (keep-a-changelog format)
  - GitHub Issues + Project board configured
  - Conventional Commits adopted (commitlint or just discipline)
- Verify OJ baseline works: `uv sync` → `uv run jarvis` → smoke test
- First PR merged to `main` (the SDLC infra itself)
- **Done when:** `jarvis doctor` reports green on your M5 Pro AND a green CI run on a real PR

### Cycle 2 — Core broker (~2 weeks)

*The first real kage code. Minimum viable broker.*

- ADR-002: routing logic & signal source
- Memory module: thin wrapper over OJ's memory; `kage memory add`, `kage memory recall`
- Identity context: detect Personal vs. NEU from active project / Chrome profile / explicit flag
- Router: minimal 2-vendor (Qwen + Claude) with hardcoded rules for v0.1
- End-to-end command: `kage ask "<question>"` → routes → returns answer
- **Done when:** one round-trip query works locally with both Qwen and Claude paths

### Cycle 3 — MCP server (~2 weeks)

*kage becomes accessible from outside. The real differentiator activates.*

- ADR-003: MCP contract & endpoints
- Implement MCP server exposing memory + context-fetch endpoints
- Configure Claude Code (this very tool) to use kage as MCP server
- Selective-disclosure logic: per-tool memory slicing
- **Done when:** Claude Code can ask kage "what does Chirag know about X?" and get a curated answer

→ **Tag `v0.1.0`. Stop. Reassess.** Use kage daily for 1-2 weeks. Capture what's painful / what's missing. THEN start Cycle 4.

### Cycle 4 — Privacy layer (~2 weeks)

- Per-identity allowlists (which entities can be shared with which tools)
- Redaction rules (PII, sensitive topics)
- Audit log: `~/.kage/audit/<date>.jsonl`
- `kage audit` command: "show me what was shared this week"

### Cycle 5 — Learning T1 (~2 weeks)

- `~/.kage/learning/{personal,neu,shared}/` structure
- `kage remember <fact>` (explicit signal)
- Edit-tracking on outputs (implicit signal)
- Preference injection into prompts
- `kage forget <thing>` for reversibility

### Cycle 6 — okiro + UX (~2 weeks)

- `okiro` startup script
- Mac menu bar app (status indicator: active model, token bar, $ spend)
- Confirmation system for write actions (cross-cutting, integrated through prior cycles)

### Cycle 7 — v1.0 polish (~2 weeks)

- Morning digest end-to-end with kage routing
- Public-facing README
- Demo recording
- ROADMAP refreshed to v2.0 horizon (voice, mobile, observation, T2 DSPy)
- Tag `v1.0.0`

---

## What's NOT in v1.0 (and that's deliberate)

These are real and valuable but **deferred** to keep v1.0 shippable:

- Voice modality (Wispr Flow integration)
- Mobile / hub-and-spoke device topology
- Observational learning (screen, IDE watch)
- DSPy programmatic optimization (T2 learning)
- LoRA fine-tuning (T3 learning)
- Übersicht HUD widget
- Skill marketplace integration (OJ's agentskills.io)
- Notion / GitHub / additional MCP connectors beyond Google
- Cross-device sync

These go on the v2.0 horizon, which we'll plan after v1.0 ships.

---

## Risk register (industry practice — list known risks early)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OJ structure doesn't accommodate the broker pattern cleanly | Medium | High | Cycle 1 audit + Cycle 2 spike will tell us early. Worst case: lift components, build broker independently. |
| MCP ecosystem shifts under us mid-build | Low-Medium | Medium | Pin MCP SDK versions; design our adapter so swapping is contained. |
| Scope creep on the broker logic | High | High | Shape Up's "fixed time, variable scope" discipline. Cut features, not extend cycles. |
| Multi-account routing has edge cases we can't predict | Medium | Medium | Start with explicit-only switching in Cycle 2; auto-detection in Cycle 4+ once we see patterns. |
| Stanford SAIL pushes upstream changes that conflict | Medium | Low-Medium | Maintain clean separation: kage code in its own modules; OJ code untouched. Sync weekly. |

---

## How this connects to your dual goal

Every cycle deliberately exercises real industry practice:

- **Cycle 1** teaches you repo setup, CI configuration, ADR discipline
- **Cycle 2** teaches you incremental design, ADR-driven architecture decisions
- **Cycle 3** teaches you protocol design (MCP) and API contracts
- **Cycle 4** teaches you cross-cutting concerns and audit/observability
- **Cycle 5** teaches you on-device personalization patterns
- **Cycle 6** teaches you Mac-native UX, system integration
- **Cycle 7** teaches you release engineering, documentation, demo polish

By v1.0, you'll have shipped: 7 cycles, ~30+ PRs (multiple per cycle), ~15-20 ADRs, full CI/release pipeline, public repo, plus 2-3 upstream PRs to Stanford SAIL OJ. **That's a resume.**

---

## Open questions to resolve before Cycle 1

These need answers in remaining Phase 0 work:

1. Learning model: T1 details — locked except for Chirag's pending discussion
2. Privacy mechanics: per-identity allowlists schema — needs design session
3. Memory shape: keep OJ's FAISS+BM25 as-is, or layer structured store on top? — design call needed
4. Modality: text-only v1, or voice from day one? — likely text-only
5. Repo strategy detail: how do we organize `src/` to keep kage code separable from upstream OJ for clean sync? — needs ADR-001

---

*Next session: continue widening dimensions, then write Cycle 1 pitch.*
