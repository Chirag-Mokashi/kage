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
    assert "SECRETBODY" not in str(results)


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
    sources = [line.split("[")[1].split("]")[0] for line in lines if line]
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
    sources = [line.split("[")[1].split("]")[0] for line in corpus.splitlines() if line]
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
    monkeypatch.setattr(scout, "_disclosure_gate", lambda rows, cfg, identity, project: ([fake_row], []))
    result = scout.scout_recall("test query")
    assert result == [{"snippet": "My snippet", "project": "kage"}]


def test_scout_recall_gates_local_only(monkeypatch):
    fake_row = ("n1", "kage", "2026-01-01", "/path", "secret", None, None, None)
    monkeypatch.setattr(scout, "_resolve_context", lambda a, b: ("personal", "kage", "fallback"))
    monkeypatch.setattr(scout, "_search", lambda q, p, limit, identity: [fake_row])
    monkeypatch.setattr(scout, "_disclosure_gate", lambda rows, cfg, identity, project: ([], [{"id": "n1", "reason": "local_only"}]))
    result = scout.scout_recall("query")
    assert result == []


def test_scout_recall_resolves_context(monkeypatch):
    captured = {}
    def fake_disclosure_gate(rows, cfg, identity, project):
        captured["identity"] = identity
        captured["project"] = project
        return ([], [])
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
    monkeypatch.setattr(scout, "_disclosure_gate", lambda rows, cfg, identity, project: ([], []))
    scout.scout_recall("anything")
    assert captured_search["identity"] == "neu"
    assert captured_search["project"] == "thesis"


def test_scout_recall_empty_query_returns_empty(monkeypatch):
    monkeypatch.setattr(scout, "_resolve_context", lambda a, b: ("personal", None, "fallback"))
    monkeypatch.setattr(scout, "_search", lambda q, p, limit, identity: [])
    monkeypatch.setattr(scout, "_disclosure_gate", lambda rows, cfg, identity, project: ([], []))
    assert scout.scout_recall("") == []


def test_build_pipeline_bootstrap_skips_cloud():
    pipeline = scout.build_pipeline({}, cloud=False)
    assert len(pipeline.sub_agents) == 1
    assert pipeline.sub_agents[0].name == "ScoutBroad"


def test_build_pipeline_cloud_has_two_stages(monkeypatch):
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
    pipeline = scout.build_pipeline(fake_cfg, cloud=True)
    assert len(pipeline.sub_agents) == 2
    assert pipeline.sub_agents[0].name == "ScoutBroad"
    assert pipeline.sub_agents[1].name == "ScoutIntegrate"


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
