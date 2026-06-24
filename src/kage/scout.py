from __future__ import annotations
import hashlib
import json
import datetime as _dt
import xml.etree.ElementTree as _ET
from collections import deque
from kage import http as _http
from kage import privacy as _privacy
from kage import runtime

_SOURCE_ORDER = ("hn", "arxiv", "github", "reddit", "rss")
_UA = {"User-Agent": "kage-scout/0.1"}
_CORPUS_CHAR_CAP = 120_000   # ≈30k tokens; headroom under Qwen3's 40k ctx


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
            "score": item.get("stargazers_count", 0),
            "snippet": item.get("description") or "",
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
                rendered = f"[{it['source']}] {it['title']} — {it['snippet']}\n"
                if len(corpus) + len(rendered) <= _CORPUS_CHAR_CAP:
                    corpus += rendered
        if not updated:
            break
    return corpus
