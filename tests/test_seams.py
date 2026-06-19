from __future__ import annotations

import json
import sqlite3

from kage import arms as _arms
from kage import cloud as _cloud
from kage.config import Config
from kage.store import Store


def test_config_paths(tmp_path):
    cfg = Config(tmp_path)
    assert cfg.db_path == tmp_path / "indexes" / "kage.db"
    assert cfg.chroma_dir == tmp_path / "chroma"


def test_config_data_missing_returns_empty(tmp_path):
    cfg = Config(tmp_path)
    assert cfg.data == {}


def test_config_data_rereads_disk(tmp_path):
    cfg = Config(tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"k": 1}))
    assert cfg.data["k"] == 1
    (tmp_path / "config.json").write_text(json.dumps({"k": 2}))
    assert cfg.data["k"] == 2


def test_store_connect_wal(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    conn = store.connect()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_store_init_schema_creates_tables(tmp_path):
    db_path = tmp_path / "test.db"
    Store(db_path).init_schema()
    conn = sqlite3.connect(str(db_path))
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"memories", "chunks", "memory_projects", "memory_identities", "sessions", "session_turns"}.issubset(tables)


def test_store_init_schema_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    store.init_schema()
    store.init_schema()  # must not raise


def test_store_allowed_note_ids_wall(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    store.init_schema()

    conn = sqlite3.connect(str(db_path))
    # m1: scoped, personal, project=kage
    # m2: baseline, personal+neu, no project (visible to both identities across any project)
    # m3: scoped, neu, project=quantum
    # m4: pending, personal — must never be returned
    conn.executemany(
        "INSERT INTO memories (id, content_path, created_at, state) VALUES (?,?,?,?)",
        [("m1","m1.md","now","scoped"), ("m2","m2.md","now","baseline"),
         ("m3","m3.md","now","scoped"), ("m4","m4.md","now","pending")],
    )
    conn.executemany(
        "INSERT INTO memory_identities (mem_id, identity) VALUES (?,?)",
        [("m1","personal"), ("m2","personal"), ("m2","neu"), ("m3","neu"), ("m4","personal")],
    )
    conn.executemany(
        "INSERT INTO memory_projects (mem_id, project) VALUES (?,?)",
        [("m1","kage"), ("m3","quantum")],
    )
    conn.commit()
    conn.close()

    assert store.allowed_note_ids("personal", "kage") == {"m1", "m2"}
    assert store.allowed_note_ids("personal", None) == {"m1", "m2"}
    assert "m3" not in store.allowed_note_ids("personal", None)   # wrong identity
    assert "m4" not in store.allowed_note_ids("personal", None)   # pending never returned
    assert "m2" in store.allowed_note_ids("neu", "quantum")       # baseline visible cross-project


# ── Slice 5: ProviderRegistry ────────────────────────────────────────────────

def test_builtin_provider_types_registered():
    for ptype in ("claude", "openai", "openai-compat", "gemini"):
        assert ptype in _cloud._PROVIDER_REGISTRY


def test_register_provider_type_custom(monkeypatch):
    calls = []
    def fake_dispatch(_pcfg, key, _system, _messages):
        calls.append(key)
        return "custom-response"
    monkeypatch.setenv("KAGE_TEST_KEY", "my-key")
    _cloud.register_provider_type("custom-type-test", fake_dispatch)
    try:
        result = _cloud.CloudClient().complete(
            "custom-provider-test",
            "sys",
            [{"role": "user", "content": "q"}],
            {"providers": {"custom-provider-test": {"type": "custom-type-test", "api_key_env": "KAGE_TEST_KEY"}}},
        )
        assert result == "custom-response"
        assert calls[0] == "my-key"
    finally:
        del _cloud._PROVIDER_REGISTRY["custom-type-test"]


# ── Slice 5: ArmRegistry ─────────────────────────────────────────────────────

def test_builtin_arms_registered_keywords():
    assert "calendar" in _arms.ARM_KEYWORDS
    assert "gmail" in _arms.ARM_KEYWORDS
    assert "calendar" in _arms.ARM_KEYWORDS["calendar"]
    assert "email" in _arms.ARM_KEYWORDS["gmail"]


def test_builtin_transport_handlers_registered():
    for transport in ("shell", "stdio", "sse"):
        assert transport in _arms._TRANSPORT_HANDLERS


def test_register_arm_adds_keywords():
    async def _stub(_n, _c, _q, _i, _t): return None
    _arms.register_arm("test-arm-kw", ["zyx-unique-kw"], "test-transport-kw", _stub)
    try:
        assert _arms.ARM_KEYWORDS["test-arm-kw"] == ["zyx-unique-kw"]
        assert _arms._TRANSPORT_HANDLERS["test-transport-kw"] is _stub
    finally:
        del _arms.ARM_KEYWORDS["test-arm-kw"]
        del _arms._TRANSPORT_HANDLERS["test-transport-kw"]


def test_register_arm_custom_transport():
    calls = []
    async def fake_handler(arm_name, _arm_cfg, _question, _identity, _timeout):
        calls.append(arm_name)
        return "fake"
    _arms.register_arm("test-arm2", ["zyx2"], "test-transport", fake_handler)
    assert _arms.ARM_KEYWORDS["test-arm2"] == ["zyx2"]
    assert _arms._TRANSPORT_HANDLERS["test-transport"] is fake_handler
    del _arms.ARM_KEYWORDS["test-arm2"]
    del _arms._TRANSPORT_HANDLERS["test-transport"]
