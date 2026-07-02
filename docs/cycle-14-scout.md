# Cycle 14 — Scout: kage's first proactive agent (ADK, v0.14.0)

*Status: SHIPPED v0.14.0 (`55150e7`) — pitch v4 (cloud-authored, Opus 4.8; 2026-06-21..24).*

*Supersedes the prior `_call_cloud`-loop framing in `Context/kage-scout-brainstorm-2026-06-16.md`. The 20 brainstorm sections still hold; this pitch re-expresses them in ADK and locks two scope changes (see §Decisions changed at the Opus gate).*

> **v2 changelog (cold review #1, independent subagent, 2026-06-21):** ADK skeleton confirmed API-correct against installed `google-adk==2.3.0`; reuse table confirmed accurate. Fixes: (Major) `_run_once` async ADK glue now fully cloud-authored + its own step — not prose Qwen3 must invent; (Major) `scout_recall` now resolves identity/project via `_resolve_context` and passes them to `_disclosure_gate` — closes a silent identity-wall widening; (Major/honesty) softened the egress claim to what the gate actually enforces (the recall tool path, not the whole request); (minor) explicit corpus char cap + round-robin truncation, per-source fetch error isolation, single `_key()` for dedup+cache, named test-mock seam, keyless `api_key=None`, dropped the speculative second source file, fixed `_resolve_context` citation.
>
> **v3 changelog (cold review #2, focused on v2 deltas, 2026-06-21):** `_run_once` glue **verified API-correct** against `google-adk==2.3.0` source (`runners.py:932,2157`, `in_memory_session_service.py:77`, `event.py:275`) — safe to copy verbatim. Fixes: (Blocker) `_litellm_target` was mis-described (claimed the key lives in providers config — it's an env var, `cloud.py:106`) and left as prose; now **authored in full** (§A1a) after reading the real config — all of Chirag's providers are `openai-compat`, mapped to LiteLLM's `openai/` route + `api_base`, returns a 3-tuple incl. `api_base`; (Major) `scout_recall` now pins `cfg = runtime.config.data` and cites the correct gating exemplar (`kage_ask`, not `kage_recall`); (Major) round-robin corpus spec made deterministic (group by source, fixed `_SOURCE_ORDER`, skip-not-stop, all-empty→`""`); (minor) bootstrap test asserts `len(sub_agents)==1` *(superseded by v4 — `sub_agents` no longer exists; use `graph.nodes` set-membership, §A1)*.
>
> **v4 changelog (Workflow API migration, Opus, all facts re-verified live on 2026-06-24):** During Step 4 the test suite surfaced `DeprecationWarning: SequentialAgent is deprecated ... use Workflow instead`. Re-verified empirically against the installed `google-adk==2.3.0` (2.3.0 is the latest on PyPI — no newer target):
> - (Decision) **`SequentialAgent`, `ParallelAgent`, AND `LoopAgent` are all `@deprecated`** → the entire orchestrator-agent family is replaced by graph `Workflow`. Migrating now (Scout unshipped) is the durable choice; building new code on a removal-warned API is debt. **Scout is now a `Workflow`** (§Decisions #1, §A1).
> - (Blocker, caught by live run — *not* by the two prior cold reviews) v3's `_run_once_async` read the final answer from `event.is_final_response()` / the original `session.state`. **Both are wrong for Workflow.** Empirically: the original session object is **not** mutated after `run_async` (`session.state['report']` → `None`); the output lives only in a **re-fetched** session via `await session_service.get_session(...)`, and `output_key` writes it to `state[key]`. §A2a rewritten to drain events then `get_session` → `state.get("report") or state.get("shortlist")`. This bug would have made every Step-5 run return `""` silently.
> - (Mechanical) `Workflow(name=..., edges=[(START, broad), (broad, integrate)])` — `LlmAgent`s pass directly into tuple edges (auto-wrapped); `InMemoryRunner(node=pipeline, ...)` (`node=`, not `agent=`); inspection is `pipeline.graph.nodes[*].name`, there is **no** `sub_agents` attribute. Reuse: Steps 1–3 (all fetch/cache/`scout_recall`/`_corpus`/`_litellm_target`) are API-agnostic and unchanged — the only deltas are `build_pipeline` (≈4 lines), the §A2a `_run_once_async` glue (the refetch fix, a not-yet-committed Step-5 deliverable), and 2 build-pipeline tests. Confirmed live: the cloud node's `tools=[scout_recall]`, `before_model_callback=_pii_seam`, and `output_key` all survive Workflow wrapping (callback fires, tool is invocable) — the disclosure-gate egress seam is intact.

---

## North star

> **Scout finds. You decide. Librarian remembers.**

Until now kage is a *fetcher* — it acts only when asked. Scout Mode 1 (autonomous overnight research) is the first time kage acts on its own initiative. It is the first crossing of the line from BROKER to MEDIATOR. It stays **Controlled**: Scout *gathers* (consequence-free) autonomously; anything consequential is a checkbox you tick in the morning.

This is also the **Kaggle capstone's primary ADK deliverable** (Concierge track). Scout is built as a real multi-agent ADK pipeline — not a script with an ADK import — because the 50-pt technical criterion scores ADK usage directly.

---

## Decisions changed at the Opus gate (2026-06-21)

The Sonnet-era brainstorm locked 20 sections. Re-interrogated under Opus, three changed:

1. **ADK is the orchestrator, not `_call_cloud`.** The brainstorm said Scout "reuses `_call_cloud`." That would be a plain Python script and fails the capstone's ADK requirement. **Locked (v4): Scout is an ADK `Workflow` graph of two `LlmAgent` nodes**, model-routed via `LiteLlm` (Qwen3→Ollama, cloud→OpenRouter/Sonnet). The 4-pass design maps onto this cleanly: Pass 1+2 = local node, Pass 3+4 = cloud node. *(Was `SequentialAgent` through v3 — but `SequentialAgent`/`ParallelAgent`/`LoopAgent` are all now `@deprecated` in `google-adk==2.3.0` in favor of `Workflow`; the two-node graph `edges=[(START, broad), (broad, integrate)]` is the same linear pipeline expressed on the supported API, and leaves the parallel-branch / conditional-route seam open for v2.)*

2. **Login / personalized-feed scraping deferred to v2.** v1 sources are public APIs + RSS only (zero login, zero cookie store). This cuts the most brittle, highest-ToS-risk, most-likely-to-break-during-judging code. The `kage scout login` + Playwright persistent-context path stays a documented seam.

3. **The disclosure gate is load-bearing in v1, not a no-op.** The old plan said v1 has near-zero PII so the gate is dormant. False: the cloud stage's `scout_recall` tool reads *personal memory* to dedup findings against what you already know — that is a real egress point. **`scout_recall` returns only rows that pass `_disclosure_gate`.** *Precise guarantee (don't overclaim):* v1 gates the **one path that touches personal memory** — the recall tool return. The rest of the cloud request body (the `shortlist` + instruction) is derived purely from the public corpus, so it carries no personal data by construction. Whole-request reversible substitution is the `before_model_callback` seam, which lands as Layer 3e v2. So: the moat runs on the memory path from day one; the request-wide masking is the documented v2 upgrade.

Everything else from the brainstorm holds: batch+launchd, `~/.kage/scout/` tree, stateless-dumb (learning → Librarian), Reddit JSON pre-filter, bootstrap guard, openrouter-free operational default, substitution-not-abort for the v2 PII path.

---

## Architecture

```
launchd (nightly, run_at) ──► kage scout run
                                   │
                    ┌──────────────┴───────────────┐
                    │  1. DETERMINISTIC FETCH       │   plain Python, no LLM
                    │     sources.py → items[]      │   HN · arXiv · GitHub · Reddit · RSS
                    │     dedup vs seen-cache        │   Reddit pre-filter (titles+scores)
                    └──────────────┬───────────────┘
                                   │ corpus (compact text)
                    ┌──────────────▼───────────────────────────────┐
                    │  2. ADK Workflow("Scout")  [graph]            │
                    │     edges: START→broad→integrate              │
                    │   ┌─ ScoutBroad (LlmAgent) ──────────────┐    │  Pass 1+2
                    │   │  model = LiteLlm(ollama/qwen3:14b)    │    │  $0, local
                    │   │  filter+cluster corpus → shortlist    │    │
                    │   └───────────────┬──────────────────────┘    │
                    │            output_key="shortlist"             │
                    │   ┌─ ScoutIntegrate (LlmAgent) ──────────┐    │  Pass 3+4
                    │   │  model = LiteLlm(openrouter|sonnet)   │    │  $0 default
                    │   │  tools = [scout_recall]  ◄── GATED    │    │
                    │   │  before_model_callback = pii_seam     │    │  3e egress point
                    │   │  → morning report markdown            │    │
                    │   └───────────────┬──────────────────────┘    │
                    └───────────────────┼───────────────────────────┘
                                        │ report
                    ┌───────────────────▼───────────────────┐
                    │  3. WRITE ~/.kage/scout/YYYY-MM-DD.md  │   [ ] Approve / Park / Discard
                    │     update seen-cache · token log      │
                    └────────────────────────────────────────┘

You read it over coffee, tick boxes.  Approved items → kage remember (explicit).
Learning from your ticks → Librarian (Cycle 15, seam only here).
```

**Why fetch is deterministic, not agentic:** the LLM never decides to hit the network — fetching is bounded Python. The one genuine agentic tool is `scout_recall` on the cloud stage, where tool-use adds real value (dedup against existing memory) and is safely gated. This is more **Controlled**, more ponytail, and keeps token cost predictable.

---

## What's already in place (reuse, no rebuild)

| Seam | Reused for | Source |
|---|---|---|
| `_privacy._disclosure_gate(rows, cfg, identity, project)` | gating `scout_recall` output | `privacy.py:19` |
| `_privacy._write_audit(record)` | Scout run + recall audit lines | `privacy.py:10` |
| `cli._search` / `_resolve_context` | the recall inside `scout_recall` | `cli.py:315` / `context.py:23` (re-exported `cli.py:28`) |
| `cli._save(...)` | promoting approved findings to `~/.kage/memory` | `cli.py:182` |
| `runtime.config.data` | scout config block **and** provider creds (no new secret store) | `runtime.py` |
| `Config.home` (`KAGE_HOME` aware) | `~/.kage/scout/` path root | `config.py:9` |
| `http._get` (NEW — GET sibling of `_post_json`, added in Step 1) | all source fetches; centralizes the UA fix in one place | `http.py` |
| `google-adk[extensions]>=2.3.0` | the whole orchestration layer | `pyproject.toml` |

> **Setup note (verified at Step 0, 2026-06-24):** `LiteLlm` is gated behind the `[extensions]` extra — bare `google-adk` raises `ImportError` on `from google.adk.models.lite_llm import LiteLlm`. Dependency is now `google-adk[extensions]>=2.3.0` (`uv add 'google-adk[extensions]'`). Full ADK surface (`create_session`/`run_async`/`InMemoryRunner`/`LlmAgent` fields/`Event.is_final_response`/`types.Content`/`LiteLlm(model,api_key,api_base)`) confirmed against the installed 2.3.0 at runtime — the §A1 skeleton + §A1a/§A2a authored blocks match exactly.

**Credential reuse (jugaad):** Scout reuses kage's *existing* provider abstraction (`cloud.py`). The provider config block holds `type` / `model` / `api_key_env` / `base_url` — **not the key itself**; the key is resolved at call time from the env var named by `api_key_env` (`os.environ.get(pcfg["api_key_env"])`, exactly as `cloud.py:106` does). No new key store, no secret in config, no duplicated secret. `_litellm_target` (§A1a) is the one small adapter that maps this config shape onto LiteLLM.

---

## Deliverables

### A. `src/kage/scout.py` — new module (the agent)

Four concerns, kept in one file (ponytail — one cohesive module, split only if it grows past ~300 lines):

- **`fetch(cfg) -> list[dict]`** — deterministic source pull + dedup. Each item normalized to `{"source", "title", "url", "score", "snippet"}`. Reddit items pre-filtered to title+score before they ever enter the corpus. **Each source is fetched inside its own `try/except` — a failed/timed-out source is dropped with an audit line, never aborts the run** (mirrors the arm pattern's best-effort `except Exception: return None`, `arms.py:101`).
- **`scout_recall(query: str) -> list[dict]`** — the ADK tool given to the cloud stage. Resolve context then gate (the gating exemplar is `kage_ask`, `mcp_server.py:131,138`, **not** `kage_recall`, which does not gate): `cfg = runtime.config.data`; `identity, project, _ = _resolve_context(None, None)`; `rows = _search(query, project, limit, identity=identity)`; `allowed, _ = _disclosure_gate(rows, cfg, identity=identity, project=project)`; return excerpts from `allowed` only. *Do not hardcode `identity`/`project` and do not invent the `cfg` source* — hardcoding would silently widen the identity wall (`_disclosure_gate` → `runtime.store.allowed_note_ids(identity, project)`). **This is the v1 egress chokepoint.**
- **`_key(item) -> str`** — the single dedup identity (`url + "|" + content_hash`). Defined once; used by **both** the dedup filter in `run()` and `_update_cache`, so the two representations can never drift (drift → first night reports the whole internet).
- **`build_pipeline(cfg, *, cloud: bool) -> Workflow`** — wires the two `LlmAgent` stages into a graph (`edges=[(START, broad)]`, or `+ (broad, integrate)` when `cloud`). `cloud=False` (bootstrap/dry-run) returns the broad stage only.
- **`run(mode)`** — orchestrate: fetch → run pipeline via `InMemoryRunner` → write report → update cache → token log.

> **Capstone comment rule applies to this file.** The no-comment default is lifted for Scout (per CLAUDE.md): comment every design decision, model-routing choice, and non-obvious behavior. Judges score this.

#### A1. The ADK skeleton (cloud-authored template — Qwen3 fills the bodies)

```python
from google.adk.agents import LlmAgent
from google.adk.workflow import Workflow, START   # v4: Workflow replaces deprecated SequentialAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.genai import types

def build_pipeline(cfg: dict, *, cloud: bool) -> Workflow:
    # Pass 1+2 — broad gather + noise filter. Local Qwen3 via LiteLLM→Ollama. $0, never leaves machine.
    broad = LlmAgent(
        name="ScoutBroad",
        model=LiteLlm(model="ollama_chat/qwen3:14b"),
        instruction=_BROAD_INSTRUCTION,     # "Select genuinely notable items, cluster, drop noise. Output a shortlist."
        output_key="shortlist",
    )
    # Workflow graph: LlmAgents go straight into the edge tuples (auto-wrapped as nodes).
    # START is the graph entry; the corpus arrives as the first node's input message.
    if not cloud:
        return Workflow(name="Scout", edges=[(START, broad)])

    # Pass 3+4 — verify + integrate against existing memory, write the morning report. Cloud judgment.
    provider = cfg["scout"].get("cloud_provider", "openrouter-free")
    model_str, api_key, api_base = _litellm_target(provider, cfg)   # §A1a — reuse kage's provider config
    # Pass api_key / api_base ONLY when present. An empty-string key makes some LiteLLM providers
    # attempt a doomed auth handshake; a None api_base lets native vendors use their own endpoint.
    kwargs = {"model": model_str}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    integrate = LlmAgent(
        name="ScoutIntegrate",
        model=LiteLlm(**kwargs),
        instruction=_INTEGRATE_INSTRUCTION,  # "{shortlist} → use scout_recall to dedup vs memory → write report w/ decision checkboxes"
        tools=[scout_recall],                # the one genuine agentic tool, gated
        before_model_callback=_pii_seam,     # v1 pass-through; v2 = Layer 3e substitution over the whole request
        output_key="report",
    )
    # broad → integrate runs sequentially; integrate's output_key="report" is the terminal state.
    return Workflow(name="Scout", edges=[(START, broad), (broad, integrate)])
```

**Step 0 (Qwen3, before writing):** run `uv run python -c "import google.adk; from google.adk.agents import LlmAgent; from google.adk.workflow import Workflow, START; from google.adk.models.lite_llm import LiteLlm; from google.adk.runners import InMemoryRunner; print('ok')"` to confirm the exact import surface of the installed `google-adk` 2.3.0. If any import path differs, fix the skeleton to match the installed version — **do not invent symbols.** This guard exists because ADK API drift is the single highest hallucination risk for local. (The skeleton above + the `_run_once` glue in §A2a were verified API-correct *and run end-to-end* against `google-adk==2.3.0` on 2026-06-24 — copy them; Step 0 only re-checks in case the installed version moved.)

> **Step 4 import edit (explicit):** the committed line 13 is `from google.adk.agents import LlmAgent, SequentialAgent`. **Replace** it with `from google.adk.agents import LlmAgent` and add `from google.adk.workflow import Workflow, START`. Remove `SequentialAgent` entirely — do not leave a dangling/duplicate import. (`from google.genai import types` belongs to §A2a, not the `build_pipeline` block — don't carry it into Step 4.)

> **Inspecting the graph in tests (READ THIS — the one ADK-shaped trap):** `pipeline.graph.nodes` **always includes a synthetic `START` node** named `__START__`. Verified node lists: bootstrap (`cloud=False`) → `['__START__', 'ScoutBroad']`; full (`cloud=True`) → `['__START__', 'ScoutBroad', 'ScoutIntegrate']`. Therefore the build-pipeline tests **must use set membership, never length or index**. Do **not** write `len(pipeline.graph.nodes) == 1` or `pipeline.graph.nodes[0].name == "ScoutBroad"` — both are wrong (index 0 is `__START__`; bootstrap has 2 nodes, not 1). The required form is:
> ```python
> names = {n.name for n in pipeline.graph.nodes}
> assert "ScoutBroad" in names
> assert "ScoutIntegrate" not in names   # bootstrap; flip to `in` for the cloud test
> ```
> Also: `graph` is an instance field (a constructed `pipeline`), not a class attribute — inspect `pipeline.graph`, never `Workflow.graph`.

#### A1a. `_litellm_target` — kage provider config → LiteLLM (cloud-authored in FULL; second-highest ADK-knowledge risk after `_run_once`)

Do **not** leave this as prose either. Every cloud provider in Chirag's config is `type: "openai-compat"` with `base_url` ending in `/v1` and `chat_path: "/chat/completions"` (e.g. `openrouter-free` → `base_url="https://openrouter.ai/api/v1"`, `model="openrouter/free"`). LiteLLM's `openai/`-prefixed custom-endpoint route reproduces kage's existing dispatch exactly (it appends `/chat/completions` to `api_base`).

```python
import os
from kage.cloud import DEFAULT_PROVIDERS

# kage provider "type" → LiteLLM provider prefix. All of Chirag's providers are "openai-compat"
# (openrouter/mistral/fireworks) → LiteLLM's "openai/" custom-endpoint route + api_base. Native
# vendors keep their own prefix so LiteLLM hits the right URL without an api_base.
_LITELLM_PREFIX = {"claude": "anthropic", "openai": "openai", "gemini": "gemini", "openai-compat": "openai"}

def _litellm_target(provider: str, cfg: dict) -> tuple[str, str | None, str | None]:
    """kage provider config → (litellm_model, api_key|None, api_base|None).

    Merges DEFAULT_PROVIDERS with user config (same as cloud.py:98-105), resolves the key from
    the env var named by api_key_env (cloud.py:106) — None, never "", when unset/keyless — and
    rebuilds the endpoint LiteLLM appends '/chat/completions' to.
    """
    pcfg = {**DEFAULT_PROVIDERS.get(provider, {}), **cfg.get("providers", {}).get(provider, {})}
    if "model" not in pcfg:
        raise ValueError(
            f"scout cloud_provider '{provider}' not configured — add providers.{provider} to ~/.kage/config.json"
        )
    ptype = pcfg.get("type", "openai-compat")
    model = f"{_LITELLM_PREFIX.get(ptype, 'openai')}/{pcfg['model']}"
    api_key = os.environ.get(pcfg["api_key_env"]) or None
    if ptype == "openai-compat":
        # kage POSTs to base_url + chat_path; LiteLLM appends '/chat/completions' to api_base,
        # so api_base = base_url + (chat_path minus that suffix). For Chirag's providers the
        # suffix is the whole chat_path → api_base == base_url (e.g. .../api/v1). Correct for a
        # hypothetical groq-style '/v1/chat/completions' too → base + '/v1'.
        api_base = pcfg["base_url"] + pcfg.get("chat_path", "/chat/completions").removesuffix("/chat/completions")
    else:
        api_base = None
    return model, api_key, api_base
```

This faithfully reproduces what kage already sends today (model `openrouter/free` → `https://openrouter.ai/api/v1/chat/completions`), so it inherits a known-working path rather than inventing one.

#### A2. The run loop

```python
def run(mode: str) -> None:
    cfg = runtime.config.data
    cache = _load_seen_cache()
    if mode == "run" and not cache:
        raise SystemExit("seen-cache empty — run: kage scout bootstrap")

    items = [it for it in fetch(cfg) if _key(it) not in cache]
    corpus = _corpus(items)                       # see _corpus cap below
    pipeline = build_pipeline(cfg, cloud=(mode == "run"))

    runner = InMemoryRunner(node=pipeline, app_name="kage-scout")   # node=, not agent= — a Workflow is a BaseNode
    final = _run_once(runner, corpus)             # full ADK glue — authored below, NOT prose
    if mode != "dry-run":
        _write_report(mode, final)
        _update_cache(cache, items)               # dry-run writes neither report nor cache
    _token_log(mode, items, final)
```

#### A2a. `_run_once` — the ADK runner glue (cloud-authored in FULL; Qwen3 copies, does not invent)

This is the highest ADK-knowledge piece and Qwen3 has no training signal for it. Do **not** leave it as prose. `InMemoryRunner` defaults to `auto_create_session=False`, so the session must be created on the session service first, then driven with `run_async`.

> **v4 correction (caught by a live run, not by reading source):** the Workflow's answer is **not** the last `is_final_response()` event's text, and it is **not** on the original `session` object — after `run_async` returns, `session.state` is unchanged (`session.state["report"]` → `None`). Each `LlmAgent`'s `output_key` writes its result into session state, but you only see it by **re-fetching** the session via `get_session(...)`. Verified empirically on 2026-06-24: single-stage → `state["shortlist"]`; two-stage → `state` holds **both** `shortlist` and `report`, so `report or shortlist` selects the terminal node's output (cloud=run) and degrades to `shortlist` (bootstrap/dry-run, one node).

```python
import asyncio
from google.genai import types

async def _run_once_async(runner: InMemoryRunner, corpus: str) -> str:
    session = await runner.session_service.create_session(
        app_name="kage-scout", user_id="scout",
    )
    message = types.Content(role="user", parts=[types.Part(text=corpus)])
    async for _ in runner.run_async(
        user_id="scout", session_id=session.id, new_message=message,
    ):
        pass  # drain the stream — each node's answer lands in session state via output_key, not in the events
    # The original `session` object is NOT mutated; re-fetch to read the terminal state.
    final = await runner.session_service.get_session(
        app_name="kage-scout", user_id="scout", session_id=session.id,
    )
    return final.state.get("report") or final.state.get("shortlist") or ""

def _run_once(runner: InMemoryRunner, corpus: str) -> str:
    return asyncio.run(_run_once_async(runner, corpus))   # batch entrypoint — own the event loop
```

> **Step 0 still applies:** if installed `google-adk` 2.3.0 differs on any of `session_service.create_session`, `run_async`, `get_session`, `output_key`→state, or `types.Content`/`types.Part`, fix to match the installed surface — do not invent symbols.

#### A2b. `_corpus` cap (explicit — don't make Qwen3 pick a number)

```python
_CORPUS_CHAR_CAP = 120_000   # ≈30k tokens at ~4 ch/tok — headroom under Qwen3's 40k ctx
                             # ponytail: char≈token proxy; ceiling = code/non-Latin items run hot.
```

Truncation is **round-robin across sources**, not first-source-wins, so no single noisy source (e.g. Reddit, even post-prefilter) crowds the others out. Specify it precisely so the test is deterministic:

1. **Group** the flat `items` list by `item["source"]`.
2. **Fixed source order** — iterate a module constant `_SOURCE_ORDER = ("hn", "arxiv", "github", "reddit", "rss")` (not dict-hash order), so the output is reproducible and the test is deterministic.
3. Each item renders to `f'[{source}] {title} — {snippet}\n'`; round-robin pop one item per source in turn, appending while `len(corpus) + len(rendered) <= _CORPUS_CHAR_CAP`.
4. **Skip, don't stop:** if an item would exceed the cap, skip it and keep serving other sources; terminate when every source queue is empty or no remaining item fits.
5. **All-empty → return `""`** — `run()` still proceeds; the report notes "no new items tonight" rather than erroring.

The Cycle 13 smoke test already saw Reddit overflow 40k raw; this cap + round-robin + fixed order is the fix.

### B. Source layer (inside `scout.py` — one file; split only if it actually crowds past ~300 lines)

v1 sources — **all public, no login:**

| Source | Access | Auth |
|---|---|---|
| Hacker News | Algolia API (`hn.algolia.com/api/v1/search?tags=front_page`) | none |
| arXiv | Atom API by category | none |
| GitHub | Search API (stars + pushed-recent) | optional token (rate limit only) |
| Reddit | `reddit.com/r/<sub>.json` + **pre-filter to titles+scores** (~2k vs ~53k tok) | none |
| Generic RSS | user-configured feed URLs | none |

`browser` arm is **not** used by Scout v1 (it's the login/JS-heavy path → v2). v1 fetch is plain GET over JSON+Atom via a new `http._get(url, headers=None, timeout=30) -> str` (GET sibling of `_post_json`, same UA-centralization rationale). Scout passes `User-Agent: kage-scout/0.1` (Reddit/GitHub 403 the default urllib UA — same bug class as the Groq fix). JSON sources `json.loads` the text; arXiv Atom + RSS parse via stdlib `xml.etree.ElementTree`.

### C. `~/.kage/config.json` — `"scout"` block (user adds)

```json
"scout": {
  "enabled": false,
  "run_at": "00:00",
  "cloud_provider": "openrouter-free",
  "reddit_subs": ["LocalLLaMA", "MachineLearning"],
  "github_token": "",
  "rss_feeds": [],
  "log_retention_days": 30
}
```

`enabled: false` default — Scout never runs until you opt in. Score thresholds are deliberately **not** configurable (that judgment is Librarian's job, Cycle 15).

### D. `~/.kage/scout/` tree (created on first run)

```
~/.kage/scout/
  YYYY-MM-DD.md        morning reports        [ ] Approve / Park / Discard per finding
  bootstrap.md         one-time orientation
  cache/seen.json      URL + content-hash set (NOT last-modified)
  log/                 per-run token+timing logs, rolling 30-day
  (browser-session/    v2 seam — not created in v1)
```

### E. launchd plist (`~/Library/LaunchAgents/com.kage.scout.plist`, user installs)

Runs `kage scout run` at `run_at`. Provided as a template in the pitch; user `launchctl load`s it. (Mac-native scheduler — no cron, no daemon. **Awareness over control**: it just runs; you see the report.)

---

## CLI surface

`kage scout <cmd>` — four commands (login dropped from v1):

| Command | Does | Cloud? | Writes cache? |
|---|---|---|---|
| `run` | full pipeline, both stages | yes | yes |
| `dry-run [--source NAME]` | fetch + broad stage only; inspect output | no | no |
| `bootstrap` | fetch + broad stage, top-5/source cap, writes `bootstrap.md`, **seeds cache** | no | yes |
| `status` | last run, cache size, enabled state, next scheduled time | no | no |

`run` refuses on an empty cache and points at `bootstrap` — without it, the first night reports the entire internet as "new."

---

## Implementation order for Qwen3

Each step is a diff or a new file. Output diffs, not full-file rewrites (Ollama context limit).

```
Step 0 — verify installed google-adk import surface (§A1 guard). STOP if it differs; report back.
Step 1 — scout.py: fetch() + per-source functions (deterministic, no LLM, per-source try/except). Pure I/O.
Step 2 — scout.py: _key() + seen-cache load/update + _corpus() round-robin cap (§A2b).
Step 3 — scout.py: scout_recall() tool — _resolve_context → _search → _disclosure_gate → excerpts. (gated egress point)
Step 4 — scout.py: _litellm_target() (COPY §A1a verbatim — authored) + build_pipeline() ADK wiring (§A1, copy the skeleton).
Step 5 — scout.py: _run_once / _run_once_async ADK runner glue. COPY §A2a verbatim; adapt only if Step 0 flagged drift.
Step 6 — scout.py: run() orchestration + _write_report() + _token_log() (§A2).
Step 7 — cli.py: `scout` Typer sub-app with run/dry-run/bootstrap/status, delegating to scout.run().
Step 8 — tests (see Test Plan).
```

Step 5 is split out from `run()` deliberately: the ADK glue is the one piece Qwen3 cannot derive, so it gets its own isolated step where the job is "copy the authored block, don't invent."

cli.py wiring (Step 7) reuses the existing Typer sub-app pattern already used by `arm` — re-export nothing new through `cli.*` beyond the sub-app registration.

---

## Test Plan (cloud-authored, Qwen3 writes)

New file `tests/test_scout.py` (Scout is its own module — don't bloat `test_cli.py`). **Never** hit a real model or real source in CI. **Exact mock seams (so Qwen3 isn't left stubbing an async ADK runner):** monkeypatch `scout._run_once` to return a canned report string (the cleanest seam — it owns the whole runner), and monkeypatch `scout.fetch` / the per-source functions to return fixed items. Tests that exercise `run()`/`bootstrap`/`dry-run` patch `scout._run_once`; the gating tests call `scout_recall` directly with `runtime.store` patched (same pattern as the existing `TestGateConversation`).

| Test | What it checks |
|---|---|
| `test_fetch_dedups_against_seen_cache` | items whose `_key` is in the cache are dropped |
| `test_reddit_prefilter_shrinks_payload` | Reddit raw JSON → titles+scores only; output token estimate << raw |
| `test_scout_recall_gates_local_only` | a `local_only` / withheld row is **never** returned by `scout_recall` (the 3e invariant) |
| `test_scout_recall_returns_allowed` | allowed rows pass through with excerpt fields |
| `test_bootstrap_seeds_cache` | bootstrap writes `bootstrap.md` and a non-empty `seen.json` |
| `test_run_refuses_on_empty_cache` | `run` with empty cache raises/points at bootstrap |
| `test_dry_run_writes_no_cache_no_report` | dry-run leaves cache + report dir untouched |
| `test_build_pipeline_bootstrap_skips_cloud` | `cloud=False` → `{n.name for n in pipeline.graph.nodes}` has `"ScoutBroad" in` and `"ScoutIntegrate" not in` (broad only — no cloud egress in bootstrap). **Set-membership only — never length/index (`__START__` is always a node); see §A1 graph-inspection note.** |
| `test_build_pipeline_cloud_has_two_stages` | `cloud=True` → that same name set has both `"ScoutBroad"` and `"ScoutIntegrate"`. Membership only. |
| `test_litellm_target_maps_openrouter` | `openrouter-free` → model `openai/openrouter/free`, `api_base="https://openrouter.ai/api/v1"`, key from `OPENROUTER_API_KEY` env |
| `test_litellm_target_keyless_returns_none` | with the env var unset, `api_key` is `None`, not `""` |
| `test_scout_recall_resolves_context` | `scout_recall` passes the resolved identity/project (not hardcoded) into `_disclosure_gate` |
| `test_fetch_isolates_failing_source` | one source raising leaves the other sources' items intact (run not aborted) |
| `test_corpus_round_robin_under_cap` | corpus respects `_CORPUS_CHAR_CAP` and interleaves sources (no single source crowds out) |

Target: ~14 tests. The gating tests (`test_scout_recall_gates_local_only`, `test_build_pipeline_bootstrap_skips_cloud`) are the **security-critical** ones — they prove no personal data leaves except through the gate.

Expanded testing (more sources, more sites, multiple real runs) is deferred until CI is green and the basics work — per the locked §19 decision.

---

## What this cycle is NOT

- **Not Librarian.** Scout is stateless-dumb: no learning, no source-quality scoring, no approval-pattern memory. Your ticks are a seam (`[x]` blocks in the report) consumed by Cycle 15.
- **Not Monitor.** No watching/alerting. Scout is overnight-batch only.
- **Not logged-in / personalized scraping.** v2 seam. v1 is public APIs + RSS.
- **Not Mode 2** (on-demand prompted research). Deferred to the Notification arm + Librarian.
- **Not a daemon.** launchd fires it nightly; it runs once and exits.
- **Not a network-tool-calling agent.** Fetch is deterministic; the only tool is gated `scout_recall`.

---

## Seams left open (deliberate, future-proofed)

| Seam | Lands in |
|---|---|
| `before_model_callback = _pii_seam` (pass-through) | Layer 3e v2 — reversible value-substitution over the whole cloud request |
| `[x] Approve/Park/Discard` decision blocks | Librarian (Cycle 15) — learns source quality + approval patterns |
| `browser-session/` dir + `kage scout login` | v2 personalized-feed scraping (Playwright persistent context) |
| Discovery gap / filter-bubble breadth | Librarian design session |
| Mode 2 (prompted) report naming `YYYY-MM-DD-prompted-[label].md` | Notification arm |

---

## Capstone mapping (this cycle)

| Concept | Scout covers it |
|---|---|
| ADK / multi-agent | `Workflow` graph of two `LlmAgent` nodes (START→broad→integrate), LiteLLM-routed |
| Security features | `scout_recall` gated by `_disclosure_gate`; bootstrap skips cloud entirely; audit log |
| Agent skill | `kage scout` command subtree |
| Deployability | launchd plist + `enabled: false` opt-in (video) |

Librarian (Cycle 15) and Monitor (Cycle 16) complete the three-agent capstone roster before the **July 6, 2026** deadline.
```