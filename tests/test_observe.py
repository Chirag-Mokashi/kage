"""Tests for kage.observe (Cycle 16/17) — unit tests, no live AX/NSWorkspace."""
from unittest.mock import MagicMock
import kage.observe as _obs
from kage import runtime


def test_observe_loop_fills_app_from_nsworkspace(monkeypatch):
    """_observe_loop must query _NSWorkspace for the frontmost app on each poll."""
    # Build fake _NSWorkspace chain
    fake_app_info = MagicMock()
    fake_app_info.localizedName.return_value = "Safari"
    fake_app_info.bundleIdentifier.return_value = "com.apple.Safari"
    fake_ws = MagicMock()
    fake_ws.frontmostApplication.return_value = fake_app_info
    fake_ns = MagicMock()
    fake_ns.sharedWorkspace.return_value = fake_ws
    monkeypatch.setattr(_obs, "_NSWorkspace", fake_ns)

    # No sleep, no AFK skip, no real DB, no real AX
    monkeypatch.setattr(_obs, "_seconds_since_input", lambda: 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setattr(_obs, "_read_ax_focused", lambda: ("ax_text", "My Window"))
    monkeypatch.setattr(runtime, "store", MagicMock())

    # Capture written event and exit the loop after one iteration
    captured = {}
    def fake_write_event(ev):
        captured["ev"] = ev
        raise StopIteration
    monkeypatch.setattr(_obs, "_write_event", fake_write_event)

    try:
        _obs._observe_loop()
    except StopIteration:
        pass

    assert captured["ev"].app == "Safari"
    assert captured["ev"].bundle == "com.apple.Safari"


def test_read_observe_log_multi_day(monkeypatch, tmp_path):
    """read_observe_log must read N days of files where N = int(hours/24)+1."""
    import json as _json
    import time as _time
    from datetime import datetime, timedelta
    import kage.observe as _obs

    observe_dir = tmp_path / ".kage" / "observe"
    observe_dir.mkdir(parents=True)
    monkeypatch.setattr(_obs.Path, "home", staticmethod(lambda: tmp_path))

    now = _time.time()
    # Write today's and two past days' files
    for i in range(3):
        day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        fp = observe_dir / f"{day}.jsonl"
        fp.write_text(
            _json.dumps({"ts": now - i * 86400 + 60, "app": f"App{i}", "ax_text": ""}) + "\n"
        )

    # hours=1: only today (1 file, 1 event)
    short = _obs.read_observe_log(hours=1.0)
    assert len(short) == 1
    assert short[0]["app"] == "App0"

    # hours=48: today + 2 past days = 3 files, 3 events
    long_ = _obs.read_observe_log(hours=48.0)
    assert len(long_) == 3

def test_active_context_honors_sticky_state(tmp_path, monkeypatch):
    kage_home = tmp_path / ".kage"
    kage_home.mkdir()
    state_path = kage_home / "state.json"
    state_path.write_text('{"identity": "school", "project": "thesis"}')
    fake_config = type("C", (), {"state_path": state_path})()
    monkeypatch.setattr(runtime, "config", fake_config)
    identity, project = _obs._active_context()
    assert identity == "school"
    assert project == "thesis"

def test_active_context_falls_back_with_no_state_file(tmp_path, monkeypatch):
    kage_home = tmp_path / ".kage"
    kage_home.mkdir()
    state_path = kage_home / "state.json"
    fake_config = type("C", (), {"state_path": state_path})()
    monkeypatch.setattr(runtime, "config", fake_config)
    identity, project = _obs._active_context()
    assert identity == "personal"
    assert project == ""
