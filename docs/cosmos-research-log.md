# kage — Cosmos Research Log

*Single consolidated index of every Cosmos deep-research query, its result, and the decision it drove.*
*Created 2026-06-10. Source: extracted from `docs/blueprint.md` decision log (#27–#76) + session log, `Context/kage-research-findings-2026-06-08.md`, and the WWDC26 research doc.*

---

## How to read this file

Cosmos queries used **two numbering schemes** over time:

- **Numeric (Q1–Q9):** the early queue (Sessions 4–8), mostly retrieval/memory-engine questions.
- **Lettered (Q A–Q O):** later queries, one cluster per layer-design session (J=Layer 3d, K=Layer 3e, L=Layer 4, M=Layer 5, etc.).

The two schemes overlap in time and are **not** a single sequence. This file lists both.

**Important caveat:** entries below are the *digested findings and the decisions they produced*, as recorded in the blueprint — not verbatim Cosmos transcripts. Raw transcripts were not preserved in-repo. Where fuller fidelity is needed, re-run or re-paste the original result.

**Status legend:**
`DELIVERED` returned + integrated · `NULL` tool failure, no usable retrieval · `NOT RUN` queued, never executed · `PENDING` awaiting result · `PARKED` deliberately deferred

---

## Master table

| Query | Topic | Status | Drove decision | Blueprint ref |
|---|---|---|---|---|
| Q1 | Personal-AI memory benchmarks (LoCoMo / LongMemEval / MemoryBench) | DELIVERED | Hybrid lexical+dense+rerank > graph at single-user scale; defer graph to v2 | §retrieval-validation, line 199 |
| Q2 | Is the (project × identity) 2-D matrix academically novel? | DELIVERED | NO — Bhatt et al. 2025 (arXiv:2509.14608) is ancestor; repositioned on product/engineering novelty | #27, #18.5 |
| Q3 | Cross-encoder re-rankers for personal AI | DELIVERED | **bge-reranker-v2-m3** (MemReranker API-only/too-heavy; jina CC BY-NC) | #51 |
| Q4 | Beyond RRF — score-fusion methods | DELIVERED | RRF validated, **no change** (k=60 stays) | line 1632 |
| Q5 | Lazy vs eager extraction in production memory systems | DELIVERED | Hybrid sync-cheap/async-expensive validated; ChatGPT eager extraction REJECTED as anti-pattern | #28, rejected #31 |
| Q6 | Ingest pipeline cost on consumer hardware (Apple Silicon, Qwen3-14B class) | NOT RUN | — (queued Session 5, never executed) | line 1447 |
| Q7 | Embedding model selection | DELIVERED | **Granite Embedding 311M R2** (jina-v3 rec'd but CC BY-NC) | #50 |
| Q8 | Miso One (8B voice) vs Piper for voice layer | PENDING | Gated — don't swap Piper until Q8 returns + tested on M5 Pro | parked #16.5 |
| Q9 | Apple Foundation Models `fm` Python SDK (Tier-0 model) | PARKED | Deprioritized 2026-06-10 — misaligned with active-mediator direction | WWDC26 doc |
| Q A | CoT preservation in context distillation | DELIVERED | MUST preserve full reasoning trace (DistillGuard: MATH-500 68.4→31.4 w/o CoT) | #44 |
| Q E (v2) | Layer 7 MCP server priority + tool architecture | DELIVERED | MCP = de-facto 2026 standard; 3 industry gaps = differentiator surfaces; OJ tool arch inherited | #41, #42, #43 |
| Q F | 4th-differentiator novelty check | NULL | Tool failure — doesn't disturb the case (not novelty evidence) | #53 |
| Q I | Rerankers / MLX search | NULL | Tool failure — bge pick defaulted from audited facts | line 1715 |
| Q J | Layer 3d tiered assembly | DELIVERED | 3-tier × 5-type model; CASCADE overflow; multi-resolution rendering | #54, #55, #56 |
| Q K | Layer 3e privacy gate | DELIVERED | 4-stage gate (identity → minimization → sensitivity cascade → per-tool policy) | #57 |
| Q L | Layer 4 multi-vendor routing | DELIVERED | (SUPPLIER, ACCOUNT, MODEL) tuple; 6-class taxonomy; min-viable-model; reputation-table graduation | #61–#68 |
| Q M | Layer 5 storage substrate | DELIVERED | markdown-authoritative + SQLite index + FAISS/Chroma derived; tri-mode interface; tri-mode = novel element | #70–#76 |
| Q N | TurboVec + TurboQuant + Permission Broker (3 parts) | DELIVERED (A partial-null) | TurboVec not production-ready; TurboQuant favorable long-term; permission broker = no prior art | line 595, 1212, 1435 |
| Q O | Interactive REPL / Layer 1 reframe | PENDING | Awaiting — informs Claude-Code-like session UX | line 1928 |

---

## Numeric queries (Q1–Q9) — retrieval & memory engine

**Q1 — Memory benchmarks.** LoCoMo / LongMemEval / MemoryBench audit confirmed hybrid lexical+dense+rerank beats graph-only at single-user scale. SmartSearch 91.9% on LoCoMo without graph. Graph helps mainly on temporal/multi-hop (GAAMA +16.1pp temporal). → **Defer-graph-to-v2 empirically supported.**

**Q2 — 2-D matrix novelty.** NOT academically novel — Bhatt et al. 2025 (Microsoft Research, arXiv:2509.14608) formalizes documents × entities as bipartite graph with bicliques for enterprise multi-user access control. kage cites it as ancestor. **kage's defensibility repositioned** on three product/engineering points: (1) first shipped personal-AI with state-aware identity partitioning, (2) three-state semantics (scoped/baseline/pending), (3) identity-as-cluster-of-accounts. Thesis-path #18.5 (personal-scale instantiation) deferred post-v1.

**Q3 — Re-rankers.** Cosmos originally recommended MemReranker-0.6B, overturned on verification: 0.6B is API-only (violates local-first); 4B is 8.83GB bf16 (too heavy); jina-reranker-v3 is CC BY-NC. → **bge-reranker-v2-m3** (Apache 2.0, ~500MB, ~4 MAP-pt gap, fits budget). v1.5 swap paths: MemReranker-0.6B if released public; 4B Q4-quantized (~2.5GB).

**Q4 — Score fusion.** RRF (k=60) validated against alternatives. **No change.**

**Q5 — Lazy vs eager extraction.** Hybrid sync-cheap / async-expensive ingest matches the "production compromise" shipping systems converge on. ChatGPT eager implicit extraction REJECTED (96% system-created, 28% GDPR-personal, 52% psychological inferences without consent). kage's wall-not-firehose save is the deliberate inverse. Optional per-state TTL on `pending` (GitHub Copilot 28-day pattern) parked to v2.

**Q6 — Ingest cost on consumer HW.** *NOT RUN.* Queued Session 5, never executed. (Now largely moot — the pipeline is built and works; revisit only if ingest latency becomes a felt problem.)

**Q7 — Embedding model.** Cosmos recommended jina-embeddings-v3, overturned on license check (CC BY-NC). → **Granite Embedding 311M R2** (IBM, Apache 2.0, 311M, 768d native, MTEB-v2 Retrieval 65.2, 200+ langs). Trade-off: no Matryoshka truncation, but native 768d already competitive.

**Q8 — Voice (Miso One vs Piper).** *PENDING.* Miso Labs 8B, 110ms via LiveKit/WebRTC, persona switching. Gated on M5 Pro memory headroom + local-deploy verification. Don't swap Piper until returned + tested. Voice-phase decision, doesn't block foundation.

**Q9 — Apple `fm` Python SDK.** *PARKED 2026-06-10.* Was framed as a Tier-0 free on-device model under the old "Stage 0" assumption. Deprioritized — a convenience model, not aligned with the active-mediator direction. Revisit only if a cheap-local-tier need emerges.

---

## Lettered queries (Q A–Q O) — layer design clusters

**Q A — CoT preservation.** If kage ever stores teacher responses as retrievable exemplars (Layer 6 learning), it MUST preserve the full reasoning trace, not just the answer. Evidence: DistillGuard MATH-500 dropped 68.4→31.4 when CoT removed (>50% degradation). Layer 6 design constraint.

**Q E (v2) — Layer 7 MCP + tools.** MCP is the de-facto 2026 distribution standard (Anthropic, OpenAI, Google, Microsoft; ~8,060 valid servers across 6 markets). Three industry gaps became kage differentiator surfaces: (1) registry trust (~50% listings invalid → kage adds per-identity allowlists + signed verification), (2) approval fatigue (→ identity-aware default policies + CGL), (3) non-uniform failure semantics (→ framework-grade resilience). OpenJarvis tool architecture inherited as substrate.

**Q F — 4th differentiator novelty.** NULL (tool failure). Didn't disturb the differentiator case — absence of evidence here is tool failure, not novelty disproof.

**Q I — Rerankers / MLX search.** NULL (tool failure, same as Q F). bge-reranker-v2-m3 pick defaulted from independently audited facts.

**Q J — Layer 3d tiered assembly.** Validated against MemGPT/Letta, Zep/Graphiti, MIRIX, Mem0, GRAVITY, ECoRAG. Locked: 3-tier (HOT/WARM/COLD) × 5-type orthogonal model; CASCADE overflow (top-K by reranker → extractive compress tail w/ evidence check → drop; recursive summarization REJECTED per MemGPT 35.3% vs 93.4%); multi-resolution rendering per target window. Type-aware rendering mandatory (GRAVITY +4.4pp).

**Q K — Layer 3e privacy gate.** Locked: 4-stage pipeline — identity check → selective disclosure/minimization → sensitivity scan (Presidio rules → local NER → local LLM-redactor on uncertain only) → per-tool policy (PERMIT/MODIFY/ASK/DENY, fail-closed). Ed25519-signed audit, SHA-256 per-identity hash chain, ~9ms async write.

**Q L — Layer 4 routing.** Validated against vLLM-SR, RouteLLM, Johnson & Lee taxonomy, Select-then-Route, AAP/OAP, RouterArena. Locked: (SUPPLIER, ACCOUNT, MODEL) tuple, account decoupled from identity; 6-class taxonomy (chat/code/reasoning/research/multimodal/system-ctrl); MINIMUM-VIABLE-MODEL principle; 3-tier Safety Copilot (Jarvis-style briefing for Tier 3); class-aware cost cascade; reputation-table + Bayesian graduation (local earns classes; ~60-70% local expected end of yr1; Qwen3-14B will NOT beat Opus on hard reasoning).

**Q M — Layer 5 storage.** Validated against Obsidian, MemX (FTS5 1100× speedup, <90ms@100K), vstash (20.9ms@50K), MIRIX, Letta, Cognee. Locked: 5A markdown-authoritative (one file/memory, folder-by-type), 5B single SQLite (join-table partition, FTS5, signed audit, schema versioning), 5C FAISS IndexFlatIP (later → ChromaDB per #85). Storage internals of Claude/ChatGPT/Gemini are OPAQUE → kage's contribution is COMPOSITION at personal scale; user-selectable tri-mode storage (#47) is the one genuinely novel element.

**Q N — TurboVec / TurboQuant / Permission Broker** (combined, 2026-06-08; full query text in `Context/kage-research-findings-2026-06-08.md`):
- **Part A — TurboVec:** partial-null (no primary evidence). Pre-finding: ~3 weeks old, Mac ARM build failure (#92), upsert data-loss bugs (#89/#90). **NOT production-ready.** Keep behind swappable backend; don't swap ChromaDB until ARM + integrity issues resolved.
- **Part B — TurboQuant** (arXiv:2504.19874): KV-cache compressor, NOT a weight quantizer — stackable with Q4_K_M (different memory pools). Quality-neutral ~4.57× at 3.5 bits/ch across 4K–104K. Ollama PR #15505 unmerged. **Passive watch** — evaluate at >32K-context or multi-session features. Long-term favorable.
- **Part C — Permission Broker:** No system does all four (revocation semantics + signed policy descriptors + centralized validation + inline enforcement) simultaneously. MCP security literature (ACM TOSEM 2026, arXiv:2511) explicitly calls for this "missing layer." MemPalace (Apr 2026) does cross-tool MEMORY brokerage, not permissions. **No prior art for the permission-specific surface.**

**Q O — Interactive REPL / Layer 1.** *PENDING.* Informs the Claude-Code-like session UX (context bar + slash commands, shortened conversations). Awaiting result.

---

## Decision-vs-implementation gaps (verified against code 2026-06-10)

Several Cosmos-locked decisions were **never implemented** — they are coding backlog, not open research:

| Cosmos decision | Locked choice | Actual code today |
|---|---|---|
| Q7 / #50 | Granite Embedding 311M R2 | `nomic-embed-text` |
| Q3 / #51 | bge-reranker-v2-m3 | no reranker (RRF only) |
| #49 | LightRAG dual-level keyword split | not implemented |
| Q M / #72 → #85 | FAISS → ChromaDB | ChromaDB ✓ (matches) |
| Q4 | RRF k=60 | RRF k=60 ✓ (matches) |

→ Closing these is **implementation work**, not Cosmos research. See [[project-ground-truth-audit]].

---

## Open / candidate Cosmos questions (2026-06-10)

- **Plan-cloud / execute-local / verify-cloud loop patterns** — proven 2026 architectures where a weak local model executes a tight spec and a strong model plans + verifies; context-passing efficiency; where verification token cost lands. (NEW — aligned with mediator vision. See [[feedback-local-draft-cloud-verify]].)
- **Spotlight semantic index from Python** — DROPPED as a Cosmos question; better answered by direct experimentation on the Mac (Apple won't expose internals; access is a quick empirical test).
- Q6, Q8, Q O, Q9 — see status above (not-run / pending / parked).

---

*Maintenance: when a new Cosmos query runs, add a row to the master table + a detail entry. When a locked decision gets implemented, update the decision-vs-implementation gap table.*
