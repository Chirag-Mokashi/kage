# Competitor Engine Flowcharts

> Visual comparison of how each significant competitor's **core engine** actually works. UX and surface features deliberately excluded — only the engine logic where the technical decisions live. This is where kage must differentiate.
>
> *Drafted 2026-05-21. Based on public docs, GitHub source, and product marketing. Some inferences flagged with ⚠️.*

---

## 1. Plurality Network

```
                            PLURALITY NETWORK
        ════════════════════════════════════════════════════════════
        Cloud / TEE-hosted broker · Hand-curated buckets · MCP

                ┌────────────────────┐
                │     User query     │
                └─────────┬──────────┘
                          │
                          ▼
              ┌──────────────────────┐
              │      AI Tool         │
              │  Claude / GPT / Gem  │
              └─────────┬────────────┘
                        │   MCP request
                        │   + active bucket hint
                        ▼
            ╔═════════════════════════════╗
            ║    PLURALITY CLOUD (TEE)    ║  ◀── cloud-hosted
            ║   Trusted Execution Env     ║      memory never local
            ╚══════════════╤══════════════╝
                           │
                           ▼
                   ┌──────────────┐
                   │   Bucket     │  ◀── user pre-curates
                   │  selector    │      each memory ⇒ bucket
                   └──────┬───────┘      NO dynamic assembly
                          │
              ┌───────────┼────────────┐
              ▼           ▼            ▼
          ┌────────┐  ┌────────┐  ┌──────────┐
          │  WORK  │  │PERSONAL│  │ CREATIVE │
          │ bucket │  │ bucket │  │  bucket  │
          └────┬───┘  └────┬───┘  └─────┬────┘
               │           │            │
               └───────────┼────────────┘
                           ▼
                  ┌──────────────────┐
                  │  Return ALL      │
                  │  memories from   │
                  │  selected bucket │
                  └────────┬─────────┘
                           │
                           ▼
                     ( AI tool uses
                       returned memories )
```

**Distinctive properties:**
- Pre-curation required — user manually assigns each memory to a bucket before any query
- Static bucket selection — once chosen, ALL memories in it are eligible (no per-query relevance filtering across buckets)
- Cloud-hosted (TEE for privacy) — memory never local
- No router — just returns memories; doesn't decide which AI to send to

**Weakest point:** No dynamic assembly. A query that legitimately touches both "Work" and "Personal" themes must choose one bucket or get a partial answer. **The user does the partitioning work, not the engine.**

---

## 2. OpenBrain

```
                              OPENBRAIN
        ════════════════════════════════════════════════════════════
        Self-hosted MCP memory · Single namespace per user

                ┌────────────────────┐
                │     User query     │
                └─────────┬──────────┘
                          │
                          ▼
              ┌──────────────────────┐
              │      AI Tool         │
              │  Claude / Cursor /…  │
              └─────────┬────────────┘
                        │   MCP: search_memory()
                        ▼
                 ┌───────────────┐
                 │  Embed query  │  ◀── embedding model
                 │   → vector    │      (sentence-transformers etc.)
                 └───────┬───────┘
                         │
                         ▼
                 ┌───────────────┐
                 │   pgvector    │
                 │  cosine sim   │
                 └───────┬───────┘
                         │
                         ▼
              ┌───────────────────────┐
              │  Single namespace     │  ◀── NO partitioning
              │     per user          │      (only user_id)
              │ Postgres + pgvector   │
              └───────────┬───────────┘
                          │
                          ▼
                  ┌────────────────┐
                  │   Top-K by     │
                  │   similarity   │
                  └────────┬───────┘
                           │
                           ▼
                    ( back to AI tool )
```

**Distinctive properties:**
- One global namespace per user — no project, identity, or topic scoping
- Pure semantic search — single retrieval strategy (cosine similarity)
- Self-hostable — Postgres + pgvector, runs anywhere
- MCP-native — the interface IS MCP, not bolted on
- No assembly logic — just returns top-K embeddings

**Weakest point:** No partitioning. Single retrieval strategy. Loses temporal, entity, and graph signals.

---

## 3. Letta (formerly MemGPT)

```
                          LETTA (MemGPT)
        ══════════════════════════════════════════════════════════════
        Stateful agent runtime · 3-tier memory hierarchy · per-agent

                  ┌────────────────────┐
                  │   User message     │
                  └──────────┬─────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │   Letta Agent       │  ◀── memory belongs
                  │     runtime          │      to THIS agent only
                  └──────────┬──────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │  Retrieval policy   │
                  │ (relevance+recency) │
                  └──────────┬──────────┘
                             │
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
       ┌─────────┐      ┌─────────┐      ┌──────────┐
       │  CORE   │      │ RECALL  │      │ ARCHIVAL │
       │ always  │      │  past   │      │persistent│
       │in prompt│      │ convos  │      │  facts   │
       │ ~few KB │      │retrievable      │  vector  │
       └────┬────┘      └────┬────┘      └─────┬────┘
            │                │                  │
            └────────────────┼──────────────────┘
                             ▼
                  ┌──────────────────────┐
                  │  Assemble prompt     │
                  │  with right tier mix │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │       LLM call        │
                  └──────────┬───────────┘
                             │
                ┌────────────┴───────────┐
                ▼                        ▼
        ┌────────────┐         ┌──────────────────┐
        │  Response  │         │  Tier promotion  │  ◀── recall items
        │  to user   │         │ recall  → core   │      that prove
        └────────────┘         │ archival→ recall │      useful
                               └──────────────────┘      get promoted
```

**Distinctive properties:**
- 3 tiers with promotion: core (always-in-prompt) ↔ recall (retrievable past convos) ↔ archival (persistent facts). Items move between tiers based on usage.
- Per-agent scoping: each agent has its own memory tree. Multiple agents = parallel memory trees.
- Agent-centric — memory serves THIS agent, not external tools

**Worth borrowing:** The 3-tier hierarchy is smart. kage could adopt — project-scoped core (always-in-context, small) + recall (retrievable per project) + archival (persistent, partitioned).

**Doesn't fit kage:** Letta is single-agent. kage serves *multiple external tools* with different context needs.

---

## 4. Mem0

```
                                MEM0
        ════════════════════════════════════════════════════════════════
        Developer SDK · Hybrid memory (vector+graph+episodic) · user_id

      ── WRITE PATH ──                ── READ PATH ──
       ┌───────────────┐               ┌────────────────────┐
       │ mem0.add(mem) │               │ mem0.search(query) │
       └───────┬───────┘               └──────────┬─────────┘
               │                                  │
               ▼                                  ▼
       ┌───────────────┐                 ┌─────────────────┐
       │  Memory type  │                 │     Hybrid      │
       │   detector    │                 │   retrieval     │
       │ fact/event/   │                 │  (parallel)     │
       │ preference    │                 └────┬───┬───┬────┘
       └───────┬───────┘                      │   │   │
               │                              │   │   │
       ┌───────┼───────┐                      │   │   │
       ▼       ▼       ▼                      ▼   ▼   ▼
    ┌──────┐ ┌─────┐ ┌────────┐         ┌──────┐┌─────┐┌────────┐
    │Vector│ │Graph│ │Episodic│         │Vector││Graph││Episodic│
    │store │ │store│ │ store  │         │search││trav.││ search │
    │  ⬇   │ │  ⬇  │ │   ⬇    │         └──┬───┘└──┬──┘└────┬───┘
    └──────┘ └─────┘ └────────┘            │       │        │
                                           └───────┼────────┘
                                                   ▼
                                          ┌─────────────────┐
                                          │  Rerank:        │
                                          │  relevance +    │
                                          │  recency        │
                                          └────────┬────────┘
                                                   │
                                                   ▼
                                          ┌─────────────────┐
                                          │  Ranked results │
                                          │  to dev code    │
                                          └─────────────────┘
```

**Distinctive properties:**
- Hybrid memory types — same input stored differently (fact → vector, entity → graph, event → episodic). Retrieval queries all three in parallel.
- SDK form factor — not a product; a library devs embed in their own agents
- user_id is the only scoping primitive
- Reranking layer combines results from multiple stores

**Worth borrowing:** Hybrid vector + graph + episodic + parallel retrieval. Technically strong. kage's context engine should likely adopt this storage shape *underneath* the partition layer.

**Doesn't fit kage:** Mem0 is a primitive other systems use. kage IS the system.

---

## 5. Digital Twin Playbook

```
                       DIGITAL TWIN PLAYBOOK
        ════════════════════════════════════════════════════════════
        MCP knowledge graph · MIT licensed · cloud-default (Supabase)

                  ┌────────────────────┐
                  │     User query     │
                  └──────────┬─────────┘
                             │
                             ▼
                ┌──────────────────────┐
                │      AI Tool         │
                │  Claude / GPT / Cur  │
                └──────────┬───────────┘
                           │   MCP
                           ▼
                  ┌──────────────────┐
                  │  Graph traversal │
                  │  + semantic srch │
                  └──────────┬───────┘
                             │
                             ▼
              ┌─────────────────────────┐
              │   Knowledge graph        │  ◀── single graph
              │   • Nodes: entities,     │      per user
              │            facts         │      no partitioning
              │   • Edges: relations     │
              │   (Supabase Postgres)    │
              └────────────┬─────────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │  Connected nodes │
                  │   + semantic     │
                  │     matches      │
                  └────────┬─────────┘
                           │
                           ▼
                    ( back to tool )
```

**Distinctive properties:**
- Graph-centric — memory is nodes + edges, not just embeddings
- Single graph per user — no partitioning
- Cloud-default (Supabase) but self-hostable
- MIT licensed — literally template-able

**Worth borrowing:** Graph relations make sense for entities ("Sarah is a colleague at NEU; the lung project involves Sarah and Professor X"). kage's entity store could be a small graph.

**Doesn't fit kage:** Single graph, no scoping, cloud default.

---

## Patterns across all five (the gap kage fills)

Common engine stages in the order they happen:

```
   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
   │ 1. Query │ ▶ │ 2. Scope │ ▶ │  3. Re-  │ ▶ │  4. Rank │ ▶ │ 5. Return│
   │  arrives │   │  filter  │   │  trieval │   │ / Assem. │   │          │
   └──────────┘   └─────╥────┘   └──────────┘   └──────────┘   └──────────┘
                        ║
                        ║  ← THIS is where every competitor is weak
                        ║     None do project × identity matrix
                        ║     Static or single-axis at best
```

| Competitor | Step 2 (Scope) |
|---|---|
| Plurality | Hand-curated buckets, user pre-assigns |
| OpenBrain | None (user_id only) |
| Letta | Per-agent (single axis) |
| Mem0 | user_id only |
| Digital Twin | None (single graph) |

**Engine intelligence is concentrated in steps 3-4 in every system surveyed.** The "scope filter" stage is universally weak — either delegated to the user (Plurality) or absent (everyone else).

**This is the wedge for kage.** Make step 2 the *star*: project × identity matrix as a first-class filter that runs before retrieval. Same retrieval primitives (borrow openly from Mem0/Hindsight/Letta), but a smarter upstream gate that no one else has.

---

## Open design questions surfaced by the comparison

These become decisions when we draft kage's engine flowchart:

1. Adopt Letta's 3-tier (core/recall/archival) *inside* each (project, identity) cell?
2. Adopt Mem0-style hybrid (vector + graph + episodic) storage?
3. Use a graph for entities + vector for documents (DTP-influenced)?
4. How does kage handle a query that *legitimately spans* multiple projects or identities?
5. Where does the "active project / active identity" signal come from at query time? (active editor file? Chrome profile? explicit flag? all of the above?)

---

*Next step: design kage's engine flowchart, with each of the 5 questions above answered explicitly inside it.*
