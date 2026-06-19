from __future__ import annotations

import json
import sqlite3

import pytest

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
