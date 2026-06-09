# kage — Research Findings
*Session: 2026-06-08 — Video analysis via Gemini + Claude synthesis*
*Status: Raw findings. Review before merging into docs/blueprint.md.*

---

## Summary

Four videos analyzed this session. Three produced findings directly relevant to kage. Items below are organized by which layer or decision they affect.

---

## Finding 1 — TurboVec (Layer 3c + Layer 5)

**What it is:**
An open-source vector index library built on Google Research's TurboQuant. Compresses float32 vectors 8x (31GB → 4GB for a 10M document corpus). Hand-written ARM NEON kernels beat FAISS on ARM by 12–20%. No codebook training required, no rebuild step, online ingest (vectors indexed immediately on add).

**GitHub:** `github.com/RyanCodrai/turbovec`

**Why it matters for kage:**
- Layer 5 currently plans FAISS as the vector store. TurboVec is a potential drop-in replacement.
- M5 Pro has 24GB unified memory shared between Qwen3 14B (~8–10GB) and kage's memory layer. 8x vector compression directly expands how much memory space is available to the intelligence layer.
- "No training phase, online ingest" property is a better fit for Layer 3b's wall flow than FAISS IVF, which requires periodic retraining as the corpus grows.
- ARM NEON optimization = Apple Silicon native. This is not incidental — it's the target platform.

**Caveat:**
`RyanCodrai/turbovec` appears to be a third-party implementation inspired by the Google Research paper, not an official Google release. Maturity and Python binding status unverified.

**Action required:**
Add to Cosmos research queue as **Question #7:**
> "TurboVec (`RyanCodrai/turbovec`) vs FAISS for personal-scale vector search on Apple Silicon M5 Pro — Python bindings, production readiness, maintenance status, and memory/speed benchmarks as of 2026."

**Decision gate:** Do not swap FAISS for TurboVec until Cosmos search returns. If it checks out → becomes the Layer 5 vector store. If not → FAISS holds, TurboVec added to watch list.

---

## Finding 2 — Miso One Voice Model (Voice Layer)

**What it is:**
An 8B open-source voice AI model from Miso Labs. Claims 110ms response latency (vs 220ms human reaction time, vs 700ms competitor AI). Persona switching built in: Friend, Therapist, YouTuber, Teacher — each with distinct tone, pacing, and emotional register. Full developer API. Test at misolabs.ai.

**Why it matters for kage:**
- The parked "voice output engine — decide after Antigravity setup" decision now has a strong candidate alongside Piper.
- 110ms latency via LiveKit's WebRTC pipeline means voice conversation stays below the 600ms threshold where it starts feeling unnatural.
- Persona switching maps directly to kage's interaction modes: okiro morning briefing ≠ urgent alert ≠ casual query. Having a model that natively supports distinct tonal registers reduces prompt engineering overhead.
- 8B open-source with API = fits the free tools philosophy. Local deployment on M5 Pro needs verification.

**Comparison with current plan (Piper):**
Piper is fast, offline, and lightweight. Miso One is more expressive but heavier (8B vs Piper's rule-based synthesis). The decision likely depends on M5 Pro memory headroom after Qwen3 14B is loaded. Both should be tested before committing.

**Action required:**
Add to Cosmos research queue as **Question #8:**
> "Miso One (Miso Labs 8B voice model) — local deployment options on Apple Silicon M5 Pro, memory footprint, Ollama or vLLM compatibility, comparison with Piper TTS for real-time voice output in a LiveKit pipeline as of 2026."

**Decision gate:** Do not swap Piper for Miso One until Cosmos search returns and both are tested on Mac. This is a voice phase decision — does not block Stage 0 or Stage 1 foundation work.

---

## Finding 3 — Context Loss at Token Limit (Design Implication)

**What was observed:**
A Chrome extension called "Tally" exists specifically to track Claude token usage and transfer context to another model when the limit hits. The fact that this has significant traction signals that context continuity is a real, felt pain point — not just an architectural concern.

**The real risk (identified this session):**
Hard context transfer (paste context into new model) reconstructs facts but not understanding. The implicit reasoning thread — *why* decisions were made, casual mentions that shaped interpretation, the conversational texture — is lost.

**Design implication for kage:**
kage's current Layer 3b design is wall-not-firehose: nothing enters memory unless explicitly saved. This is correct for signal quality. But the most valuable context — the implicit reasoning thread mid-session — is precisely what never gets explicitly saved because the user is in flow.

The session inbox (Flow 2) partially addresses this, but depends on the user completing the review at session end.

**Open question to add to blueprint.md:**
> How does kage capture implicit session reasoning, not just explicit saves? Is this the Librarian's job? Does it require a lightweight always-on observation mode that flags "this looks like a decision being made" without full scraping?

**Note:** This is not a new layer — it is a refinement question for Layer 3b and the Librarian's responsibilities. Do not let it block current blueprint progress.

---

## Finding 4 — TurboQuant (Qwen3 14B Quantization — Minor Flag)

**What was observed:**
One video referenced "TurboQuant" in the context of aggressive quantization of a 12B model, achieving better quality-per-token than standard GGUF Q4_K_M.

**Current kage stack:** Qwen3 14B Q4_K_M via Ollama.

**Relevance:** If TurboQuant-based GGUF formats become available for Qwen3 14B, they could improve inference quality at the same memory footprint. Low priority — Q4_K_M is working and smoke tests passed.

**Action:** Passive watch item. Check when doing the TurboVec Cosmos search — same research thread.

---

## Cosmos Research Queue — Updated

Previous 6 questions from blueprint.md Section 8 remain. Two new questions added earlier this session (TurboVec #7, Miso One #8). These are now superseded by one combined query below that covers all new findings from 2026-06-08.

| # | Question | Priority |
|---|---|---|
| 1 | Personal AI memory layer benchmarks 2025-2026 (LoCoMo, LongMemEval, MemoryBench) | High |
| 2 | Multi-tenant / partitioned RAG literature — is kage's 2-D matrix novel? | High |
| 3 | Cross-encoder re-rankers for personal AI 2025-2026 | Medium |
| 4 | Beyond RRF: score fusion methods 2024-2026 | Medium |
| 5 | Lazy vs. eager extraction in production agent memory systems | High |
| 6 | Ingest pipeline cost on consumer hardware (Apple Silicon, Qwen3 14B class) | Medium |
| **8** | **Miso One local deployment on M5 Pro — memory footprint, LiveKit compatibility, vs Piper** | **Medium** |
| **N** | **Combined query below — TurboVec + TurboQuant + Cross-tool portability** | **High** |

---

### Combined Cosmos Query — Session 2026-06-08

> **Context for Cosmos:** kage is a local-first personal context broker running on Apple Silicon M5 Pro (24GB unified memory). Current stack: Qwen3 14B Q4_K_M via Ollama (~9GB), ChromaDB/FAISS for vector search, plain markdown as memory source of truth. kage is designed for the long term — not just current scale but future scale, future tools, future ecosystem. Do not close questions based on current limitations.

**Research the following:**

**Part A — TurboVec (vector index)**
1. `RyanCodrai/turbovec` — production readiness trajectory: Mac ARM build failure (issue #92) and upsert data-loss bugs (#89, #90) — what is the resolution timeline? Is the project actively maintained or at risk of abandonment?
2. At what corpus scale does TurboVec's 8x compression and ARM NEON speed advantage become meaningfully better than ChromaDB/FAISS? Does the advantage hold at personal scale (thousands of docs) or only at 10M+ docs?
3. How does TurboVec's online ingest (no retraining) compare to ChromaDB's behaviour as a corpus grows? Is ChromaDB's FAISS index rebuild a real bottleneck at scale?
4. Python ecosystem integration — LangChain, LlamaIndex, Haystack adapters: how mature are they? Can TurboVec slot into a ChromaDB-shaped interface?
5. Projected maturity window — at the current development pace, when is TurboVec likely to be production-safe for a personal AI use case?

**Part B — TurboQuant (KV-cache compression)**
6. TurboQuant (arXiv:2504.19874, Google Research) — as a KV-cache compressor stacked on top of Q4_K_M weight quantization: at what context lengths does it meaningfully reduce memory pressure on a 24GB system running Qwen3 14B?
7. Ollama PR #15505 (TurboQuant KV-cache compression) — what is the integration timeline? Any community forks (TheTom/llama-cpp-turboquant, AtomicBot-ai/atomic-llama-cpp-turboquant) that are usable now without building from source?
8. Quality impact — does KV-cache compression with TurboQuant degrade answer quality at typical context lengths (4K–32K tokens)? What do benchmarks show?
9. Long-term trajectory — as kage's context windows grow and multi-session context becomes a feature, does TurboQuant become load-bearing? What is the 2-year horizon for this technology in the local LLM stack?

**Part C — Cross-tool portability + Permission Broker**
10. AI tool config fragmentation landscape mid-2026: `~/.claude/`, `~/.codex/`, `~/.gemini/`, Cursor SQLite — how siloed are these in practice? Is any standardisation effort underway at the config/permission layer (not just the instruction file layer)?
11. AGENTS.md as a cross-tool instruction standard (donated to Linux Foundation, December 2025) — which tools have adopted it, which are resisting, and what is the realistic convergence timeline?
12. MemPalace (April 2026) and other MCP-based cross-tool memory servers — architecture, open source status, what problem they solve vs what kage's permission broker layer would solve that they don't. Is there any prior art for permission brokerage (not just memory brokerage) across AI tools?
13. MCP as the realistic portability layer — is MCP gaining enough adoption across Codex, Gemini CLI, Cursor, and Claude Code that an MCP-native kage could serve all of them without tool-specific file generation? What is the gap between MCP's memory/context capabilities and permission management?
14. Is there any system (open source or commercial) that already acts as a permission mediator between a user and multiple AI coding tools — surfacing shared permissions, requesting approval for new ones, writing tool-native permission files? If not, how novel is kage's proposed Permission Broker layer?

---

## Design Insight — kage as Permission Broker (brainstorm 2026-06-08)

**What was identified:**
Every AI tool (Claude Code, Codex, Gemini CLI, Cursor) creates its own silo:
`~/.claude/`, `~/.codex/`, `~/.gemini/` etc. — each with its own permissions,
settings, and memory. None talk to each other. Installing a new tool means
starting from zero and re-granting permissions blindly.

**The design:**
kage intercepts when a new tool is installed and acts as a permission mediator:

1. Compares the new tool's requested permissions against the existing canonical
   baseline (e.g. what Claude Code already has approved)
2. Surfaces what is SHARED — "these map directly, port them over?" (approve all
   or review one by one)
3. Surfaces what is NEW — permissions the new tool wants that haven't been
   granted before; user approves or rejects each explicitly
4. Writes the tool-specific permission file in that tool's native format

**Key principle:** kage assumes nothing. User sees everything, decides everything.

**Why it matters:**
- Hits 4 characteristics simultaneously: Transparent, Controlled, Broker, Seamless
- Solves a real security gap — today you have no reference point when a new tool
  asks for permissions; kage gives you one
- Permission brokerage is the capability equivalent of memory brokerage (Layer 3e)

**Relationship to existing layers:**
Not Layer 3e (selective disclosure of memory) but a parallel surface —
selective disclosure of *capabilities*. Sits above the tool layer, below the
user.

**Action required:**
Add to `docs/blueprint.md` as a new open design surface — "Permission Broker"
layer. Not a Stage 1 blocker but should inform how kage's tool-registration
architecture is designed from the start.

---

## Parked Items — Not Acted On This Session

- Artificial Lung Capacity module — explicitly excluded from this document per session instruction. Full research documented in `Tell_me_something__How_does_an_AI_at_itsspeak_mimi.md`.

---

## Merge Instructions

When merging into `docs/blueprint.md`:

1. Add TurboVec finding to **Layer 3c** (PROPOSED section) as a candidate replacement for FAISS, gated on Cosmos #7
2. Add TurboVec to **Layer 5** open decisions alongside FAISS
3. Add Miso One to **voice layer parked decisions** — replaces the generic "decide after Antigravity setup" placeholder
4. Add implicit session context capture as a new **open question** in Section 8
5. Update Cosmos research queue table with questions #7 and #8
6. Add TurboQuant as a passive watch item under Qwen3 14B intelligence layer notes
7. Add Permission Broker as a new open design surface — kage mediates tool permission onboarding; user approves shared + new permissions explicitly; nothing assumed

---

*Generated: 2026-06-08*
*Source: 4 videos analyzed via Gemini, synthesized by Claude*
*Next action: Run Cosmos searches #7 and #8 before implementing voice layer or finalizing Layer 5 storage choice*
