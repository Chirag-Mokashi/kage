# Odysseus Reconciliation — every prior decision, mapped

> **Status:** Decision-support inventory. Purpose: make sure the substrate swap
> (OpenJarvis → Odysseus) drops **nothing**. This walks all 80 locked decisions +
> the 13 Locked Principles and tags each. *How* we implement each is deliberately
> NOT decided here — this is "what's present vs not present," per the
> adopt-don't-switch rule.
>
> *Last updated: 2026-06-03.* Companion: [odysseus-deep-dive.md](odysseus-deep-dive.md) · [blueprint.md](blueprint.md)

## Legend

```
  KEEP       Unaffected by Odysseus. Stands exactly as locked. (identity/strategy/SDLC/principles)
  BUILD      kage's distinctive capability. Odysseus LACKS it → we build it on top. (the moat) Nothing lost.
  DONATED    Odysseus already ships this capability → we reuse/inherit it. (commodity)
  RECONCILE  ⚠ Capability is PRESERVED, but its source/implementation changes — OR there's a
             real conflict to resolve. These are the only ones that need attention.
```

A separate section at the end covers the reverse: **Odysseus gaps we fill** and
**Odysseus gifts we never planned** ("what we might have missed").

---

## Identity / North-Star — all KEEP (and reinforced)
| # | Decision | Status |
|---|---|---|
| #5 | kage = personal context broker, not "yet another personal AI" | KEEP — Odysseus is *not* a broker; reinforces |
| #21 | The 10 Core Characteristics | KEEP |
| #29 | COMPLEMENT→MEDIATOR→BROKER + audience split | KEEP |

## Strategy
| # | Decision | Status |
|---|---|---|
| #6 | Core differentiator = context engine; routing downstream | KEEP — validated; Odysseus lacks the engine |
| **#7** | Fork OpenJarvis as `kage`, stay close to upstream | **RECONCILE ⚠ — SUPERSEDED: extend Odysseus, own repo (not fork)** |
| #8 | Dual goal: ship + learn SDLC | KEEP — Odysseus is also a top-tier SDLC reference |
| **#9** | Dual portfolio: own repo + upstream PRs to OJ | **RECONCILE ⚠ — "PRs to OJ" part changes; own-repo holds** |
| #10 | UX is not a defensible differentiator | KEEP — so adopting Odysseus's UX is fine; we just can't claim it |
| #24 | Gemini Spark validates the moat | KEEP — add Odysseus as another validation point |
| **#26** | Substrate = OJ + AGENTS.md/SKILL.md loader; Antigravity rejected | **RECONCILE ⚠ — substrate→Odysseus; re-check SKILL.md loader vs Odysseus skills/MCP** |
| #27 | Defensibility at product/eng novelty (2-D not academically novel) | KEEP — Odysseus is 1-D, product novelty stands |
| #32 | Learning cross-cutting, deferred to Layer 6 | KEEP |
| #38 | USE what exists, MCP-first, discover/route — never duplicate | KEEP — this principle *predicted* the Odysseus adoption |
| #42 | 3 industry gaps (registry trust, approval fatigue, failure semantics) | KEEP — Odysseus addresses none; still ours |
| #53 | 4th differentiator: multi-modal memory + CGL + constraint encoding | KEEP decision / BUILD capability — Odysseus lacks CGL & constraints |

## SDLC / Process — all KEEP
| # | Decision | Status |
|---|---|---|
| #11 | ASCII not Mermaid (repo docs) | KEEP — (Odysseus uses Mermaid in its UI; irrelevant to our docs) |
| #12 | Layer-by-layer planning | KEEP |
| #13 | Two stages (0 = blueprint, 1 = build) | KEEP |
| #23 | No time pressure; depth over speed | KEEP |
| #25 | MCP as distribution standard | KEEP — Odysseus is MCP-native; eases Layer 7 |
| #36 | Drop 4-week target; 5 essentials / ≥2 cycles | KEEP |

## Layer 1 — Interface
| # | Decision | Status |
|---|---|---|
| **#77** | Permission model rides macOS TCC/TouchID/OAuth + Safety Copilot | **RECONCILE ⚠ — Odysseus has its OWN web auth (bcrypt/2FA/admin). If kage stays headless, kage keeps #77; resolve overlap** |
| #78 | CLI embodies the 10 characteristics from command one | KEEP — headless CLI core; Odysseus is a separate front-end |
| #79 | Terminal-first; all UIs are front-ends on one CLI core | KEEP — **this decision is exactly what lets Odysseus be a wrapper** |
| #80 | Daemon sequencing: on-demand v0, daemon later | KEEP |

## Layer 2 — Agents
| # | Decision | Status |
|---|---|---|
| **#14** | Hybrid: Librarian + opt-in Monitor internal; external via MCP | **RECONCILE — keep Librarian/Monitor (tied to our partition); external-agent/MCP machinery is DONATED by Odysseus** |

## Layer 3a — Active Context Detection ★ — all BUILD (the star; Odysseus has none)
| # | Decision | Status |
|---|---|---|
| #15 | 4 signals, 6-level cascade, bootstrap wizard, identity model, 7 privacy principles | BUILD — Odysseus has zero active-context detection |
| #35 | Self-Discovery + bootstrap wizard refinement | BUILD |

## Layer 3b — Partition Filter ★ (THE WEDGE) — all BUILD (Odysseus is 1-D owner only)
| # | Decision | Status |
|---|---|---|
| #16 | Wall, not firehose (explicit save only) | BUILD |
| #17 | Two write flows (direct + session inbox) | BUILD |
| #18 | Tag schema: projects[] + identities[≥1] + state | BUILD — extends Odysseus's `owner` into the 2-D matrix |
| #19 | Filter logic: identity wall + state-aware spillover | BUILD |
| #20 | Save-time prompt UX | BUILD |

## Layer 3c — Hybrid Retrieval
| # | Decision | Status |
|---|---|---|
| #28 | Ingest: hybrid sync-cheap / async-expensive | RECONCILE — storage+index DONATED by Odysseus; async entity/relation passes are ours |
| **#49** | 3c FULLY LOCKED: BM25 + Granite-emb + **FAISS** + LightRAG split + RRF + bge-reranker + provenance | **RECONCILE ⚠ — FAISS→ChromaDB; keep RRF + reranker + LightRAG split as our layer ON TOP of Chroma** |
| **#50** | Embedding = Granite Embedding 311M R2 (768d) | **RECONCILE ⚠ — wire Granite via Odysseus's fastembed/EMBEDDING_URL, or accept its default; decide** |
| #51 | Re-ranker = bge-reranker-v2-m3 | BUILD — Odysseus has no cross-encoder rerank; we add it over Chroma results |
| #52 | Constraint Reconsideration Trigger | BUILD — Odysseus has nothing like it (ties to Layer 6) |

## Layer 3d — Tiered Assembly — BUILD on Odysseus's compaction
| # | Decision | Status |
|---|---|---|
| #54 | 3-tier (HOT/WARM/COLD) × 5-type model | BUILD — Odysseus has token-aware compaction but no tier×type schema |
| #55 | Cascade overflow; reject recursive summarization | BUILD |
| #56 | Multi-resolution cross-tool rendering; type-aware mandatory | BUILD |

## Layer 3e — Privacy / Selective Disclosure ★ — BUILD (the moat; Odysseus has ZERO)
| # | Decision | Status |
|---|---|---|
| #57 | Four-stage gate (identity → minimize → sensitivity → policy) + audit | BUILD — splices into Odysseus's `llm_core.py` dispatch chokepoint |
| #58 | Minimization relevance-first, not age-based | BUILD |
| #59 | Per-tool token budgets | BUILD |
| #60 | Novelty = integration, cite components | KEEP — Odysseus's absence strengthens it |

## Layer 4 — Multi-Vendor Router
| # | Decision | Status |
|---|---|---|
| **#61** | Routing tuple (VENDOR, **ACCOUNT**, MODEL); account first-class | **RECONCILE ⚠ — Odysseus dispatch is (vendor, model), NO account dimension; we extend it** |
| #62 | Pre-classification: 6-class taxonomy + per-class policy + embedding classifier | BUILD — Odysseus = manual model pick, no classifier |
| #63 | Minimum-viable-model routing principle | BUILD |
| #64 | Layer 3e × Layer 4 contract (Design B) | BUILD — depends on 3e (absent in Odysseus) |
| #65 | Safety Copilot 3-tier risk model | BUILD — Odysseus has admin-gating only, no risk-tiered confirm/undo |
| #66 | Cost ceiling graduated mitigation | BUILD — Odysseus has no cost management |
| #67 | Failure cascade per-class chain | RECONCILE — Odysseus ships `llm_call_with_fallback` + dead-host cooldown (primitive DONATED); per-class chains are ours |
| #68 | Local→cloud graduation (reputation table + Bayesian CI) | BUILD — Odysseus has none (ties to Layer 6) |
| #69 | Novelty = integration | KEEP |

## Layer 5 — Memory Storage
| # | Decision | Status |
|---|---|---|
| #46 | Five memory types (Core/Procedural/Semantic-SOR/vocab/Episodic) | BUILD — Odysseus memory is untyped entries + skills; schema is ours over Chroma |
| #47 | Three-mode (local / Notion-hybrid / Notion-canonical) | KEEP — v1 local only; Odysseus memory is local-only too |
| #48 | Consequences-field-as-detection-signal | BUILD — Odysseus has nothing |
| **#70** | 5A: **markdown file per memory**, frontmatter partition, source-of-truth | **RECONCILE ⚠ — Odysseus stores memory in `memory.json` + ChromaDB, NOT markdown SoT. Keep our markdown-SoT (transparency value-add) or adopt theirs? Real conflict** |
| **#71** | 5B: SQLite `kage.db`, FTS5 BM25, join-table partition, hash-chain audit | **RECONCILE ⚠ — Odysseus has its own SQLite `app.db` + Chroma. Our partition tables + hash-chain audit are additive; decide co-existence** |
| **#72** | 5C: **FAISS** IndexFlatIP, Granite 768d, ~16-18GB budget | **RECONCILE ⚠ — SUPERSEDED by ChromaDB; vector-search capability preserved, backend swaps; re-budget** |
| #73 | Retention: never auto-expire committed; soft-delete 30-day grace | BUILD — Odysseus has no retention policy; we add it |
| #74 | `MemoryStore` interface; v1 LocalAdapter only | RECONCILE — interface now wraps Chroma/Odysseus memory instead of FAISS; principle KEEPS |
| #75 | Schema evolution; markdown-SoT migration; embedding-change→reindex | RECONCILE — depends on #70 outcome |
| #76 | Novelty = composition; tri-mode storage is the novel bit | KEEP |

## Layer 6 / 7
| # | Decision | Status |
|---|---|---|
| #39 | Layer 6 = memory-layer learning, NOT LoRA | KEEP / BUILD — Odysseus "skills evolve" is adjacent, not CGL |
| #40 | Layer 4 refinements / reputation precursor | BUILD |
| #41 | Layer 7 MCP-server-OUT priority HIGH | KEEP — *easier* now; headless kage exposes MCP, Odysseus can consume it |
| #44 | CoT preservation for any future distillation | KEEP |

## Cross-cutting
| # | Decision | Status |
|---|---|---|
| #1 | Local model Qwen3 14B Q4_K_M via Ollama | RECONCILE — Odysseus DONATES serving (Cookbook/Ollama); wire Qwen3 through it |
| **#2** | Sandbox: Docker | **RECONCILE ⚠ — Odysseus runs in Docker but its THREAT_MODEL admits NO shell/FS sandbox for agent tools. We must ADD what it lacks** |
| #3 | Cloud fallback Claude Sonnet 4.6 | KEEP — Odysseus supports Anthropic |
| **#4** | OpenJarvis audited & chosen as substrate | **RECONCILE — historical; substrate audit now points to Odysseus (this doc + deep-dive)** |
| #22 | Six operating principles | KEEP |
| #30 | Seven Locked Principles (13 total) | KEEP |
| #31 | Capability 0.60 = baseline not constraint | KEEP / BUILD |
| #33 | Layer 4 Pattern 5 (pre-classification) v1 default | BUILD |
| #34 | Distillation Harness | N/A — already superseded internally by #39 |
| #37 | Briefer agent deferred to v1.5 | KEEP — but Odysseus's Deep Research + email triage could accelerate it (see Gifts) |
| **#43** | Inherit OpenJarvis tool architecture as substrate | **RECONCILE ⚠ — tools now inherited from Odysseus (tool_implementations/tool_execution/MCP/opencode agent), not OJ. Capability preserved, source flips** |
| #45 | Blank Slate scope = runtime only | KEEP |

## The 13 Locked Principles + non-numbered locks
- Principles #1–#13 (Transparency, Awareness-over-control, Options-over-suggestions, Build-for-now/architect-3yr, Complete-over-fast, Bold-recommendation-first, Blank-Slate-Boot, Adaptation, Honesty/TARS, Testing-Protocol, Capability, Raising/Nurturing, Self-Discovery): **all KEEP.** None touched by the substrate.
- **Principle #8 (Adaptation)** is the *justification* for this whole reconciliation.
- SDLC starter pack (Shape Up, GitHub Flow, ADRs, Conventional Commits, semver, CI, pre-commit): **KEEP** — applies to kage's own repo regardless of substrate.

---

## Reverse 1 — Odysseus's GAPS we fill (nothing of ours is lost here; these are our value)
- **No selective disclosure (3e)** — our moat.
- **No active context detection (3a)** — our star.
- **No project×identity partition (3b)** — it's 1-D owner.
- **No auto-routing / pre-classification / cost mgmt / local→cloud graduation** (#62–#68).
- **No agent shell/FS sandbox** (#2) — and they *admit* it (THREAT_MODEL gap #1).
- **No markdown source-of-truth, no typed memory schema, no hash-chain audit** (#70/#46/#71).
- **No constraint reconsideration / Consequences field** (#52/#48).
- Weak security edges: coarse token scopes, an SSRF, advisory-only prompt-injection defense.

## Reverse 2 — Odysseus GIFTS we never planned ("what we might have missed" → ADOPT candidates, post-engine)
- **Email/Calendar/Tasks AI triage incl. style-matched draft replies** — this is basically our parked *outbound draft-and-confirm* flagship, already shipped for email.
- **Cookbook** — hardware-aware model download/serve, VRAM fit, 270+ models (we'd only decided "Qwen3 via Ollama").
- **Deep Research** (Tongyi) — accelerates our deferred Briefer (#37) / briefing idea.
- **Compare mode** (blind multi-model test) — directly relevant to our `kage test` local-vs-cloud benchmark.
- **ntfy push notifications** + **cron task scheduler** — channels for our daemon/briefing/ambient features (#80).
- **PWA / mobile** — a path into our parked multi-device items.
- Extras: documents/image editors, TTS/STT, YouTube transcripts, 2FA/multi-user.

---

## Bottom line (counts)
- **KEEP:** ~38 (all identity, strategy, SDLC, principles, and the moat-framing decisions) — untouched.
- **BUILD:** ~24 (Layers 3a, 3b, 3e, most of 4, parts of 3c/3d, Layer-6 learning) — **our moat, fully intact, nothing dropped.**
- **DONATED:** the commodity we now get for free (serving, vector plumbing, MCP, retrieval baseline, fallback primitive).
- **RECONCILE ⚠ (the watch-list, ~12):** #7, #9, #26, #43, #4 (substrate identity & tool architecture) · #49, #50, #72 (FAISS+Granite → Chroma) · #70, #71, #75 (memory storage format) · #61 (account-routing) · #77, #14 (auth/agents) · #1, #2 (serving & sandbox).

No BUILD/moat decision is lost. Every RECONCILE preserves the *capability* — only the *source* changes — except the genuine open conflicts (#70 markdown-SoT, #77 permission model) which we decide deliberately, one at a time.
