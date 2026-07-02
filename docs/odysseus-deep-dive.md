# Odysseus — Deep-Dive (substrate analysis for kage)

> **DIVERGENCE NOTE (2026-07-02):** The build did NOT follow this plan. kage shipped **standalone** — its own `cli.py`/`privacy.py`/`redact.py` 3e gate, own ChromaDB index, own dispatch (`cloud.py`) — and integrates Odysseus (if at all) only arm's-length via MCP. The "inherit / splice into llm_core.py / DONATED reuse" framing in this doc never materialized. Kept as historical decision-support, not an accurate description of the shipped architecture.

> **Status:** Reference / decision-support doc. Odysseus is kage's chosen
> substrate (decided 2026-06-03: *extend*, not fork OpenJarvis). This file is
> the detailed reading of what we're building on.
>
> **Purpose:** Understand Odysseus end-to-end — its architecture, whether it
> has "layers" like kage, what each part does, how extensible it is, its
> implicit "characteristics" (mentality), and its shortcomings — so Chirag can
> read it cold and bring recommendations.
>
> *Last updated: 2026-06-03. Source: github.com/pewdiepie-archdaemon/odysseus
> @ main (MIT), cloned to /tmp/odysseus. ~113K LOC Python · 558 files · 359 test files.*
>
> *Companion docs:* [blueprint.md](blueprint.md) · [jarvis-design-reference.md](jarvis-design-reference.md)

---

## 0 · TL;DR (one screen)

- **What it is:** a self-hosted, local-first AI **workspace** — "the ChatGPT/Claude
  UI experience, on your own hardware, with more jank and fun." A *destination* you
  open in a browser. MIT-licensed, production-grade, ~113K LOC.
- **Does it have layers like kage?** It has an *implicit* request pipeline
  (route → auth → context assembly → dispatch → agent/tools → write-back) but it
  is **not formalized into named layers.** It has **no Layer 3a (active context
  detection)** and **no Layer 3e (selective disclosure)** — the two things kage
  inserts. Its memory is **1-D owner-scoped**, not kage's 2-D project×identity.
- **Can we build on it cleanly?** Yes. MIT, well-tested, and — crucially — its
  model-dispatch path has a **natural chokepoint** (`src/llm_core.py`) where a
  kage selective-disclosure gate drops in with low invasiveness.
- **Where it's weak:** no sandbox for agent shell/file tools, prompt-injection
  defense is advisory-only, coarse token scopes, and zero per-vendor privacy
  minimization. These are kage's opportunities.
- **Mentality:** Local ✓, User-agency ✓, Adoptable ✓✓, Modular ◐ — but **not**
  Silent, **not** Invisible, **not** Aware, **not** a Broker. The four it lacks
  are exactly kage's differentiators.

---

## 1 · What Odysseus *is* (identity + philosophy)

From the README, verbatim:

> "A self-hosted AI workspace — meant to be the self-hosted version of the UI
> experience you get from ChatGPT and Claude. But with more jank and fun.
> Running on your own hardware, with your own data — local-first, privacy-first,
> and no trojan."

> "Documents — **YOU write the text, AI is there to assist, not the opposite.**"

Two more tells about its worldview:
- The THREAT_MODEL says: *"designed for trusted users on a private network… treat
  it like an admin console."* It deliberately gives a logged-in admin shell, file,
  and email power — and does **not** try to constrain the admin.
- ACKNOWLEDGMENTS: *"Most of Odysseus's code was written **with** AI models, not
  just by a human."* (Credits gpt-oss-120b, Qwen3-235B, DeepSeek, Claude, Codex.)

So its self-image is: a **hacker's all-in-one local AI cockpit** — broad,
powerful, honest about being a little janky, owned end-to-end by the user.

### Its implicit "characteristics" — Odysseus's mentality vs kage's 10

kage has 10 explicit characteristics. Odysseus never wrote a list, but one is
*implied* by its choices. Mapping them against kage's is the most useful lens:

```
  kage characteristic   Odysseus?   notes
  ───────────────────   ─────────   ─────────────────────────────────────────────
  Local                 ✓ STRONG    own hardware, own data, no telemetry, "no trojan"
  Controlled            ✓ STRONG    "YOU write the text"; user drives everything
  Adoptable             ✓✓ HUGE     one-command install, PWA, 34k★ — adoption is its superpower
  Modular               ◐ PARTIAL   clean MCP + service split; but a monolith FastAPI app
  Transparent           ◐ PARTIAL   shows what it does in-UI; not an audit-trail design
  Broker                ✗ NO        sends FULL context to whatever vendor — no minimization
  Aware                 ✗ NO        you log in as a user; no auto-detection of active context
  Silent                ✗ NO        it's a destination you open and operate
  Invisible             ✗ NO        a visible workspace, the opposite of invisible
  Seamless              ✗ N/A       different goal — it's a tool you wield, not a shadow
```

**Read this carefully:** the four kage characteristics Odysseus lacks —
**Broker, Aware, Silent, Invisible** — are precisely kage's moat. Odysseus is a
*cockpit you fly*; kage is a *co-pilot that flies quietly*. They share the
foundation (Local, Controlled, Adoptable, Modular) and diverge exactly where
kage is distinct. That's the cleanest possible relationship with a substrate:
inherit the foundation, own the divergence.

---

## 2 · Top-level structure

```
/tmp/odysseus/
├── app.py                 [1,071 LOC]  FastAPI entry point + middleware wiring
├── core/                  [~2,100 LOC] cross-cutting infrastructure
│   ├── auth.py            user/token/2FA, DEFAULT_PRIVILEGES, RESERVED_USERNAMES
│   ├── database.py        SQLAlchemy models (Session, ChatMessage, Document, …)
│   ├── middleware.py      SecurityHeaders, auth, internal-tool loopback, require_admin
│   ├── session_manager.py session lifecycle
│   ├── atomic_io.py       atomic writes (sessions.json)
│   └── constants.py / exceptions.py
├── src/                   [~35K LOC]   the brain: orchestration, LLM, agents, memory, RAG
│   ├── llm_core.py        [1,529] HTTP clients + model calls (OpenAI/Anthropic/vLLM/Ollama)
│   ├── chat_processor.py  context assembly (build_context_preface) + hybrid retrieval
│   ├── agent_loop.py      [2,300] streaming agent + tool-execution loop (from opencode)
│   ├── tool_implementations.py [4,144] native tools (bash, python, web, files, docs)
│   ├── tool_execution.py  [1,010] tool dispatch + MCP gateway
│   ├── tool_schemas.py    [1,236] OpenAI-format function schemas
│   ├── tool_security.py   NON_ADMIN_BLOCKED_TOOLS, owner_is_admin_or_single_user
│   ├── prompt_security.py UNTRUSTED_CONTEXT_POLICY, untrusted_context_message()
│   ├── mcp_manager.py     MCP connections (stdio + SSE), tool discovery
│   ├── task_scheduler.py  [2,255] cron-style recurring tasks (croniter)
│   ├── deep_research.py   [912]   plan→search→extract→synthesize (from Tongyi DeepResearch)
│   ├── builtin_actions.py [2,237] document/calendar/email/note/task ops
│   └── search/            search core/providers (aliases services.search)
├── routes/                FastAPI endpoints: chat, session, document, memory, model,
│                          mcp, cookbook, hwfit, research, … (the HTTP surface)
├── services/              decoupled feature services:
│   ├── memory/            memory.py (owner-filtered store) + memory_vector.py (ChromaDB)
│   ├── search/            metasearch (SearXNG client)
│   ├── hwfit/             Cookbook — hardware detect + model fit scoring (from llmfit)
│   ├── research/          deep-research pipeline support
│   ├── docs/ faces/ shell/ stt/ tts/ youtube/   (documents, avatars, shell, speech, transcripts)
├── mcp_servers/           built-in MCP servers auto-registered at startup (e.g. browser)
├── static/                vanilla-JS PWA frontend (index.html + app.js + js/ modules)
├── companion/             companion/mobile integration
├── docker/                GPU overlay compose files (nvidia/amd)
├── docs/                  landing page + demo clips
├── licenses/              third-party license texts
├── tests/                 359 test files
├── docker-compose.yml     Odysseus + ChromaDB + SearXNG + ntfy
├── THREAT_MODEL.md  SECURITY.md  ACKNOWLEDGMENTS.md  CONTRIBUTING.md  ROADMAP.md
└── pyproject.toml  requirements.txt  requirements-optional.txt
```

**Shape:** a FastAPI monolith (`app.py` + `routes/`) over a thick orchestration
core (`src/`) and a set of decoupled feature `services/`. Frontend is
framework-free vanilla JS served statically.

---

## 3 · Does it have layers? — the request lifecycle

Odysseus does **not** name layers, but a chat request flows through an implicit
pipeline. Here it is, mapped against kage's 7-layer architecture so you can see
exactly where they align and where kage adds something Odysseus doesn't have:

```
  ODYSSEUS PIPELINE (a chat turn)              ↔  kage layer
  ──────────────────────────────────────────     ─────────────────────────────
  1. HTTP POST /chat  (routes/chat_routes.py)  ↔  Layer 1 (Interface)
       browser UI / API token                       BUT: web UI, not CLI/MCP-in
  2. Auth + user resolve (core/middleware.py,  ↔  (kage has no equivalent —
       get_current_user) → `owner`                  rides macOS TCC / OAuth)
  3. CONTEXT ASSEMBLY (src/chat_processor.py
       build_context_preface):
        • memory load(owner=user)              ↔  Layer 3b — but 1-D OWNER only,
                                                    no project axis, no state model
        • ⟨no active-context detection⟩        ↔  Layer 3a — ABSENT in Odysseus
        • hybrid retrieve (BM25 + vector,      ↔  Layer 3c — simpler (no RRF /
          top-k, owner-scoped)                      cross-encoder / query expansion)
        • RAG over docs + web + skills inject
        • token-aware budget / compaction      ↔  Layer 3d — simpler (no type-aware
                                                    rendering, no HOT/WARM/COLD tiers)
        • ⟨no per-vendor minimization⟩         ↔  Layer 3e — ABSENT in Odysseus ★
  4. DISPATCH (src/llm_core.py llm_call_async):
        _detect_provider(url) → vendor known   ↔  Layer 4 — multi-vendor, but no
        _sanitize_llm_messages() strips only        (vendor,ACCOUNT,model) tuple;
        internal metadata → full context sent       no identity-bound account routing
  5. AGENT LOOP if agent mode (agent_loop.py + ↔  Layer 2 (internal agents) +
        tool_execution.py + MCP gateway)            Layer 7 (MCP out) — but one
                                                    opencode-derived agent, not
                                                    Librarian/Monitor
  6. Stream response back to UI
  7. MEMORY WRITE-BACK (explicit save →        ↔  Layer 5 (storage) — ChromaDB,
        services/memory + ChromaDB index)           not kage's planned FAISS+BM25
```

**The two gaps are the whole story.** Odysseus has a perfectly serviceable
version of Layers 1, 3b(1-D), 3c, 3d, 4, 5 and an agent for 2/7. It has **nothing
at Layer 3a** (it never asks "which project/identity is active?" — it only knows
"which user is logged in") and **nothing at Layer 3e** (it never asks "what is
this *specific vendor* allowed to see?" — it sends everything). Those two are
kage's stars and kage's broker. We inherit the pipeline and splice in 3a at the
front and 3e before dispatch.

---

## 4 · Subsystem tour

- **Chat / context assembly** (`src/chat_processor.py`): `build_context_preface`
  pulls owner-scoped memories, retrieves via hybrid **BM25 + vector top-k**,
  injects RAG/doc/web/skill context, and fits it to a token budget. All
  external content is wrapped as *untrusted* (see Security).
- **Agent** (`src/agent_loop.py`, adapted from **opencode**, MIT): streaming
  plan→tool-call→observe loop. Native tools in `tool_implementations.py` (bash,
  python, web fetch, file read/write, doc ops); dispatched via `tool_execution.py`
  which also bridges to MCP tools.
- **Memory / Skills** (`services/memory/`): entries in `data/memory.json` each
  carry an optional `owner`; `load(owner=…)` filters to that user. Vector index
  is a **single ChromaDB collection `odysseus_memories`**; retrieval is
  owner-scoped at query time. fastembed (ONNX) for embeddings. "Skills" are
  persistent, owner-scoped procedures the agent accumulates.
- **Model serving — "Cookbook"** (`services/hwfit/`, from **llmfit**, MIT):
  scans hardware, scores model "fit" for your VRAM, one-click downloads
  (GGUF/FP8/AWQ) and serves via llama.cpp / vLLM. tmux for background jobs; SSH
  to drive remote model servers. (On M-series Macs, run native for Metal.)
- **MCP** (`src/mcp_manager.py`, `mcp_servers/`): connects MCP servers over
  **stdio** (subprocess) or **SSE** (URL); auto-discovers tools; a few built-in
  servers auto-register at startup (e.g. Playwright browser). **This is the clean
  third-party extension surface.**
- **Deep Research** (`src/deep_research.py`, from **Tongyi DeepResearch**,
  Apache-2.0): iterative gather→read→synthesize into a visual report.
- **Email / Calendar / Tasks / Notes** (`src/builtin_actions.py` + routes):
  IMAP/SMTP inbox with AI triage (urgency, auto-tag, summary, **draft replies**,
  spam); CalDAV calendar; cron-style scheduled tasks (`task_scheduler.py`,
  croniter) with ntfy/browser/email notification channels.
- **Documents** (`services/docs/`): multi-tab editor, markdown/HTML/CSV, AI edits.
- **Auth** (`core/auth.py`): bcrypt + 7-day sessions + TOTP 2FA; admin vs
  non-admin privilege model; reserved usernames.
- **Frontend** (`static/`): framework-free vanilla JS PWA, mobile-friendly.

---

## 5 · Tech stack, deployment, data

- **Backend:** Python 3.11+, **FastAPI** + Uvicorn, **SQLAlchemy** over SQLite
  (`data/app.db`), HTTPX, Pydantic, **MCP SDK**, croniter, caldav/icalendar,
  bcrypt/pyotp.
- **Vector / embeddings:** **ChromaDB** + **fastembed** (ONNX). ← note: kage's
  3c design assumed FAISS+BM25; extending Odysseus means inheriting ChromaDB.
- **Bundled via Docker:** ChromaDB (Apache-2.0), **SearXNG (AGPL-3.0)**, ntfy.
- **Adapted code:** opencode (agent, MIT), llmfit (Cookbook, MIT), Tongyi
  DeepResearch (research, Apache-2.0). All credited in ACKNOWLEDGMENTS.
- **Run:** `docker compose up -d --build` → `http://localhost:7000` (7860 on
  native macOS). Auto-creates an admin account with a printed temp password.
- **Data (all gitignored, in `data/`):** `app.db`, `memory.json`, `presets.json`,
  `settings.json`, `chroma/`, `uploads/`, `personal_docs/`.

### License hygiene note (proactive)
Core is **MIT-clean** — they deliberately removed copyleft deps (dropped chardet
LGPL; PyMuPDF AGPL is now *optional*, used only for PDF form-filling). The two
AGPL items are **SearXNG** (composed as a Docker image, not linked into code →
fine) and optional PyMuPDF (skip it → MIT-clean). If kage ever redistributes a
bundle, keep SearXNG as a separate composed service and don't install PyMuPDF,
and the whole stack stays permissive.

---

## 6 · Extensibility — and where kage's broker layer slots in

**How a third party adds capability (in order of cleanliness):**
1. **MCP server** (stdio or SSE) — register via `src/mcp_manager.py`; tools are
   auto-discovered, no core changes. This is the blessed path.
2. **Native tool** — add to `tool_implementations.py` + schema in `tool_schemas.py`.
3. **Service + routes** — drop a module in `services/` and wire `routes/`.
4. **Presets / skills / webhooks** — user-level extension, no code.

**The key finding — kage's selective-disclosure gate (Layer 3e) has a natural
home.** The model-dispatch path is a chokepoint:

```
  build_context_preface()  ──assembled messages──►  llm_call_async(url, model, messages)
                                                         │  (src/llm_core.py)
                                                         ├─ _detect_provider(url)  ← VENDOR known here
                                                         └─ _sanitize_llm_messages(messages)  ← existing
                                                            "modify messages before send" hook
                                                            (today only strips internal metadata)

   kage 3e gate slots in RIGHT HERE:
   take (messages, target_provider) →  identity check → minimize → sensitivity
   scan → per-vendor policy (PERMIT/MODIFY/ASK/DENY) → then dispatch + audit-log
```

This is the best possible news for the extend strategy: at the dispatch point
Odysseus *already* knows the exact `(context, vendor)` tuple kage's 3e needs, and
it *already* has a "transform messages before they leave" function
(`_sanitize_llm_messages`). kage's privacy gate is a sibling of that function —
**low-invasiveness, well-defined seam.** Layer 3a (active-context detection)
splices in earlier, before `build_context_preface`, to set the active
(project, identity) that 3b/3e then enforce.

---

## 7 · Shortcomings / limitations

From the project's own THREAT_MODEL "Known Gaps" plus analysis:

**Acknowledged by the project:**
1. **No shell/filesystem sandbox** — agent `bash`/`read_file`/`write_file` run as
   the app user with no egress filtering or FS confinement. A prompt-injection in
   an admin session can reach internal services. (Proposal #1058.)
2. **SSRF via `/api/v1/chat` `base_url`** — a chat token can point dispatch at an
   arbitrary host; scheme/address unvalidated. (PR #1039.)
3. **`src/search/` partial consolidation** — duplicated modules can drift.
4. **Coarse token scopes** — only `chat` or `admin`; no per-capability grants.

**Additional, relevant to kage:**
5. **No selective disclosure / per-vendor minimization** — the full assembled
   context goes to whatever vendor is selected. *This is kage's headline gap to fill.*
6. **Privacy is by-locality, not by-design** — "run it on your box" ≠ "the cloud
   models you call see only the minimum." Once you use a cloud provider, Odysseus
   sends everything.
7. **Identity = login owner only (1-D)** — no project scoping, no "same human,
   different hats," no auto-detected active context. kage's whole wedge.
8. **Prompt-injection defense is advisory** — `UNTRUSTED_CONTEXT_POLICY` *asks*
   the model not to obey injected instructions; nothing enforces it.
9. **`internal-tool` loopback grants admin unconditionally** — safe only because
   that username is reserved; a fragile design smell.
10. **AI-written, self-described "jank"** — broad surface, uneven polish; treat
    individual modules with healthy skepticism before depending on them.

None of these are disqualifying for a substrate — items 5–7 are literally the
space kage occupies.

---

## 8 · What kage lifts vs. builds (working map)

```
  LIFT / REUSE from Odysseus            BUILD ourselves (the moat + the learning)
  ──────────────────────────────       ───────────────────────────────────────────
  • Model serving (Cookbook/hwfit)      • Layer 3a — active context detection
  • Multi-vendor dispatch (llm_core)      (editor path / calendar / cwd → project,identity)
  • ChromaDB memory plumbing (Layer 5)  • Layer 3b — 2-D project×identity partition
  • Hybrid retrieval baseline (3c)        + three-state machine (extend owner→identity matrix)
  • Tiered assembly baseline (3d)       • Layer 3e — selective-disclosure gate
  • MCP integration                       (slots into llm_core dispatch chokepoint)
  • Email/calendar/tasks (optional)     • The broker policy + audit log
  • Auth/sessions (or bypass for        • (decide) Layer 1 interface: keep kage
    single-user local)                    headless CLI/MCP, OR ride Odysseus UI
```

---

## 9 · Open questions to decide (for the reframe discussion)

1. **Interface:** does kage stay a headless broker (CLI + MCP) that Odysseus
   *consumes*, or does kage live inside Odysseus's web UI? (Leaning: headless —
   preserves Invisible/Silent; Odysseus is an "arm.")
2. **Repo/ownership:** separate `kage` repo depending on Odysseus (cleanest "my
   project") vs. fork. (Leaning: separate repo.)
3. **Vector substrate:** adopt ChromaDB (Odysseus default) or keep FAISS+BM25
   plan? (Leaning: adopt ChromaDB to minimize divergence.)
4. **Identity model:** extend Odysseus's `owner` field into kage's
   project×identity matrix, or run kage's partition above it?
5. **Internal agents (Layer 2):** reuse Odysseus's opencode agent, or keep
   kage's Librarian/Monitor? (Leaning: keep ours — tied to our partition.)
6. **Promote Layer 3e** to a co-primary moat now that the category leader ships
   zero selective disclosure?
