"""Tests for kage.monitor (Cycle 16, v0.17.0) — no live LLM, no live MCP, no live Ollama."""
import json
import asyncio
from datetime import datetime, timezone, timedelta
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from kage import runtime, monitor
from kage.config import Config
from kage.store import Store
from kage.monitor import (
    _apply_migrations, _connect,
    write_alert, set_item_priority,
    read_pipeline_state, read_system_metrics,
    ping_kage_mcp, read_observe_log,
    _write_state_json, _generate_plist,
    _pii_seam, read_command_history, read_antigravity_ctx,
    read_session_log,
)
from kage.observe import _heartbeat_merge, _pii_strip, CaptureTrigger
from kage.arms import _INTERNAL_ARMS


@pytest.fixture
def mon_env(monkeypatch, tmp_path):
    """Isolated kage home — patches runtime.store and runtime.config to temp dir."""
    kage_home = tmp_path / ".kage"
    kage_home.mkdir()
    (kage_home / "indexes").mkdir()
    (kage_home / "memory").mkdir()
    db_path = kage_home / "indexes" / "kage.db"
    store = Store(db_path)
    store.init_schema()
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "config", Config(kage_home))
    conn = store.connect()
    _apply_migrations(conn)
    conn.commit()
    conn.close()
    return kage_home


def test_schema_migration_idempotent(mon_env):
    """_apply_migrations must be safe to call multiple times."""
    conn = _connect()
    for _ in range(3):
        _apply_migrations(conn)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='monitor_alerts'"
    )
    assert cursor.fetchone() is not None
    conn.close()


def test_write_alert_inserts_row(mon_env):
    """write_alert must insert a row with the given level and msg."""
    alert_id = write_alert("warn", "test message", "monitor")
    assert alert_id
    conn = _connect()
    row = conn.execute(
        "SELECT level, msg FROM monitor_alerts WHERE id=?", (alert_id,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "warn"
    assert row[1] == "test message"


def test_write_alert_resolved_default_false(mon_env):
    """Newly inserted alerts must have resolved=0."""
    alert_id = write_alert("info", "boot", "monitor")
    conn = _connect()
    row = conn.execute(
        "SELECT resolved FROM monitor_alerts WHERE id=?", (alert_id,)
    ).fetchone()
    conn.close()
    assert row[0] == 0


def test_write_alert_invalid_level_becomes_info(mon_env):
    """An unrecognised level must be coerced to 'info'."""
    alert_id = write_alert("critical", "bad level", "monitor")
    conn = _connect()
    row = conn.execute(
        "SELECT level FROM monitor_alerts WHERE id=?", (alert_id,)
    ).fetchone()
    conn.close()
    assert row[0] == "info"


def test_set_item_priority_updates_row(mon_env):
    """set_item_priority must update priority column in staging_queue."""
    conn = _connect()
    conn.execute(
        "INSERT INTO staging_queue (id, content, content_hash, source, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("sq-1", "test", "hash1", "scout", "pending", "2026-06-28T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()
    result = set_item_priority("sq-1", 5)
    assert result is True
    conn = _connect()
    row = conn.execute("SELECT priority FROM staging_queue WHERE id='sq-1'").fetchone()
    conn.close()
    assert row[0] == 5


def test_set_item_priority_unknown_id_returns_true(mon_env):
    """UPDATE with no matching row must return True (no crash)."""
    result = set_item_priority("nonexistent-id", 3)
    assert result is True


def test_read_pipeline_state_keys(mon_env):
    """read_pipeline_state must return all expected keys."""
    result = read_pipeline_state()
    for key in ("scout_last_run", "librarian_queue_depth", "memory_count",
                "memory_added_today", "librarian_oldest_pending_hours", "scout_items_today",
                "hours_since_scout_run"):
        assert key in result, f"missing key: {key}"


def test_read_pipeline_state_empty_db(mon_env):
    """Empty DB must produce safe zero values, not a crash."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM scout_runs")
    except Exception:
        pass  # table may not exist on fresh DB
    conn.execute("DELETE FROM staging_queue")
    conn.commit()
    conn.close()
    result = read_pipeline_state()
    assert result.get("scout_last_run") is None
    assert result.get("librarian_queue_depth") == 0
    assert result.get("memory_count") == 0
    assert result.get("hours_since_scout_run") is None


def test_read_session_log_empty(mon_env):
    """read_session_log must return [] when session_turns has no recent rows."""
    result = read_session_log(hours=1.0)
    assert result == []


def test_read_session_log_returns_turns(mon_env):
    """read_session_log must return session_turns rows with content gated."""
    conn = _connect()
    conn.execute(
        "INSERT INTO sessions (session_id, created_at, identity, project, destination) VALUES (?, ?, ?, ?, ?)",
        ("sess-1", "2026-06-28T10:00:00+00:00", "personal", "kage", "ollama"),
    )
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO session_turns (session_id, idx, role, content, note_ids, destination, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("sess-1", 0, "user", "hello world", "[]", "ollama", ts),
    )
    conn.commit()
    conn.close()
    result = read_session_log(hours=1.0)
    assert len(result) >= 1
    assert result[0]["content"] == "hello world"


def test_read_system_metrics_keys(mon_env):
    """read_system_metrics must include cpu_pct, ram_mb, disk_used_mb."""
    result = read_system_metrics()
    assert "cpu_pct" in result
    assert "ram_mb" in result
    assert "disk_used_mb" in result


def test_read_system_metrics_ollama_down(monkeypatch, mon_env):
    """When Ollama is unreachable, ollama_up must be False."""
    import urllib.request as _ureq
    monkeypatch.setattr(_ureq, "urlopen", MagicMock(side_effect=OSError))
    result = read_system_metrics()
    assert result["ollama_up"] is False
    assert result["ollama_latency_ms"] == -1


def test_check_mcp_health_timeout(mon_env):
    """An unreachable shell arm must produce a non-healthy status without crashing."""
    import json as _json
    from kage.monitor import check_mcp_health
    # Write arms config directly — Config.data reads from config.json in kage_home
    cfg_data = {"arms": {"fake": {"enabled": True, "transport": "shell", "command": "false"}}}
    (mon_env / "config.json").write_text(_json.dumps(cfg_data))
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=asyncio.TimeoutError)):
        result = asyncio.run(check_mcp_health())
    assert result["fake"]["status"] in ("timeout", "error", "degraded")


def test_call_internal_arm_unknown_name():
    """_call_internal_arm must raise ValueError for unknown arm names."""
    from kage.arms import _call_internal_arm
    with pytest.raises(ValueError):
        asyncio.run(_call_internal_arm("nonexistent-arm", "tool", "input"))


def test_internal_arm_registry_has_kage_mcp():
    """kage-mcp must be present in _INTERNAL_ARMS with expected tools."""
    assert "kage-mcp" in _INTERNAL_ARMS
    assert "kage_status" in _INTERNAL_ARMS["kage-mcp"]["tools"]
    assert _INTERNAL_ARMS["kage-mcp"]["command"][0] == "uv"


def test_ping_kage_mcp_returns_dict(monkeypatch, mon_env):
    """ping_kage_mcp must return a dict with 'status' even when mocked."""
    monkeypatch.setattr(
        "kage.monitor._call_internal_arm",
        AsyncMock(return_value={"output": "ok"}),
    )
    result = asyncio.run(ping_kage_mcp())
    assert "status" in result


def test_read_observe_log_empty(monkeypatch, mon_env):
    """read_observe_log must return [] when no events exist."""
    monkeypatch.setattr("kage.observe.read_observe_log", MagicMock(return_value=[]))
    result = read_observe_log(hours=1.0)
    assert result == []


def test_pii_strip_email():
    result = _pii_strip("reach me at user@example.com today")
    assert "user@example.com" not in result
    assert "[EMAIL_1]" in result


def test_pii_strip_api_key():
    result = _pii_strip("key=sk-abcdefghijklmnopqrstuvwxyz12345678")
    assert "sk-abcdefghijklmnopqrstuvwxyz12345678" not in result


def test_pii_clean_passthrough():
    result = _pii_strip("The Eiffel Tower is 330 metres tall.")
    assert result == "The Eiffel Tower is 330 metres tall."


def test_heartbeat_merge_extends_duration():
    last = {"app": "Xcode", "window": "main.swift", "ts": 1000.0, "duration": 5.0}
    new  = {"app": "Xcode", "window": "main.swift", "ts": 1010.0, "duration": 0.0}
    result = _heartbeat_merge(last, new, pulsetime=30.0)
    assert result is True
    assert last["duration"] == 10.0


def test_heartbeat_merge_max_guard():
    """A late heartbeat must not shrink an already-long event duration."""
    last = {"app": "Xcode", "window": "main.swift", "ts": 1000.0, "duration": 600.0}
    new  = {"app": "Xcode", "window": "main.swift", "ts": 1001.0, "duration": 0.0}
    _heartbeat_merge(last, new, pulsetime=30.0)
    assert last["duration"] >= 600.0


def test_heartbeat_no_merge_different_app():
    last = {"app": "Xcode", "window": "main.swift", "ts": 1000.0, "duration": 5.0}
    new  = {"app": "Terminal", "window": "bash", "ts": 1002.0, "duration": 0.0}
    result = _heartbeat_merge(last, new, pulsetime=30.0)
    assert result is False


def test_capture_trigger_enum():
    """CaptureTrigger must have exactly 6 values matching the spec."""
    assert len(list(CaptureTrigger)) == 6
    assert CaptureTrigger.APP_SWITCH.value    == "app_switch"
    assert CaptureTrigger.WINDOW_FOCUS.value  == "window_focus"
    assert CaptureTrigger.TYPING_PAUSE.value  == "typing_pause"
    assert CaptureTrigger.SCROLL_STOP.value   == "scroll_stop"
    assert CaptureTrigger.VISUAL_CHANGE.value == "visual_change"
    assert CaptureTrigger.IDLE.value          == "idle"


def test_state_json_written(mon_env, monkeypatch):
    """_write_state_json must create state.json at ~/.kage/monitor/state.json."""
    monkeypatch.setattr(runtime.config, "home", str(mon_env))
    _write_state_json({"key": "value", "ts": 1234})
    state_path = mon_env / "monitor" / "state.json"
    assert state_path.exists()
    data = json.loads(state_path.read_text())
    assert data["key"] == "value"


def test_generate_plist_contains_uv_path():
    plist = _generate_plist("/usr/local/bin/uv", "/home/user/kage", "/home/user")
    assert "/usr/local/bin/uv" in plist
    assert "dev.kage.monitor" in plist
    assert "/home/user/kage" in plist


def test_generate_plist_valid_xml():
    import xml.etree.ElementTree as ET
    plist = _generate_plist("/usr/bin/uv", "/tmp/kage", "/tmp")
    xml_body = plist.split("?>", 1)[1] if "?>" in plist else plist
    ET.fromstring(xml_body)  # must not raise


def test_pii_seam_strips_email():
    """_pii_seam must redact PII in llm_request.contents before cloud dispatch."""
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
    _pii_seam(None, req)
    assert "admin@example.com" not in req.contents[0].parts[0].text
    assert "[EMAIL_1]" in req.contents[0].parts[0].text


def test_read_command_history(mon_env, monkeypatch):
    """read_command_history must return only type==command entries."""
    audit_path = mon_env / "audit.jsonl"
    audit_path.write_text(
        '{"type": "command", "cmd": "recall", "ts": 1}\n'
        '{"type": "arm_call", "arm": "calendar", "ts": 2}\n'
        '{"type": "command", "cmd": "ask", "ts": 3}\n'
    )
    monkeypatch.setattr(runtime.config, "home", str(mon_env))
    result = read_command_history(n=10)
    assert len(result) == 2
    assert all(r["type"] == "command" for r in result)


def test_read_antigravity_ctx(mon_env, monkeypatch):
    """read_antigravity_ctx must return md content and filtered audit entries."""
    monkeypatch.setattr(runtime.config, "home", str(mon_env))
    # Function checks Path.cwd() / ".antigravity.md" first
    monkeypatch.chdir(mon_env.parent)
    (mon_env.parent / ".antigravity.md").write_text("# Antigravity context")
    audit_path = mon_env / "audit.jsonl"
    audit_path.write_text(
        '{"source": "antigravity", "ts": 1, "type": "call"}\n'
        '{"source": "kage", "ts": 2, "type": "command"}\n'
    )
    result = read_antigravity_ctx()
    assert result["workspace_md"] == "# Antigravity context"
    assert len(result["recent_mcp_calls"]) == 1
    assert result["recent_mcp_calls"][0]["source"] == "antigravity"


def test_monitor_digest_output_key_set(mon_env, monkeypatch):
    """build_monitor must set output_key='monitor_digest' on digest_agent."""
    from kage import monitor
    from kage.monitor import build_monitor
    monkeypatch.setattr(monitor, "_litellm_target", lambda p, c: ("ollama_chat/qwen3:14b", None, None))
    cfg = {"local_model": "qwen3:14b", "cloud_provider": "openrouter-free"}
    workflow = build_monitor(cfg)
    digest_agent = workflow.edges[1][1]
    assert digest_agent.output_key == "monitor_digest"


def test_check_mcp_health_stdio_ping(monkeypatch):
    """check_mcp_health must send a JSON-RPC initialize ping and return healthy."""
    import asyncio
    import json as _json
    from unittest.mock import MagicMock, AsyncMock
    import kage.monitor as _mon
    from kage import runtime

    # Config with one enabled stdio arm
    monkeypatch.setattr(runtime, "config", MagicMock())
    runtime.config.data = {
        "arms": {
            "test-mcp": {
                "enabled": True,
                "transport": "stdio",
                "mcp_command": "echo hello",
            }
        }
    }

    # Fake process whose stdout returns a valid JSON-RPC result
    response_line = (_json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n").encode()

    fake_stdout = MagicMock()
    fake_stdout.readline = AsyncMock(return_value=response_line)

    fake_stdin = MagicMock()
    fake_stdin.write = MagicMock()
    fake_stdin.drain = AsyncMock()

    fake_proc = MagicMock()
    fake_proc.stdin = fake_stdin
    fake_proc.stdout = fake_stdout
    fake_proc.kill = MagicMock()
    fake_proc.wait = AsyncMock()

    async def fake_subprocess_exec(*args, **kwargs):
        return fake_proc

    monkeypatch.setattr(_mon.asyncio, "create_subprocess_exec", fake_subprocess_exec)

    result = asyncio.run(_mon.check_mcp_health())

    assert "test-mcp" in result
    assert result["test-mcp"]["status"] == "healthy"


# ── Cycle 20: plist generators ────────────────────────────────────────────────

def test_generate_observe_plist_start_interval():
    result = monitor._generate_observe_plist("/usr/bin/uv", "/proj", "/home/user")
    assert "StartInterval" in result
    assert "<integer>300</integer>" in result
    assert "observe" in result
    assert "StartCalendarInterval" not in result


def test_generate_digest_plist_calendar_interval():
    result = monitor._generate_digest_plist("/usr/bin/uv", "/proj", "/home/user")
    assert "StartCalendarInterval" in result
    assert "<integer>7</integer>" in result
    assert "digest" in result
    assert "StartInterval" not in result


# ── Cycle 20: build functions ─────────────────────────────────────────────────

def test_build_monitor_observe_single_node():
    pipeline = monitor.build_monitor_observe({"local_model": "qwen3:14b"})
    node_names = {n.name for n in pipeline.graph.nodes}
    assert "MonitorObserve" in node_names
    assert "MonitorDigest" not in node_names


def test_build_monitor_digest_single_node(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = {
        "monitor": {"cloud_provider": "openrouter-free"},
        "providers": {
            "openrouter-free": {
                "type": "openai-compat",
                "api_key_env": "OPENROUTER_API_KEY",
                "base_url": "https://openrouter.ai/api/v1",
                "model": "openrouter/free",
            }
        },
    }
    pipeline = monitor.build_monitor_digest(cfg)
    node_names = {n.name for n in pipeline.graph.nodes}
    assert "MonitorDigest" in node_names
    assert "MonitorObserve" not in node_names


# ── Cycle 20: _observe_impl ───────────────────────────────────────────────────

def _make_fake_runner(findings="cpu normal"):
    import json as _json
    class FakeSess:
        id = "s1"
        state = {"monitor_findings": findings}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw): return iter([])
    return FakeRun


def test_observe_impl_writes_observations_jsonl(monkeypatch, tmp_path):
    import datetime as _dt, json as _json, google.adk.runners as _runners
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(monitor, "runtime", FakeRuntime())
    monkeypatch.setattr(monitor, "build_monitor_observe", lambda cfg: None)
    monkeypatch.setattr(_runners, "InMemoryRunner", lambda *a, **kw: _make_fake_runner()())
    monitor._observe_impl({})
    today = _dt.datetime.now().strftime("%Y-%m-%d")
    obs_path = tmp_path / "monitor" / f"observations-{today}.jsonl"
    assert obs_path.exists()
    record = _json.loads(obs_path.read_text().strip())
    assert "findings" in record


def test_observe_impl_updates_state_json(monkeypatch, tmp_path):
    import json as _json, google.adk.runners as _runners
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(monitor, "runtime", FakeRuntime())
    monkeypatch.setattr(monitor, "build_monitor_observe", lambda cfg: None)
    monkeypatch.setattr(_runners, "InMemoryRunner", lambda *a, **kw: _make_fake_runner()())
    monitor._observe_impl({})
    state = _json.loads((tmp_path / "monitor" / "state.json").read_text())
    assert "last_observe" in state


# ── Cycle 20: _digest_impl ────────────────────────────────────────────────────

def test_digest_impl_empty_observations(monkeypatch, tmp_path):
    import google.adk.runners as _runners
    captured = []
    class FakeSess:
        id = "s1"
        state = {"monitor_digest": ""}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw):
            captured.append(kw.get("new_message"))
            return iter([])
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(monitor, "runtime", FakeRuntime())
    monkeypatch.setattr(monitor, "build_monitor_digest", lambda cfg: None)
    monkeypatch.setattr(_runners, "InMemoryRunner", lambda *a, **kw: FakeRun())
    monitor._digest_impl({})
    assert len(captured) == 1
    assert captured[0].parts[0].text == "No observations recorded today."


def test_digest_impl_writes_md_file(monkeypatch, tmp_path):
    import datetime as _dt, json as _json, google.adk.runners as _runners
    today = _dt.datetime.now().strftime("%Y-%m-%d")
    monitor_dir = tmp_path / "monitor"
    monitor_dir.mkdir(parents=True, exist_ok=True)
    obs_path = monitor_dir / f"observations-{today}.jsonl"
    obs_path.write_text(_json.dumps({"ts": "2026-06-29T07:00:00+00:00", "findings": "all ok"}) + "\n")
    class FakeSess:
        id = "s1"
        state = {"monitor_digest": "## Daily digest"}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw): return iter([])
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(monitor, "runtime", FakeRuntime())
    monkeypatch.setattr(monitor, "build_monitor_digest", lambda cfg: None)
    monkeypatch.setattr(_runners, "InMemoryRunner", lambda *a, **kw: FakeRun())
    monkeypatch.setattr(monitor, "_deposit_context_snapshot", lambda s: None)
    monkeypatch.setattr(monitor, "_maybe_trigger_learn", lambda p: None)
    monitor._digest_impl({})
    md_path = monitor_dir / f"{today}.md"
    assert md_path.exists()
    assert "## Daily digest" in md_path.read_text()


def test_digest_impl_no_deposit_on_empty_digest(monkeypatch, tmp_path):
    import google.adk.runners as _runners
    calls = []
    class FakeSess:
        id = "s1"
        state = {"monitor_digest": ""}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw): return iter([])
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(monitor, "runtime", FakeRuntime())
    monkeypatch.setattr(monitor, "build_monitor_digest", lambda cfg: None)
    monkeypatch.setattr(_runners, "InMemoryRunner", lambda *a, **kw: FakeRun())
    monkeypatch.setattr(monitor, "_deposit_context_snapshot", lambda s: calls.append(s))
    monkeypatch.setattr(monitor, "_maybe_trigger_learn", lambda p: None)
    monitor._digest_impl({})
    assert calls == []


def test_digest_impl_reads_observations(monkeypatch, tmp_path):
    import datetime as _dt, json as _json, google.adk.runners as _runners
    today = _dt.datetime.now().strftime("%Y-%m-%d")
    monitor_dir = tmp_path / "monitor"
    monitor_dir.mkdir(parents=True, exist_ok=True)
    (monitor_dir / f"observations-{today}.jsonl").write_text(
        _json.dumps({"ts": "2026-06-29T07:00:00+00:00", "findings": "CPU_SPIKE_SIGNAL"}) + "\n"
    )
    captured = []
    class FakeSess:
        id = "s1"
        state = {"monitor_digest": ""}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw):
            captured.append(kw.get("new_message"))
            return iter([])
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(monitor, "runtime", FakeRuntime())
    monkeypatch.setattr(monitor, "build_monitor_digest", lambda cfg: None)
    monkeypatch.setattr(_runners, "InMemoryRunner", lambda *a, **kw: FakeRun())
    monitor._digest_impl({})
    assert len(captured) == 1
    assert "CPU_SPIKE_SIGNAL" in captured[0].parts[0].text


def test_digest_impl_caps_at_50k(monkeypatch, tmp_path):
    import datetime as _dt, json as _json, google.adk.runners as _runners
    today = _dt.datetime.now().strftime("%Y-%m-%d")
    monitor_dir = tmp_path / "monitor"
    monitor_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(
        _json.dumps({"ts": "2026-06-29T07:00:00+00:00", "findings": "x" * 200})
        for _ in range(300)
    ) + "\n"
    (monitor_dir / f"observations-{today}.jsonl").write_text(lines)
    captured = []
    class FakeSess:
        id = "s1"
        state = {"monitor_digest": ""}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw):
            captured.append(kw.get("new_message"))
            return iter([])
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(monitor, "runtime", FakeRuntime())
    monkeypatch.setattr(monitor, "build_monitor_digest", lambda cfg: None)
    monkeypatch.setattr(_runners, "InMemoryRunner", lambda *a, **kw: FakeRun())
    monitor._digest_impl({})
    assert len(captured) == 1
    assert len(captured[0].parts[0].text) <= 51000
    assert captured[0].parts[0].text != "No observations recorded today."


# ── Cycle 20: CLI commands ────────────────────────────────────────────────────

def test_monitor_run_calls_both(monkeypatch):
    """monitor_run() must call both _observe_impl and _digest_impl."""
    from kage.cli import monitor_run
    import kage.monitor as _kmon
    observe_calls, digest_calls = [], []
    monkeypatch.setattr(_kmon, "_observe_impl", lambda cfg: observe_calls.append(cfg))
    monkeypatch.setattr(_kmon, "_digest_impl", lambda cfg: digest_calls.append(cfg))
    monkeypatch.setattr("kage.cli._config", lambda: {})
    monitor_run()
    assert len(observe_calls) == 1
    assert len(digest_calls) == 1


def test_monitor_install_creates_both_plists(monkeypatch, tmp_path):
    """monitor_install writes all three plist files and calls bootout+bootstrap for each label."""
    import shutil as _shutil, subprocess as _sp, pathlib, kage.monitor as _kmon
    from kage.cli import monitor_install
    from pathlib import Path

    sp_calls = []
    monkeypatch.setattr(_shutil, "which", lambda x: "/usr/local/bin/uv" if x == "uv" else None)
    monkeypatch.setattr(_sp, "run", lambda cmd, **kw: sp_calls.append(cmd))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("kage.arms._resolve_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr("kage.cli._config", lambda: {})

    monitor_install()

    # both plist files must exist
    for label in ["dev.kage.monitor.ax", "dev.kage.monitor.observe", "dev.kage.monitor.digest"]:
        plist_path = tmp_path / ".config" / "kage" / f"{label}.plist"
        assert plist_path.exists(), f"{label}.plist not created"

    # bootout + bootstrap called for each of the three plists
    bootstrap_calls = [c for c in sp_calls if "bootstrap" in c and "bootout" not in c]
    assert len(bootstrap_calls) == 3


# ── Cycle 22 — Monitor correction-count trigger ───────────────────────────────

def test_digest_triggers_learn_at_threshold(monkeypatch, tmp_path):
    """When delta >= 7, kage learn --all fires and learn_state updates."""
    import subprocess
    import kage.learn as learn_mod
    from kage.learn import _write_learn_state, _read_learn_state
    from kage.monitor import _maybe_trigger_learn

    _write_learn_state({"last_learn_correction_count": 74}, home=tmp_path)
    monkeypatch.setattr(learn_mod, "_count_total_corrections", lambda home=None: 81)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    _maybe_trigger_learn(tmp_path)

    assert calls == [["kage", "learn", "--all"]]
    assert _read_learn_state(home=tmp_path)["last_learn_correction_count"] == 81


def test_digest_no_trigger_below_threshold(monkeypatch, tmp_path):
    """When delta < 7, subprocess.run is NOT called."""
    import subprocess
    import kage.learn as learn_mod
    from kage.learn import _write_learn_state
    from kage.monitor import _maybe_trigger_learn

    _write_learn_state({"last_learn_correction_count": 78}, home=tmp_path)
    monkeypatch.setattr(learn_mod, "_count_total_corrections", lambda home=None: 81)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    _maybe_trigger_learn(tmp_path)

    assert calls == []


def test_digest_updates_learn_state_after_trigger(monkeypatch, tmp_path):
    """After trigger, last_learn_correction_count is set to exact total; other keys preserved."""
    import subprocess
    import kage.learn as learn_mod
    from kage.learn import _write_learn_state, _read_learn_state
    from kage.monitor import _maybe_trigger_learn

    _write_learn_state({"last_learn_correction_count": 70, "other_key": "preserved"}, home=tmp_path)
    monkeypatch.setattr(learn_mod, "_count_total_corrections", lambda home=None: 81)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: None)

    _maybe_trigger_learn(tmp_path)

    state = _read_learn_state(home=tmp_path)
    assert state["last_learn_correction_count"] == 81
    assert state["other_key"] == "preserved"


def test_maybe_trigger_learn_librarian_fires_at_threshold(monkeypatch, tmp_path):
    import subprocess
    import kage.learn as learn_mod
    from kage.learn import _write_learn_state, _read_learn_state
    from kage.monitor import _maybe_trigger_learn
    _write_learn_state({"last_learn_correction_count": 81, "last_librarian_learn_count": 0}, home=tmp_path)
    monkeypatch.setattr(learn_mod, "_count_total_corrections", lambda home=None: 81)
    monkeypatch.setattr(learn_mod, "_count_corrections", lambda name, home=None: 9)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    _maybe_trigger_learn(tmp_path)
    assert calls == [["kage", "learn", "--librarian"]]
    assert _read_learn_state(home=tmp_path)["last_librarian_learn_count"] == 9

def test_check_mcp_health_blocks_shell_interpreter(mon_env):
    """A shell arm with a shell interpreter as command must be blocked."""
    import json as _json
    from kage.monitor import check_mcp_health
    cfg_data = {"arms": {"fake": {"enabled": True, "transport": "shell", "command": "bash"}}}
    (mon_env / "config.json").write_text(_json.dumps(cfg_data))
    result = asyncio.run(check_mcp_health())
    assert result["fake"]["status"] == "blocked"
    assert result["fake"]["error"] == "interpreter"

def test_check_mcp_health_bad_command_syntax(mon_env):
    """A shell arm with bad command syntax must produce an error."""
    import json as _json
    from kage.monitor import check_mcp_health
    cfg_data = {"arms": {"fake": {"enabled": True, "transport": "shell", "command": "echo \"unterminated"}}}
    (mon_env / "config.json").write_text(_json.dumps(cfg_data))
    result = asyncio.run(check_mcp_health())
    assert result["fake"]["status"] == "error"
    assert result["fake"]["error"] == "bad command syntax"


# ── AX daemon plist (Cycle 28 monitor fix) ────────────────────────────────────

def test_generate_ax_plist_content():
    from kage.monitor import _generate_ax_plist
    content = _generate_ax_plist("uv", "/proj", "/home")
    assert "dev.kage.monitor.ax" in content
    assert "ax-daemon" in content
    assert "<key>KeepAlive</key><true/>" in content
    assert "StartInterval" not in content


def test_monitor_install_writes_ax_plist(tmp_path, monkeypatch):
    import shutil, subprocess as _sp
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(_sp, "run", lambda *a, **kw: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from typer.testing import CliRunner
    from kage.cli import app
    result = CliRunner().invoke(app, ["monitor", "install"])
    assert result.exit_code == 0
    assert (tmp_path / ".config" / "kage" / "dev.kage.monitor.ax.plist").exists()


def test_monitor_uninstall_removes_ax_plist(tmp_path, monkeypatch):
    import subprocess as _sp
    monkeypatch.setattr(_sp, "run", lambda *a, **kw: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    plist = tmp_path / ".config" / "kage" / "dev.kage.monitor.ax.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text("")
    from typer.testing import CliRunner
    from kage.cli import app
    result = CliRunner().invoke(app, ["monitor", "uninstall"])
    assert result.exit_code == 0
    assert not plist.exists()


def test_read_pipeline_state_hours_since_scout_run_recent(mon_env):
    """hours_since_scout_run must be a small float when scout ran recently."""
    conn = _connect()
    conn.execute("CREATE TABLE IF NOT EXISTS scout_runs (created_at TEXT, notes_fetched INTEGER, mode TEXT)")
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    conn.execute("INSERT INTO scout_runs (created_at, notes_fetched, mode) VALUES (?, ?, ?)", (recent, 5, "run"))
    conn.commit()
    conn.close()
    result = read_pipeline_state()
    val = result.get("hours_since_scout_run")
    assert val is not None
    assert 1.5 < val < 3.0


def test_read_pipeline_state_hours_since_scout_run_stale(mon_env):
    """hours_since_scout_run must be >= 49 when scout ran 50h ago."""
    conn = _connect()
    conn.execute("CREATE TABLE IF NOT EXISTS scout_runs (created_at TEXT, notes_fetched INTEGER, mode TEXT)")
    stale = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
    conn.execute("INSERT INTO scout_runs (created_at, notes_fetched, mode) VALUES (?, ?, ?)", (stale, 3, "run"))
    conn.commit()
    conn.close()
    result = read_pipeline_state()
    val = result.get("hours_since_scout_run")
    assert val is not None
    assert val >= 49.0


def test_monitor_observe_instruction_scout_reporting():
    """Instruction must report Scout last-run as a fact, not as a threshold alert."""
    from kage.monitor import _MONITOR_OBSERVE_INSTRUCTION
    assert "hours_since_scout_run" in _MONITOR_OBSERVE_INSTRUCTION
    assert "Do NOT write an alert for Scout" in _MONITOR_OBSERVE_INSTRUCTION
    # no threshold comparisons
    assert "48h" not in _MONITOR_OBSERVE_INSTRUCTION
    assert "36h" not in _MONITOR_OBSERVE_INSTRUCTION


# ── _deposit_context_snapshot (Cycle 29) ────────────────────────────────────

def test_deposit_context_snapshot_calls_deposit_to_queue(monkeypatch, tmp_path):
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(monitor, 'runtime', FakeRuntime())
    monkeypatch.setattr(monitor, 'read_pipeline_state', lambda: {'hours_since_scout_run': 2.5, 'librarian_queue_depth': 1, 'memory_count': 42})
    monkeypatch.setattr('kage.context._read_active', lambda: {'identity': 'personal', 'project': 'kage'})
    calls = []
    monkeypatch.setattr('kage.librarian.deposit_to_queue', lambda *a, **kw: calls.append((a, kw)))
    monitor._deposit_context_snapshot('test summary')
    assert len(calls) == 1
    assert calls[0][1].get('source') == 'monitor'
    assert calls[0][1].get('project') == 'kage'


def test_deposit_context_snapshot_content_has_required_fields(monkeypatch, tmp_path):
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(monitor, 'runtime', FakeRuntime())
    monkeypatch.setattr(monitor, 'read_pipeline_state', lambda: {'hours_since_scout_run': 2.5, 'librarian_queue_depth': 1, 'memory_count': 42})
    monkeypatch.setattr('kage.context._read_active', lambda: {'identity': 'personal', 'project': 'kage'})
    calls = []
    monkeypatch.setattr('kage.librarian.deposit_to_queue', lambda *a, **kw: calls.append((a, kw)))
    monitor._deposit_context_snapshot('test summary')
    content = calls[0][0][0]
    assert 'Active project:' in content
    assert 'Active identity:' in content
    assert 'Pipeline state' in content
    assert '2.5h ago' in content


def test_deposit_context_snapshot_dedup(mon_env, monkeypatch):
    monkeypatch.setattr(monitor, 'read_pipeline_state', lambda: {'hours_since_scout_run': None, 'librarian_queue_depth': 0, 'memory_count': 0})
    monkeypatch.setattr('kage.context._read_active', lambda: {'identity': 'personal', 'project': 'kage'})
    monitor._deposit_context_snapshot('same')
    monitor._deposit_context_snapshot('same')
    from kage.librarian import _connect
    conn = _connect()
    count = conn.execute("SELECT COUNT(*) FROM staging_queue WHERE source='monitor'").fetchone()[0]
    conn.close()
    assert count == 1


def test_digest_impl_calls_deposit_context_snapshot(monkeypatch, tmp_path):
    import google.adk.runners as _runners
    monkeypatch.setattr(monitor, 'build_monitor_digest', lambda cfg: None)
    monkeypatch.setattr(monitor, '_write_state_json', lambda state: None)
    monkeypatch.setattr(monitor, '_maybe_trigger_learn', lambda path: None)
    deposit_calls = []
    monkeypatch.setattr(monitor, '_deposit_context_snapshot', lambda s: deposit_calls.append(s))
    class FakeSess:
        id = 's1'
        state = {'monitor_digest': 'some digest'}
    class FakeSvc:
        async def create_session(self, **kw): return FakeSess()
        async def get_session(self, **kw): return FakeSess()
    class FakeRun:
        session_service = FakeSvc()
        def run(self, **kw): return iter([])
    class FakeConfig:
        home = tmp_path
    class FakeRuntime:
        config = FakeConfig()
    monkeypatch.setattr(monitor, 'runtime', FakeRuntime())
    monkeypatch.setattr(_runners, 'InMemoryRunner', lambda *a, **kw: FakeRun())
    monitor._digest_impl({})
    assert len(deposit_calls) == 1
