# CLAUDE.md — kage

*Entry point for any Claude Code session in this repo. Lightweight orientation only — the canonical planning state lives in [docs/blueprint.md](docs/blueprint.md).*

*Last updated: 2026-07-04 (through Cycle 28 in progress — Monitor AX daemon wiring fixed; Scout provider hardened)*

---

## Who I Am

- **Name:** Chirag Mokashi
- **Program:** Northeastern University — Masters in Applied AI
- **Hardware:** MacBook Pro M5 Pro, 24GB unified memory
- **GitHub:** Chirag-Mokashi
- **Email:** school@example.com

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

## Operating Value: Jugaad (above the 10) — locked 2026-06-10

**jugaad** (जुगाड़) — kage's *spirit*, sitting above the 10 characteristics (those are system properties; this is the lens for WHAT kage reaches for). Frugal, resourceful ingenuity under constraint: extract maximum capability from what you already have; route *around* artificial constraints (paywalls, missing APIs, double-billing) using existing resources rather than paying to remove them. Canonical example: drive the subscription web UI you already pay for instead of paying again for the API.

**Guardrail (inseparable from jugaad):** jugaad governs WHAT we reach for and HOW we route around constraints — *never how we build*. The workaround is resourceful; the implementation stays clean, tested, and complete. Jugaad is resourceful in *what*; **Complete over fast** governs *how*. They check each other.

## Current State

**Working CLI exists.** The repository is no longer purely Stage 0 planning: `src/kage/cli.py` implements the headless local broker thin slice and all cycles through 25.

Current implemented surface (through Cycle 25, v0.25.0; Cycle 26 calendar-write built on branch, v0.26.0):
- local markdown source of truth under `~/.kage/memory`
- SQLite FTS5 index and project partition filter
- ChromaDB chunk/vector index with `kage reindex`
- recursive chunking + bge-reranker retrieval (Cycle 8)
- identity × project wall (Cycle 9); active context via `kage use` / `where` (Cycle 10.5)
- stateful sessions + `kage chat` REPL, safe model-switching (Cycle 10)
- 3e disclosure gate — local-only notes hard-blocked; PII reversibly masked before cloud dispatch and restored in the response (Cycle 7 → Cycle 21)
- `remember`, `import`, `recall`, `ask`, `list`, `forget`, `status`, `doctor`, `chat`, `use`, `where`, `arm`
- local Ollama answering by default
- cloud answering via named providers (`claude`, `openai`, `gemini`, `groq`, `perplexity`, plus user config)
- **MCP client / arm routing (Cycle 11):** `_detect_arms` keyword routing, `_call_arm` graceful fallback, audit log. Three transports — `shell` (local command), `stdio` (local MCP process), `sse` (remote MCP). First live arm reads the local macOS Calendar via `osascript`/Calendar.app (`shell`, zero OAuth/cloud; `icalbuddy` was the original transport, replaced after it broke on macOS 16).
- MCP server (`kage mcp serve`) exposing `kage_recall`, `kage_remember`, `kage_ask`, `kage_status` (Cycle 6)
- **Modularity (Cycle 12):** 25 modules, injectable runtime seams, ProviderRegistry + ArmRegistry, egress golden tests
- **Arms expansion (Cycle 13):** gmail arm (osascript/Mail.app, zero OAuth) + browser arm (Playwright MCP, headless stealth)
- **Scout agent (Cycle 14):** proactive ADK Workflow — ScoutBroad (local Qwen3) shortlists → ScoutIntegrate (cloud) writes digest; 5 sources; two-stage deep fetch via Jina/GitHub API/Reddit body (Cycle 20). **Working cloud provider: `openrouter-reason` (nvidia/nemotron-3-ultra-550b-a55b:free)** — `openrouter-free` hallucinates (calls `scout_recall` then writes about kage's own docs); Gemini via LiteLLM silently writes 0 chars to `output_key` (needs native ADK `Gemini()` integration, deferred). Confirmed producing real 23K-char reports with correct Tier 1/Tier 2 structure.
- **Librarian agent (Cycle 15):** ADK LlmAgent, 3e-gated distill-and-judge, HITL staging → approval pipeline, sole memory writer
- **Monitor agent (Cycle 16 + 20):** macOS AX daemon (observe.py) captures app-switch/typing-pause events → `observations-YYYY-MM-DD.jsonl`; cadence split: observe runs every 5 min (launchd StartInterval), digest runs 07:00 daily (StartCalendarInterval); `kage monitor observe/digest/run/install/uninstall/status/last`. **AX daemon wiring fixed (Cycle 28, 2026-07-04):** added `pyobjc-framework-ApplicationServices` + `pyobjc-framework-Cocoa` to pyproject.toml; new `kage monitor ax-daemon` command + `_generate_ax_plist()` with `KeepAlive: true`; `kage monitor install` now loads 3 plists (ax-daemon + observe + digest). Confirmed producing real activity-aware digests (tested: Terminal → Calendar → Safari → Mail → Antigravity → Safari → Calendar → Terminal sequence, 49 AX events). Known gap: `kage ask` (non-REPL) does not write to `session_turns` — only `kage chat` does; Monitor sees arm activity via AX events only. Known miscalibration: "Scout not run in 48h" alert fires regardless of actual elapsed time — fix planned (pre-compute `hours_since_scout_run` in `read_pipeline_state()`).
- **Gap fixes (Cycle 17):** 10 structural gaps across scout/librarian/monitor/observe
- **Layer 4 router (Cycle 18):** keyword task-class classification (code/research/multimodal/reasoning/chat) → ordered provider candidate list; config-driven routing table override
- **Sensitive vault (Cycle 19):** user-defined regex PII patterns in `~/.kage/sensitive.json`; `kage sensitive list/add/scan`
- **Reversible PII masking (Cycle 21):** substitute-before-dispatch / restore-in-response; PII notes no longer withheld
- **Layer 6 `kage learn` (Cycle 22):** ProTeGi prompt learning from the `kage-corrections` log; Monitor auto-triggers at 7+ new corrections
- **Librarian EPM (Cycle 24):** Librarian learns from its own *rejections* — distills rejection patterns into its distill prompt; `kage learn --librarian`
- **Librarian CTM (Cycle 25):** Librarian learns from its own *approvals* — recent approved precedents injected as few-shot examples (MemAPO dual-memory loop)
- **Calendar-write arm (Cycle 26, on branch):** kage's first WRITE arm — EventKit create-only (write-only access), `propose → approve → execute` over human-readable markdown proposals + `kage calendar` CLI; excluded from `_detect_arms`, HITL-gated, audited. The template for future write arms; delete/reschedule/undo deferred (need full-access via a signed-helper identity)
- **Gate hardening (Cycle 23, v0.23.0):** mask-at-dispatch — condensed query + history + retrieved context are masked through one shared per-request map and restored in the response (closes F13 condensed-query cleartext leak); audit log emits `pii_type_counts` instead of placeholder labels (closes F1). Audit + build plan: `docs/security-audit-2026-07-01.md`, `docs/cycle-23-gate-hardening.md`.
- 723 tests across 13 test files

The long-term blueprint still matters for direction, but docs that say "no code yet" or "Stage 1 has not started" are historical/stale unless explicitly marked current. For implementation truth, inspect `README.md`, `src/kage/cli.py`, and `tests/test_cli.py`.

## Canonical Docs (where the real planning lives)

| File | What it is |
|---|---|
| [docs/blueprint.md](docs/blueprint.md) | **Read this for strategic context.** The detailed long-term planning state. Some status language is historical; current implementation may be ahead of it. |
| [docs/cycle-1-pitch.md](docs/cycle-1-pitch.md) | Historical v0.1 thin-slice pitch. Useful for original scope, not a complete description of current code. |
| [docs/architecture.md](docs/architecture.md) | ⚠️ LEGACY (Session 1) — superseded by blueprint.md §4 (Odysseus substrate). See banner in file. |
| [docs/ROADMAP.md](docs/ROADMAP.md) | ⚠️ LEGACY (Session 1) — superseded by cycle-1-pitch.md + blueprint.md. See banner in file. |
| [docs/competitor-flowcharts.md](docs/competitor-flowcharts.md) | Engine-level comparisons with prior art |

For a fresh coding session: read `README.md`, then `src/kage/cli.py`, `tests/test_cli.py`, and `docs/blueprint.md` for strategic context.

## Strategic Anchors (stable across sessions)

- **Build approach:** EXTEND PewDiePie's Odysseus (**AGPL-3.0**, NOT MIT) as the substrate, in kage's OWN repo (NOT a fork). kage itself is MIT — the MCP boundary (separate process, arm's-length protocol) keeps kage legally independent of Odysseus's copyleft. (OpenJarvis retired as substrate Session 13; kept only as a design reference.)
- **Dual goal:** Ship kage AND learn industry SDLC by mimicking real-team practice.
- **SDLC starter pack:** Shape Up cycles · GitHub Flow · ADRs · Conventional Commits · README/ROADMAP/CHANGELOG · GitHub Actions CI · pre-commit · semver.
- **Local stack:** Qwen3 14B Q4_K_M via Ollama (direct), Docker sandbox, ChromaDB vector index (derived — markdown files are the memory source of truth).
- **Cloud relationships:** Claude (reasoning), Perplexity (research), Gemini (Workspace), Cosmos (deep research). (Antigravity rejected as substrate #26 — optional client only.)
- **Repo:** github.com/Chirag-Mokashi/kage — kage's OWN repo (live on GitHub); extends Odysseus (AGPL-3.0) via MCP, not a fork; kage's own license is MIT.

## Operating Rules

- **Default coding workflow:** inspect first, make scoped changes when asked, run relevant tests, and report clearly.
- **Suggest, don't execute.** Chirag approves and runs everything. Never act autonomously.
- **All write actions require explicit user confirmation** (every agent, every flow).
- **When a decision needs to be made — stop, discuss, decide together.**
- **Do not treat the repo as planning-only.** Implementation work is active; keep docs and code aligned.
- **No Mermaid in new docs** — ASCII / Unicode box-drawing characters only (renderer-independent).
- **Bold recommendation first.** Lead with the conclusion + argument. Never bury opinion at the end. Save neutral menus for true value-driven choices.
- **Complete over fast.** The original 3-week build plan is deprioritized. Real goal: become a better AI engineer through depth while still shipping useful slices. **Push back if Chirag is rushing.**
- **Awareness over control.** When designing UX or routing, the user is *aware* of what's running but does NOT have to steer it. Status is a transparency layer, not a control surface.
- **Options over suggestions.** Wherever a decision is presented, surface options explicitly. Don't make silent choices.
- **Memory auto-loads** across sessions (see `~/.claude/projects/-Users-mokashi-Projects-kage/memory/`) — durable preferences and project state persist there.

## Implementation Workflow (HARD GATE — never skip)

Locked 7-step split for ALL implementation work. The roles do **NOT** collapse:

- **Cloud (the session model) PLANS and REVIEWS only.**
- **Local (Qwen3 via `kage ask`) WRITES all code and tests.**
- **Local RUNS tests** (`uv run pytest` via Bash).

Per step, in order:

```
1. PLAN code     → cloud
2. WRITE code    → local (Qwen3)
3. REVIEW code   → cloud      ← NEVER skipped
4. PLAN tests    → cloud
5. WRITE tests   → local (Qwen3)
6. REVIEW tests  → cloud      ← NEVER skipped
7. RUN tests     → local
```

**THE GATE:** I never write implementation code or tests myself with Edit/Write. The instant I do, three roles collapse into one, the review step has nothing independent to check, and the learning signal is destroyed. If I catch myself about to edit `cli.py` / `test_cli.py` directly — **STOP**. That is the exact failure mode this rule exists to prevent. (Planning stays on cloud deliberately: reasoning is local's known weak class, so routing it to local produces predictable noise, not insight.)

**COLD REVIEW (HARD RULE — never skip, every cycle):** Every major artifact gets **1-2 cold-review passes before it is accepted** — the **pitch** (before any code is written), the **code**, and the **tests**. "Cold" = a fresh, adversarial pass hunting for contradictions and load-bearing flaws, NOT a re-read by the same train of thought that produced it. Each pass names what it checked against (architecture, the 10 characteristics, jugaad, ponytail, completeness, security/egress) and the count is tracked in the doc/PR (e.g. "v3, two cold reviews"). **Mechanism:** the **pitch** is authored by cloud, so its cold review must come from an *independent* context — spawn a **subagent** (or fresh session) to review it against the real code seams. **Code and tests** are authored by local (Qwen3), so cloud reviewing them inline is cold w.r.t. the code — but cloud wrote the *spec*, so it is warm on the design. Therefore (refined 2026-06-24): **mechanical** code/test steps get cloud-inline review; **security-critical or complex** steps (egress/gate logic, ADK/model wiring, auth) ALSO get a **subagent** cold-review against the real repo; and the **whole feature gets one consolidated subagent cold-review before the PR**. This has repeatedly caught problems a single pass missed — Cycle 4 pitch (×2), Cycle 12 (×2; v1's egress claim was wrong), Scout pitch (the ADK-vs-`_call_cloud` contradiction that would have failed the capstone). One extra pass is cheap; a wrong locked decision is a rebuild.

**MISTAKE LOG (mandatory, after every step):** every cloud correction of local's output is recorded via `kage remember --project kage-corrections`, in the format:

> *"Correction log — `<feature>` Step N (date): Local made X errors: … **Pattern:** …"*

Bidirectional — log cloud-introduced bugs too. **This log is the deliverable; the code is the byproduct.** It is the Layer 6 fuel and the entire reason the split exists. See `feedback_dev_workflow.md` in memory.

## Kaggle Capstone — Active Build (deadline July 6, 2026)

kage is being submitted to the **Kaggle AI Agents: Intensive Vibe Coding Capstone** (Track: Concierge Agents). Deadline: July 6, 2026 at 11:59 PM PT.

**What is being submitted:** Three new internal agents — Scout, Librarian, Monitor — as a self-contained multi-agent pipeline built on top of the existing kage stack.

**Why ADK:** The capstone requires ADK in code. Scout, Librarian, and Monitor must be built as ADK agents (not plain Python scripts). ADK is the orchestration layer only — model stack unchanged (Qwen3 14B local for Pass 1/2, Claude Sonnet cloud for Pass 3/4). ADK supports both via LiteLLM.

**Capstone requirement mapping:**

| Concept | How kage covers it |
|---|---|
| ADK / Multi-agent | Scout + Librarian + Monitor as three ADK agents |
| MCP Server | `kage mcp serve` — already shipped |
| Antigravity | Video only — no code change needed |
| Security features | 3e gate, audit log, per-agent permissions — already shipped |
| Deployability | Video only — `okiro` startup sequence |
| Agent skills | Skill files already exist |

**Code comment rule (capstone override):** Ponytail applies fully to Scout, Librarian, and Monitor — minimal code, no abstractions, no boilerplate. One exception: the no-comment default is lifted for these three agents only. They must have comments on implementation decisions, design choices, and non-obvious behaviors — judges score this directly (50pt technical implementation criteria).

**README.md required:** kage's GitHub repo is the public submission link judges review. README must cover: problem, solution, architecture, setup instructions, diagrams. Worth 20pts. Submission assets (writeup, video script) live in the `kaggle-competition` project — NOT here.

**Scout brainstorm:** `Context/kage-scout-brainstorm-2026-06-16.md` — sections 12–20 still need desktop review before building starts.

---

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
