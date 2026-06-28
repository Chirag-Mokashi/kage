"""Tests for kage.monitor (Cycle 16, v0.17.0) — no live LLM, no live MCP, no live Ollama."""
import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from kage import runtime
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
                "memory_added_today", "librarian_oldest_pending_hours", "scout_items_today"):
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
    with patch("asyncio.create_subprocess_shell", new=AsyncMock(side_effect=asyncio.TimeoutError)):
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
    assert "[REDACTED_PII]" in result


def test_pii_strip_api_key():
    result = _pii_strip("key=sk-abcdefghijklmnopqrstuvwxyz12345678")
    assert "[REDACTED_PII]" in result


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
    assert "[REDACTED_PII]" in req.contents[0].parts[0].text


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
