from __future__ import annotations
import hashlib
import json
import datetime as _dt
import xml.etree.ElementTree as _ET
from collections import deque
from kage import http as _http
from kage import privacy as _privacy
from kage import runtime
from kage.cli import _search, _disclosure_gate
from kage.context import _resolve_context
import os
import asyncio
from google.genai import types
from google.adk.agents import LlmAgent
from google.adk.workflow import Workflow, START
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from kage.cloud import DEFAULT_PROVIDERS

_SOURCE_ORDER = ("hn", "arxiv", "github", "reddit", "rss")
_UA = {"User-Agent": "kage-scout/0.1"}
# ponytail: 100k cap leaves ~6k token headroom in Qwen3's 32k window;
# ceiling = Qwen3 ctx limit; upgrade path = raise cap if model is swapped for larger ctx
_CORPUS_CHAR_CAP = 100_000
_SCOUT_RECALL_LIMIT = 5
_LITELLM_PREFIX = {"claude": "anthropic", "openai": "openai", "gemini": "gemini", "openai-compat": "openai"}

_BROAD_INSTRUCTION = (
    "You are Scout's triage stage. You receive a corpus of recent items from Hacker News, "
    "arXiv, GitHub, Reddit, and RSS feeds.\n\n"
    "CRITICAL: Only classify items explicitly present in the corpus. "
    "Do not add, invent, or infer items from your training knowledge.\n\n"
    "Classify every item into exactly one tier. Nothing is dropped.\n\n"
    "You have no information about the active project. Classify generically:\n"
    "Tier 1 — Actionable: items that could become a task, implementation decision, or cycle "
    "for a software engineering project. Includes: GitHub repos with novel/useful functionality, "
    "research papers with concrete implementation implications, tools or techniques that could "
    "replace something in a typical stack.\n\n"
    "Tier 2 — Good to Know: everything else. Includes: company news, acquisitions, funding, "
    "general releases, industry trends, opinion pieces, world events. Interesting but not "
    "directly actionable in a software project.\n\n"
    "Output format — use exactly:\n\n"
    "## Tier 1 — Actionable\n"
    "- [source] Title — one sentence why actionable\n\n"
    "## Tier 2 — Good to Know\n"
    "- [source] Title — one sentence summary\n\n"
    "Where [source] is one of: hn, arxiv, github, reddit, rss.\n"
    "If a tier has no items write: (none)"
)
# ponytail: ScoutIntegrate receives ScoutBroad's output as its user message (ADK Workflow
# passes previous node's final response to next node). Format compliance depends on Qwen3 14B.
# If Tier 1/Tier 2 headers are malformed or [source] tags are inconsistent, ScoutIntegrate
# sees noise and may hallucinate structure. Upgrade path = validate shortlist format before
# passing to cloud stage (e.g. regex check for "## Tier" headers before run_async).

_INTEGRATE_INSTRUCTION = (
    "You are Scout's integration stage. You receive a classified shortlist of items "
    "as your input message above.\n\n"
    "CRITICAL: Only include items from the shortlist above. "
    "Do not add, invent, or infer items from your training knowledge.\n\n"
    "Step 1 — Project context (do this FIRST, before analyzing any item):\n"
    "Call scout_recall with the query: "
    "'{project} current stack implementation goals and recent changes'\n"
    "If scout_recall returns empty results, write 'unknown' for all "
    "'Currently used' and 'Previously used' fields. Do not infer from training knowledge.\n\n"
    "Step 2 — For each Tier 1 item, call scout_recall with a short targeted query "
    "(e.g. the tool or technique name) to check project memory. "
    "Use the result for 'Currently used' and 'Previously used' fields.\n\n"
    "Step 3 — Write the morning digest:\n\n"
    "# Scout Report — {today}\n"
    "**Active project:** {project}\n\n"
    "## Tier 1 — Actionable\n\n"
    "If Tier 1 contains only '(none)', write '(none)' and no cards.\n"
    "Otherwise for each Tier 1 item:\n"
    "### [source] Title\n"
    "> ⭐ X stars · 🍴 Y forks · Language · License · Last push: YYYY-MM-DD\n"
    "  (GitHub items only — omit this entire block for non-GitHub items)\n\n"
    "**Tech relevance:** one sentence why the tech world cares\n"
    "**{project} relevance:** why this matters to {project} — or 'N/A — [reason]'\n"
    "**Where in {project}:** which module/layer/component — or 'N/A'\n"
    "**Currently used:** from recall — or 'unknown'\n"
    "**Previously used:** from recall — or 'unknown'\n"
    "**Competitors:** 2–4 main alternatives\n"
    "**Outperforms by:** how and how much — or 'unclear'\n"
    "**Complexity:** low/medium/high — ~N specs, ~N days\n"
    "**Worth your time?** yes/no + decisive reason\n"
    "**Cycle candidate:** [ ] yes — one-line pitch  OR  [-] no — one-line reason\n\n"
    "## Tier 2 — Good to Know\n\n"
    "For each Tier 2 item:\n"
    "### [source] Title\n"
    "**What happened:** one sentence\n"
    "**Tech relevance:** one sentence\n"
    "**{project} relevance:** 'N/A — [reason]' or one sentence if it applies\n\n"
    "---\n"
    "**What to dig into today:** 2–3 sentences on highest-signal Tier 1 items "
    "and why they are worth time today. Omit this paragraph if Tier 1 is (none)."
)


def _fetch_hn() -> list[dict]:
    """Hacker News front-page items (Algolia API), normalized to the source-item shape."""
    text = _http._get("https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30", headers=_UA)
    data = json.loads(text)
    results = []
    for hit in data["hits"]:
        title = hit.get("title") or ""
        if not title:
            continue
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
        results.append({"source": "hn", "title": title, "url": url, "score": hit.get("points", 0), "snippet": ""})
    return results


def _fetch_github(cfg) -> list[dict]:
    """GitHub repos with >100 stars pushed in the last 7 days (Search API; token optional, rate-limit only)."""
    date = str(_dt.date.today() - _dt.timedelta(days=7))
    url = f"https://api.github.com/search/repositories?q=stars:>100+pushed:>{date}&sort=stars&order=desc&per_page=20"
    headers = dict(_UA)
    headers["Accept"] = "application/vnd.github+json"
    token = cfg.get("scout", {}).get("github_token", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.loads(_http._get(url, headers=headers))
    results = []
    for item in data.get("items", []):
        results.append({
            "source": "github",
            "title": item["full_name"],
            "url": item["html_url"],
            "score":     item.get("stargazers_count", 0),
            "snippet":   item.get("description") or "",
            "forks":     item.get("forks_count", 0),
            "language":  item.get("language") or "",
            "license":   (item.get("license") or {}).get("spdx_id") or "",
            "pushed_at": (item.get("pushed_at") or "")[:10],
        })
    return results


def _fetch_reddit(cfg) -> list[dict]:
    """Reddit posts from configured subs — PRE-FILTERED to title+score+url only (drops body; the 40k-ctx fix)."""
    subs = cfg.get("scout", {}).get("reddit_subs", [])
    results = []
    for sub in subs:
        data = json.loads(_http._get(f"https://www.reddit.com/r/{sub}/.json?limit=25", headers=_UA))
        for child in data["data"]["children"]:
            d = child["data"]
            results.append({
                "source": "reddit",
                "title": d["title"],
                "url": f"https://reddit.com{d['permalink']}",
                "score": d.get("score", 0),
                "snippet": "",
            })
    return results


def _fetch_arxiv() -> list[dict]:
    """Latest cs.AI submissions from the arXiv Atom API, normalized to the source-item shape."""
    text = _http._get(
        "https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=20",
        headers=_UA,
    )
    root = _ET.fromstring(text)
    ns = "{http://www.w3.org/2005/Atom}"
    results = []
    for entry in root.findall(ns + "entry"):
        title = entry.findtext(ns + "title", "").strip()
        url = entry.findtext(ns + "id", "").strip()
        summary = entry.findtext(ns + "summary", "").strip()
        results.append({"source": "arxiv", "title": title, "url": url, "score": 0, "snippet": summary[:200]})
    return results


def _fetch_rss(cfg) -> list[dict]:
    """Items from each configured RSS 2.0 feed (stdlib xml parse)."""
    # ponytail: RSS 2.0 <item> elements only; Atom-only feeds and HTML-in-description left raw.
    # Upgrade: feedparser for Atom + sanitized text.
    feeds = cfg.get("scout", {}).get("rss_feeds", [])
    results = []
    for feed_url in feeds:
        root = _ET.fromstring(_http._get(feed_url, headers=_UA))
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            results.append({"source": "rss", "title": title, "url": url, "score": 0, "snippet": desc[:200]})
    return results


def fetch(cfg) -> list[dict]:
    """Aggregate all enabled sources; each source isolated in its own try/except (one failure never aborts the run)."""
    results = []
    for name in _SOURCE_ORDER:
        try:
            if name == "hn":
                src_data = _fetch_hn()
            elif name == "arxiv":
                src_data = _fetch_arxiv()
            elif name == "github":
                src_data = _fetch_github(cfg)
            elif name == "reddit":
                src_data = _fetch_reddit(cfg) if cfg.get("scout", {}).get("reddit_subs", []) else []
            elif name == "rss":
                src_data = _fetch_rss(cfg) if cfg.get("scout", {}).get("rss_feeds", []) else []
            results.extend(src_data)
            _privacy._write_audit({
                "type": "scout_fetch", "source": name, "success": True, "items": len(src_data),
                "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            })
        except Exception:
            _privacy._write_audit({
                "type": "scout_fetch", "source": name, "success": False,
                "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            })
    return results


def _key(item) -> str:
    """The single dedup identity (url + content hash) — used by BOTH the dedup filter and the cache writer so they can never drift."""
    return item["url"] + "|" + hashlib.sha1((item["title"] + item["snippet"]).encode()).hexdigest()[:12]


def _cache_path():
    """Path to the seen-cache (url+hash set), under the KAGE_HOME-aware scout tree."""
    return runtime.config.home / "scout" / "cache" / "seen.json"


def _load_seen_cache() -> set:
    """Load the seen-cache as a set; empty set if it doesn't exist yet."""
    path = _cache_path()
    if not path.exists():
        return set()
    return set(json.loads(path.read_text()))


def _update_cache(cache: set, items) -> None:
    """Add each item's key to the cache and persist it (sorted JSON list)."""
    for item in items:
        cache.add(_key(item))
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(cache)))


def scout_recall(query: str) -> list[dict]:
    """ADK tool for the cloud stage — resolves identity/project, searches memory, gates via _disclosure_gate, returns only allowed excerpts (the v1 egress chokepoint)."""
    cfg = runtime.config.data
    identity, project, _ = _resolve_context(None, None)
    rows = _search(query, project, limit=_SCOUT_RECALL_LIMIT, identity=identity)
    allowed, _ = _disclosure_gate(rows, cfg, identity=identity, project=project)
    return [{"snippet": row[4], "project": row[1]} for row in allowed]


def _pii_seam(callback_context, llm_request):
    # ponytail: v1 pass-through — Layer 3e v2 will implement reversible value-substitution here
    return None


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


def build_pipeline(cfg: dict, *, cloud: bool) -> Workflow:
    # Pass 1+2 — broad gather + noise filter. Local Qwen3 via LiteLLM→Ollama. $0, never leaves machine.
    broad = LlmAgent(
        name="ScoutBroad",
        model=LiteLlm(model="ollama_chat/qwen3:14b"),
        instruction=_BROAD_INSTRUCTION,
        output_key="shortlist",
    )
    # Workflow graph: LlmAgents go straight into the edge tuples (auto-wrapped as nodes).
    # START is the graph entry; the corpus arrives as the first node's input message.
    if not cloud:
        return Workflow(name="Scout", edges=[(START, broad)])

    # Pass 3+4 — verify + integrate against existing memory, write the morning report. Cloud judgment.
    provider = cfg["scout"].get("cloud_provider", "openrouter-free")
    model_str, api_key, api_base = _litellm_target(provider, cfg)
    # Pass api_key / api_base ONLY when present. An empty-string key makes some LiteLLM providers
    # attempt a doomed auth handshake; a None api_base lets native vendors use their own endpoint.
    kwargs = {"model": model_str}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    # ponytail: ADK substitutes {project}/{today} from session state into instruction strings at
    # run time (confirmed empirically — v0.14.0 shipped {today} substitution and produced correct
    # dates in reports). Ceiling: if ADK removes this feature, {project} appears literally in the
    # report and Step 1 scout_recall query fires with "{project} current stack..." (silent failure).
    # Upgrade path: explicit _INTEGRATE_INSTRUCTION.format(project=..., today=...) in _run_once_async.
    integrate = LlmAgent(
        name="ScoutIntegrate",
        model=LiteLlm(**kwargs),
        instruction=_INTEGRATE_INSTRUCTION,
        tools=[scout_recall],
        before_model_callback=_pii_seam,
        output_key="report",
    )
    # broad → integrate runs sequentially; integrate's output_key="report" is the terminal state.
    return Workflow(name="Scout", edges=[(START, broad), (broad, integrate)])


def _corpus(items) -> str:
    """Deterministic round-robin across sources (fixed _SOURCE_ORDER); skip items that would exceed the cap but keep going so smaller later items still fit. Empty items → ""."""
    queues = {s: deque() for s in _SOURCE_ORDER}
    for it in items:
        if it["source"] in queues:
            queues[it["source"]].append(it)
    corpus = ""
    while True:
        updated = False
        for source in _SOURCE_ORDER:
            if queues[source]:
                updated = True
                it = queues[source].popleft()
                if it["source"] == "github":
                    parts = [f"⭐ {it.get('score', 0)} stars", f"🍴 {it.get('forks', 0)} forks"]
                    for field in (it.get("language", ""), it.get("license", ""), f"last push {it.get('pushed_at', '')}"):
                        if field and field != "last push ":
                            parts.append(field)
                    stats = " · ".join(parts)
                    rendered = f"[github] {it['title']} — {it['snippet']}\n  {stats}\n" if stats else f"[github] {it['title']} — {it['snippet']}\n"
                else:
                    rendered = f"[{it['source']}] {it['title']} — {it['snippet']}\n"
                if len(corpus) + len(rendered) <= _CORPUS_CHAR_CAP:
                    corpus += rendered
        if not updated:
            break
    return corpus


async def _run_once_async(runner: InMemoryRunner, corpus: str) -> str:
    _, project, _ = _resolve_context(None, None)   # sync file read, safe in CLI batch
    session = await runner.session_service.create_session(
        app_name="kage-scout", user_id="scout",
        state={
            "today": str(_dt.date.today()),
            "project": project or "kage",
        },
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


def _write_report(mode: str, final: str) -> None:
    if mode == "bootstrap":
        filename = "bootstrap.md"
    else:
        filename = f"{_dt.date.today()}.md"
    output_path = runtime.config.home / "scout" / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final)
    _privacy._write_audit({
        "type": "scout_report",
        "mode": mode,
        "path": str(output_path),
        "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    })


def _token_log(mode: str, items: list, final: str) -> None:
    # ponytail: char-count proxy for tokens (no tokenizer dep); upgrade to tiktoken when precision matters
    log_path = runtime.config.home / "scout" / "log" / f"{_dt.date.today()}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": mode,
        "items": len(items),
        "corpus_chars": sum(len(it.get("title", "")) + len(it.get("snippet", "")) for it in items),
        "report_chars": len(final),
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def run(mode: str) -> str:
    cfg = runtime.config.data
    cache = _load_seen_cache()
    if mode == "run" and not cache:
        raise RuntimeError("seen-cache empty — run: kage scout bootstrap")

    items = [it for it in fetch(cfg) if _key(it) not in cache]
    corpus = _corpus(items)
    pipeline = build_pipeline(cfg, cloud=(mode == "run"))   # dry-run → cloud=False intentionally (broad pass only, no egress)

    runner = InMemoryRunner(node=pipeline, app_name="kage-scout")   # node=, not agent= — Workflow is a BaseNode
    final = _run_once(runner, corpus)
    if mode != "dry-run":
        _write_report(mode, final)
        _update_cache(cache, items)               # dry-run writes neither report nor cache
    _token_log(mode, items, final)
    return final
