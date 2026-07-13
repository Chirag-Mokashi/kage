from unittest.mock import MagicMock
from kage import scout


def test_fetch_hn_parses(monkeypatch):
    def fake_get(url, headers=None, timeout=30):
        return '{"hits":[{"title":"A","url":"http://a.com","points":5,"objectID":"1"},{"title":"B","url":null,"points":2,"objectID":"99"}]}'
    monkeypatch.setattr(scout._http, "_get", fake_get)
    results = scout._fetch_hn()
    assert len(results) == 2
    assert set(results[0].keys()) == {"source", "title", "url", "score", "snippet"}
    assert results[0]["url"] == "http://a.com"
    assert results[1]["url"] == "https://news.ycombinator.com/item?id=99"
    assert results[0]["score"] == 5


def test_fetch_reddit_prefilters_body(monkeypatch):
    def fake_get(url, headers=None, timeout=30):
        return '{"data":{"children":[{"data":{"title":"R1","permalink":"/r/x/1","score":7,"selftext":"SECRETBODY"}}]}}'
    monkeypatch.setattr(scout._http, "_get", fake_get)
    results = scout._fetch_reddit({"scout": {"reddit_subs": ["x"]}})
    assert len(results) == 1
    assert results[0]["snippet"] == ""
    assert results[0]["url"] == "https://reddit.com/r/x/1"
    assert results[0]["score"] == 7
    assert "SECRETBODY" not in scout._corpus(results)
    assert results[0].get("body") is not None


def test_fetch_github_auth_header(monkeypatch):
    recorded_headers = []
    def fake_get(url, headers=None, timeout=30):
        recorded_headers.append(headers)
        return '{"items":[]}'
    monkeypatch.setattr(scout._http, "_get", fake_get)
    scout._fetch_github({"scout": {"github_token": "TKN"}})
    assert recorded_headers[0]["Authorization"] == "Bearer TKN"
    recorded_headers.clear()
    scout._fetch_github({"scout": {}})
    assert "Authorization" not in recorded_headers[0]

    def fake_get_item(url, headers=None, timeout=30):
        return '{"items":[{"full_name":"a/b","html_url":"http://h","stargazers_count":10,"description":"desc","forks_count":5,"language":"Python","license":{"spdx_id":"MIT"},"pushed_at":"2026-06-01T00:00:00Z"}]}'
    monkeypatch.setattr(scout._http, "_get", fake_get_item)
    items = scout._fetch_github({"scout": {}})
    assert items[0]["forks"] == 5
    assert items[0]["language"] == "Python"
    assert items[0]["license"] == "MIT"
    assert items[0]["pushed_at"] == "2026-06-01"


def test_fetch_isolates_failing_source(monkeypatch):
    audit_log = []
    monkeypatch.setattr(scout._privacy, "_write_audit", lambda arg: audit_log.append(arg))
    def fake_fetch_hn(*args, **kwargs):
        raise RuntimeError("Test error")
    monkeypatch.setattr(scout, "_fetch_hn", fake_fetch_hn)
    monkeypatch.setattr(scout, "_fetch_arxiv", lambda *a, **k: [{"source": "arxiv", "title": "x", "url": "u", "score": 0, "snippet": ""}])
    monkeypatch.setattr(scout, "_fetch_github", lambda *a, **k: [])
    results = scout.fetch({"scout": {"reddit_subs": [], "rss_feeds": []}})
    assert any(item["source"] == "arxiv" for item in results)
    assert not any(item["source"] == "hn" for item in results)
    assert any(record["source"] == "hn" and record["success"] is False for record in audit_log)


def test_fetch_audits_successful_source(monkeypatch):
    audit_log = []
    monkeypatch.setattr(scout._privacy, "_write_audit", lambda arg: audit_log.append(arg))
    monkeypatch.setattr(scout, "_fetch_hn", lambda: [{"source": "hn", "title": "T", "url": "u", "score": 1, "snippet": ""}])
    monkeypatch.setattr(scout, "_fetch_arxiv", lambda: [])
    monkeypatch.setattr(scout, "_fetch_github", lambda cfg: [])
    scout.fetch({"scout": {"reddit_subs": [], "rss_feeds": []}})
    success_records = [r for r in audit_log if r.get("success") is True]
    assert any(r["source"] == "hn" and r["items"] == 1 for r in success_records)


def test_fetch_arxiv_parses_atom(monkeypatch):
    fake = lambda url, headers=None, timeout=30: '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>PaperA</title><id>http://arxiv.org/abs/1234</id><summary>This is the abstract.</summary></entry></feed>'
    monkeypatch.setattr(scout._http, "_get", fake)
    items = scout._fetch_arxiv()
    assert len(items) == 1
    assert items[0]["source"] == "arxiv"
    assert items[0]["title"] == "PaperA"
    assert items[0]["url"] == "http://arxiv.org/abs/1234"
    assert items[0]["snippet"].startswith("This is")
    assert items[0]["score"] == 0


def test_fetch_rss_parses_items(monkeypatch):
    fake = lambda url, headers=None, timeout=30: '<rss version="2.0"><channel><item><title>Post1</title><link>http://ex.com/1</link><description>Body text here.</description></item></channel></rss>'
    monkeypatch.setattr(scout._http, "_get", fake)
    items = scout._fetch_rss({"scout": {"rss_feeds": ["http://feed"]}})
    assert len(items) == 1
    assert items[0]["source"] == "rss"
    assert items[0]["title"] == "Post1"
    assert items[0]["url"] == "http://ex.com/1"
    assert items[0]["snippet"].startswith("Body")
    assert items[0]["score"] == 0


def test_key_is_deterministic_and_url_prefixed():
    item = {"source": "hn", "title": "T", "url": "http://a", "score": 1, "snippet": "s"}
    assert scout._key(item) == scout._key(dict(item))
    assert scout._key(item).startswith("http://a|")


def test_seen_cache_round_trip(tmp_path, monkeypatch):
    cache_file = tmp_path / "seen.json"
    monkeypatch.setattr(scout, "_cache_path", lambda: cache_file)
    assert scout._load_seen_cache() == set()
    item = {"source": "hn", "title": "T", "url": "http://a", "score": 1, "snippet": "s"}
    cache = set()
    scout._update_cache(cache, [item])
    assert cache_file.exists()
    assert scout._key(item) in scout._load_seen_cache()


def test_corpus_round_robin_order():
    items = [
        {"source": "github", "title": "G", "url": "u", "score": 0, "snippet": ""},
        {"source": "hn", "title": "H", "url": "u", "score": 0, "snippet": ""},
        {"source": "arxiv", "title": "A", "url": "u", "score": 0, "snippet": ""},
    ]
    corpus = scout._corpus(items)
    lines = corpus.splitlines()
    sources = [line.split("[")[1].split("]")[0] for line in lines if line.startswith("[")]
    assert sources == ["hn", "arxiv", "github"]


def test_corpus_empty_returns_empty():
    assert scout._corpus([]) == ""


def test_corpus_respects_cap():
    items = [{"source": "hn", "title": "a" * 5000, "url": "u", "score": 0, "snippet": "s" * 5000} for _ in range(50)]
    corpus = scout._corpus(items)
    assert len(corpus) <= scout._CORPUS_CHAR_CAP


def test_corpus_round_robin_interleaves():
    items = [
        {"source": "hn", "title": "item1", "url": "http://example.com", "score": 0, "snippet": ""},
        {"source": "hn", "title": "item2", "url": "http://example.com", "score": 0, "snippet": ""},
        {"source": "hn", "title": "item3", "url": "http://example.com", "score": 0, "snippet": ""},
        {"source": "arxiv", "title": "item4", "url": "http://example.com", "score": 0, "snippet": ""},
    ]
    corpus = scout._corpus(items)
    sources = [line.split("[")[1].split("]")[0] for line in corpus.splitlines() if line.startswith("[")]
    assert sources == ["hn", "arxiv", "hn", "hn"]


def test_corpus_single_oversized_item_skipped():
    big_item = {
        "source": "hn",
        "title": "x" * scout._CORPUS_CHAR_CAP,
        "url": "u",
        "score": 0,
        "snippet": "",
    }
    assert scout._corpus([big_item]) == ""


def test_scout_recall_returns_allowed(monkeypatch):
    fake_row = ("n1", "kage", "2026-01-01", "/path", "My snippet", None, None, None)
    monkeypatch.setattr(scout, "_resolve_context", lambda a, b: ("personal", "kage", "fallback"))
    monkeypatch.setattr(scout, "_search", lambda q, p, limit, identity: [fake_row])
    monkeypatch.setattr(scout, "_disclosure_gate", lambda rows, cfg, identity, project: ([fake_row], [], {}))
    result = scout.scout_recall("test query")
    assert result == [{"snippet": "My snippet", "project": "kage"}]


def test_scout_recall_gates_local_only(monkeypatch):
    fake_row = ("n1", "kage", "2026-01-01", "/path", "secret", None, None, None)
    monkeypatch.setattr(scout, "_resolve_context", lambda a, b: ("personal", "kage", "fallback"))
    monkeypatch.setattr(scout, "_search", lambda q, p, limit, identity: [fake_row])
    monkeypatch.setattr(scout, "_disclosure_gate", lambda rows, cfg, identity, project: ([], [{"id": "n1", "reason": "local_only"}], {}))
    result = scout.scout_recall("query")
    assert result == []


def test_scout_recall_resolves_context(monkeypatch):
    captured = {}
    def fake_disclosure_gate(rows, cfg, identity, project):
        captured["identity"] = identity
        captured["project"] = project
        return ([], [], {})
    monkeypatch.setattr(scout, "_resolve_context", lambda a, b: ("neu", "thesis", "sticky"))
    monkeypatch.setattr(scout, "_search", lambda q, p, limit, identity: [])
    monkeypatch.setattr(scout, "_disclosure_gate", fake_disclosure_gate)
    scout.scout_recall("anything")
    assert captured["identity"] == "neu"
    assert captured["project"] == "thesis"


def test_scout_recall_search_uses_resolved_identity(monkeypatch):
    captured_search = {}
    def fake_search(q, p, limit, identity):
        captured_search["identity"] = identity
        captured_search["project"] = p
        return []
    monkeypatch.setattr(scout, "_resolve_context", lambda a, b: ("neu", "thesis", "sticky"))
    monkeypatch.setattr(scout, "_search", fake_search)
    monkeypatch.setattr(scout, "_disclosure_gate", lambda rows, cfg, identity, project: ([], [], {}))
    scout.scout_recall("anything")
    assert captured_search["identity"] == "neu"
    assert captured_search["project"] == "thesis"


def test_scout_recall_empty_query_returns_empty(monkeypatch):
    monkeypatch.setattr(scout, "_resolve_context", lambda a, b: ("personal", None, "fallback"))
    monkeypatch.setattr(scout, "_search", lambda q, p, limit, identity: [])
    monkeypatch.setattr(scout, "_disclosure_gate", lambda rows, cfg, identity, project: ([], [], {}))
    assert scout.scout_recall("") == []



def test_litellm_target_maps_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    fake_cfg = {
        "scout": {"cloud_provider": "openrouter-free"},
        "providers": {
            "openrouter-free": {
                "type": "openai-compat",
                "api_key_env": "OPENROUTER_API_KEY",
                "base_url": "https://openrouter.ai/api/v1",
                "chat_path": "/chat/completions",
                "model": "openrouter/free",
            }
        }
    }
    model, api_key, api_base = scout._litellm_target("openrouter-free", fake_cfg)
    assert model == "openai/openrouter/free"
    assert api_base == "https://openrouter.ai/api/v1"
    assert api_key == "test-key"


def test_litellm_target_keyless_returns_none(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    fake_cfg = {
        "scout": {"cloud_provider": "openrouter-free"},
        "providers": {
            "openrouter-free": {
                "type": "openai-compat",
                "api_key_env": "OPENROUTER_API_KEY",
                "base_url": "https://openrouter.ai/api/v1",
                "chat_path": "/chat/completions",
                "model": "openrouter/free",
            }
        }
    }
    _, api_key, _ = scout._litellm_target("openrouter-free", fake_cfg)
    assert api_key is None


def test_litellm_target_native_claude_returns_none_base(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    fake_cfg = {
        "scout": {"cloud_provider": "claude"},
        "providers": {
            "claude": {
                "type": "claude",
                "api_key_env": "ANTHROPIC_API_KEY",
                "model": "claude-sonnet-4-6",
            }
        }
    }
    model, api_key, api_base = scout._litellm_target("claude", fake_cfg)
    assert model == "anthropic/claude-sonnet-4-6"
    assert api_base is None
    assert api_key == "ant-test"


def test_run_filters_seen_items_from_corpus(monkeypatch, tmp_path):
    old_item = {"source": "hn", "title": "Old", "url": "http://old", "score": 1, "snippet": ""}
    new_item = {"source": "hn", "title": "New", "url": "http://new", "score": 2, "snippet": ""}
    existing_key = scout._key(old_item)
    numbered_calls = []
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: {existing_key})
    monkeypatch.setattr(scout, "fetch", lambda cfg: [old_item, new_item])
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    class FakeConfig:
        data = {"scout": {"cloud_provider": "openrouter-free"}}
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    class FakeSession:
        id = "s1"
        state = {"shortlist_indices": ""}
    class FakeService:
        async def create_session(self, **kw): return FakeSession()
        async def get_session(self, **kw): return FakeSession()
    class FakeRunner:
        session_service = FakeService()
        def run(self, **kw):
            numbered_calls.append(kw.get("new_message"))
            return iter([])
    monkeypatch.setattr(scout, "InMemoryRunner", lambda *a, **kw: FakeRunner())
    scout.run("bootstrap")
    assert len(numbered_calls) == 1
    assert "Old" not in numbered_calls[0].parts[0].text
    assert "New" in numbered_calls[0].parts[0].text


def test_bootstrap_seeds_cache(monkeypatch, tmp_path):
    item = {"source": "arxiv", "title": "Paper", "url": "http://p", "score": 0, "snippet": "s"}
    update_cache_calls = []
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: set())
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_update_cache", lambda cache, items: update_cache_calls.append(items))
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    class FakeConfig:
        data = {"scout": {"cloud_provider": "openrouter-free"}}
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    class FakeSession:
        id = "s1"
        state = {"shortlist_indices": "1. reason"}
    class FakeService:
        async def create_session(self, **kw): return FakeSession()
        async def get_session(self, **kw): return FakeSession()
    class FakeRunner:
        session_service = FakeService()
        def run(self, **kw): return iter([])
    monkeypatch.setattr(scout, "InMemoryRunner", lambda *a, **kw: FakeRunner())
    scout.run("bootstrap")
    assert len(update_cache_calls) == 1
    assert update_cache_calls[0][0]["title"] == "Paper"


def test_run_refuses_on_empty_cache(monkeypatch, tmp_path):
    class FakeConfig:
        data = {"scout": {}}
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: set())
    monkeypatch.setattr(scout, "fetch", lambda cfg: [])
    import pytest
    with pytest.raises(RuntimeError):
        scout.run(mode="run")


def test_dry_run_skips_report_and_cache(monkeypatch, tmp_path):
    item = {"source": "hn", "title": "T", "url": "http://x", "score": 1, "snippet": ""}
    write_report_calls, update_cache_calls = [], []
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: set())
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "_write_report", lambda *a, **kw: write_report_calls.append(1))
    monkeypatch.setattr(scout, "_update_cache", lambda *a, **kw: update_cache_calls.append(1))
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    class FakeConfig:
        data = {"scout": {"cloud_provider": "openrouter-free"}}
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    class FakeSession:
        id = "s1"
        state = {"shortlist_indices": ""}
    class FakeService:
        async def create_session(self, **kw): return FakeSession()
        async def get_session(self, **kw): return FakeSession()
    class FakeRunner:
        session_service = FakeService()
        def run(self, **kw): return iter([])
    monkeypatch.setattr(scout, "InMemoryRunner", lambda *a, **kw: FakeRunner())
    scout.run(mode="dry-run")
    assert write_report_calls == []
    assert update_cache_calls == []





def test_write_report_creates_dated_file(monkeypatch, tmp_path):
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout._privacy, "_write_audit", lambda *args, **kwargs: None)
    scout._write_report("run", "# Report content")
    import datetime
    date_today = datetime.date.today()
    assert (tmp_path / "scout" / f"{date_today}.md").read_text() == "# Report content"


def test_write_report_bootstrap_filename(monkeypatch, tmp_path):
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout._privacy, "_write_audit", lambda *args, **kwargs: None)
    scout._write_report("bootstrap", "# Bootstrap")
    assert (tmp_path / "scout" / "bootstrap.md").exists()


def test_write_report_calls_audit(monkeypatch, tmp_path):
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    audit_records = []
    monkeypatch.setattr(scout._privacy, "_write_audit", lambda r: audit_records.append(r))
    scout._write_report("run", "content")
    assert len(audit_records) == 1
    assert audit_records[0]["type"] == "scout_report"
    assert audit_records[0]["mode"] == "run"


def test_token_log_appends_jsonl(monkeypatch, tmp_path):
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    items = [{"source": "hn", "title": "T", "url": "u", "score": 1, "snippet": "snip"}]
    scout._token_log("run", items, "final report text")
    import json, datetime
    log_file = tmp_path / "scout" / "log" / f"{datetime.date.today()}.jsonl"
    assert log_file.exists()
    record = json.loads(log_file.read_text().strip())
    assert record["mode"] == "run"
    assert record["items"] == 1
    assert record["corpus_chars"] > 0
    assert record["report_chars"] == len("final report text")


def test_fetch_github_stats_fields(monkeypatch):
    def fake_get(url, headers=None, timeout=30):
        return '{"items":[{"full_name":"owner/repo","html_url":"http://h","stargazers_count":42,"description":"desc","forks_count":7,"language":"Go","license":{"spdx_id":"Apache-2.0"},"pushed_at":"2026-01-15T10:00:00Z"}]}'
    monkeypatch.setattr(scout._http, "_get", fake_get)
    result = scout._fetch_github({"scout": {}})
    assert result[0]["forks"] == 7
    assert result[0]["language"] == "Go"
    assert result[0]["license"] == "Apache-2.0"
    assert result[0]["pushed_at"] == "2026-01-15"


def test_fetch_github_stats_null_license(monkeypatch):
    def fake_get(url, headers=None, timeout=30):
        return '{"items":[{"full_name":"a/b","html_url":"http://h","stargazers_count":1,"description":"","forks_count":0,"language":"Python","license":null,"pushed_at":"2026-01-01T00:00:00Z"}]}'
    monkeypatch.setattr(scout._http, "_get", fake_get)
    result = scout._fetch_github({"scout": {}})
    assert result[0]["license"] == ""


def test_corpus_github_stats_line():
    item = {"source": "github", "title": "owner/repo", "url": "u", "score": 100, "snippet": "A useful tool", "forks": 20, "language": "Rust", "license": "MIT", "pushed_at": "2026-06-01"}
    corpus = scout._corpus([item])
    assert "⭐" in corpus
    assert "🍴" in corpus
    lines = corpus.splitlines()
    assert len(lines) >= 2
    second_line = lines[1]
    assert second_line.startswith("  ")
    assert "100 stars" in second_line
    assert "20 forks" in second_line


def test_corpus_github_omits_empty_language():
    item = {"source": "github", "title": "owner/repo", "url": "u", "score": 5, "snippet": "desc", "forks": 3, "language": "", "license": "", "pushed_at": "2026-06-01"}
    corpus = scout._corpus([item])
    assert " · · " not in corpus


def test_corpus_github_cap_atomicity():
    # Atomicity: first line alone fits; combined two-liner does not; whole item must be skipped.
    item = {"source": "github", "title": "owner/repo", "url": "u", "score": 5, "snippet": "desc", "forks": 3, "language": "Python", "license": "MIT", "pushed_at": "2026-06-01"}
    first_line = "[github] owner/repo — desc\n"
    original_cap = scout._CORPUS_CHAR_CAP
    scout._CORPUS_CHAR_CAP = len(first_line)  # fits first line, not the two-line block
    try:
        corpus = scout._corpus([item])
    finally:
        scout._CORPUS_CHAR_CAP = original_cap
    assert corpus == ""  # entire two-line block rejected, not just second line



def test_run_stage1_uses_numbered_corpus(monkeypatch, tmp_path):
    numbered_calls = []
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: set())
    monkeypatch.setattr(scout, "fetch", lambda cfg: [{"source": "hn", "title": "HN item", "url": "http://h", "score": 5, "snippet": "s"}])
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    class FakeConfig:
        data = {"scout": {}}
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    class FakeSession:
        id = "s1"
        state = {"shortlist_indices": ""}
    class FakeService:
        async def create_session(self, **kw): return FakeSession()
        async def get_session(self, **kw): return FakeSession()
    class FakeRunner:
        session_service = FakeService()
        def run(self, **kw):
            numbered_calls.append(kw.get("new_message"))
            return iter([])
    monkeypatch.setattr(scout, "InMemoryRunner", lambda *a, **kw: FakeRunner())
    scout.run("bootstrap")
    assert len(numbered_calls) == 1
    assert "1." in numbered_calls[0].parts[0].text
    assert "[hn]" in numbered_calls[0].parts[0].text


def test_broad_instruction_has_grounding_rule():
    assert "Only classify items explicitly present in the corpus" in scout._BROAD_INSTRUCTION


def test_broad_instruction_has_tier_format():
    assert "## Tier 1 — Actionable" in scout._BROAD_INSTRUCTION
    assert "## Tier 2 — Good to Know" in scout._BROAD_INSTRUCTION


def test_integrate_instruction_has_project_variable():
    assert "{project}" in scout._INTEGRATE_INSTRUCTION


def test_integrate_instruction_has_step1():
    assert "Step 1" in scout._INTEGRATE_INSTRUCTION
    assert "scout_recall" in scout._INTEGRATE_INSTRUCTION


def test_integrate_instruction_handles_none_tier():
    assert "only '(none)'" in scout._INTEGRATE_INSTRUCTION


def test_scout_deposits_tier1_to_queue(monkeypatch, tmp_path):
    """scout.run() must deposit Tier 1 items to librarian queue, skip Tier 2."""
    from unittest.mock import patch

    tier1_output = (
        "## Tier 1 — Actionable\n\n"
        "### [hn] First item\n"
        "**Tech:** foo\n\n"
        "### [hn] Second item\n"
        "**Tech:** bar\n\n"
        "## Tier 2 — Good to Know\n"
        "- Should not deposit\n"
    )
    item = {"source": "hn", "title": "T", "url": "http://x", "score": 1, "snippet": "s"}

    class FakeConfig:
        data = {"scout": {"cloud_provider": "openrouter-free"}}
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()

    # Two sequential runners: stage1 → shortlist_indices, stage3 → report
    class FakeSess1:
        id = "s1"
        state = {"shortlist_indices": "1. reason"}
    class FakeSess3:
        id = "s3"
        state = {"report": tier1_output}
    class FakeSvc1:
        async def create_session(self, **kw): return FakeSess1()
        async def get_session(self, **kw): return FakeSess1()
    class FakeSvc3:
        async def create_session(self, **kw): return FakeSess3()
        async def get_session(self, **kw): return FakeSess3()
    class FakeRun1:
        session_service = FakeSvc1()
        def run(self, **kw): return iter([])
    class FakeRun3:
        session_service = FakeSvc3()
        def run(self, **kw): return iter([])

    call_idx = [0]
    runners = [FakeRun1(), FakeRun3()]
    def make_runner(*a, **kw):
        r = runners[call_idx[0]]
        call_idx[0] += 1
        return r

    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: {"old_key"})  # non-empty so mode="run" allowed
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "build_integrate_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "InMemoryRunner", make_runner)
    monkeypatch.setattr(scout, "_fetch_full", lambda it: "")
    monkeypatch.setattr(scout, "_write_report", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_update_cache", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_resolve_context", lambda *a: ("personal", "kage", "default"))

    with patch("kage.scout.deposit_to_queue") as mock_deposit:
        scout.run("run")

    assert mock_deposit.call_count == 2
    calls = [c.args[0] for c in mock_deposit.call_args_list]
    assert calls[0].startswith("### [hn] First item")
    assert calls[1].startswith("### [hn] Second item")
    assert all("Should not deposit" not in c for c in calls)


def test_scout_pii_seam_strips_email():
    """_pii_seam must redact PII in llm_request contents before cloud dispatch."""
    class FakePart:
        def __init__(self, text):
            self.text = text
    class FakeContent:
        def __init__(self, text):
            self.parts = [FakePart(text)]
    class FakeRequest:
        def __init__(self, text):
            self.contents = [FakeContent(text)]

    req = FakeRequest("contact admin@example.com for help")
    scout._pii_seam(None, req)
    assert "admin@example.com" not in req.contents[0].parts[0].text
    assert "[EMAIL_1]" in req.contents[0].parts[0].text


def test_scout_run_writes_scout_runs(monkeypatch, tmp_path):
    """scout.run() must create and insert a row in scout_runs after each run."""
    import sqlite3
    from kage.store import Store

    db_path = tmp_path / "kage.db"
    _store = Store(db_path)
    _store.init_schema()

    class FakeConfig:
        data = {"scout": {"cloud_provider": "openrouter-free"}}
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = _store

    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: set())
    monkeypatch.setattr(scout, "fetch", lambda cfg: [
        {"source": "hn", "title": "T", "url": "http://x", "score": 1, "snippet": "s"}
    ])
    monkeypatch.setattr(scout, "_write_report", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_update_cache", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    class FakeSession:
        id = "s1"
        state = {"shortlist_indices": ""}
    class FakeService:
        async def create_session(self, **kw): return FakeSession()
        async def get_session(self, **kw): return FakeSession()
    class FakeRunner:
        session_service = FakeService()
        def run(self, **kw): return iter([])
    monkeypatch.setattr(scout, "InMemoryRunner", lambda *a, **kw: FakeRunner())

    scout.run("bootstrap")

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT notes_fetched, mode FROM scout_runs").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == 1
    assert rows[0][1] == "bootstrap"


def test_parse_shortlist_indices_valid():
    text = "3. reason\n7. reason"
    items = [{"source": "hn", "title": f"Item {i}"} for i in range(10)]
    result = scout._parse_shortlist_indices(text, items)
    assert result == [items[2], items[6]]

def test_parse_shortlist_indices_out_of_bounds():
    text = "99. reason"
    items = [{"source": "hn", "title": f"Item {i}"} for i in range(10)]
    result = scout._parse_shortlist_indices(text, items)
    assert result == []

def test_parse_shortlist_indices_empty_on_malformed():
    text = "no leading digits\nsome text"
    items = [{"source": "hn", "title": f"Item {i}"} for i in range(10)]
    result = scout._parse_shortlist_indices(text, items)
    assert result == []

def test_parse_shortlist_indices_deduplicates():
    text = "2. first\n2. duplicate"
    items = [{"source": "hn", "title": f"Item {i}"} for i in range(10)]
    result = scout._parse_shortlist_indices(text, items)
    assert result == [items[1]]

def test_parse_shortlist_indices_max_8():
    text = "1.\n2.\n3.\n4.\n5.\n6.\n7.\n8.\n9.\n10."
    items = [{"source": "hn", "title": f"Item {i}"} for i in range(10)]
    result = scout._parse_shortlist_indices(text, items)
    assert result == items[:8]


def test_fetch_full_github_decodes_readme(monkeypatch):
    import json, base64
    item = {"title": "owner/repo", "source": "github", "url": ""}
    monkeypatch.setattr(scout._http, "_get", lambda *a, **kw: json.dumps({"content": base64.b64encode(b"hello").decode()}))
    assert scout._fetch_full(item) == "hello"


def test_fetch_full_reddit_uses_body_field(monkeypatch):
    item = {"source": "reddit", "body": "body text", "url": ""}
    calls = []
    monkeypatch.setattr(scout._http, "_get", lambda *a, **kw: calls.append(1) or "")
    assert scout._fetch_full(item) == "body text"
    assert calls == []


def test_fetch_full_youtube_returns_empty():
    assert scout._fetch_full({"source": "youtube", "url": "http://y"}) == ""


def test_fetch_full_arxiv_capped_at_2000(monkeypatch):
    item = {"source": "arxiv", "url": "http://arxiv.org/abs/1234"}
    monkeypatch.setattr(scout._http, "_get", lambda *a, **kw: "x" * 5000)
    assert len(scout._fetch_full(item)) == 2000


def test_fetch_full_jina_reader_other(monkeypatch):
    item = {"source": "rss", "url": "http://article"}
    monkeypatch.setattr(scout._http, "_get", lambda *a, **kw: "article text")
    assert scout._fetch_full(item) == "article text"


def test_fetch_full_fails_gracefully(monkeypatch):
    item = {"source": "github", "title": "owner/repo", "url": ""}
    monkeypatch.setattr(scout._http, "_get", lambda *a, **kw: (_ for _ in ()).throw(Exception("network error")))
    assert scout._fetch_full(item) == ""


def _make_item(n):
    return {"source": "hn", "title": f"Item {n}", "url": f"http://{n}", "score": 0, "snippet": f"snip{n}"}


def test_corpus_enriched_two_sections():
    items = [_make_item(1), _make_item(2)]
    shortlisted = [items[0]]
    full_map = {id(items[0]): "Full content for item 1"}
    result = scout._corpus_enriched(items, shortlisted, full_map)
    assert "=== FULL CONTENT ===" in result
    assert "=== HEADLINES ===" in result


def test_corpus_enriched_cap():
    items = [_make_item(1)]
    shortlisted = [items[0]]
    full_map = {id(items[0]): "a" * (scout._ENRICHED_CORPUS_CAP + 100)}
    result = scout._corpus_enriched(items, shortlisted, full_map)
    assert len(result) <= scout._ENRICHED_CORPUS_CAP


def test_corpus_enriched_shortlisted_not_in_headlines():
    items = [_make_item(1), _make_item(2)]
    shortlisted = [items[0]]
    full_map = {id(items[0]): "Full content"}
    result = scout._corpus_enriched(items, shortlisted, full_map)
    headlines_section = result.split("=== HEADLINES ===")[1]
    assert items[0]["title"] not in headlines_section


def test_corpus_enriched_empty_shortlist():
    items = [_make_item(1), _make_item(2)]
    result = scout._corpus_enriched(items, [], {})
    assert result.startswith("=== FULL CONTENT ===")
    headlines_section = result.split("=== HEADLINES ===")[1]
    assert items[0]["title"] in headlines_section
    assert items[1]["title"] in headlines_section


def test_build_broad_pipeline_has_scoutbroad():
    cfg = {"local_model": "qwen3:14b", "scout": {}}
    pipeline = scout.build_broad_pipeline(cfg)
    node_names = {n.name for n in pipeline.graph.nodes}
    assert "ScoutBroad" in node_names


def test_build_integrate_pipeline_has_scoutintegrate(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = {
        "scout": {"cloud_provider": "openrouter-free"},
        "providers": {
            "openrouter-free": {
                "type": "openai-compat",
                "api_key_env": "OPENROUTER_API_KEY",
                "base_url": "https://openrouter.ai/api/v1",
                "chat_path": "/chat/completions",
                "model": "openrouter/free",
            }
        }
    }
    pipeline = scout.build_integrate_pipeline(cfg)
    node_names = {n.name for n in pipeline.graph.nodes}
    assert "ScoutIntegrate" in node_names


def test_run_two_stage_pipeline(monkeypatch, tmp_path):
    """run('run') calls broad → fetch_full → integrate → returns report."""
    report_text = "## Tier 1\n- Good item\n## Tier 2\n- Meh item"
    item = {"source": "hn", "title": "Good item", "url": "http://x", "score": 1, "snippet": "s"}

    class FakeSess1:
        id = "s1"
        state = {"shortlist_indices": "1. because it is good"}
    class FakeSess3:
        id = "s3"
        state = {"report": report_text}
    class FakeSvc1:
        async def create_session(self, **kw): return FakeSess1()
        async def get_session(self, **kw): return FakeSess1()
    class FakeSvc3:
        async def create_session(self, **kw): return FakeSess3()
        async def get_session(self, **kw): return FakeSess3()
    class FakeRun1:
        session_service = FakeSvc1()
        def run(self, **kw): return iter([])
    class FakeRun3:
        session_service = FakeSvc3()
        def run(self, **kw): return iter([])

    call_idx = [0]
    instances = [FakeRun1(), FakeRun3()]
    def make_runner(*a, **kw):
        r = instances[call_idx[0]]
        call_idx[0] += 1
        return r

    class FakeConfig:
        data = {"scout": {"cloud_provider": "openrouter-free"}}
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()

    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: {"old"})
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "build_integrate_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "InMemoryRunner", make_runner)
    monkeypatch.setattr(scout, "_fetch_full", lambda it: "full content")
    monkeypatch.setattr(scout, "_write_report", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_update_cache", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_resolve_context", lambda *a: ("personal", "kage", None))

    result = scout.run("run")
    assert result == report_text


def test_run_neutralizes_and_triages_fetched_blocks(monkeypatch, tmp_path):
    """Each fetched block must be neutralized (wrapped) before it enters the
    corpus -- proves wrapping runs per-block, not after assembly, where
    truncation could sever a shared wrap's closing delimiter. Also proves
    guard._scout_triage runs on the raw fetched content (before wrapping)."""
    report_text = "## Tier 1\n- Good item"
    item = {"source": "hn", "title": "Good item", "url": "http://x", "score": 1, "snippet": "s"}

    class FakeSess1:
        id = "s1"
        state = {"shortlist_indices": "1. because it is good"}
    class FakeSess3:
        id = "s3"
        state = {"report": report_text}
    class FakeSvc1:
        async def create_session(self, **kw): return FakeSess1()
        async def get_session(self, **kw): return FakeSess1()
    class FakeSvc3:
        async def create_session(self, **kw): return FakeSess3()
        async def get_session(self, **kw): return FakeSess3()
    class FakeRun1:
        session_service = FakeSvc1()
        def run(self, **kw): return iter([])
    class FakeRun3:
        session_service = FakeSvc3()
        def run(self, **kw): return iter([])

    call_idx = [0]
    instances = [FakeRun1(), FakeRun3()]
    def make_runner(*a, **kw):
        r = instances[call_idx[0]]
        call_idx[0] += 1
        return r

    class FakeConfig:
        data = {"scout": {"cloud_provider": "openrouter-free"}}
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()

    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: {"old"})
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "build_integrate_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "InMemoryRunner", make_runner)
    monkeypatch.setattr(scout, "_fetch_full", lambda it: "some article content")
    monkeypatch.setattr(scout, "_write_report", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_update_cache", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_resolve_context", lambda *a: ("personal", "kage", None))

    triage_calls = []
    monkeypatch.setattr(scout.guard, "_scout_triage", lambda text, cfg: triage_calls.append(text) or False)

    captured_corpus = []
    orig_corpus_enriched = scout._corpus_enriched
    def spy_corpus_enriched(*a, **kw):
        result = orig_corpus_enriched(*a, **kw)
        captured_corpus.append(result)
        return result
    monkeypatch.setattr(scout, "_corpus_enriched", spy_corpus_enriched)

    scout.run("run")
    assert triage_calls == ["some article content"]
    assert "UNTRUSTED-" in captured_corpus[0]


def test_run_writes_injection_audit_when_flagged(monkeypatch, tmp_path):
    report_text = "## Tier 1\n- Good item"
    item = {"source": "hn", "title": "Good item", "url": "http://x", "score": 1, "snippet": "s"}

    class FakeSess1:
        id = "s1"
        state = {"shortlist_indices": "1. because it is good"}
    class FakeSess3:
        id = "s3"
        state = {"report": report_text}
    class FakeSvc1:
        async def create_session(self, **kw): return FakeSess1()
        async def get_session(self, **kw): return FakeSess1()
    class FakeSvc3:
        async def create_session(self, **kw): return FakeSess3()
        async def get_session(self, **kw): return FakeSess3()
    class FakeRun1:
        session_service = FakeSvc1()
        def run(self, **kw): return iter([])
    class FakeRun3:
        session_service = FakeSvc3()
        def run(self, **kw): return iter([])

    call_idx = [0]
    instances = [FakeRun1(), FakeRun3()]
    def make_runner(*a, **kw):
        r = instances[call_idx[0]]
        call_idx[0] += 1
        return r

    class FakeConfig:
        data = {"scout": {"cloud_provider": "openrouter-free"}}
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()

    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: {"old"})
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "build_integrate_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "InMemoryRunner", make_runner)
    monkeypatch.setattr(scout, "_fetch_full", lambda it: "some article content")
    monkeypatch.setattr(scout, "_write_report", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_update_cache", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_resolve_context", lambda *a: ("personal", "kage", None))
    monkeypatch.setattr(scout.guard, "_scout_triage", lambda *a, **kw: True)

    audit_calls = []
    monkeypatch.setattr(scout._privacy, "_write_audit", lambda record: audit_calls.append(record))

    scout.run("run")
    flagged = [r for r in audit_calls if r.get("type") == "inbound_injection_flagged"]
    assert len(flagged) == 1
    assert flagged[0]["source"] == "scout"


def test_dry_run_stops_after_stage1(monkeypatch, tmp_path):
    """run('dry-run') returns shortlist_text without calling build_integrate_pipeline."""
    integrate_calls = []
    item = {"source": "hn", "title": "T", "url": "http://x", "score": 1, "snippet": "s"}

    class FakeSess:
        id = "s1"
        state = {"shortlist_indices": "1. good"}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw): return iter([])

    class FakeConfig:
        data = {"scout": {"cloud_provider": "openrouter-free"}}
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()

    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: set())
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "build_integrate_pipeline", lambda *a: integrate_calls.append(1) or None)
    monkeypatch.setattr(scout, "InMemoryRunner", lambda *a, **kw: FakeRun())
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)

    result = scout.run("dry-run")
    assert result == "1. good"
    assert integrate_calls == []


def test_bootstrap_stops_after_stage1(monkeypatch, tmp_path):
    """run('bootstrap') returns shortlist_text without calling build_integrate_pipeline."""
    integrate_calls = []
    item = {"source": "hn", "title": "T", "url": "http://x", "score": 1, "snippet": "s"}

    class FakeSess:
        id = "s1"
        state = {"shortlist_indices": "2. reason"}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw): return iter([])

    class FakeConfig:
        data = {"scout": {"cloud_provider": "openrouter-free"}}
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()

    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: set())
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "build_integrate_pipeline", lambda *a: integrate_calls.append(1) or None)
    monkeypatch.setattr(scout, "InMemoryRunner", lambda *a, **kw: FakeRun())
    monkeypatch.setattr(scout, "_update_cache", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)

    result = scout.run("bootstrap")
    assert result == "2. reason"
    assert integrate_calls == []


def test_run_shell_llm_calls_subprocess_not_adk(monkeypatch, tmp_path):
    """When cloud_provider is shell-llm, Stage 3 uses subprocess.run, not a second InMemoryRunner."""
    import subprocess
    subprocess_calls = []
    runner_app_names = []
    item = {"source": "hn", "title": "T", "url": "http://x", "score": 1, "snippet": "s"}

    class FakeSess:
        id = "s1"
        state = {"shortlist_indices": "1. T"}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw): return iter([])

    class FakeConfig:
        data = {
            "scout": {"cloud_provider": "claude-sonnet"},
            "providers": {"claude-sonnet": {"type": "shell-llm", "command": "claude", "model": "claude-sonnet-4-6"}},
        }
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()

    fake_proc = MagicMock()
    fake_proc.stdout = "## Scout Report\n- item1"
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess_calls.append(a) or fake_proc)
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: {"seen"})
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "InMemoryRunner", lambda app_name=None, **kw: runner_app_names.append(app_name) or FakeRun())
    monkeypatch.setattr(scout, "_parse_shortlist_indices", lambda *a: [item])
    monkeypatch.setattr(scout, "_fetch_full", lambda it: "full body")
    monkeypatch.setattr(scout, "_corpus_enriched", lambda *a: "enriched corpus")
    monkeypatch.setattr(scout, "_resolve_context", lambda *a: (None, "kage", None))
    monkeypatch.setattr(scout, "_write_report", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_update_cache", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "deposit_to_queue", lambda *a, **kw: None)

    scout.run("run")
    assert len(subprocess_calls) == 1
    assert subprocess_calls[0][0][0] == "claude"
    assert subprocess_calls[0][0][1] == "-p"
    # shell-llm path: only ScoutBroad runner created, not ScoutIntegrate
    assert "kage-scout-int" not in runner_app_names


def test_run_shell_llm_formats_today_and_project(monkeypatch, tmp_path):
    """shell-llm path substitutes {today} and {project} into the instruction."""
    import subprocess, datetime
    captured_prompt = []
    item = {"source": "hn", "title": "T", "url": "http://x", "score": 1, "snippet": "s"}

    class FakeSess:
        id = "s1"
        state = {"shortlist_indices": "1. T"}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw): return iter([])

    class FakeConfig:
        data = {
            "scout": {"cloud_provider": "claude-sonnet"},
            "providers": {"claude-sonnet": {"type": "shell-llm", "command": "claude", "model": "claude-sonnet-4-6"}},
        }
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()

    fake_proc = MagicMock()
    fake_proc.stdout = "report"
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: captured_prompt.append(a[0][2]) or fake_proc)
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: {"seen"})
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "InMemoryRunner", lambda *a, **kw: FakeRun())
    monkeypatch.setattr(scout, "_parse_shortlist_indices", lambda *a: [item])
    monkeypatch.setattr(scout, "_fetch_full", lambda it: "full body")
    monkeypatch.setattr(scout, "_corpus_enriched", lambda *a: "enriched corpus")
    monkeypatch.setattr(scout, "_resolve_context", lambda *a: (None, "myproject", None))
    monkeypatch.setattr(scout, "_write_report", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_update_cache", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "deposit_to_queue", lambda *a, **kw: None)

    scout.run("run")
    assert len(captured_prompt) == 1
    prompt = captured_prompt[0]
    assert str(datetime.date.today()) in prompt
    assert "myproject" in prompt
    assert "{today}" not in prompt
    assert "{project}" not in prompt


def test_deposit_loop_two_tier1_cards(monkeypatch, tmp_path):
    import subprocess
    item = {"source": "hn", "title": "T", "url": "http://x", "score": 1, "snippet": "s"}

    class FakeSess:
        id = "s1"
        state = {"shortlist_indices": "1. T"}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw): return iter([])
    class FakeConfig:
        data = {
            "scout": {"cloud_provider": "claude-sonnet"},
            "providers": {"claude-sonnet": {"type": "shell-llm", "command": "claude", "model": "claude-sonnet-4-6"}},
        }
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()

    fake_proc = MagicMock()
    fake_proc.stdout = "## Tier 1 — Actionable\n\n### [hn] Alpha\n**Tech:** foo\n\n### [hn] Beta\n**Tech:** bar\n\n## Tier 2\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_proc)
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: {"seen"})
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "InMemoryRunner", lambda app_name=None, **kw: FakeRun())
    monkeypatch.setattr(scout, "_parse_shortlist_indices", lambda *a: [item])
    monkeypatch.setattr(scout, "_fetch_full", lambda it: "full body")
    monkeypatch.setattr(scout, "_corpus_enriched", lambda *a: "enriched corpus")
    monkeypatch.setattr(scout, "_resolve_context", lambda *a: (None, "kage", None))
    monkeypatch.setattr(scout, "_write_report", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_update_cache", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    deposited = []
    monkeypatch.setattr(scout, "deposit_to_queue", lambda content, source, project=None: deposited.append(content))

    scout.run("run")
    assert len(deposited) == 2
    assert deposited[0].startswith("### [hn] Alpha")
    assert deposited[1].startswith("### [hn] Beta")


def test_deposit_loop_tier2_not_deposited(monkeypatch, tmp_path):
    import subprocess
    item = {"source": "hn", "title": "T", "url": "http://x", "score": 1, "snippet": "s"}

    class FakeSess:
        id = "s1"
        state = {"shortlist_indices": "1. T"}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw): return iter([])
    class FakeConfig:
        data = {
            "scout": {"cloud_provider": "claude-sonnet"},
            "providers": {"claude-sonnet": {"type": "shell-llm", "command": "claude", "model": "claude-sonnet-4-6"}},
        }
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()

    fake_proc = MagicMock()
    fake_proc.stdout = "## Tier 1 — Actionable\n\n### [hn] Alpha\n**Tech:** foo\n\n## Tier 2 — Good to Know\n\n### [hn] Beta\n**Tech:** bar\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_proc)
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: {"seen"})
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "InMemoryRunner", lambda app_name=None, **kw: FakeRun())
    monkeypatch.setattr(scout, "_parse_shortlist_indices", lambda *a: [item])
    monkeypatch.setattr(scout, "_fetch_full", lambda it: "full body")
    monkeypatch.setattr(scout, "_corpus_enriched", lambda *a: "enriched corpus")
    monkeypatch.setattr(scout, "_resolve_context", lambda *a: (None, "kage", None))
    monkeypatch.setattr(scout, "_write_report", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_update_cache", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    deposited = []
    monkeypatch.setattr(scout, "deposit_to_queue", lambda content, source, project=None: deposited.append(content))

    scout.run("run")
    assert len(deposited) == 1
    assert deposited[0].startswith("### [hn] Alpha")


def test_deposit_loop_none_tier1(monkeypatch, tmp_path):
    import subprocess
    item = {"source": "hn", "title": "T", "url": "http://x", "score": 1, "snippet": "s"}

    class FakeSess:
        id = "s1"
        state = {"shortlist_indices": "1. T"}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw): return iter([])
    class FakeConfig:
        data = {
            "scout": {"cloud_provider": "claude-sonnet"},
            "providers": {"claude-sonnet": {"type": "shell-llm", "command": "claude", "model": "claude-sonnet-4-6"}},
        }
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()

    fake_proc = MagicMock()
    fake_proc.stdout = "## Tier 1 — Actionable\n\n(none)\n\n## Tier 2\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_proc)
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: {"seen"})
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "InMemoryRunner", lambda app_name=None, **kw: FakeRun())
    monkeypatch.setattr(scout, "_parse_shortlist_indices", lambda *a: [item])
    monkeypatch.setattr(scout, "_fetch_full", lambda it: "full body")
    monkeypatch.setattr(scout, "_corpus_enriched", lambda *a: "enriched corpus")
    monkeypatch.setattr(scout, "_resolve_context", lambda *a: (None, "kage", None))
    monkeypatch.setattr(scout, "_write_report", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_update_cache", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    deposited = []
    monkeypatch.setattr(scout, "deposit_to_queue", lambda content, source, project=None: deposited.append(content))

    scout.run("run")
    assert len(deposited) == 0


def test_deposit_loop_trailing_card_no_boundary(monkeypatch, tmp_path):
    import subprocess
    item = {"source": "hn", "title": "T", "url": "http://x", "score": 1, "snippet": "s"}

    class FakeSess:
        id = "s1"
        state = {"shortlist_indices": "1. T"}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw): return iter([])
    class FakeConfig:
        data = {
            "scout": {"cloud_provider": "claude-sonnet"},
            "providers": {"claude-sonnet": {"type": "shell-llm", "command": "claude", "model": "claude-sonnet-4-6"}},
        }
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
        store = MagicMock()

    fake_proc = MagicMock()
    fake_proc.stdout = "## Tier 1 — Actionable\n\n### [hn] Alpha\n**Tech:** foo\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_proc)
    monkeypatch.setattr(scout, "runtime", FakeRuntime())
    monkeypatch.setattr(scout, "_load_seen_cache", lambda: {"seen"})
    monkeypatch.setattr(scout, "fetch", lambda cfg: [item])
    monkeypatch.setattr(scout, "build_broad_pipeline", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "InMemoryRunner", lambda app_name=None, **kw: FakeRun())
    monkeypatch.setattr(scout, "_parse_shortlist_indices", lambda *a: [item])
    monkeypatch.setattr(scout, "_fetch_full", lambda it: "full body")
    monkeypatch.setattr(scout, "_corpus_enriched", lambda *a: "enriched corpus")
    monkeypatch.setattr(scout, "_resolve_context", lambda *a: (None, "kage", None))
    monkeypatch.setattr(scout, "_write_report", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_update_cache", lambda *a, **kw: None)
    monkeypatch.setattr(scout, "_token_log", lambda *a, **kw: None)
    deposited = []
    monkeypatch.setattr(scout, "deposit_to_queue", lambda content, source, project=None: deposited.append(content))

    scout.run("run")
    assert len(deposited) == 1
    assert deposited[0].startswith("### [hn] Alpha")


def test_build_broad_pipeline_sets_num_ctx():
    from kage.scout import build_broad_pipeline
    cfg = {"local_model": "qwen3:14b"}
    workflow = build_broad_pipeline(cfg)
    agent = workflow.edges[0][1]
    assert agent.model._additional_args["num_ctx"] == 16384
