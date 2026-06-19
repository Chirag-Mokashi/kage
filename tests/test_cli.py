"""End-to-end tests for the kage CLI.

Black-box: each test runs the real `kage` command in a subprocess with an
isolated KAGE_HOME (a temp dir), so the user's real ~/.kage is never touched.
Covers the smoke path + the two invariants that guard correctness:
the save-wall (#16) and the project partition wall (#99).
"""

from __future__ import annotations

import json
import os
import asyncio
import re
import sqlite3
import subprocess
import sys
import urllib.error

import chromadb

import pytest
from typer.testing import CliRunner
from unittest import mock

from kage import cli, cloud, runtime
from kage import embed as _embed_module
from kage.config import Config
from kage.store import Store
from fakes import RecordingCloud, FakeEmbedder, FakeVectorIndex, _FakeChromaCollection  # noqa: F401


def _patch_home(monkeypatch, home) -> None:
    """Patch all kage path constants AND runtime.config/store to use `home`.

    Called by every in-process test helper that creates an isolated kage home.
    Required so runtime.store.connect() and runtime.config.data see the temp
    path after the 4 cli.py seam forwarders are wired in Cycle 12 Slice 4a.
    """
    db_path = home / "indexes" / "kage.db"
    for attr, val in {
        "KAGE_HOME": home, "MEMORY_DIR": home / "memory",
        "INDEX_DIR": home / "indexes", "DB_PATH": db_path,
        "CONFIG_PATH": home / "config.json", "CHROMA_DIR": home / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)
    monkeypatch.setattr(runtime, "config", Config(home))
    monkeypatch.setattr(runtime, "store", Store(db_path))


# ── Test fakes ──────────────────────────────────────────────────────────────


def run(args, home, stdin=None):
    """Invoke the kage CLI in a subprocess with an isolated KAGE_HOME."""
    env = {**os.environ, "KAGE_HOME": str(home)}
    return subprocess.run(
        [sys.executable, "-m", "kage.cli", *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
    )


def _id_from(stdout: str) -> str:
    m = re.search(r"\[([0-9T]+-[0-9a-f]+)\]", stdout)
    assert m, f"no memory id found in output:\n{stdout}"
    return m.group(1)


@pytest.fixture
def home(tmp_path):
    """A fresh, initialized, isolated kage store."""
    h = tmp_path / ".kage"
    assert run(["init"], h).returncode == 0
    return h


# ── smoke ──────────────────────────────────────────────────────────────────

def test_init_creates_store(tmp_path):
    h = tmp_path / ".kage"
    res = run(["init"], h)
    assert res.returncode == 0
    assert (h / "memory").is_dir()
    assert (h / "indexes" / "kage.db").is_file()
    assert (h / "config.json").is_file()


def test_remember_recall_roundtrip(home):
    r = run(["remember", "the eiffel tower is in paris", "-p", "trivia", "-y"], home)
    assert r.returncode == 0 and "saved" in r.stdout

    found = run(["recall", "eiffel"], home)
    assert found.returncode == 0
    assert "paris" in found.stdout.lower()


# ── invariants (must always hold) ───────────────────────────────────────────

def test_wall_blocks_unconfirmed_save(home):
    # Decline the confirm prompt -> nothing may persist (the wall, #16).
    r = run(["remember", "secret note", "-p", "x"], home, stdin="n\n")
    assert "Discarded" in r.stdout
    assert "No matches" in run(["recall", "secret"], home).stdout


def test_partition_wall_isolates_projects(home):
    run(["remember", "alpha shared word", "-p", "projA", "-y"], home)
    run(["remember", "beta shared word", "-p", "projB", "-y"], home)

    a = run(["recall", "shared", "-p", "projA"], home).stdout
    assert "alpha" in a and "beta" not in a  # projA query must not leak projB

    b = run(["recall", "shared", "-p", "projB"], home).stdout
    assert "beta" in b and "alpha" not in b


# ── forget + doctor ──────────────────────────────────────────────────────────

def test_forget_removes_note(home):
    saved = run(["remember", "delete me please", "-p", "tmp", "-y"], home)
    mem_id = _id_from(saved.stdout)

    f = run(["forget", mem_id, "-y"], home)
    assert f.returncode == 0 and "forgotten" in f.stdout
    assert "No matches" in run(["recall", "delete"], home).stdout


def test_doctor_healthy(home):
    r = run(["doctor"], home)
    assert r.returncode == 0 and "healthy" in r.stdout


def test_doctor_detects_drift(home):
    run(["remember", "a note", "-p", "p", "-y"], home)
    # Delete the markdown file behind kage's back -> index now disagrees.
    next((home / "memory").glob("*.md")).unlink()

    r = run(["doctor"], home)
    assert r.returncode == 1          # unhealthy
    assert "consistent" in r.stdout   # the consistency check is the one that fails


# ── doctor update (Step 10) ─────────────────────────────────────────────────

def test_doctor_warns_on_pending_embeddings(monkeypatch, tmp_path):
    """doctor must warn when notes have needs_embed=1, but still exit 0."""
    h = tmp_path / ".kage"
    _patch_home(monkeypatch, h)
    r = CliRunner()
    r.invoke(cli.app, ["init"])

    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("pending note one", "proj")
    cli._save("pending note two", "proj")

    fake_coll = type("C", (), {
        "count": lambda self: 0,
        "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]},
        "metadata": {"embed_model": "nomic-embed-text"},
    })()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)

    result = r.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    assert "chunk(s) not yet embedded" in result.output


def test_doctor_warns_on_embed_model_mismatch(monkeypatch, tmp_path):
    """doctor must warn when config embed_model differs from ChromaDB collection metadata."""
    h = tmp_path / ".kage"
    _patch_home(monkeypatch, h)
    r = CliRunner()
    r.invoke(cli.app, ["init"])

    fake_coll = type("C", (), {
        "count": lambda self: 0,
        "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]},
        "metadata": {"embed_model": "old-model"},
    })()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)

    result = r.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    assert "embedding model changed" in result.output


def test_import_folder(home, tmp_path):
    notes = tmp_path / "notes"
    (notes / "sub").mkdir(parents=True)
    (notes / "a.md").write_text("alpha note about cats")
    (notes / "sub" / "b.txt").write_text("beta note about dogs")
    (notes / "skip.png").write_bytes(b"\x00")  # non-text -> must be skipped

    r = run(["import", str(notes), "-p", "imported"], home)
    assert r.returncode == 0 and "imported 2" in r.stdout  # .md + .txt only

    listed = run(["list", "-p", "imported"], home).stdout
    assert "alpha" in listed and "beta" in listed
    assert "cats" in run(["recall", "cats", "-p", "imported"], home).stdout


# ── import_ update (Step 8) ─────────────────────────────────────────────────

def test_import_skips_embedding(monkeypatch, tmp_path):
    """import_ must NOT call _embed — bulk import defers embedding to kage reindex."""
    home = tmp_path / ".kage"
    _patch_home(monkeypatch, home)
    r = CliRunner()
    assert r.invoke(cli.app, ["init"]).exit_code == 0

    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("first imported note")
    (notes / "b.md").write_text("second imported note")

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("_embed must not be called during import_")

    monkeypatch.setattr(cli, "_embed", must_not_be_called)

    result = r.invoke(cli.app, ["import", str(notes), "-p", "bulk"])
    assert result.exit_code == 0

    conn = sqlite3.connect(str(home / "indexes" / "kage.db"))
    rows = conn.execute(
        "SELECT c.needs_embed FROM chunks c JOIN memories m ON m.id = c.note_id WHERE m.project='bulk'"
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert all(row[0] == 1 for row in rows)


def test_import_prints_reindex_hint(monkeypatch, tmp_path):
    """import_ must print the reindex hint after bulk import completes."""
    home = tmp_path / ".kage"
    _patch_home(monkeypatch, home)
    r = CliRunner()
    assert r.invoke(cli.app, ["init"]).exit_code == 0

    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "note.md").write_text("a note to import")

    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no embed")))

    result = r.invoke(cli.app, ["import", str(notes), "-p", "bulk"])
    assert result.exit_code == 0
    assert "kage reindex" in result.output


def test_ask_honors_partition_and_returns_answer(monkeypatch, tmp_path):
    """ask must send ONLY the active project's notes as context (the wall), and return the model's answer.

    In-process + mocked model call, so it runs in CI without Ollama.
    """
    home = tmp_path / ".kage"
    _patch_home(monkeypatch, home)
    r = CliRunner()
    assert r.invoke(cli.app, ["init"]).exit_code == 0
    r.invoke(cli.app, ["remember", "alpha shared secret", "-p", "A", "-y"])
    r.invoke(cli.app, ["remember", "beta shared secret", "-p", "B", "-y"])

    captured = {}

    def fake_post(url, payload, headers=None, timeout=120):
        captured["payload"] = payload
        return {"response": "the answer"}

    monkeypatch.setattr(cli, "_post_json", fake_post)

    res = r.invoke(cli.app, ["ask", "what is the shared secret", "-p", "A"])
    assert res.exit_code == 0
    prompt = captured["payload"]["prompt"]
    assert "alpha" in prompt and "beta" not in prompt   # the partition wall holds for ask
    assert "the answer" in res.stdout


# ── _search hybrid router (Step 6) ─────────────────────────────────────────

def test_search_returns_empty_for_empty_query():
    assert cli._search("   ", None, 5) == []
    assert cli._search("", None, 5) == []


def test_search_falls_back_to_fts_when_embed_disabled(monkeypatch):
    captured = {}
    def fake_fts(query, project, limit, any_terms=False, identity="personal"):
        captured["limit"] = limit
        return [("A", "p", "t", "a.md", "snip")]
    monkeypatch.setattr(cli, "_config", lambda: {"embeddings": False})
    monkeypatch.setattr(cli, "_search_fts", fake_fts)
    result = cli._search("hello", "p", 5)
    assert captured["limit"] == 5
    assert result[0][0] == "A"


def test_search_falls_back_to_fts_when_ollama_down(monkeypatch):
    monkeypatch.setattr(cli, "_config", lambda: {"embeddings": True})
    monkeypatch.setattr(cli, "_search_fts", lambda *a, **kw: [("A", "p", "t", "a.md", "snip")])
    def raise_unavailable(*a, **kw):
        raise cli.OllamaUnavailable("down")
    monkeypatch.setattr(cli, "_embed", raise_unavailable)
    result = cli._search("hello", "p", 5)
    assert result[0][0] == "A"


def test_search_hybrid_fuses_both_results(monkeypatch):
    monkeypatch.setattr(cli, "_config", lambda: {"embeddings": True})
    monkeypatch.setattr(cli, "_search_fts", lambda *a, **kw: [("A", "p", "t", "a.md", "snip")])
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1, 0.2])
    monkeypatch.setattr(cli, "_search_vec", lambda *a, **kw: [("B", "p", "t", "b.md", 0.9, "", 0, 10)])
    monkeypatch.setattr(cli, "_read_body", lambda *a, **kw: "body")
    result = cli._search("hello", "p", 5)
    ids = [r[0] for r in result]
    assert "A" in ids
    assert "B" in ids


# ── _search_vec (Step 5) ────────────────────────────────────────────────────

def test_search_vec_returns_correct_shape(monkeypatch):
    # v0.4: rows are 8-tuples (note_id, project, created_at, path, score, title, cs, ce)
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: {"n1", "n2"})

    class FakeCollection:
        def count(self): return 2
        def get(self, where=None, include=None): return {"ids": ["n1_c0", "n2_c0"]}
        def query(self, **kwargs):
            return {
                "ids": [["n1_c0", "n2_c0"]],
                "metadatas": [[
                    {"note_id": "n1", "project": "p", "created_at": "t", "content_path": "c.md",
                     "section_title": "", "char_start": 0, "char_end": 10},
                    {"note_id": "n2", "project": "p", "created_at": "t", "content_path": "d.md",
                     "section_title": "", "char_start": 0, "char_end": 10},
                ]],
                "distances": [[0.1, 0.2]],
            }

    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeCollection())
    result = cli._search_vec([0.1, 0.2], "p", 5)
    assert len(result) == 2
    assert len(result[0]) == 8   # 8-tuple: (note_id, project, created_at, path, score, title, cs, ce)


def test_search_vec_applies_project_filter(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: {"n1"})

    class FakeCollection:
        def count(self): return 1
        def get(self, where=None, include=None): return {"ids": ["n1_c0"]}
        def query(self, **kwargs):
            captured["where"] = kwargs.get("where")
            return {"ids": [["n1_c0"]], "metadatas": [[
                {"note_id": "n1", "project": "projA", "created_at": "t", "content_path": "c.md",
                 "section_title": "", "char_start": 0, "char_end": 10}
            ]], "distances": [[0.1]]}

    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeCollection())
    cli._search_vec([0.1], "projA", 5)
    assert "note_id" in captured["where"]
    assert set(captured["where"]["note_id"]["$in"]) == {"n1"}


def test_search_vec_returns_empty_on_empty_collection(monkeypatch):
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: {"n1"})

    class FakeCollection:
        def count(self): return 0
        def get(self, where=None, include=None): return {"ids": []}

    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeCollection())
    assert cli._search_vec([0.1], "p", 5) == []


def test_search_vec_no_where_when_project_is_none(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: {"n1"})

    class FakeCollection:
        def count(self): return 1
        def get(self, where=None, include=None): return {"ids": ["n1_c0"]}
        def query(self, **kwargs):
            captured["where"] = kwargs.get("where")
            return {"ids": [["n1_c0"]], "metadatas": [[
                {"note_id": "n1", "project": None, "created_at": "t", "content_path": "c.md",
                 "section_title": "", "char_start": 0, "char_end": 10}
            ]], "distances": [[0.1]]}

    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeCollection())
    cli._search_vec([0.1], None, 5)
    assert "note_id" in captured["where"]
    assert set(captured["where"]["note_id"]["$in"]) == {"n1"}


# ── _get_chroma (Step 4) ────────────────────────────────────────────────────

def test_get_chroma_returns_collection(monkeypatch):
    class FakeCollection:
        metadata = {"embed_model": "nomic-embed-text", "schema_version": "4"}

    class FakePersistentClient:
        def __init__(self, path):
            pass
        def get_or_create_collection(self, name, **kwargs):
            return FakeCollection()

    monkeypatch.setattr(chromadb, "PersistentClient", FakePersistentClient)
    result = cli._get_chroma()
    assert result.metadata["embed_model"] == "nomic-embed-text"


def test_get_chroma_raises_on_model_mismatch(monkeypatch):
    class FakeCollection:
        metadata = {"embed_model": "old-model"}

    class FakePersistentClient:
        def __init__(self, path):
            pass
        def get_or_create_collection(self, name, **kwargs):
            return FakeCollection()

    monkeypatch.setattr(chromadb, "PersistentClient", FakePersistentClient)
    with pytest.raises(cli.OllamaUnavailable):
        cli._get_chroma()


# ── _embed (Step 3) ─────────────────────────────────────────────────────────

def test_embed_returns_floats(monkeypatch):
    monkeypatch.setattr(_embed_module, "_post_json", lambda url, payload, **kw: {"embeddings": [[0.1, 0.2, 0.3]]})
    assert cli._embed("hello") == [0.1, 0.2, 0.3]


def test_embed_truncates_long_input(monkeypatch):
    captured = {}
    def fake_post(url, payload, **kw):
        captured["payload"] = payload
        return {"embeddings": [[0.1]]}
    monkeypatch.setattr(_embed_module, "_post_json", fake_post)
    cli._embed("x" * 40000)
    assert len(captured["payload"]["input"]) == 6000


def test_embed_raises_on_urlerror(monkeypatch):
    def raise_it(*a, **kw):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(_embed_module, "_post_json", raise_it)
    with pytest.raises(cli.OllamaUnavailable):
        cli._embed("test")


def test_embed_raises_on_timeout(monkeypatch):
    def raise_it(*a, **kw):
        raise TimeoutError()
    monkeypatch.setattr(_embed_module, "_post_json", raise_it)
    with pytest.raises(cli.OllamaUnavailable):
        cli._embed("test")


# ── schema migration (Step 2) ───────────────────────────────────────────────

# ── config update (Step 11) ──────────────────────────────────────────────────

def test_init_config_has_embedding_keys(tmp_path):
    """A fresh kage init must write embeddings and embed_model to config.json."""
    import json as _json
    h = tmp_path / ".kage"
    assert run(["init"], h).returncode == 0
    cfg = _json.loads((h / "config.json").read_text())
    assert cfg.get("embeddings") is True
    assert cfg.get("embed_model") == "nomic-embed-text"


def test_init_creates_chroma_dir(tmp_path):
    h = tmp_path / ".kage"
    assert run(["init"], h).returncode == 0
    assert (h / "chroma").is_dir()


def test_init_creates_needs_embed_column(tmp_path):
    h = tmp_path / ".kage"
    run(["init"], h)
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(memories)")]
    conn.close()
    assert "needs_embed" in cols


def test_chunks_table_created_on_init(tmp_path):
    h = tmp_path / ".kage"
    run(["init"], h)
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(chunks)")]
    conn.close()
    assert cols == ["id", "note_id", "section_title", "char_start", "char_end", "needs_embed"]


def test_chunks_table_created_on_existing_db(tmp_path):
    h = tmp_path / ".kage"
    (h / "indexes").mkdir(parents=True)
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    conn.executescript("""
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, content_path TEXT NOT NULL,
            project TEXT, created_at TEXT NOT NULL, needs_embed INTEGER NOT NULL DEFAULT 1
        );
        CREATE VIRTUAL TABLE memory_fts USING fts5(id UNINDEXED, body);
    """)
    conn.close()
    assert run(["init"], h).returncode == 0
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(chunks)")]
    conn.close()
    assert "id" in cols and "char_start" in cols


# ── schema Step 1 (Cycle 9): join tables + state column ────────────────────

def test_init_creates_join_tables(tmp_path):
    h = tmp_path / ".kage"
    run(["init"], h)
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    table_names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    index_names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")]
    conn.close()
    assert "memory_projects" in table_names
    assert "memory_identities" in table_names
    assert "idx_mem_projects_project" in index_names
    assert "idx_mem_identities_identity" in index_names


def test_init_creates_state_column(tmp_path):
    h = tmp_path / ".kage"
    run(["init"], h)
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(memories)")]
    conn.close()
    assert "state" in cols


def test_init_migration_adds_state_to_existing_db(tmp_path):
    h = tmp_path / ".kage"
    (h / "indexes").mkdir(parents=True)
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    conn.executescript("""
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, content_path TEXT NOT NULL,
            project TEXT, created_at TEXT NOT NULL, needs_embed INTEGER NOT NULL DEFAULT 1,
            local_only INTEGER NOT NULL DEFAULT 0
        );
        CREATE VIRTUAL TABLE memory_fts USING fts5(id UNINDEXED, body);
    """)
    conn.close()
    assert run(["init"], h).returncode == 0
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(memories)")]
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    conn.close()
    assert "state" in cols
    assert "memory_projects" in tables
    assert "memory_identities" in tables


def test_init_idempotent_on_migrated_db(tmp_path):
    h = tmp_path / ".kage"
    run(["init"], h)
    assert run(["init"], h).returncode == 0
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(memories)")]
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    conn.close()
    assert "state" in cols
    assert "memory_projects" in tables
    assert "memory_identities" in tables


# ── _allowed_note_ids wall (Cycle 9, Step 2) — M1-M7 TDD ──────────────────

def _wall_home(monkeypatch, tmp_path):
    h = tmp_path / ".kage"
    _patch_home(monkeypatch, h)
    CliRunner().invoke(cli.app, ["init"])
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    conn.executemany(
        "INSERT INTO memories(id, content_path, created_at, state) VALUES (?,?,?,?)",
        [
            ("m1","m1.md","2026-01-01","scoped"),
            ("m2","m2.md","2026-01-01","baseline"),
            ("m3","m3.md","2026-01-01","scoped"),
            ("m4","m4.md","2026-01-01","baseline"),
            ("m5","m5.md","2026-01-01","scoped"),
            ("m6","m6.md","2026-01-01","baseline"),
            ("m7","m7.md","2026-01-01","pending"),
        ],
    )
    conn.executemany(
        "INSERT INTO memory_identities(mem_id, identity) VALUES (?,?)",
        [
            ("m1","personal"),
            ("m2","personal"),("m2","neu"),
            ("m3","neu"),
            ("m4","neu"),
            ("m5","neu"),
            ("m6","personal"),("m6","neu"),
            ("m7","personal"),
        ],
    )
    conn.executemany(
        "INSERT INTO memory_projects(mem_id, project) VALUES (?,?)",
        [("m1","kage"),("m3","quantum"),("m5","llm-rsrch")],
    )
    conn.commit()
    conn.close()
    return h


def test_allowed_note_ids_personal_kage(monkeypatch, tmp_path):
    _wall_home(monkeypatch, tmp_path)
    assert cli._allowed_note_ids("personal", "kage") == {"m1", "m2", "m6"}

def test_allowed_note_ids_personal_no_project(monkeypatch, tmp_path):
    _wall_home(monkeypatch, tmp_path)
    assert cli._allowed_note_ids("personal", None) == {"m1", "m2", "m6"}

def test_allowed_note_ids_neu_quantum(monkeypatch, tmp_path):
    _wall_home(monkeypatch, tmp_path)
    assert cli._allowed_note_ids("neu", "quantum") == {"m2", "m3", "m4", "m6"}

def test_allowed_note_ids_neu_no_project(monkeypatch, tmp_path):
    _wall_home(monkeypatch, tmp_path)
    assert cli._allowed_note_ids("neu", None) == {"m2", "m3", "m4", "m5", "m6"}

def test_allowed_note_ids_wall_invariant(monkeypatch, tmp_path):
    _wall_home(monkeypatch, tmp_path)
    personal_all = cli._allowed_note_ids("personal", None)
    neu_all = cli._allowed_note_ids("neu", None)
    assert "m1" not in neu_all
    assert "m3" not in personal_all
    assert "m5" not in personal_all

def test_allowed_note_ids_pending_never_returned(monkeypatch, tmp_path):
    _wall_home(monkeypatch, tmp_path)
    assert "m7" not in cli._allowed_note_ids("personal", None)
    assert "m7" not in cli._allowed_note_ids("personal", "kage")
    assert "m7" not in cli._allowed_note_ids("personal", "some-other-project")


# ── _search_fts wall (Cycle 9, Step 5) — FTS enforces identity ─────────────

def test_search_fts_enforces_identity_wall(monkeypatch, tmp_path):
    _wall_home(monkeypatch, tmp_path)
    conn = sqlite3.connect(cli.DB_PATH)
    conn.execute("INSERT INTO memory_fts(id, body) VALUES ('m1', 'alpha unique kage note')")
    conn.execute("INSERT INTO memory_fts(id, body) VALUES ('m3', 'alpha unique quantum note')")
    conn.commit()
    conn.close()
    personal_rows = cli._search_fts("alpha", "kage", 10, identity="personal")
    personal_ids = {r[0] for r in personal_rows}
    neu_rows = cli._search_fts("alpha", "quantum", 10, identity="neu")
    neu_ids = {r[0] for r in neu_rows}
    assert "m1" in personal_ids
    assert "m3" not in personal_ids
    assert "m3" in neu_ids
    assert "m1" not in neu_ids

def test_search_fts_empty_when_no_allowed_ids(monkeypatch, tmp_path):
    _wall_home(monkeypatch, tmp_path)
    conn = sqlite3.connect(cli.DB_PATH)
    conn.execute("INSERT INTO memory_fts(id, body) VALUES ('m1', 'hello world')")
    conn.commit()
    conn.close()
    result = cli._search_fts("hello", None, 10, identity="ghost")
    assert result == []

def test_search_embeddings_off_uses_wall(monkeypatch, tmp_path):
    _wall_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_config", lambda: {"embeddings": False, "rerank": False})
    conn = sqlite3.connect(cli.DB_PATH)
    conn.execute("INSERT INTO memory_fts(id, body) VALUES ('m1', 'beta personal note')")
    conn.execute("INSERT INTO memory_fts(id, body) VALUES ('m3', 'beta neu note')")
    conn.commit()
    conn.close()
    result = cli._search("beta", "kage", 10, identity="personal")
    ids = {r[0] for r in result}
    assert "m1" in ids
    assert "m3" not in ids


# ── _migrate_identity_axis (Cycle 9, Step 3) ───────────────────────────────

def _mp_home(monkeypatch, tmp_path):
    h = tmp_path / ".kage"
    _patch_home(monkeypatch, h)
    CliRunner().invoke(cli.app, ["init"])
    return h


def test_migrate_backfills_identity(monkeypatch, tmp_path):
    h = _mp_home(monkeypatch, tmp_path)
    md = h / "memory" / "test-note.md"
    md.write_text("---\nid: test-note\nproject: proj1\ncreated_at: 2026-01-01\n---\n\nhello world\n")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    conn.execute("INSERT INTO memories(id, content_path, project, created_at) VALUES (?,?,?,?)", ("test-note", "memory/test-note.md", "proj1", "2026-01-01"))
    conn.commit()
    conn.close()
    cli._migrate_identity_axis(dry_run=False)
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    assert "personal" in {row[0] for row in conn.execute("SELECT identity FROM memory_identities WHERE mem_id='test-note'")}
    assert "proj1" in {row[0] for row in conn.execute("SELECT project FROM memory_projects WHERE mem_id='test-note'")}
    conn.close()


def test_migrate_dry_run_writes_nothing(monkeypatch, tmp_path):
    h = _mp_home(monkeypatch, tmp_path)
    md = h / "memory" / "test-note.md"
    md.write_text("---\nid: test-note\nproject: proj1\ncreated_at: 2026-01-01\n---\n\nhello world\n")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    conn.execute("INSERT INTO memories(id, content_path, project, created_at) VALUES (?,?,?,?)", ("test-note", "memory/test-note.md", "proj1", "2026-01-01"))
    conn.commit()
    conn.close()
    cli._migrate_identity_axis(dry_run=True)
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    assert conn.execute("SELECT COUNT(*) FROM memory_identities").fetchone()[0] == 0
    conn.close()
    assert "identities:" not in md.read_text()


def test_migrate_is_idempotent(monkeypatch, tmp_path):
    h = _mp_home(monkeypatch, tmp_path)
    md = h / "memory" / "test-note.md"
    md.write_text("---\nid: test-note\nproject: proj1\ncreated_at: 2026-01-01\n---\n\nhello world\n")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    conn.execute("INSERT INTO memories(id, content_path, project, created_at) VALUES (?,?,?,?)", ("test-note", "memory/test-note.md", "proj1", "2026-01-01"))
    conn.commit()
    conn.close()
    stats1 = cli._migrate_identity_axis(dry_run=False)
    assert stats1["identities_added"] == 1
    assert stats1["projects_added"] == 1
    assert stats1["frontmatter_updated"] == 1
    stats2 = cli._migrate_identity_axis(dry_run=False)
    assert stats2["identities_added"] == 0
    assert stats2["projects_added"] == 0
    assert stats2["frontmatter_updated"] == 0


def test_migrate_cli_dry_run(tmp_path):
    h = tmp_path / ".kage"
    run(["init"], h)
    run(["remember", "some text", "-p", "myproject", "-y"], h)
    result = run(["migrate", "--dry-run"], h)
    assert result.returncode == 0
    assert "[DRY RUN]" in result.stdout
    assert "identities added:" in result.stdout


# ── _save identity matrix (Cycle 9, Step 4) ────────────────────────────────

def test_save_writes_personal_identity_by_default(monkeypatch, tmp_path):
    h = _mp_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1] * 768)
    fake_coll = type("C", (), {"add": lambda self, **kw: None, "count": lambda self: 0, "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]}, "delete": lambda self, **kw: None})()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)
    mem_id = cli._save("hello world", "myproject")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    identities = {r[0] for r in conn.execute("SELECT identity FROM memory_identities WHERE mem_id=?", (mem_id,))}
    conn.close()
    assert identities == {"personal"}

def test_save_writes_state_scoped_when_project_given(monkeypatch, tmp_path):
    h = _mp_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1] * 768)
    fake_coll = type("C", (), {"add": lambda self, **kw: None, "count": lambda self: 0, "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]}, "delete": lambda self, **kw: None})()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)
    mem_id = cli._save("some note", "myproject")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    state = conn.execute("SELECT state FROM memories WHERE id=?", (mem_id,)).fetchone()[0]
    conn.close()
    assert state == "scoped"

def test_save_writes_state_baseline_when_no_project(monkeypatch, tmp_path):
    h = _mp_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1] * 768)
    fake_coll = type("C", (), {"add": lambda self, **kw: None, "count": lambda self: 0, "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]}, "delete": lambda self, **kw: None})()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)
    mem_id = cli._save("some note", None)
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    state = conn.execute("SELECT state FROM memories WHERE id=?", (mem_id,)).fetchone()[0]
    conn.close()
    assert state == "baseline"

def test_save_writes_explicit_identity(monkeypatch, tmp_path):
    h = _mp_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1] * 768)
    fake_coll = type("C", (), {"add": lambda self, **kw: None, "count": lambda self: 0, "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]}, "delete": lambda self, **kw: None})()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)
    mem_id = cli._save("neu note", "hsi", identities=["neu"])
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    identities = {r[0] for r in conn.execute("SELECT identity FROM memory_identities WHERE mem_id=?", (mem_id,))}
    conn.close()
    assert identities == {"neu"}

def test_save_round_trips_through_allowed_note_ids(monkeypatch, tmp_path):
    h = _mp_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1] * 768)
    fake_coll = type("C", (), {"add": lambda self, **kw: None, "count": lambda self: 0, "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]}, "delete": lambda self, **kw: None})()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)
    mem_id = cli._save("kage context note", "kage", identities=["personal"])
    result = cli._allowed_note_ids("personal", "kage")
    assert mem_id in result
    result_neu = cli._allowed_note_ids("neu", "kage")
    assert mem_id not in result_neu


# ── _chunk_note (Step 2) ────────────────────────────────────────────────────

def test_chunk_note_splits_on_h2():
    section_one = "x" * 110
    section_two = "y" * 110
    body = f"## Section One\n{section_one}\n\n## Section Two\n{section_two}"
    result = cli._chunk_note(body)
    assert len(result) == 2
    assert result[0]["title"] == "Section One"
    assert result[1]["title"] == "Section Two"


def test_chunk_note_splits_on_h3():
    section_one = "a" * 110
    section_two = "b" * 110
    body = f"### Header One\n{section_one}\n\n### Header Two\n{section_two}"
    result = cli._chunk_note(body)
    assert len(result) == 2
    assert result[0]["title"] == "Header One"
    assert result[1]["title"] == "Header Two"


def test_chunk_note_skips_short_chunks():
    body = "## Too Short\nThis is too short to be a chunk."
    result = cli._chunk_note(body)
    assert len(result) == 1
    assert result[0]["title"] == ""


def test_chunk_note_fallback_no_headers():
    body = "This is a body with no headers at all."
    result = cli._chunk_note(body)
    assert result == [{"title": "", "char_start": 0, "char_end": len(body)}]


def test_chunk_note_fallback_all_short():
    body = "## First\nToo short.\n\n## Second\nAlso too short."
    result = cli._chunk_note(body)
    assert result == [{"title": "", "char_start": 0, "char_end": len(body)}]


def test_chunk_note_char_offsets_are_correct():
    section_one = "x" * 110
    section_two = "y" * 110
    body = f"## First\n{section_one}\n\n## Second\n{section_two}"
    result = cli._chunk_note(body)
    assert len(result) == 2
    # char_end for first chunk points to the start of "## Second", so the
    # slice includes the trailing "\n\n" separator — strip for comparison
    assert body[result[0]["char_start"]:result[0]["char_end"]].strip() == section_one
    assert body[result[1]["char_start"]:result[1]["char_end"]].strip() == section_two


def test_chunk_note_char_end_does_not_exceed_body():
    body = "## Section\n" + "x" * 110  # no trailing newline
    result = cli._chunk_note(body)
    assert all(chunk["char_end"] <= len(body) for chunk in result)


# ── _chunk_note recursive splitting (Cycle 8) ───────────────────────────────

def test_chunk_note_headerless_long_splits_by_paragraph():
    body = (('word ' * 60).strip() + '\n\n') * 6
    result = cli._chunk_note(body)
    assert len(result) > 1
    for chunk in result:
        assert chunk['char_end'] - chunk['char_start'] <= cli._CHUNK_TARGET + 10
    for chunk in result:
        assert chunk['char_end'] <= len(body)

def test_chunk_note_oversized_header_section_splits():
    section_text = ('sentence here. ' * 130).strip()
    body = '## Big Section\n' + section_text
    result = cli._chunk_note(body)
    assert len(result) > 1
    for chunk in result:
        assert chunk['char_end'] - chunk['char_start'] <= cli._CHUNK_TARGET + 10
    for chunk in result:
        assert chunk['char_end'] <= len(body)

def test_chunk_note_recursive_chunks_span_body():
    para = ('word ' * 80).strip()
    body = (para + '\n\n') * 5
    result = cli._chunk_note(body)
    assert result[0]['char_start'] < cli._CHUNK_OVERLAP
    assert result[-1]['char_end'] >= len(body) - cli._CHUNK_OVERLAP
    for chunk in result:
        assert 0 <= chunk['char_start'] < chunk['char_end'] <= len(body)

def test_chunk_note_offsets_index_into_body():
    para = ('word ' * 80).strip()
    body = (para + '\n\n') * 5
    result = cli._chunk_note(body)
    for chunk in result:
        text = body[chunk['char_start']:chunk['char_end']]
        assert len(text) >= cli._CHUNK_MIN

def test_hard_windows_covers_text():
    text = 'x' * 5000
    chunks = cli._hard_windows(text, 0, 't')
    covered = set()
    for c in chunks:
        covered.update(range(c['char_start'], c['char_end']))
    assert covered.issuperset(range(len(text)))
    for c in chunks:
        assert c['char_end'] - c['char_start'] <= cli._CHUNK_TARGET

def test_window_by_pieces_tracks_positions():
    # text must be > _CHUNK_MIN (100) for any chunk to emit
    words = [f"word{i:03d}" for i in range(20)]  # 20 × 7 chars = 140 chars total
    text = " ".join(words)
    pieces = words
    result = cli._window_by_pieces(pieces, text, 0, "test")
    assert len(result) > 0
    for chunk in result:
        assert 0 <= chunk["char_start"]
        assert chunk["char_end"] <= len(text)
        assert chunk["char_end"] > chunk["char_start"]


# ── _read_section (Step 3) ──────────────────────────────────────────────────

def test_read_section_returns_correct_slice(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "KAGE_HOME", tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "note.md").write_text("This is the body of the note.")
    result = cli._read_section("memory/note.md", 5, 15)
    assert result == "is the bod"


def test_read_section_with_frontmatter_file(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "KAGE_HOME", tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "note.md").write_text(
        "---\ntitle: Test Note\n---\nThis is the body of the note."
    )
    # _read_body strips frontmatter + strips whitespace → body = "This is the body of the note."
    result = cli._read_section("memory/note.md", 5, 15)
    assert result == "is the bod"


def test_read_section_returns_empty_on_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "KAGE_HOME", tmp_path)
    result = cli._read_section("memory/nonexistent.md", 0, 10)
    assert result == ""


def test_read_section_full_body_slice(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "KAGE_HOME", tmp_path)
    (tmp_path / "memory").mkdir()
    body = "This is the body of the note."
    (tmp_path / "memory" / "note.md").write_text(body)
    result = cli._read_section("memory/note.md", 0, len(body))
    assert result == body


# ── _get_chroma (Step 4) ────────────────────────────────────────────────────

def _fake_chroma_client(metadata):
    """Return a fake chromadb client whose collection has the given metadata."""
    coll = type("Coll", (), {"metadata": metadata, "add": lambda *a, **kw: None})()
    return type("Client", (), {"get_or_create_collection": lambda self, **kw: coll})()


def test_get_chroma_returns_collection_on_fresh_db(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(cli, "_config", lambda: {"embed_model": "nomic-embed-text"})
    import chromadb
    monkeypatch.setattr(chromadb, "PersistentClient", lambda path: _fake_chroma_client(
        {"embed_model": "nomic-embed-text", "schema_version": "4"}
    ))
    result = cli._get_chroma()
    assert result is not None


def test_get_chroma_raises_on_embed_model_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(cli, "_config", lambda: {"embed_model": "nomic-embed-text"})
    import chromadb
    monkeypatch.setattr(chromadb, "PersistentClient", lambda path: _fake_chroma_client(
        {"embed_model": "old-model", "schema_version": "4"}
    ))
    with pytest.raises(cli.OllamaUnavailable):
        cli._get_chroma()


def test_get_chroma_raises_on_missing_schema_version(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(cli, "_config", lambda: {"embed_model": "nomic-embed-text"})
    import chromadb
    monkeypatch.setattr(chromadb, "PersistentClient", lambda path: _fake_chroma_client(
        {"embed_model": "nomic-embed-text"}  # no schema_version key
    ))
    with pytest.raises(cli.OllamaUnavailable):
        cli._get_chroma()


def test_get_chroma_raises_on_wrong_schema_version(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(cli, "_config", lambda: {"embed_model": "nomic-embed-text"})
    import chromadb
    monkeypatch.setattr(chromadb, "PersistentClient", lambda path: _fake_chroma_client(
        {"embed_model": "nomic-embed-text", "schema_version": "3"}
    ))
    with pytest.raises(cli.OllamaUnavailable):
        cli._get_chroma()


def test_get_chroma_banner_printed_before_raise(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(cli, "_config", lambda: {"embed_model": "nomic-embed-text"})
    import chromadb
    monkeypatch.setattr(chromadb, "PersistentClient", lambda path: _fake_chroma_client(
        {"embed_model": "nomic-embed-text"}  # missing schema_version
    ))
    try:
        cli._get_chroma()
    except cli.OllamaUnavailable:
        pass
    captured = capsys.readouterr()
    assert "schema version mismatch" in captured.err


def test_wal_mode_enabled(tmp_path):
    h = tmp_path / ".kage"
    run(["init"], h)
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_save_sets_needs_embed_to_0_when_ollama_up(monkeypatch, tmp_path):
    h = tmp_path / ".kage"
    _patch_home(monkeypatch, h)
    CliRunner().invoke(cli.app, ["init"])
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1, 0.2])
    fake_coll = type("C", (), {
        "add": lambda self, **kw: None,
        "count": lambda self: 0,
        "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]},
        "delete": lambda self, **kw: None,
    })()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)
    mem_id = cli._save("some note", "test")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    # v0.4: embed status lives in chunks.needs_embed, not memories.needs_embed
    vals = [r[0] for r in conn.execute("SELECT needs_embed FROM chunks WHERE note_id=?", (mem_id,)).fetchall()]
    conn.close()
    assert all(v == 0 for v in vals)


def test_save_sets_needs_embed_to_1_when_ollama_down(monkeypatch, tmp_path):
    h = tmp_path / ".kage"
    _patch_home(monkeypatch, h)
    CliRunner().invoke(cli.app, ["init"])
    def embed_down(*a, **kw): raise cli.OllamaUnavailable("down")
    monkeypatch.setattr(cli, "_embed", embed_down)
    mem_id = cli._save("some note", "test")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    result = conn.execute("SELECT needs_embed FROM chunks WHERE note_id=?", (mem_id,)).fetchone()
    conn.close()
    assert result[0] == 1


def test_init_migration_adds_needs_embed_to_existing_db(tmp_path):
    h = tmp_path / ".kage"
    (h / "indexes").mkdir(parents=True)
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    conn.executescript("""
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, content_path TEXT NOT NULL,
            project TEXT, created_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE memory_fts USING fts5(id UNINDEXED, body);
    """)
    conn.close()
    assert run(["init"], h).returncode == 0
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(memories)")]
    conn.close()
    assert "needs_embed" in cols


# ── _save chunks (Step 5) ───────────────────────────────────────────────────

def _save_home(monkeypatch, tmp_path):
    """Isolated in-process kage home for _save chunk tests."""
    h = tmp_path / ".kage"
    _patch_home(monkeypatch, h)
    CliRunner().invoke(cli.app, ["init"])
    return h


def test_save_inserts_chunks_into_db(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    mem_id = cli._save("## Intro\n" + "x" * 110, "proj")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    rows = conn.execute("SELECT * FROM chunks WHERE note_id=?", (mem_id,)).fetchall()
    conn.close()
    assert len(rows) >= 1


def test_save_chunk_ids_follow_scheme(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    mem_id = cli._save("## Intro\n" + "x" * 110, "proj")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE note_id=?", (mem_id,)).fetchall()]
    conn.close()
    for cid in ids:
        assert cid.startswith(f"{mem_id}_c")
        assert cid[len(f"{mem_id}_c"):].isdigit()


def test_save_sets_chunk_needs_embed_0_when_ollama_up(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1, 0.2])
    fake_coll = type("C", (), {"add": lambda self, **kw: None})()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)
    mem_id = cli._save("## Intro\n" + "x" * 110, "proj")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    vals = [r[0] for r in conn.execute("SELECT needs_embed FROM chunks WHERE note_id=?", (mem_id,)).fetchall()]
    conn.close()
    assert all(v == 0 for v in vals)


def test_save_sets_chunk_needs_embed_1_when_ollama_down(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    def embed_down(*a, **kw): raise cli.OllamaUnavailable("down")
    monkeypatch.setattr(cli, "_embed", embed_down)
    mem_id = cli._save("## Intro\n" + "x" * 110, "proj")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    vals = [r[0] for r in conn.execute("SELECT needs_embed FROM chunks WHERE note_id=?", (mem_id,)).fetchall()]
    conn.close()
    assert all(v == 1 for v in vals)


def test_save_chunk_transaction_rolls_back_on_failure(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    # Return a chunk with char_start=None — violates NOT NULL, causes INSERT to fail mid-transaction
    monkeypatch.setattr(cli, "_chunk_note", lambda body: [{"title": "", "char_start": None, "char_end": None}])
    with pytest.raises(Exception):
        cli._save("some text", "proj")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    chunk_rows = conn.execute("SELECT * FROM chunks").fetchall()
    mem_rows = conn.execute("SELECT * FROM memories").fetchall()
    conn.close()
    assert len(chunk_rows) == 0
    assert len(mem_rows) == 0  # rollback covers memories INSERT too


# ── forget chunks (Step 8) ──────────────────────────────────────────────────

def test_forget_deletes_chunks_from_sqlite(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    def embed_down(*a, **kw): raise cli.OllamaUnavailable("down")
    monkeypatch.setattr(cli, "_embed", embed_down)
    mem_id = cli._save("## Intro\n" + "x" * 110, "proj")

    conn = sqlite3.connect(h / "indexes" / "kage.db")
    assert conn.execute("SELECT COUNT(*) FROM chunks WHERE note_id=?", (mem_id,)).fetchone()[0] >= 1
    conn.close()

    CliRunner().invoke(cli.app, ["forget", mem_id, "--yes"])

    conn = sqlite3.connect(h / "indexes" / "kage.db")
    remaining = conn.execute("SELECT COUNT(*) FROM chunks WHERE note_id=?", (mem_id,)).fetchone()[0]
    conn.close()
    assert remaining == 0


def test_forget_deletes_chunks_from_chromadb(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    def embed_down(*a, **kw): raise cli.OllamaUnavailable("down")
    monkeypatch.setattr(cli, "_embed", embed_down)
    mem_id = cli._save("## Intro\n" + "x" * 110, "proj")

    # Collect expected chunk IDs from DB before forget
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    expected_ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE note_id=?", (mem_id,)).fetchall()]
    conn.close()
    assert expected_ids  # sanity check

    deleted = []
    fake_coll = type("C", (), {"delete": lambda self, ids=None: deleted.extend(ids or [])})()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)

    CliRunner().invoke(cli.app, ["forget", mem_id, "--yes"])

    assert sorted(deleted) == sorted(expected_ids)   # chunk IDs, not note ID


def test_forget_does_not_pass_note_id_to_chromadb(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    def embed_down(*a, **kw): raise cli.OllamaUnavailable("down")
    monkeypatch.setattr(cli, "_embed", embed_down)
    mem_id = cli._save("## Intro\n" + "x" * 110, "proj")

    deleted = []
    fake_coll = type("C", (), {"delete": lambda self, ids=None: deleted.extend(ids or [])})()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)

    CliRunner().invoke(cli.app, ["forget", mem_id, "--yes"])

    assert mem_id not in deleted          # note ID must NOT be passed to ChromaDB
    assert all("_c" in cid for cid in deleted)  # all deleted IDs are chunk IDs


# ── _search_vec (Step 7) ────────────────────────────────────────────────────

def _fake_vec_coll(ids, metadatas, distances, project_ids=None, total_count=None):
    """Build a fake ChromaDB collection for _search_vec tests."""
    _project_ids = project_ids
    _total = total_count if total_count is not None else len(ids)

    class Coll:
        def count(self): return _total
        def get(self, where=None, include=None):
            return {"ids": _project_ids if _project_ids is not None else ids}
        def query(self, query_embeddings=None, n_results=None, where=None, include=None):
            return {"ids": [ids], "metadatas": [metadatas], "distances": [distances]}

    return Coll()


def test_search_vec_returns_empty_when_no_docs(monkeypatch):
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: set())
    monkeypatch.setattr(cli, "_get_chroma", lambda: _fake_vec_coll([], [], [], total_count=0))
    assert cli._search_vec([0.1, 0.2], None, 10) == []


def test_search_vec_returns_8_tuples(monkeypatch):
    meta = {"note_id": "n1", "project": "proj", "created_at": "t", "content_path": "p.md",
            "section_title": "Intro", "char_start": 0, "char_end": 100}
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: {"n1"})
    monkeypatch.setattr(cli, "_get_chroma", lambda: _fake_vec_coll(["n1_c0"], [meta], [0.1]))
    result = cli._search_vec([0.1], None, 10)
    assert len(result) == 1
    assert len(result[0]) == 8
    note_id, proj, created, path, score, title, cs, ce = result[0]
    assert note_id == "n1"
    assert proj == "proj"
    assert score == 0.1
    assert title == "Intro"
    assert cs == 0 and ce == 100


def test_search_vec_deduplicates_chunks_by_note(monkeypatch):
    # Two chunks from same note — lower distance (0.1) wins
    meta = {"note_id": "n1", "project": "p", "created_at": "t", "content_path": "f.md",
            "section_title": "A", "char_start": 0, "char_end": 50}
    meta2 = {**meta, "section_title": "B", "char_start": 50, "char_end": 100}
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: {"n1"})
    monkeypatch.setattr(cli, "_get_chroma", lambda: _fake_vec_coll(
        ["n1_c0", "n1_c1"], [meta, meta2], [0.1, 0.3]
    ))
    result = cli._search_vec([0.1], None, 10)
    assert len(result) == 1
    assert result[0][4] == 0.1   # lower distance kept
    assert result[0][5] == "A"   # section from best chunk


def test_search_vec_two_notes_both_returned(monkeypatch):
    # Two chunks from different notes — both survive deduplication
    meta_a = {"note_id": "n1", "project": "p", "created_at": "t", "content_path": "a.md",
              "section_title": "A", "char_start": 0, "char_end": 50}
    meta_b = {"note_id": "n2", "project": "p", "created_at": "t", "content_path": "b.md",
              "section_title": "B", "char_start": 0, "char_end": 50}
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: {"n1", "n2"})
    monkeypatch.setattr(cli, "_get_chroma", lambda: _fake_vec_coll(
        ["n1_c0", "n2_c0"], [meta_a, meta_b], [0.1, 0.2]
    ))
    result = cli._search_vec([0.1], None, 10)
    assert len(result) == 2


def test_search_vec_per_project_count_uses_get_not_count(monkeypatch):
    # count() returns 10, but per-allowed-notes get() returns only 1 chunk id
    # → n_results passed to query must be 1 (min(limit, 1)), not 10
    meta = {"note_id": "n1", "project": "proj", "created_at": "t", "content_path": "f.md",
            "section_title": "", "char_start": 0, "char_end": 50}
    queried_n = []
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: {"n1"})

    class Coll:
        def count(self): return 10
        def get(self, where=None, include=None): return {"ids": ["n1_c0"]}
        def query(self, query_embeddings=None, n_results=None, where=None, include=None):
            queried_n.append(n_results)
            return {"ids": [["n1_c0"]], "metadatas": [[meta]], "distances": [[0.1]]}

    monkeypatch.setattr(cli, "_get_chroma", lambda: Coll())
    cli._search_vec([0.1], "proj", 10)
    assert queried_n[0] == 1   # capped at allowed-note chunk count, not total count


# ── reindex (Step 9) ────────────────────────────────────────────────────────

def _reindex_home(monkeypatch, tmp_path):
    """Set up an isolated in-process kage home and return (home, runner)."""
    h = tmp_path / ".kage"
    _patch_home(monkeypatch, h)
    r = CliRunner()
    r.invoke(cli.app, ["init"])
    return h, r


def test_reindex_embeds_pending_notes(monkeypatch, tmp_path):
    """reindex must embed all chunks with needs_embed=1 and set needs_embed=0."""
    h, r = _reindex_home(monkeypatch, tmp_path)

    added = []
    fake_coll = type("C", (), {
        "add": lambda self, **kw: added.extend(kw["ids"]),
        "upsert": lambda self, **kw: None,
        "count": lambda self: 0,
        "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]},
        "delete": lambda self, **kw: None,
        "metadata": {"embed_model": "nomic-embed-text", "schema_version": "4"},
    })()
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1, 0.2])
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)

    cli._save("note one", "proj", embed=False)
    cli._save("note two", "proj", embed=False)

    conn = sqlite3.connect(h / "indexes" / "kage.db")
    assert conn.execute("SELECT COUNT(*) FROM chunks WHERE needs_embed=1").fetchone()[0] == 2
    conn.close()

    result = r.invoke(cli.app, ["reindex"])
    assert result.exit_code == 0

    conn = sqlite3.connect(h / "indexes" / "kage.db")
    assert conn.execute("SELECT COUNT(*) FROM chunks WHERE needs_embed=1").fetchone()[0] == 0
    conn.close()
    assert len(added) == 2


def test_reindex_idempotent(monkeypatch, tmp_path):
    """Running reindex twice must not error — second run finds nothing to do."""
    h, r = _reindex_home(monkeypatch, tmp_path)

    fake_coll = type("C", (), {
        "add": lambda self, **kw: None,
        "upsert": lambda self, **kw: None,
        "count": lambda self: 0,
        "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]},
        "delete": lambda self, **kw: None,
        "metadata": {"embed_model": "nomic-embed-text", "schema_version": "4"},
    })()
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1, 0.2])
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)

    cli._save("note", "proj", embed=False)

    assert r.invoke(cli.app, ["reindex"]).exit_code == 0
    result = r.invoke(cli.app, ["reindex"])
    assert result.exit_code == 0
    assert "nothing to reindex" in result.output


def test_reindex_force_clears_and_rechunks(monkeypatch, tmp_path):
    """reindex --force must nuke old chunks, rechunk all notes, re-embed everything."""
    h, r = _reindex_home(monkeypatch, tmp_path)

    added = []
    fake_coll = type("C", (), {
        "add": lambda self, **kw: added.extend(kw["ids"]),
        "upsert": lambda self, **kw: None,
        "count": lambda self: 0,
        "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]},
        "delete": lambda self, **kw: None,
        "metadata": {"embed_model": "nomic-embed-text", "schema_version": "4"},
    })()
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1, 0.2])
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)

    cli._save("already embedded note", "proj")

    # force wipes chunks table then rechunks
    result = r.invoke(cli.app, ["reindex", "--force"])
    assert result.exit_code == 0, result.output

    conn = sqlite3.connect(h / "indexes" / "kage.db")
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM chunks WHERE needs_embed=1").fetchone()[0]
    conn.close()
    assert chunk_count >= 1       # rechunked
    assert pending == 0           # all re-embedded
    assert len(added) >= 1        # chunk IDs passed to coll.add


def test_reindex_nothing_to_reindex_exits_cleanly(monkeypatch, tmp_path):
    """reindex on empty DB must exit 0 and report nothing to do."""
    _, r = _reindex_home(monkeypatch, tmp_path)
    result = r.invoke(cli.app, ["reindex"])
    assert result.exit_code == 0
    assert "nothing to reindex" in result.output


def test_reindex_exits_on_ollama_down(monkeypatch, tmp_path):
    """reindex must exit 1 with a human-readable message when Ollama is unreachable."""
    h, r = _reindex_home(monkeypatch, tmp_path)

    fake_coll = type("C", (), {
        "add": lambda self, **kw: None,
        "upsert": lambda self, **kw: None,
        "count": lambda self: 0,
        "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]},
        "delete": lambda self, **kw: None,
        "metadata": {"embed_model": "nomic-embed-text"},
    })()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)

    def embed_down(*a, **kw): raise cli.OllamaUnavailable("down")
    monkeypatch.setattr(cli, "_embed", embed_down)

    cli._save("pending note", "proj", embed=False)

    result = r.invoke(cli.app, ["reindex"])
    assert result.exit_code == 1
    assert "ollama serve" in result.output


# ── Step 12: pitch-mandated expansion ───────────────────────────────────────

def test_vec_search_respects_project_partition(monkeypatch, tmp_path):
    """CRITICAL (pitch-mandated): _search_vec must return only notes from the queried project.

    Wall is enforced by _allowed_note_ids (SQLite pre-filter) → Chroma gets
    where={"note_id": {"$in": allowed_ids}}. Uses real ChromaDB to verify the
    $in filter actually isolates projA notes — not just that the kwarg is passed.
    """
    chroma_dir = tmp_path / "chroma"
    config_path = tmp_path / "config.json"
    config_path.write_text('{"embed_model": "nomic-embed-text"}')

    monkeypatch.setattr(cli, "CHROMA_DIR", chroma_dir)
    monkeypatch.setattr(cli, "CONFIG_PATH", config_path)
    # Wall: projA identity wall returns only note-A; note-B is projB (different identity scope)
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: {"note-A"} if project == "projA" else {"note-B"})

    client = chromadb.PersistentClient(path=str(chroma_dir))
    coll = client.get_or_create_collection(
        "chunks", metadata={"embed_model": "nomic-embed-text", "schema_version": "4"}
    )
    coll.add(
        ids=["note-A_c0"],
        embeddings=[[1.0, 0.0, 0.0]],
        metadatas=[{"note_id": "note-A", "project": "projA", "created_at": "t",
                    "content_path": "memory/note-A.md", "section_title": "", "char_start": 0, "char_end": 10}],
    )
    coll.add(
        ids=["note-B_c0"],
        embeddings=[[0.0, 1.0, 0.0]],
        metadatas=[{"note_id": "note-B", "project": "projB", "created_at": "t",
                    "content_path": "memory/note-B.md", "section_title": "", "char_start": 0, "char_end": 10}],
    )

    result = cli._search_vec([1.0, 0.0, 0.0], "projA", 5)
    ids = [r[0] for r in result]
    assert "note-A" in ids
    assert "note-B" not in ids   # partition wall must hold in the vector path


# ── Step 12: forget vector sync ──────────────────────────────────────────────

def _step12_home(monkeypatch, tmp_path):
    """Shared helper: isolated in-process kage home, fully init'd."""
    h = tmp_path / ".kage"
    _patch_home(monkeypatch, h)
    r = CliRunner()
    r.invoke(cli.app, ["init"])
    return h, r


def test_forget_deletes_vector_index(monkeypatch, tmp_path):
    """forget() must call _get_chroma().delete(ids=[mem_id]) — ghost vectors must not persist."""
    h, r = _step12_home(monkeypatch, tmp_path)

    deleted_ids = []

    class FakeColl:
        metadata = {"embed_model": "nomic-embed-text"}
        def delete(self, ids): deleted_ids.extend(ids)
        def add(self, **kw): pass
        def upsert(self, **kw): pass
        def count(self): return 0
        def query(self, **kw): return {"ids": [[]], "metadatas": [[]], "distances": [[]]}

    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1])
    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeColl())

    mem_id = cli._save("a note to delete", "proj")

    deleted_ids.clear()  # reset — only care about delete from forget, not save
    result = r.invoke(cli.app, ["forget", mem_id, "--yes"])
    assert result.exit_code == 0
    # Step 8: forget deletes chunk IDs (e.g. mem_id_c0), not the note ID itself
    assert any(cid.startswith(mem_id) for cid in deleted_ids)


def test_forget_warns_if_ollama_down(monkeypatch, tmp_path):
    """forget() must succeed even if ChromaDB is unreachable — markdown and DB row must be deleted."""
    h, r = _step12_home(monkeypatch, tmp_path)

    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    mem_id = cli._save("note to forget", "proj")

    def chroma_down(): raise cli.OllamaUnavailable("down")
    monkeypatch.setattr(cli, "_get_chroma", chroma_down)

    result = r.invoke(cli.app, ["forget", mem_id, "--yes"])
    assert result.exit_code == 0
    assert "vector index not updated" in result.output

    assert not (h / "memory" / f"{mem_id}.md").exists()   # markdown gone
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    row = conn.execute("SELECT id FROM memories WHERE id=?", (mem_id,)).fetchone()
    conn.close()
    assert row is None   # DB row gone


# ── Step 12: hybrid search correctness ──────────────────────────────────────

def test_search_hybrid_snippet_for_vec_only_results(monkeypatch, tmp_path):
    """Vec-only results (not returned by FTS) must get a text snippet from markdown, not a float score."""
    h = tmp_path / ".kage"
    config_path = h / "config.json"
    h.mkdir()
    (h / "memory").mkdir()
    import json as _j
    config_path.write_text(_j.dumps({"embeddings": True}))

    monkeypatch.setattr(cli, "KAGE_HOME", h)
    monkeypatch.setattr(cli, "CONFIG_PATH", config_path)

    md_path = h / "memory" / "note-A.md"
    md_path.write_text("---\nid: note-A\n---\n\nNeural networks and transformers for semantic search")

    monkeypatch.setattr(cli, "_search_fts", lambda *a, **kw: [])  # FTS returns nothing
    monkeypatch.setattr(cli, "_search_vec", lambda *a, **kw: [
        ("note-A", "proj", "t", "memory/note-A.md", 0.95, "", 0, 100)  # 8-tuple vec row
    ])
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1])

    result = cli._search("neural networks", None, 5)
    assert len(result) == 1
    assert result[0][0] == "note-A"
    assert isinstance(result[0][4], str)      # must be a text snippet, not a float
    assert "Neural" in result[0][4]           # snippet comes from the markdown body


def test_search_handles_missing_markdown_during_snippet_gen(monkeypatch, tmp_path):
    """If a vec-only result's markdown is deleted, _search must return empty excerpt — not crash."""
    h = tmp_path / ".kage"
    config_path = h / "config.json"
    h.mkdir()
    import json as _j
    config_path.write_text(_j.dumps({"embeddings": True}))

    monkeypatch.setattr(cli, "KAGE_HOME", h)
    monkeypatch.setattr(cli, "CONFIG_PATH", config_path)

    monkeypatch.setattr(cli, "_search_fts", lambda *a, **kw: [])
    monkeypatch.setattr(cli, "_search_vec", lambda *a, **kw: [
        ("note-X", "proj", "t", "memory/note-X.md", 0.9, "", 0, 100)  # markdown does NOT exist
    ])
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1])

    result = cli._search("anything", None, 5)
    assert len(result) == 1
    assert result[0][0] == "note-X"
    assert result[0][4] == ""   # empty excerpt, not an exception


def test_search_hybrid_limit_applies_after_fusion(monkeypatch, tmp_path):
    """_search(q, None, limit=2) must return exactly 2 results after RRF fusion — not limit*2."""
    config_path = tmp_path / "config.json"
    import json as _j
    config_path.write_text(_j.dumps({"embeddings": True}))
    monkeypatch.setattr(cli, "CONFIG_PATH", config_path)

    # 3 shared IDs — no vec-only snippet extraction needed
    shared = [
        ("A", "p", "t", "a.md", "snip-a"),
        ("B", "p", "t", "b.md", "snip-b"),
        ("C", "p", "t", "c.md", "snip-c"),
    ]
    monkeypatch.setattr(cli, "_search_fts", lambda *a, **kw: shared)
    monkeypatch.setattr(cli, "_search_vec", lambda *a, **kw: [
        ("A", "p", "t", "a.md", 0.9, "", 0, 10),
        ("B", "p", "t", "b.md", 0.8, "", 0, 10),
        ("C", "p", "t", "c.md", 0.7, "", 0, 10),
    ])
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1])

    result = cli._search("query", None, 2)
    assert len(result) == 2   # limit=2 applied after fusion of 3 candidates


# ── Step 12: reindex edge cases ──────────────────────────────────────────────

def test_reindex_skips_missing_markdown_file(monkeypatch, tmp_path):
    """reindex must warn and skip notes whose markdown file is gone — not crash, not embed."""
    h, r = _step12_home(monkeypatch, tmp_path)

    added_ids = []

    class FakeColl:
        metadata = {"embed_model": "nomic-embed-text"}
        def add(self, **kw): added_ids.extend(kw["ids"])
        def upsert(self, **kw): added_ids.extend(kw["ids"])
        def count(self): return 0
        def query(self, **kw): return {"ids": [[]], "metadatas": [[]], "distances": [[]]}
        def delete(self, **kw): pass

    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1])
    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeColl())

    mem_id = cli._save("will be orphaned", "proj", embed=False)
    # Delete the markdown file behind kage's back
    (h / "memory" / f"{mem_id}.md").unlink()

    result = r.invoke(cli.app, ["reindex"])
    assert result.exit_code == 0
    # v0.4: _read_section catches OSError and returns "" → "empty section" warning
    assert "skipping" in result.output     # warning printed
    assert not added_ids                   # ChromaDB.add must NOT be called for orphan


def test_reindex_force_uses_add_on_fresh_collection(monkeypatch, tmp_path):
    """reindex --force wipes the collection first, then uses add() (not upsert) — no duplicates possible."""
    h, r = _step12_home(monkeypatch, tmp_path)

    calls = {"add": 0, "upsert": 0}

    class FakeColl:
        metadata = {"embed_model": "nomic-embed-text", "schema_version": "4"}
        def add(self, **kw): calls["add"] += 1
        def upsert(self, **kw): calls["upsert"] += 1
        def count(self): return 0
        def query(self, **kw): return {"ids": [[]], "metadatas": [[]], "distances": [[]]}
        def delete(self, **kw): pass

    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1])
    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeColl())

    cli._save("already embedded note", "proj")

    calls["add"] = calls["upsert"] = 0  # reset after save
    result = r.invoke(cli.app, ["reindex", "--force"])
    assert result.exit_code == 0
    assert calls["add"] >= 1     # force uses add() on the wiped-then-fresh collection
    assert calls["upsert"] == 0  # upsert not needed


# ── Step 12: RRF correctness ─────────────────────────────────────────────────

def test_rrf_fuse_preserves_fts_row_for_shared_id():
    """When both lists share an ID, the FTS row (with snippet) must win over the vec row (float score)."""
    fts = [("A", "p", "t", "a.md", "fts-snippet")]
    vec = [("A", "p", "t", "a.md", 0.9)]

    result = cli._rrf_fuse(fts, vec, k=60)
    assert len(result) == 1                      # deduplicated
    assert result[0][4] == "fts-snippet"         # FTS row wins — snippet preserved, not float


# ── Step 12: ask robustness ──────────────────────────────────────────────────

def test_ask_returns_model_answer_when_no_notes_match(monkeypatch, tmp_path):
    """ask must call the model and show its answer even when search returns no matching notes."""
    h, r = _step12_home(monkeypatch, tmp_path)

    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("note about cats", "proj")  # unrelated note — won't match query

    def fake_post(url, payload, headers=None, timeout=120):
        return {"response": "I have no idea about quantum physics"}

    monkeypatch.setattr(cli, "_post_json", fake_post)

    result = r.invoke(cli.app, ["ask", "quantum physics", "-p", "proj"])
    assert result.exit_code == 0
    assert "quantum physics" in result.output or "no idea" in result.output


# ── hybrid retrieval ────────────────────────────────────────────────────────

def test_rrf_fuse_merges_correctly():
    # B tops BOTH lists → highest RRF score
    # A is second in both → clear second place
    # C only in fts, D only in vec → rank-penalised, must rank below A
    fts = [("B", "p", "t", "b.md", "snip"), ("A", "p", "t", "a.md", "snip"), ("C", "p", "t", "c.md", "snip")]
    vec = [("B", "p", "t", "b.md", 0.9),   ("A", "p", "t", "a.md", 0.8),   ("D", "p", "t", "d.md", 0.7)]

    result = cli._rrf_fuse(fts, vec, k=60)
    ids = [r[0] for r in result]

    assert ids[0] == "B"              # tops both lists — unambiguous winner
    assert ids[1] == "A"              # second in both — unambiguous second
    assert len(result) == 4           # union: A B C D, no duplicates
    assert len(set(ids)) == len(ids)  # no duplicate IDs in output
    assert result[0][0] == "B"        # full row tuple preserved, not just ID


# ── _search / ask normalization (Step 9) ────────────────────────────────────

def test_search_embeddings_off_returns_8tuples(monkeypatch):
    monkeypatch.setattr(cli, "_config", lambda: {"embeddings": False})
    monkeypatch.setattr(cli, "_search_fts", lambda *a, **kw: [("id1","proj","2024","path/x.md","snippet")])
    result = cli._search("q", None, 5)
    assert len(result) == 1
    assert len(result[0]) == 8
    assert result[0][5] is None and result[0][6] is None and result[0][7] is None


def test_search_fts_rows_padded_to_8tuples(monkeypatch):
    monkeypatch.setattr(cli, "_search_fts", lambda *a, **kw: [("id1","proj","2024","path/x.md","snip")])
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1])
    monkeypatch.setattr(cli, "_search_vec", lambda *a, **kw: [])
    result = cli._search("q", None, 5)
    assert len(result[0]) == 8
    assert result[0][5] is None and result[0][6] is None and result[0][7] is None


def test_search_shared_id_fts_row_gets_section_fields_from_vec(monkeypatch):
    # When a note appears in both FTS and vec, the fused row should carry
    # section_title/char_start/char_end from the vec row (not Nones).
    fts_row = ("id1", "proj", "2024", "path/x.md", "fts snippet")
    vec_row = ("id1", "proj", "2024", "path/x.md", 0.9, "Layer 3e", 100, 500)
    monkeypatch.setattr(cli, "_search_fts", lambda *a, **kw: [fts_row])
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1])
    monkeypatch.setattr(cli, "_search_vec", lambda *a, **kw: [vec_row])
    result = cli._search("q", None, 5)
    assert len(result) == 1
    row = result[0]
    assert row[4] == "fts snippet"     # FTS snippet preserved at [4]
    assert row[5] == "Layer 3e"        # section_title from vec
    assert row[6] == 100               # char_start from vec
    assert row[7] == 500               # char_end from vec


def test_search_vec_only_row_excerpt_at_index4(monkeypatch):
    monkeypatch.setattr(cli, "_search_fts", lambda *a, **kw: [])
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1])
    monkeypatch.setattr(cli, "_search_vec", lambda *a, **kw: [("id1","proj","2024","p/x.md",0.42,"Intro",0,50)])
    monkeypatch.setattr(cli, "_read_body", lambda *a, **kw: "hello world")
    result = cli._search("q", None, 5)
    assert isinstance(result[0][4], str)
    assert result[0][4] == "hello world"
    assert result[0][5] == "Intro"
    assert result[0][6] == 0
    assert result[0][7] == 50


def test_search_ollama_unavailable_fallback_returns_8tuples(monkeypatch):
    monkeypatch.setattr(cli, "_search_fts", lambda *a, **kw: [("id1","proj","2024","p/x.md","snip")])
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    result = cli._search("q", None, 5)
    assert len(result) == 1
    assert len(result[0]) == 8
    assert result[0][5] is None


def test_ask_sources_block_appears(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("## Intro\n" + "x" * 110, "proj")
    monkeypatch.setattr(cli, "_post_json", lambda *a, **kw: {"response": "mock answer"})
    r = CliRunner()
    result = r.invoke(cli.app, ["ask", "Intro", "-p", "proj"])
    assert "Sources:" in result.output


def test_ask_no_sources_suppresses_block(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("## Intro\n" + "x" * 110, "proj")
    monkeypatch.setattr(cli, "_post_json", lambda *a, **kw: {"response": "mock answer"})
    r = CliRunner()
    result = r.invoke(cli.app, ["ask", "Intro", "-p", "proj", "--no-sources"])
    assert "Sources:" not in result.output


def test_ask_uses_read_section_when_char_offsets_present(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [("id1","proj","2024","p/x.md","snip","Intro",5,50)])
    monkeypatch.setattr(cli, "_read_section", lambda path, cs, ce: calls.append((path, cs, ce)) or "section text here")
    captured = []
    def fake_post(url, payload, **kw):
        captured.append(payload)
        return {"response": "x"}
    monkeypatch.setattr(cli, "_post_json", fake_post)
    monkeypatch.setattr(cli, "_require_init", lambda: None)
    monkeypatch.setattr(cli, "_config", lambda: {})
    r = CliRunner()
    r.invoke(cli.app, ["ask", "what is intro"])
    assert calls
    assert any("section text here" in str(p) for p in captured)


def test_ask_uses_read_body_when_no_char_offsets(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [("id1","proj","2024","p/x.md","snip",None,None,None)])
    monkeypatch.setattr(cli, "_read_body", lambda path: calls.append(path) or "body text")
    captured = []
    def fake_post(url, payload, **kw):
        captured.append(payload)
        return {"response": "x"}
    monkeypatch.setattr(cli, "_post_json", fake_post)
    monkeypatch.setattr(cli, "_require_init", lambda: None)
    monkeypatch.setattr(cli, "_config", lambda: {})
    r = CliRunner()
    r.invoke(cli.app, ["ask", "what"])
    assert calls
    assert any("body text" in str(p) for p in captured)


# ── doctor (Step 10) ────────────────────────────────────────────────────────

def test_doctor_chunks_not_notes_in_pending_message(monkeypatch, tmp_path):
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("note one", "proj")
    cli._save("note two", "proj")
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    result = CliRunner().invoke(cli.app, ["doctor"])
    assert "chunk(s) not yet embedded" in result.output
    assert "note(s) not yet embedded" not in result.output


def test_doctor_schema_version_shown_when_chroma_ok(monkeypatch, tmp_path):
    _save_home(monkeypatch, tmp_path)
    fake_collection = type("C", (), {
        "count": lambda self: 0,
        "get": lambda self, **kw: {"ids": []},
        "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]},
        "metadata": {"embed_model": "nomic-embed-text", "schema_version": "4"},
    })()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_collection)
    result = CliRunner().invoke(cli.app, ["doctor"])
    assert "schema v4" in result.output
    assert "nomic-embed-text" in result.output


def test_doctor_no_schema_line_when_chroma_raises(monkeypatch, tmp_path):
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    result = CliRunner().invoke(cli.app, ["doctor"])
    assert "schema v" not in result.output
    assert "vector index" not in result.output


# ── _call_cloud (Cycle 5 Step 1) ──────────────────────────────────────────

def test_call_cloud_unknown_provider(monkeypatch):
    with pytest.raises(cli.CloudError) as e:
        cli._call_cloud("no_such", "sys", "msg", {})
    assert "Unknown provider" in str(e.value)


def test_call_cloud_missing_env_var(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(cli.CloudError) as e:
        cli._call_cloud("openai", "sys", "msg", {})
    assert "OPENAI_API_KEY" in str(e.value)


# Cycle 12 Slice 1: cloud dispatch moved to kage.cloud.CloudClient, so these provider-
# dispatch tests now patch cloud._post_json (the http call site in cloud.py). They still
# enter via cli._call_cloud (a call-time forwarder → runtime.cloud.complete).
def test_call_cloud_claude_uses_anthropic_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls = []
    monkeypatch.setattr(cloud, "_post_json", lambda url, payload, **kw: calls.append((url, kw)) or {"content": [{"text": "ans"}]})
    result = cli._call_cloud("claude", "sys", "msg", {})
    assert result == "ans"
    assert "anthropic.com" in calls[0][0]
    assert calls[0][1]["headers"]["x-api-key"] == "test-key"


def test_call_cloud_openai_uses_bearer_auth(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "oai-key")
    calls = []
    monkeypatch.setattr(cloud, "_post_json", lambda url, payload, **kw: calls.append((url, kw)) or {"choices": [{"message": {"content": "ans"}}]})
    result = cli._call_cloud("openai", "sys", "msg", {})
    assert result == "ans"
    assert "openai.com/v1/chat/completions" in calls[0][0]
    assert calls[0][1]["headers"]["Authorization"] == "Bearer oai-key"


def test_call_cloud_groq_url_has_v1_path(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    calls = []
    monkeypatch.setattr(cloud, "_post_json", lambda url, payload, **kw: calls.append(url) or {"choices": [{"message": {"content": "ans"}}]})
    cli._call_cloud("groq", "sys", "msg", {})
    assert calls[0] == "https://api.groq.com/openai/v1/chat/completions"


def test_call_cloud_perplexity_url_has_no_v1(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "ppl-key")
    calls = []
    monkeypatch.setattr(cloud, "_post_json", lambda url, payload, **kw: calls.append(url) or {"choices": [{"message": {"content": "ans"}}]})
    cli._call_cloud("perplexity", "sys", "msg", {})
    assert calls[0] == "https://api.perplexity.ai/chat/completions"


def test_call_cloud_gemini_key_in_url(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    calls = []
    monkeypatch.setattr(cloud, "_post_json", lambda url, payload, **kw: calls.append(url) or {"candidates": [{"content": {"parts": [{"text": "ans"}]}}]})
    result = cli._call_cloud("gemini", "sys", "msg", {})
    assert result == "ans"
    assert "?key=gem-key" in calls[0]
    assert "generateContent" in calls[0]


def test_call_cloud_gemini_safety_block_raises(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.setattr(cloud, "_post_json", lambda *a, **kw: {"candidates": [{}]})
    with pytest.raises(cli.CloudError):
        cli._call_cloud("gemini", "sys", "msg", {})


def test_call_cloud_user_config_partial_override_keeps_defaults(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "oai-key")
    calls = []
    monkeypatch.setattr(cloud, "_post_json", lambda url, payload, **kw: calls.append(payload) or {"choices": [{"message": {"content": "ans"}}]})
    cfg = {"providers": {"openai": {"model": "gpt-4o-mini"}}}
    cli._call_cloud("openai", "sys", "msg", cfg)
    assert calls[0]["model"] == "gpt-4o-mini"


def test_call_cloud_network_error_raises_cloud_error(monkeypatch):
    import urllib.error
    monkeypatch.setenv("OPENAI_API_KEY", "oai-key")
    def bad_post(*a, **kw): raise urllib.error.URLError("timeout")
    monkeypatch.setattr(cloud, "_post_json", bad_post)
    with pytest.raises(cli.CloudError, match="request failed"):
        cli._call_cloud("openai", "sys", "msg", {})


# ── ask --provider (Cycle 5 Step 2) ──────────────────────────────────────

def test_ask_cloud_default_provider_is_claude(monkeypatch, tmp_path):
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])
    captured = []
    monkeypatch.setattr(cli, "_call_cloud", lambda name, *a, **kw: captured.append(name) or "ans")
    CliRunner().invoke(cli.app, ["ask", "q", "--cloud"])
    assert captured[0] == "claude"


def test_ask_cloud_provider_flag_overrides_default(monkeypatch, tmp_path):
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])
    captured = []
    monkeypatch.setattr(cli, "_call_cloud", lambda name, *a, **kw: captured.append(name) or "ans")
    CliRunner().invoke(cli.app, ["ask", "q", "--cloud", "--provider", "openai"])
    assert captured[0] == "openai"


def test_ask_cloud_config_provider_used_when_no_flag(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    (h / "config.json").write_text('{"cloud_provider": "groq"}')
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])
    captured = []
    monkeypatch.setattr(cli, "_call_cloud", lambda name, *a, **kw: captured.append(name) or "ans")
    CliRunner().invoke(cli.app, ["ask", "q", "--cloud"])
    assert captured[0] == "groq"


def test_ask_cloud_flag_overrides_config_provider(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    (h / "config.json").write_text('{"cloud_provider": "groq"}')
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])
    captured = []
    monkeypatch.setattr(cli, "_call_cloud", lambda name, *a, **kw: captured.append(name) or "ans")
    CliRunner().invoke(cli.app, ["ask", "q", "--cloud", "--provider", "gemini"])
    assert captured[0] == "gemini"


def test_ask_cloud_error_exits_nonzero(monkeypatch, tmp_path):
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: (_ for _ in ()).throw(cli.CloudError("bad key")))
    r = CliRunner().invoke(cli.app, ["ask", "q", "--cloud"])
    assert r.exit_code == 1


def test_ask_cloud_status_line_shows_model_and_provider(monkeypatch, tmp_path):
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: "ans")
    r = CliRunner().invoke(cli.app, ["ask", "q", "--cloud", "--provider", "openai"])
    assert "gpt-4o" in r.output
    assert "openai" in r.output


def test_ask_local_path_unchanged(monkeypatch, tmp_path):
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])
    calls = []
    monkeypatch.setattr(cli, "_post_json", lambda url, payload, **kw: calls.append(url) or {"response": "local ans"})
    r = CliRunner().invoke(cli.app, ["ask", "q"])
    assert any("11434" in c for c in calls)
    assert "local ans" in r.output


# ── doctor cloud providers (Cycle 5 Step 3) ──────────────────────────────────

def test_doctor_cloud_key_set_shows_checkmark(monkeypatch, tmp_path):
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert "✓ claude" in r.output
    assert "· openai" in r.output


def test_doctor_cloud_all_missing_shows_dots(monkeypatch, tmp_path):
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "PERPLEXITY_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert r.output.count("· ") >= 5


def test_doctor_cloud_user_provider_appears(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    (h / "config.json").write_text('{"providers": {"myprovider": {"api_key_env": "MY_CUSTOM_KEY"}}}')
    monkeypatch.delenv("MY_CUSTOM_KEY", raising=False)
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert "myprovider" in r.output
    assert "MY_CUSTOM_KEY" in r.output


def test_doctor_cloud_user_provider_key_set(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    (h / "config.json").write_text('{"providers": {"myprovider": {"api_key_env": "MY_CUSTOM_KEY"}}}')
    monkeypatch.setenv("MY_CUSTOM_KEY", "val")
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert "✓ myprovider" in r.output


# ── status cloud model line (Cycle 5 Step 4) ─────────────────────────────────

def test_status_cloud_model_shows_provider_name(monkeypatch, tmp_path):
    _save_home(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli.app, ["status"])
    assert "claude-sonnet-4-6 via claude" in r.output


def test_status_cloud_model_uses_config_provider(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    (h / "config.json").write_text('{"cloud_provider": "groq"}')
    r = CliRunner().invoke(cli.app, ["status"])
    assert "llama-3.3-70b-versatile via groq" in r.output


def test_status_cloud_model_user_model_override(monkeypatch, tmp_path):
    h = _save_home(monkeypatch, tmp_path)
    (h / "config.json").write_text('{"cloud_provider": "openai", "providers": {"openai": {"model": "gpt-4o-mini"}}}')
    r = CliRunner().invoke(cli.app, ["status"])
    assert "gpt-4o-mini via openai" in r.output


# ── MCP server (Cycle 6) ──────────────────────────────────────────────────────

mcp_server = pytest.importorskip("kage.mcp_server", reason="mcp[cli] not installed")


def _mcp_home(monkeypatch, tmp_path):
    """Isolated in-process kage home for MCP tool tests."""
    h = tmp_path / ".kage"
    _patch_home(monkeypatch, h)
    CliRunner().invoke(cli.app, ["init"])
    return h


def test_mcp_recall_returns_list(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    cli._save("the eiffel tower is in paris", "test", embed=False)
    results = mcp_server.kage_recall("eiffel")
    assert isinstance(results, list)
    assert len(results) >= 1
    assert results[0]["id"]
    assert "excerpt" in results[0]


def test_mcp_recall_partition_filter(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    cli._save("alpha shared word", "projA", embed=False)
    cli._save("beta shared word", "projB", embed=False)

    a = mcp_server.kage_recall("shared", project="projA")
    assert len(a) >= 1
    assert all(r["project"] == "projA" for r in a)
    assert not any(r["project"] == "projB" for r in a)

    b = mcp_server.kage_recall("shared", project="projB")
    assert len(b) >= 1
    assert all(r["project"] == "projB" for r in b)
    assert not any(r["project"] == "projA" for r in b)


def test_mcp_recall_no_project_returns_all(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    cli._save("alpha shared word", "projA", embed=False)
    cli._save("beta shared word", "projB", embed=False)
    results = mcp_server.kage_recall("shared", project=None)
    projects = {r["project"] for r in results}
    assert "projA" in projects
    assert "projB" in projects


def test_mcp_remember_write_gate_off_by_default(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    result = mcp_server.kage_remember("test note")
    assert result["saved"] is False
    assert "writes disabled" in result["reason"]
    assert result["id"] is None


def test_mcp_remember_write_gate_on(monkeypatch, tmp_path):
    import json as _j
    h = _mcp_home(monkeypatch, tmp_path)
    cfg = _j.loads((h / "config.json").read_text())
    cfg["mcp_allow_writes"] = True
    (h / "config.json").write_text(_j.dumps(cfg, indent=2))

    result = mcp_server.kage_remember("MCP saved note", project="test")
    assert result["saved"] is True
    assert result["id"]
    assert result["reason"] == "saved"


def test_mcp_ask_local_returns_answer(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    cli._save("the eiffel tower is in paris", "test", embed=False)

    monkeypatch.setattr(cli, "_post_json", lambda url, payload, **kw: {"response": "Paris."})

    result = asyncio.run(mcp_server.kage_ask("where is the eiffel tower"))
    assert result["answer"] == "Paris."
    assert isinstance(result["sources"], list)
    assert result["provider"].startswith("local:")


def test_mcp_ask_with_provider(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    cli._save("dogs are mammals", "test", embed=False)

    monkeypatch.setattr(cli, "_call_cloud", lambda name, sys, msg, cfg: "Yes, dogs are mammals.")

    result = asyncio.run(mcp_server.kage_ask("are dogs mammals", provider="claude"))
    assert result["answer"] == "Yes, dogs are mammals."
    assert result["provider"] == "claude"


def test_mcp_ask_cloud_error_returns_error_message(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)

    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: (_ for _ in ()).throw(cli.CloudError("bad key")))

    result = asyncio.run(mcp_server.kage_ask("q", provider="openai"))
    assert "bad key" in result["answer"]
    assert result["sources"] == []


def test_mcp_status_correct_count_and_projects(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    cli._save("note one", "projA", embed=False)
    cli._save("note two", "projA", embed=False)
    cli._save("note three", "projB", embed=False)

    result = mcp_server.kage_status()
    assert result["memory_count"] == 3
    assert "projA" in result["projects"]
    assert "projB" in result["projects"]
    assert "model" in result
    assert result["disk_free"].endswith("GB")


def test_mcp_status_empty_store(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    result = mcp_server.kage_status()
    assert result["memory_count"] == 0
    assert result["projects"] == []


def test_doctor_shows_mcp_check(monkeypatch, tmp_path):
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert "✓ MCP server (mcp[cli])" in r.output


def test_mcp_remember_write_gate_on_persists_to_disk(monkeypatch, tmp_path):
    import json as _j, sqlite3 as _sq
    h = _mcp_home(monkeypatch, tmp_path)
    cfg = _j.loads((h / "config.json").read_text())
    cfg["mcp_allow_writes"] = True
    (h / "config.json").write_text(_j.dumps(cfg, indent=2))

    result = mcp_server.kage_remember("MCP persisted note", project="mcp-test")
    assert result["saved"] is True
    mem_id = result["id"]

    assert (h / "memory" / f"{mem_id}.md").exists()
    conn = _sq.connect(h / "indexes" / "kage.db")
    row = conn.execute("SELECT project FROM memories WHERE id=?", (mem_id,)).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "mcp-test"


def test_mcp_ask_uses_read_section_when_char_offsets_present(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [
        ("id1", "proj", "2024", "memory/n.md", "snip", "Intro", 5, 50)
    ])
    read_calls = []
    monkeypatch.setattr(cli, "_read_section",
                        lambda path, cs, ce: read_calls.append((path, cs, ce)) or "section text")
    monkeypatch.setattr(cli, "_post_json", lambda *a, **kw: {"response": "answer"})

    result = asyncio.run(mcp_server.kage_ask("what is intro"))
    assert read_calls                     # _read_section was called (line 63)
    assert result["answer"] == "answer"
    assert "id1" in result["sources"]


def test_mcp_ask_handles_missing_markdown_gracefully(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    # Search returns a hit with no char offsets; the markdown file doesn't exist
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [
        ("id1", "proj", "2024", "memory/gone.md", "snip", None, None, None)
    ])
    monkeypatch.setattr(cli, "_post_json", lambda *a, **kw: {"response": "fallback answer"})

    result = asyncio.run(mcp_server.kage_ask("q"))      # _read_body raises OSError → text = "" → no source
    assert result["answer"] == "fallback answer"
    assert result["sources"] == []        # OSError path (lines 67-68) — no source added


def test_mcp_ask_local_unavailable_returns_error_dict(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])

    import urllib.error
    monkeypatch.setattr(cli, "_post_json",
                        lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError("down")))

    result = asyncio.run(mcp_server.kage_ask("q"))     # local Ollama down — lines 100-101
    assert result["answer"].startswith("Local model unavailable:")
    assert result["sources"] == []
    assert result["provider"] == "local"


# ── Coverage gap fill: cli.py 82% → 100% ────────────────────────────────────

# ── init edge cases ──────────────────────────────────────────────────────────

def test_init_rerun_shows_config_existed(monkeypatch, tmp_path):
    """Line 101: re-running init on an existing store must mark config as 'exists'."""
    h = tmp_path / ".kage"
    _patch_home(monkeypatch, h)
    r = CliRunner()
    r.invoke(cli.app, ["init"])          # first run — creates everything
    result = r.invoke(cli.app, ["init"]) # second run — config already exists
    assert result.exit_code == 0
    assert "exists" in result.output     # CONFIG_PATH was appended to existed list


def test_init_migration_adds_needs_embed_in_process(monkeypatch, tmp_path):
    """Line 126: conn.commit() after ALTER TABLE must be called when migration succeeds."""
    h = tmp_path / ".kage"
    (h / "indexes").mkdir(parents=True)
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    conn.executescript("""
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, content_path TEXT NOT NULL,
            project TEXT, created_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE memory_fts USING fts5(id UNINDEXED, body);
    """)
    conn.close()
    _patch_home(monkeypatch, h)
    result = CliRunner().invoke(cli.app, ["init"])
    assert result.exit_code == 0
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(memories)")]
    conn.close()
    assert "needs_embed" in cols


# ── _require_init ─────────────────────────────────────────────────────────────

def test_require_init_exits_when_db_missing(monkeypatch, tmp_path):
    """Lines 148-149: any command must exit 1 with 'kage init' hint if DB doesn't exist."""
    h = tmp_path / "empty"
    _patch_home(monkeypatch, h)
    r = CliRunner().invoke(cli.app, ["status"])
    assert r.exit_code == 1
    assert "kage init" in r.output


# ── _search_fts ───────────────────────────────────────────────────────────────

def test_search_fts_returns_empty_for_blank_query():
    """Line 291: _search_fts with no real terms must return [] without touching the DB."""
    assert cli._search_fts("", None, 5) == []
    assert cli._search_fts("   ", None, 5) == []


# ── _config ───────────────────────────────────────────────────────────────────

def test_config_returns_empty_dict_when_file_missing(monkeypatch, tmp_path):
    """_config must return {} when config.json doesn't exist."""
    monkeypatch.setattr(runtime, "config", Config(tmp_path / "nonexistent"))
    assert cli._config() == {}


def test_config_returns_empty_dict_on_invalid_json(monkeypatch, tmp_path):
    """_config must return {} on JSON parse error."""
    bad_home = tmp_path / "bad"
    bad_home.mkdir()
    (bad_home / "config.json").write_text("not json {{{")
    monkeypatch.setattr(runtime, "config", Config(bad_home))
    assert cli._config() == {}


# ── _call_cloud unknown type ───────────────────────────────────────────────────

def test_call_cloud_unknown_provider_type_raises(monkeypatch):
    """Line 436: user-defined provider with an unknown 'type' must raise CloudError."""
    monkeypatch.setenv("CUSTOM_KEY", "x")
    cfg = {"providers": {"custom": {"type": "magic-type", "api_key_env": "CUSTOM_KEY", "model": "m"}}}
    with pytest.raises(cli.CloudError, match="Unknown provider type"):
        cli._call_cloud("custom", "sys", "msg", cfg)


# ── _embed HTTP errors ────────────────────────────────────────────────────────

def test_embed_raises_on_http_400(monkeypatch):
    """Lines 466-467: HTTP 400 from embed endpoint must raise OllamaUnavailable with 'HTTP 400'."""
    import urllib.error as _ue
    err = _ue.HTTPError(url="http://x", code=400, msg="Bad Request", hdrs={}, fp=None)
    monkeypatch.setattr(_embed_module, "_post_json", lambda *a, **kw: (_ for _ in ()).throw(err))
    with pytest.raises(cli.OllamaUnavailable, match="HTTP 400"):
        cli._embed("test")


def test_embed_raises_on_non_400_http_error(monkeypatch):
    """Line 468: non-400 HTTPError must re-raise as OllamaUnavailable."""
    import urllib.error as _ue
    err = _ue.HTTPError(url="http://x", code=500, msg="Server Error", hdrs={}, fp=None)
    monkeypatch.setattr(_embed_module, "_post_json", lambda *a, **kw: (_ for _ in ()).throw(err))
    with pytest.raises(cli.OllamaUnavailable):
        cli._embed("test")


# ── _ollama_status ────────────────────────────────────────────────────────────

def test_ollama_status_unreachable(monkeypatch):
    """Lines 549-550: URLError must return (False, 'Ollama not reachable')."""
    import urllib.request as _req, urllib.error as _ue
    monkeypatch.setattr(_req, "urlopen", lambda *a, **kw: (_ for _ in ()).throw(_ue.URLError("refused")))
    ok, msg = cli._ollama_status({}, "qwen3:14b")
    assert ok is False
    assert "not reachable" in msg


def test_ollama_status_model_not_pulled(monkeypatch):
    """Line 553: Ollama reachable but model absent must return (False, '...not pulled')."""
    import urllib.request as _req, json as _j

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return _j.dumps({"models": [{"name": "other:latest"}]}).encode()

    monkeypatch.setattr(_req, "urlopen", lambda *a, **kw: _FakeResp())
    ok, msg = cli._ollama_status({}, "qwen3:14b")
    assert ok is False
    assert "not pulled" in msg


# ── remember: decline confirm ─────────────────────────────────────────────────

def test_remember_decline_confirm_discards_note(monkeypatch, tmp_path):
    """Lines 569-570: declining the confirm prompt must print 'Discarded' and save nothing."""
    h = _save_home(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli.app, ["remember", "secret note", "-p", "x"], input="n\n")
    assert "Discarded" in r.output
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    conn.close()
    assert count == 0


# ── import_ edge cases ────────────────────────────────────────────────────────

def test_import_non_folder_exits_1(monkeypatch, tmp_path):
    """Lines 587-588: import_ on a regular file must exit 1 with 'Not a folder'."""
    _save_home(monkeypatch, tmp_path)
    f = tmp_path / "file.txt"
    f.write_text("hello")
    r = CliRunner().invoke(cli.app, ["import", str(f)])
    assert r.exit_code == 1
    assert "Not a folder" in r.output


def test_import_dry_run_lists_files_writes_nothing(monkeypatch, tmp_path):
    """Lines 596-600: --dry-run must list files but write nothing to the store."""
    h = _save_home(monkeypatch, tmp_path)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("note a content")
    (notes / "b.md").write_text("note b content")
    r = CliRunner().invoke(cli.app, ["import", str(notes), "--dry-run"])
    assert r.exit_code == 0
    assert "Dry run" in r.output
    assert "no changes made" in r.output
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    conn.close()
    assert count == 0


def test_import_empty_folder_exits_cleanly(monkeypatch, tmp_path):
    """Lines 603-604: import_ with no .md/.txt files must report 'No .md/.txt files' and exit 0."""
    _save_home(monkeypatch, tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    r = CliRunner().invoke(cli.app, ["import", str(empty)])
    assert r.exit_code == 0
    assert "No .md/.txt files" in r.output


def test_import_skips_blank_files(monkeypatch, tmp_path):
    """Line 610: import_ must skip files whose body is only whitespace."""
    h = _save_home(monkeypatch, tmp_path)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "blank.md").write_text("   \n   ")
    (notes / "real.md").write_text("actual content here")
    r = CliRunner().invoke(cli.app, ["import", str(notes)])
    assert r.exit_code == 0
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    conn.close()
    assert count == 1  # blank file skipped


# ── reindex --force edge cases ────────────────────────────────────────────────

def _fake_force_coll():
    """Minimal fake ChromaDB collection for reindex --force tests."""
    return type("C", (), {
        "add": lambda self, **kw: None,
        "count": lambda self: 0,
        "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]},
        "metadata": {"embed_model": "nomic-embed-text", "schema_version": "4"},
        "delete": lambda self, **kw: None,
    })()


def test_reindex_force_empty_db_reports_nothing(monkeypatch, tmp_path):
    """Lines 645-646: reindex --force on empty DB must print 'nothing to reindex' and exit 0."""
    _, r = _reindex_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_get_chroma", lambda: _fake_force_coll())
    result = r.invoke(cli.app, ["reindex", "--force"])
    assert result.exit_code == 0
    assert "nothing to reindex" in result.output


def test_reindex_force_ollama_down_exits_1(monkeypatch, tmp_path):
    """Lines 650-652: reindex --force must exit 1 when _get_chroma raises OllamaUnavailable."""
    h, r = _reindex_home(monkeypatch, tmp_path)
    cli._save("a note", "proj", embed=False)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    result = r.invoke(cli.app, ["reindex", "--force"])
    assert result.exit_code == 1
    assert "ollama serve" in result.output


def test_reindex_force_skips_missing_markdown(monkeypatch, tmp_path):
    """Lines 658-660: reindex --force must warn and skip a note whose markdown file is gone."""
    h, r = _reindex_home(monkeypatch, tmp_path)
    added = []
    fake_coll = type("C", (), {
        "add": lambda self, **kw: added.extend(kw["ids"]),
        "count": lambda self: 0,
        "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]},
        "metadata": {"embed_model": "nomic-embed-text", "schema_version": "4"},
        "delete": lambda self, **kw: None,
    })()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1])
    mem_id = cli._save("orphaned note", "proj", embed=False)
    (h / "memory" / f"{mem_id}.md").unlink()   # delete the markdown behind kage's back
    result = r.invoke(cli.app, ["reindex", "--force"])
    assert result.exit_code == 0
    assert "skipping" in result.output
    assert not added   # nothing embedded — the orphaned note was skipped


def test_reindex_force_chunk_insert_failure_propagates(monkeypatch, tmp_path):
    """Lines 674-676: reindex --force must rollback and re-raise if chunk INSERT fails."""
    h, r = _reindex_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_get_chroma", lambda: _fake_force_coll())
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1])
    # Save the note FIRST (with valid _chunk_note), then patch to return NULL char_start.
    # NULL char_start violates NOT NULL → INSERT raises sqlite3.IntegrityError during reindex.
    cli._save("a note", "proj", embed=False)
    monkeypatch.setattr(cli, "_chunk_note", lambda body: [{"title": "", "char_start": None, "char_end": None}])
    result = r.invoke(cli.app, ["reindex", "--force"])
    # The exception propagates out of the command — CliRunner captures it
    assert result.exit_code != 0 or result.exception is not None


def test_reindex_force_embed_raises_exits_1(monkeypatch, tmp_path):
    """Lines 684-686: reindex --force must exit 1 when _embed raises OllamaUnavailable."""
    h, r = _reindex_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_get_chroma", lambda: _fake_force_coll())
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("a note", "proj", embed=False)
    result = r.invoke(cli.app, ["reindex", "--force"])
    assert result.exit_code == 1
    assert "ollama serve" in result.output


# ── reindex non-force: _get_chroma raises ─────────────────────────────────────

def test_reindex_non_force_ollama_down_exits_1(monkeypatch, tmp_path):
    """Lines 728-730: reindex must exit 1 when _get_chroma raises OllamaUnavailable."""
    h, r = _reindex_home(monkeypatch, tmp_path)
    cli._save("a pending note", "proj", embed=False)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    result = r.invoke(cli.app, ["reindex"])
    assert result.exit_code == 1
    assert "ollama serve" in result.output


# ── list_ command ─────────────────────────────────────────────────────────────

def test_list_empty_store_shows_nothing_saved(monkeypatch, tmp_path):
    """Lines 789-792: list_ on an empty store must print 'Nothing saved yet'."""
    _save_home(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli.app, ["list"])
    assert r.exit_code == 0
    assert "Nothing saved yet" in r.output


def test_list_shows_notes_with_preview(monkeypatch, tmp_path):
    """Lines 795-801: list_ must show each note's preview, project, and ID."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("the quick brown fox", "myproj", embed=False)
    r = CliRunner().invoke(cli.app, ["list"])
    assert r.exit_code == 0
    assert "quick brown fox" in r.output
    assert "myproj" in r.output


def test_list_truncates_long_preview(monkeypatch, tmp_path):
    """Lines 798-799: list_ must truncate previews longer than 70 chars with '…'."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("x" * 100, "proj", embed=False)
    r = CliRunner().invoke(cli.app, ["list"])
    assert "…" in r.output


def test_list_with_project_filter(monkeypatch, tmp_path):
    """list_ -p must only show notes from that project."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("alpha content", "projA", embed=False)
    cli._save("beta content", "projB", embed=False)
    r = CliRunner().invoke(cli.app, ["list", "-p", "projA"])
    assert r.exit_code == 0
    assert "alpha" in r.output
    assert "beta" not in r.output


def test_list_project_filter_no_results(monkeypatch, tmp_path):
    """list_ -p with no matching notes shows 'Nothing saved yet' with identity context."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("something", "other", embed=False)
    r = CliRunner().invoke(cli.app, ["list", "-p", "missing-proj"])
    assert r.exit_code == 0
    assert "Nothing saved yet" in r.output
    assert "personal" in r.output  # identity shown in the empty message


# ── recall command ────────────────────────────────────────────────────────────

def test_recall_empty_query_exits_1(monkeypatch, tmp_path):
    """Lines 815-816: recall with a blank query must exit 1 with 'Empty query'."""
    _save_home(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli.app, ["recall", ""])
    assert r.exit_code == 1
    assert "Empty query" in r.output


def test_recall_no_matches(monkeypatch, tmp_path):
    """Lines 819-821: recall with no results must print 'No matches' and exit 0."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])
    r = CliRunner().invoke(cli.app, ["recall", "xyz"])
    assert r.exit_code == 0
    assert "No matches" in r.output


def test_recall_shows_matched_results(monkeypatch, tmp_path):
    """Lines 839-842: recall with results must print snippet, project, and ID."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [
        ("id1", "projA", "2026-01-01T00:00:00", "memory/id1.md", "quick brown fox", None, None, None)
    ])
    r = CliRunner().invoke(cli.app, ["recall", "fox"])
    assert r.exit_code == 0
    assert "quick brown fox" in r.output
    assert "projA" in r.output


def test_recall_pipe_sends_to_clipboard(monkeypatch, tmp_path):
    """Lines 823-834: recall --pipe must format notes and call pbcopy."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("clipboard test content", "proj", embed=False)

    pbcopy_input = []

    def fake_run(cmd, input=None, check=False):
        pbcopy_input.append(input)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    r = CliRunner().invoke(cli.app, ["recall", "clipboard test", "--pipe"])
    assert r.exit_code == 0
    assert pbcopy_input
    assert b"clipboard test content" in pbcopy_input[0]


def test_recall_pipe_fallback_when_pbcopy_absent(monkeypatch, tmp_path):
    """Lines 835-836: recall --pipe must print payload to stdout if pbcopy is not found."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("fallback pipe content", "proj", embed=False)

    def fake_run(cmd, input=None, check=False):
        raise FileNotFoundError("pbcopy not found")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    r = CliRunner().invoke(cli.app, ["recall", "fallback pipe", "--pipe"])
    assert "fallback pipe content" in r.output


# ── ask edge cases ────────────────────────────────────────────────────────────

def test_ask_handles_missing_markdown_in_context_build(monkeypatch, tmp_path):
    """Lines 868-869: ask must silently skip a note whose markdown file can't be read (OSError)."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [
        ("id1", "proj", "2026", "memory/gone.md", "snip", None, None, None)
    ])
    monkeypatch.setattr(cli, "_post_json", lambda *a, **kw: {"response": "the answer"})
    r = CliRunner().invoke(cli.app, ["ask", "q"])
    assert r.exit_code == 0
    assert "the answer" in r.output  # proceeds with empty context, no crash


def test_ask_local_urlerror_exits_1(monkeypatch, tmp_path):
    """Lines 909-911: ask must exit 1 with a friendly message when the local model is unreachable."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])
    import urllib.error as _ue
    monkeypatch.setattr(cli, "_post_json", lambda *a, **kw: (_ for _ in ()).throw(_ue.URLError("refused")))
    r = CliRunner().invoke(cli.app, ["ask", "q"])
    assert r.exit_code == 1
    assert "ollama" in r.output.lower() or "Ollama" in r.output


def test_ask_think_flag_shows_thinking_block(monkeypatch, tmp_path):
    """Line 916: ask --think must print '[thinking]' block when model returns thinking text."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])

    def fake_post(url, payload, headers=None, timeout=120):
        return {"response": "the final answer", "thinking": "step by step reasoning here"}

    monkeypatch.setattr(cli, "_post_json", fake_post)
    r = CliRunner().invoke(cli.app, ["ask", "q", "--think"])
    assert r.exit_code == 0
    assert "[thinking]" in r.output
    assert "step by step reasoning here" in r.output


# ── forget edge cases ─────────────────────────────────────────────────────────

def test_forget_no_match_exits_1(monkeypatch, tmp_path):
    """Lines 942-943: forget with an ID that doesn't exist must exit 1."""
    _save_home(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli.app, ["forget", "nonexistent-id-xyz"])
    assert r.exit_code == 1
    assert "No note matches" in r.output


def test_forget_multiple_matches_exits_1(monkeypatch, tmp_path):
    """Lines 945-948: forget with a prefix matching multiple notes must exit 1."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("note one", "proj", embed=False)
    cli._save("note two", "proj", embed=False)
    # All IDs start with "202" (year 20xx) — matches both
    r = CliRunner().invoke(cli.app, ["forget", "202"])
    assert r.exit_code == 1
    assert "matches" in r.output


def test_forget_decline_confirm_keeps_note(monkeypatch, tmp_path):
    """Lines 956-957: declining the forget confirm must keep the note intact."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    mem_id = cli._save("keep me safe", "proj", embed=False)
    r = CliRunner().invoke(cli.app, ["forget", mem_id], input="n\n")
    assert r.exit_code == 0
    assert "Kept" in r.output
    # Verify note is still in DB
    conn = sqlite3.connect(cli.DB_PATH)
    row = conn.execute("SELECT id FROM memories WHERE id=?", (mem_id,)).fetchone()
    conn.close()
    assert row is not None


# ── status edge cases ─────────────────────────────────────────────────────────

def test_status_shows_per_project_breakdown(monkeypatch, tmp_path):
    """Line 1004: status must print per-project rows when notes exist."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("note in alpha", "alpha", embed=False)
    cli._save("note in beta", "beta", embed=False)
    r = CliRunner().invoke(cli.app, ["status"])
    assert r.exit_code == 0
    assert "alpha" in r.output
    assert "beta" in r.output


def test_status_shows_question_mark_when_config_unreadable(monkeypatch, tmp_path):
    """Lines 996-997: status must show '?' for version when config.json has invalid JSON."""
    h = _save_home(monkeypatch, tmp_path)
    (h / "config.json").write_text("not valid json {{{")
    r = CliRunner().invoke(cli.app, ["status"])
    assert r.exit_code == 0
    assert "config v?" in r.output


# ── doctor edge cases ─────────────────────────────────────────────────────────

def test_doctor_config_unreadable_marks_check_failed(monkeypatch, tmp_path):
    """Lines 1029-1030: doctor must fail the config check when config.json has bad JSON."""
    h = _save_home(monkeypatch, tmp_path)
    (h / "config.json").write_text("not valid json {{{")
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert r.exit_code == 1
    assert "✗ config.json readable" in r.output


def test_doctor_shows_fix_hint_for_failed_check(monkeypatch, tmp_path):
    """Line 1064: doctor must print '→ fix' text for each failed check."""
    h = _save_home(monkeypatch, tmp_path)
    (h / "config.json").write_text("bad json")
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert "→ run: kage init" in r.output


def test_doctor_sqlite_error_marks_db_check_failed(monkeypatch, tmp_path):
    """Lines 1044-1045: doctor must mark db check failed when sqlite3.Error is raised."""
    import json as _j
    h = tmp_path / ".kage"
    h.mkdir()
    (h / "memory").mkdir()
    (h / "indexes").mkdir()
    (h / "indexes" / "kage.db").write_bytes(b"not a sqlite database")  # corrupted DB
    (h / "config.json").write_text(_j.dumps({"version": "0.1.0"}))
    _patch_home(monkeypatch, h)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert r.exit_code == 1
    assert "✗ database" in r.output


def test_doctor_sqlite_error_in_chunks_check_is_silenced(monkeypatch, tmp_path):
    """Lines 1075-1076: sqlite3.Error in the chunks pending check must be silently swallowed."""
    import json as _j
    h = tmp_path / ".kage"
    h.mkdir()
    (h / "memory").mkdir()
    (h / "indexes").mkdir()
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    conn.executescript("""
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, content_path TEXT NOT NULL,
            project TEXT, created_at TEXT NOT NULL,
            needs_embed INTEGER NOT NULL DEFAULT 1
        );
        CREATE VIRTUAL TABLE memory_fts USING fts5(id UNINDEXED, body);
    """)
    conn.close()
    # Note: chunks table deliberately absent → SELECT COUNT(*) FROM chunks raises sqlite3.Error
    (h / "config.json").write_text(_j.dumps({"version": "0.1.0"}))
    _patch_home(monkeypatch, h)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    monkeypatch.setattr(cli, "_ollama_status", lambda cfg, model: (True, "mocked ok"))
    r = CliRunner().invoke(cli.app, ["doctor"])
    # Must not crash and all_ok must remain True — the sqlite3.Error was silenced
    assert "kage doctor" in r.output
    assert r.exit_code == 0


def test_doctor_ollama_down_shows_advisory(monkeypatch, tmp_path):
    """Line 1096: doctor must print Ollama advisory when local model is not ready."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    monkeypatch.setattr(cli, "_ollama_status", lambda cfg, model: (False, "Ollama not reachable"))
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert "ollama serve" in r.output
    assert "ollama pull" in r.output


def test_doctor_mcp_not_installed_shows_warning(monkeypatch, tmp_path):
    """Lines 1119-1120: doctor must warn when the mcp package is not importable."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    monkeypatch.setitem(sys.modules, "mcp", None)  # None in sys.modules → ImportError on 'import mcp'
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert "⚠ MCP server" in r.output
    assert "pip install" in r.output


def test_doctor_exits_1_with_failure_summary(monkeypatch, tmp_path):
    """Lines 1128-1129: doctor must exit 1 and print failure message when any check fails."""
    h = _save_home(monkeypatch, tmp_path)
    (h / "config.json").write_text("bad json")  # makes cfg_ok = False
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert r.exit_code == 1
    assert "some checks failed" in r.output


# ── mcp_serve command ─────────────────────────────────────────────────────────

def test_mcp_serve_when_mcp_not_installed(monkeypatch, tmp_path):
    """Lines 1135-1140: mcp_serve must exit 1 with a friendly message when kage.mcp_server is missing."""
    _save_home(monkeypatch, tmp_path)
    # Setting sys.modules[key] = None makes 'from key import ...' raise ImportError
    monkeypatch.setitem(sys.modules, "kage.mcp_server", None)
    r = CliRunner().invoke(cli.app, ["mcp", "serve"])
    assert r.exit_code == 1
    assert "MCP not installed" in r.output


def test_mcp_serve_calls_mcp_run(monkeypatch, tmp_path):
    """Line 1141: mcp_serve must call mcp.run(transport='stdio') on the real mcp object."""
    import types
    _save_home(monkeypatch, tmp_path)
    run_calls = []

    class FakeMCP:
        def run(self, transport=None):
            run_calls.append(transport)

    fake_mod = types.ModuleType("kage.mcp_server")
    fake_mod.mcp = FakeMCP()
    monkeypatch.setitem(sys.modules, "kage.mcp_server", fake_mod)
    r = CliRunner().invoke(cli.app, ["mcp", "serve"])
    assert r.exit_code == 0
    assert run_calls == ["stdio"]


# ── Cycle 7 — Layer 3e privacy gate ───────────────────────────────────────────

import json as _json  # noqa: E402 — used in gate tests only


# ── _pii_scan ─────────────────────────────────────────────────────────────────

def test_pii_scan_matches_aadhaar():
    assert "Aadhaar" in cli._pii_scan("my id is 1234 5678 9012")


def test_pii_scan_matches_pan():
    assert "PAN card" in cli._pii_scan("PAN: ABCDE1234F")


def test_pii_scan_matches_openai_key():
    assert "OpenAI key" in cli._pii_scan("key=sk-abcdefghijklmnopqrstuv")


def test_pii_scan_matches_email():
    assert "Email" in cli._pii_scan("reach me at user@example.com please")


def test_pii_scan_matches_upi():
    assert "UPI ID" in cli._pii_scan("pay me at 9876543210@ybl now")


def test_pii_scan_upi_ignores_email():
    assert "UPI ID" not in cli._pii_scan("email john@gmail.com today")


def test_pii_scan_upi_short_handle_caught():
    # security baseline (Slice 0): privacy gate must not leak short UPI handles;
    # FN (leak) is worse than FP (over-withhold), so the username floor is {2,}.
    assert "UPI ID" in cli._pii_scan("refund to ab@hdfc")
    assert "UPI ID" not in cli._pii_scan("rate is 5@bar")  # 1-char username still dropped


def test_pii_scan_ipv4_removed():
    assert "IPv4 address" not in cli._pii_scan("connect to 192.168.1.1 please")


def test_pii_scan_matches_aws_key():
    assert "AWS access key" in cli._pii_scan("AKIAIOSFODNN7EXAMPLE")


def test_pii_scan_matches_ssh_key():
    assert "SSH private key" in cli._pii_scan("-----BEGIN RSA PRIVATE KEY-----")


def test_pii_scan_clean_text_returns_empty():
    assert cli._pii_scan("today I learned about recursion in Python") == []


def test_pii_scan_extra_patterns_respected():
    hits = cli._pii_scan("EMP-12345", extra_patterns=[{"name": "EmployeeID", "pattern": r"EMP-\d+"}])
    assert "EmployeeID" in hits


# ── _save local_only flag ─────────────────────────────────────────────────────

def test_save_local_only_writes_frontmatter_and_db(monkeypatch, tmp_path):
    """--local flag must set local_only:true in markdown frontmatter and local_only=1 in DB."""
    h = _save_home(monkeypatch, tmp_path)
    mem_id = cli._save("my Aadhaar details", None, local_only=True)
    md = (h / "memory" / f"{mem_id}.md").read_text()
    assert "local_only: true" in md
    conn = cli._connect()
    row = conn.execute("SELECT local_only FROM memories WHERE id=?", (mem_id,)).fetchone()
    conn.close()
    assert row[0] == 1


def test_remember_local_flag_sets_local_only(monkeypatch, tmp_path):
    """kage remember --local must set local_only via _save and confirm in output."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    r = CliRunner().invoke(cli.app, ["remember", "passport info", "--local", "--yes"])
    assert r.exit_code == 0
    assert "local-only" in r.output
    md_files = list((h / "memory").glob("*.md"))
    assert len(md_files) == 1
    assert "local_only: true" in md_files[0].read_text()


def test_save_auto_flags_local_only_from_project_config(monkeypatch, tmp_path):
    """Notes saved to a project listed in local_only_projects must be auto-flagged."""
    h = _save_home(monkeypatch, tmp_path)
    cfg = _json.loads((h / "config.json").read_text())
    cfg["local_only_projects"] = ["health"]
    (h / "config.json").write_text(_json.dumps(cfg))
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))

    mem_id = cli._save("doctor visit notes", "health")
    conn = cli._connect()
    row = conn.execute("SELECT local_only FROM memories WHERE id=?", (mem_id,)).fetchone()
    conn.close()
    assert row[0] == 1


def test_save_non_local_project_not_flagged(monkeypatch, tmp_path):
    """Notes in unlisted projects must NOT be auto-flagged as local_only."""
    h = _save_home(monkeypatch, tmp_path)
    cfg = _json.loads((h / "config.json").read_text())
    cfg["local_only_projects"] = ["health"]
    (h / "config.json").write_text(_json.dumps(cfg))
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))

    mem_id = cli._save("public tech note", "kage")
    conn = cli._connect()
    row = conn.execute("SELECT local_only FROM memories WHERE id=?", (mem_id,)).fetchone()
    conn.close()
    assert row[0] == 0


# ── _disclosure_gate ──────────────────────────────────────────────────────────

def _fake_row(mem_id, project=None):
    """Build a minimal 8-tuple row matching _search() output."""
    return (mem_id, project, "2026-06-10", f"memory/{mem_id}.md", "snip", None, None, None)


def test_disclosure_gate_withholds_local_only_flag(monkeypatch, tmp_path):
    """Gate must block a note whose local_only DB flag is 1."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    mem_id = cli._save("secret", None, local_only=True)
    cfg = cli._config()
    allowed, withheld = cli._disclosure_gate([_fake_row(mem_id)], cfg)
    assert allowed == []
    assert len(withheld) == 1
    assert withheld[0]["reason"] == "local_only:flag"


def test_disclosure_gate_withholds_local_only_project(monkeypatch, tmp_path):
    """Gate must block a note via project rule even when note was saved before the rule existed."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    # Save before adding finance to local_only_projects → local_only=0 in DB
    mem_id = cli._save("bank statement", "finance")
    # Now retroactively add the project rule
    cfg_data = _json.loads((h / "config.json").read_text())
    cfg_data["local_only_projects"] = ["finance"]
    (h / "config.json").write_text(_json.dumps(cfg_data))
    cfg = cli._config()
    allowed, withheld = cli._disclosure_gate([_fake_row(mem_id, "finance")], cfg)
    assert allowed == []
    assert withheld[0]["reason"] == "local_only:project:finance"


def test_disclosure_gate_withholds_pii_detected(monkeypatch, tmp_path):
    """Gate must block a note that matches a PII pattern even without the local_only flag."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    mem_id = cli._save("my key is sk-abcdefghijklmnopqrstuv", None)
    cfg = cli._config()
    allowed, withheld = cli._disclosure_gate([_fake_row(mem_id)], cfg)
    assert allowed == []
    assert withheld[0]["reason"] == "pii_detected"
    assert "OpenAI key" in withheld[0]["pii_patterns"]


def test_disclosure_gate_allows_clean_note(monkeypatch, tmp_path):
    """Gate must allow a clean note with no local_only flag and no PII."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    mem_id = cli._save("Python is a dynamically typed language", None)
    cfg = cli._config()
    allowed, withheld = cli._disclosure_gate([_fake_row(mem_id)], cfg)
    assert len(allowed) == 1
    assert withheld == []


def test_disclosure_gate_empty_rows():
    """Gate on empty input must return two empty lists without error."""
    allowed, withheld = cli._disclosure_gate([], {})
    assert allowed == []
    assert withheld == []


# ── ask command — gate integration ────────────────────────────────────────────

def test_ask_cloud_all_withheld_falls_back_to_ollama(monkeypatch, tmp_path):
    """Case 2: when all notes are local-only the gate must skip cloud and call Ollama."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    mem_id = cli._save("my passport number", None, local_only=True)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [_fake_row(mem_id)])
    cloud_calls: list[str] = []
    monkeypatch.setattr(cli, "_call_cloud", lambda name, *a, **kw: cloud_calls.append(name) or "ans")
    monkeypatch.setattr(cli, "_post_json", lambda url, p, **kw: {"response": "local ans"})
    r = CliRunner().invoke(cli.app, ["ask", "q", "--cloud"])
    assert r.exit_code == 0
    assert cloud_calls == []
    assert "local-only" in r.output
    assert "Proceed" not in r.output  # no prompt for Case 2


def test_ask_cloud_some_withheld_prompts_user(monkeypatch, tmp_path):
    """Case 1: local_only note withheld — gate shows 'Preparing to send context' preamble + [y/N] prompt."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    # local_only=True, clean text — withheld by flag, not PII
    secret_id = cli._save("launch presentation notes", None, local_only=True)
    clean_id = cli._save("recursion is a useful concept", None)
    monkeypatch.setattr(cli, "_search",
        lambda *a, **kw: [_fake_row(secret_id), _fake_row(clean_id)])
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: "cloud answer")
    monkeypatch.setattr(cli, "_session_approvals", {})
    r = CliRunner().invoke(cli.app, ["ask", "q", "--cloud"], input="y\n")
    assert r.exit_code == 0
    assert "Preparing to send context" in r.output
    assert "Proceed with partial context?" in r.output
    assert "withheld" in r.output


def test_ask_cloud_user_denies_falls_back_to_ollama(monkeypatch, tmp_path):
    """When user answers N at the gate prompt the cloud must not be called."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    secret_id = cli._save("my Aadhaar 1234 5678 9012", None)
    clean_id = cli._save("clean note", None)
    monkeypatch.setattr(cli, "_search",
        lambda *a, **kw: [_fake_row(secret_id), _fake_row(clean_id)])
    cloud_calls: list[str] = []
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: cloud_calls.append(1) or "ans")
    monkeypatch.setattr(cli, "_post_json", lambda url, p, **kw: {"response": "local ans"})
    monkeypatch.setattr(cli, "_session_approvals", {})
    r = CliRunner().invoke(cli.app, ["ask", "q", "--cloud"], input="n\n")
    assert r.exit_code == 0
    assert cloud_calls == []
    assert "Denied" in r.output


def test_ask_cloud_session_approval_suppresses_reprompt(monkeypatch, tmp_path):
    """Second cloud call to same provider in a session must skip the prompt."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    secret_id = cli._save("my Aadhaar 1234 5678 9012", None)
    clean_id = cli._save("clean note", None)
    monkeypatch.setattr(cli, "_search",
        lambda *a, **kw: [_fake_row(secret_id), _fake_row(clean_id)])
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: "cloud answer")
    monkeypatch.setattr(cli, "_session_approvals", {})

    r1 = CliRunner().invoke(cli.app, ["ask", "q", "--cloud"], input="y\n")
    assert "Proceed" in r1.output

    r2 = CliRunner().invoke(cli.app, ["ask", "q", "--cloud"])
    assert "Proceed" not in r2.output


def test_ask_cloud_always_ask_overrides_session_memory(monkeypatch, tmp_path):
    """--always-ask must re-prompt even after a session approval."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    secret_id = cli._save("my Aadhaar 1234 5678 9012", None)
    clean_id = cli._save("clean note", None)
    monkeypatch.setattr(cli, "_search",
        lambda *a, **kw: [_fake_row(secret_id), _fake_row(clean_id)])
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: "cloud answer")
    monkeypatch.setattr(cli, "_session_approvals", {"claude": True})

    r = CliRunner().invoke(cli.app, ["ask", "q", "--cloud", "--always-ask"], input="y\n")
    assert "Proceed" in r.output


# ── audit log ─────────────────────────────────────────────────────────────────

def test_audit_log_written_on_dispatch(monkeypatch, tmp_path):
    """Gate must write a JSONL record to audit.jsonl on each cloud dispatch."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: "answer")
    CliRunner().invoke(cli.app, ["ask", "q", "--cloud"])
    records = [_json.loads(l) for l in (h / "audit.jsonl").read_text().strip().splitlines()]
    assert len(records) == 1
    assert records[0]["provider"] == "claude"
    assert records[0]["outcome"] == "dispatched"
    assert records[0]["notes_withheld"] == 0


def test_audit_log_written_on_block(monkeypatch, tmp_path):
    """Gate must write an audit record with outcome blocked_all_local when all notes are withheld."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    mem_id = cli._save("secret", None, local_only=True)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [_fake_row(mem_id)])
    monkeypatch.setattr(cli, "_post_json", lambda url, p, **kw: {"response": "local"})
    CliRunner().invoke(cli.app, ["ask", "q", "--cloud"])
    records = [_json.loads(l) for l in (h / "audit.jsonl").read_text().strip().splitlines()]
    assert records[0]["outcome"] == "blocked_all_local"
    assert records[0]["notes_withheld"] == 1


def test_audit_log_written_on_denial(monkeypatch, tmp_path):
    """Gate must write an audit record with outcome denied_by_user when user answers N."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    secret_id = cli._save("Aadhaar 1234 5678 9012", None)
    clean_id = cli._save("public note", None)
    monkeypatch.setattr(cli, "_search",
        lambda *a, **kw: [_fake_row(secret_id), _fake_row(clean_id)])
    monkeypatch.setattr(cli, "_post_json", lambda url, p, **kw: {"response": "local"})
    monkeypatch.setattr(cli, "_session_approvals", {})
    CliRunner().invoke(cli.app, ["ask", "q", "--cloud"], input="n\n")
    records = [_json.loads(l) for l in (h / "audit.jsonl").read_text().strip().splitlines()]
    assert records[0]["outcome"] == "denied_by_user"
    assert records[0]["user_approved"] is False


# ── status and doctor ─────────────────────────────────────────────────────────

def test_status_shows_local_only_count(monkeypatch, tmp_path):
    """kage status must display the count of local-only notes when non-zero."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    cli._save("public note", None)
    cli._save("private note", None, local_only=True)
    r = CliRunner().invoke(cli.app, ["status"])
    assert "local-only" in r.output


def test_status_audit_flag_shows_records(monkeypatch, tmp_path):
    """kage status --audit must display dispatch records from the audit log."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: "answer")
    CliRunner().invoke(cli.app, ["ask", "q", "--cloud"])
    r = CliRunner().invoke(cli.app, ["status", "--audit"])
    assert "dispatched" in r.output
    assert "claude" in r.output


def test_status_audit_flag_no_log_yet(monkeypatch, tmp_path):
    """kage status --audit must report cleanly when no audit log exists yet."""
    _save_home(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli.app, ["status", "--audit"])
    assert r.exit_code == 0
    assert "no audit log" in r.output


def test_doctor_shows_privacy_gate_advisory(monkeypatch, tmp_path):
    """kage doctor must show the privacy gate line for local_only_projects."""
    h = _save_home(monkeypatch, tmp_path)
    cfg_data = _json.loads((h / "config.json").read_text())
    cfg_data["local_only_projects"] = ["health", "finance"]
    (h / "config.json").write_text(_json.dumps(cfg_data))
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert "privacy gate" in r.output
    assert "2 local-only project" in r.output


def test_doctor_shows_no_local_only_projects_advisory(monkeypatch, tmp_path):
    """kage doctor must show advisory when local_only_projects is not configured."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert "no local_only_projects" in r.output


def test_doctor_shows_audit_log_advisory(monkeypatch, tmp_path):
    """kage doctor must confirm the audit log path is writable."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert "audit log" in r.output


# ── MCP gate — kage_ask ───────────────────────────────────────────────────────

def test_mcp_kage_ask_gate_withholds_local_only(monkeypatch, tmp_path):
    """kage_ask MCP tool must run the disclosure gate and fall back to Ollama when all withheld."""
    from kage import mcp_server
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    mem_id = cli._save("secret passport", None, local_only=True)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [_fake_row(mem_id)])
    cloud_calls: list[str] = []
    monkeypatch.setattr(cli, "_call_cloud", lambda name, *a, **kw: cloud_calls.append(name) or "ans")
    monkeypatch.setattr(cli, "_post_json", lambda url, p, **kw: {"response": "local ans"})
    result = asyncio.run(mcp_server.kage_ask("what is my passport?", provider="groq"))
    assert cloud_calls == []
    assert result["withheld_count"] == 1


def test_mcp_kage_ask_gate_allows_clean_note(monkeypatch, tmp_path):
    """kage_ask MCP tool must pass clean notes through to the cloud provider."""
    from kage import mcp_server
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    mem_id = cli._save("Python uses indentation", None)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [_fake_row(mem_id)])
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: "cloud answer")
    result = asyncio.run(mcp_server.kage_ask("what about Python?", provider="groq"))
    assert result["withheld_count"] == 0
    assert result["answer"] == "cloud answer"


def test_mcp_kage_ask_audit_written(monkeypatch, tmp_path):
    """kage_ask MCP tool must write an audit record on every cloud dispatch."""
    from kage import mcp_server
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: "answer")
    asyncio.run(mcp_server.kage_ask("q", provider="groq"))
    records = [_json.loads(l) for l in (h / "audit.jsonl").read_text().strip().splitlines()]
    assert records[0]["provider"] == "groq"
    assert records[0]["outcome"] == "dispatched_mcp"


# ── coverage completeness for new Cycle 7 lines ───────────────────────────────

def test_post_json_success_return(monkeypatch):
    """Line 393: _post_json must parse and return the HTTP response body as JSON."""
    import urllib.request as _req
    expected = {"status": "ok", "value": 42}

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return _json.dumps(expected).encode()

    monkeypatch.setattr(_req, "urlopen", lambda req, timeout=120: _FakeResp())
    result = cli._post_json("http://fake-host/api", {"key": "val"})
    assert result == expected


def test_write_audit_oserror_is_silent(monkeypatch, tmp_path):
    """Lines 516-517: _write_audit must silently swallow OSError (e.g. disk full)."""
    import builtins
    h = _save_home(monkeypatch, tmp_path)
    real_open = builtins.open

    def bad_open(path, mode="r", *a, **kw):
        if "audit.jsonl" in str(path):
            raise OSError("disk full")
        return real_open(path, mode, *a, **kw)

    monkeypatch.setattr(builtins, "open", bad_open)
    cli._write_audit({"ts": "now", "outcome": "test"})  # must not raise


def test_disclosure_gate_uses_section_offsets(monkeypatch, tmp_path):
    """Line 569: gate must call _read_section when a row has char_start/char_end set."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    mem_id = cli._save("safe content about coding", None)
    cfg = cli._config()
    row_with_offsets = (mem_id, None, "2026", f"memory/{mem_id}.md", "snip", "Intro", 0, 24)
    allowed, withheld = cli._disclosure_gate([row_with_offsets], cfg)
    assert len(allowed) == 1
    assert withheld == []


def test_disclosure_gate_missing_file_treated_as_clean(monkeypatch, tmp_path):
    """Lines 573-574: gate must allow a note whose markdown file is missing (empty text = no PII)."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    mem_id = cli._save("something", None)
    (h / "memory" / f"{mem_id}.md").unlink()
    cfg = cli._config()
    allowed, withheld = cli._disclosure_gate([_fake_row(mem_id)], cfg)
    assert len(allowed) == 1
    assert withheld == []


def test_ollama_status_model_ready(monkeypatch):
    """Line 697: _ollama_status must return (True, ...) when the model name is in the tags list."""
    import urllib.request as _req
    model = "qwen3:14b"

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return _json.dumps({"models": [{"name": model}]}).encode()

    monkeypatch.setattr(_req, "urlopen", lambda *a, **kw: _FakeResp())
    ok, msg = cli._ollama_status({}, model)
    assert ok is True
    assert "ready" in msg


def test_status_audit_flag_unreadable_log(monkeypatch, tmp_path):
    """Lines 1224-1225: status --audit must handle a corrupt audit log without crashing."""
    h = _save_home(monkeypatch, tmp_path)
    (h / "audit.jsonl").write_text("not valid json {{{")
    r = CliRunner().invoke(cli.app, ["status", "--audit"])
    assert r.exit_code == 0
    assert "unreadable" in r.output


def test_doctor_audit_log_unwritable(monkeypatch, tmp_path):
    """Lines 1385-1386, 1389: doctor must show ⚠ when the audit log path is not writable."""
    import builtins
    h = _save_home(monkeypatch, tmp_path)
    real_open = builtins.open

    def bad_open(path, mode="r", *a, **kw):
        if "audit.jsonl" in str(path) and "a" in mode:
            raise OSError("read-only filesystem")
        return real_open(path, mode, *a, **kw)

    monkeypatch.setattr(builtins, "open", bad_open)
    monkeypatch.setattr(cli, "_get_chroma", lambda: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert "⚠" in r.output
    assert "audit log" in r.output


# ── missing-test additions (post-review) ──────────────────────────────────────

def test_pii_scan_invalid_extra_pattern_is_skipped():
    """Malformed regex in extra_patterns must be silently skipped — must not raise."""
    hits = cli._pii_scan("some text", extra_patterns=[{"name": "bad", "pattern": r"[invalid"}])
    assert isinstance(hits, list)  # did not raise


def test_ask_cloud_require_approval_false_skips_prompt_filters_and_audits_none(monkeypatch, tmp_path):
    """require_approval:false must skip the prompt, still withhold PII notes, and write user_approved=null."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    cfg_data = _json.loads((h / "config.json").read_text())
    cfg_data["require_approval"] = False
    (h / "config.json").write_text(_json.dumps(cfg_data))
    secret_id = cli._save("my Aadhaar 1234 5678 9012", None)
    clean_id = cli._save("clean public note", None)
    monkeypatch.setattr(cli, "_search",
        lambda *a, **kw: [_fake_row(secret_id), _fake_row(clean_id)])
    cloud_calls: list = []
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: cloud_calls.append(1) or "cloud answer")
    monkeypatch.setattr(cli, "_session_approvals", {})
    r = CliRunner().invoke(cli.app, ["ask", "q", "--cloud"])
    assert r.exit_code == 0
    assert "Proceed" not in r.output  # no prompt when require_approval=false
    assert cloud_calls  # cloud was still called (clean note passed through)
    records = [_json.loads(l) for l in (h / "audit.jsonl").read_text().strip().splitlines()]
    assert records[0]["user_approved"] is None  # auto-approved — no prompt shown


def test_ask_cloud_session_approval_actually_calls_cloud(monkeypatch, tmp_path):
    """After session approval, cloud must actually be called — not silently fall back to Ollama."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    secret_id = cli._save("my Aadhaar 1234 5678 9012", None)
    clean_id = cli._save("clean note", None)
    monkeypatch.setattr(cli, "_search",
        lambda *a, **kw: [_fake_row(secret_id), _fake_row(clean_id)])
    cloud_calls: list = []
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: cloud_calls.append(1) or "cloud answer")
    monkeypatch.setattr(cli, "_session_approvals", {"claude": True})  # already approved
    r = CliRunner().invoke(cli.app, ["ask", "q", "--cloud"])
    assert r.exit_code == 0
    assert "Proceed" not in r.output  # no re-prompt
    assert cloud_calls  # cloud was actually called
    assert "cloud answer" in r.output


def test_ask_cloud_session_remember_false_always_prompts(monkeypatch, tmp_path):
    """session_remember_approval:false must prompt even if provider was pre-approved in _session_approvals."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    cfg_data = _json.loads((h / "config.json").read_text())
    cfg_data["session_remember_approval"] = False
    (h / "config.json").write_text(_json.dumps(cfg_data))
    secret_id = cli._save("my Aadhaar 1234 5678 9012", None)
    clean_id = cli._save("clean note", None)
    monkeypatch.setattr(cli, "_search",
        lambda *a, **kw: [_fake_row(secret_id), _fake_row(clean_id)])
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: "cloud answer")
    monkeypatch.setattr(cli, "_session_approvals", {"claude": True})  # would suppress prompt if remembered
    r = CliRunner().invoke(cli.app, ["ask", "q", "--cloud"], input="y\n")
    assert r.exit_code == 0
    assert "Proceed" in r.output  # prompt fired despite pre-existing session approval


def test_ask_cloud_case3_pii_preamble(monkeypatch, tmp_path):
    """When withheld note is blocked due to PII scan, preamble must say 'PII detected in'."""
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("x")))
    # Save a note whose text contains an Aadhaar number (PII) but is NOT flagged local_only
    pii_id = cli._save("my Aadhaar is 1234 5678 9012", None)
    clean_id = cli._save("clean note", None)
    monkeypatch.setattr(cli, "_search",
        lambda *a, **kw: [_fake_row(pii_id), _fake_row(clean_id)])
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: "cloud answer")
    monkeypatch.setattr(cli, "_session_approvals", {})
    r = CliRunner().invoke(cli.app, ["ask", "q", "--cloud"], input="y\n")
    assert r.exit_code == 0
    assert "PII detected in" in r.output
    assert "Preparing to send context" not in r.output


# ── Reranker tests (Cycle 8 Step 3) ─────────────────────────────────────────

def test_get_reranker_returns_none_when_not_installed():
    cli._reranker_cache[0] = False
    cli._reranker_cache[1] = None
    original_modules = sys.modules.copy()
    sys.modules["sentence_transformers"] = None
    try:
        result = cli._get_reranker()
        assert result is None
    finally:
        if "sentence_transformers" in original_modules:
            sys.modules["sentence_transformers"] = original_modules["sentence_transformers"]
        elif "sentence_transformers" in sys.modules:
            del sys.modules["sentence_transformers"]


def test_get_reranker_caches_result():
    cli._reranker_cache[0] = False
    cli._reranker_cache[1] = None
    original_modules = sys.modules.copy()
    sys.modules["sentence_transformers"] = None
    try:
        result1 = cli._get_reranker()
        result2 = cli._get_reranker()
        assert result1 is None
        assert result2 is None
        assert cli._reranker_cache[0] is True
    finally:
        if "sentence_transformers" in original_modules:
            sys.modules["sentence_transformers"] = original_modules["sentence_transformers"]
        elif "sentence_transformers" in sys.modules:
            del sys.modules["sentence_transformers"]


def test_rerank_falls_back_when_no_reranker():
    cli._reranker_cache[0] = True
    cli._reranker_cache[1] = None
    rows = [
        ("id1", "p", "ts", "path", "snip",  "title", None, None),
        ("id2", "p", "ts", "path", "snip2", "title", None, None),
        ("id3", "p", "ts", "path", "snip3", "title", None, None),
    ]
    result = cli._rerank(rows, "query", 2)
    assert result == rows[:2]


def test_rerank_falls_back_on_empty_rows():
    cli._reranker_cache[0] = True
    cli._reranker_cache[1] = None
    result = cli._rerank([], "query", 5)
    assert result == []


def test_rerank_scores_and_reorders():
    mock_reranker = mock.MagicMock()
    mock_reranker.predict.return_value.tolist.return_value = [0.1, 0.9, 0.5]
    cli._reranker_cache[0] = True
    cli._reranker_cache[1] = mock_reranker
    rows = [
        ("id1", "p", "ts", "path", "snip1", "title", None, None),
        ("id2", "p", "ts", "path", "snip2", "title", None, None),
        ("id3", "p", "ts", "path", "snip3", "title", None, None),
    ]
    result = cli._rerank(rows, "q", 3)
    assert result[0] == rows[1]
    assert result[2] == rows[0]


def test_rerank_respects_top_n():
    mock_reranker = mock.MagicMock()
    mock_reranker.predict.return_value.tolist.return_value = [0.1, 0.9, 0.5]
    cli._reranker_cache[0] = True
    cli._reranker_cache[1] = mock_reranker
    rows = [
        ("id1", "p", "ts", "path", "snip1", "title", None, None),
        ("id2", "p", "ts", "path", "snip2", "title", None, None),
        ("id3", "p", "ts", "path", "snip3", "title", None, None),
    ]
    result = cli._rerank(rows, "q", 2)
    assert len(result) == 2
    assert result[0] == rows[1]


def test_search_rerank_off_by_default():
    with mock.patch.object(cli, "_config", return_value={}):
        with mock.patch.object(cli, "_search_fts", return_value=[("id1", "proj", "ts", "path", "snip")]):
            with mock.patch.object(cli, "_embed", side_effect=cli.OllamaUnavailable("off")):
                with mock.patch.object(cli, "_rerank") as mock_rerank:
                    cli._search("hello", None, 5)
                    mock_rerank.assert_not_called()


def test_search_rerank_on_calls_rerank_fts_fallback():
    with mock.patch.object(cli, "_config", return_value={"rerank": True}):
        with mock.patch.object(cli, "_search_fts", return_value=[("id1", "proj", "ts", "path", "snip")]):
            with mock.patch.object(cli, "_embed", side_effect=cli.OllamaUnavailable("off")):
                with mock.patch.object(cli, "_rerank", return_value=["sentinel"]) as mock_rerank:
                    result = cli._search("hello", None, 5)
                    assert result == ["sentinel"]
                    mock_rerank.assert_called_once()


def test_search_rerank_on_calls_rerank_hybrid():
    with mock.patch.object(cli, "_config", return_value={"rerank": True}):
        with mock.patch.object(cli, "_search_fts", return_value=[("id1", "proj", "ts", "path", "snip")]):
            with mock.patch.object(cli, "_search_vec", return_value=[("id1", "proj", "ts", "path", "snip", "title", 0, 10)]):
                with mock.patch.object(cli, "_embed", return_value=[0.1, 0.2]):
                    with mock.patch.object(cli, "_rrf_fuse", return_value=[("id1", "proj", "ts", "path", "snip")]):
                        with mock.patch.object(cli, "_rerank", return_value=["sentinel"]) as mock_rerank:
                            result = cli._search("hello", None, 5)
                            assert result == ["sentinel"]
                            mock_rerank.assert_called_once()


# ── _search_vec identity wall (Cycle 9, Step 6) ─────────────────────────────

def test_search_vec_returns_empty_when_no_allowed_ids(monkeypatch):
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: set())
    result = cli._search_vec([0.1] * 4, None, 10)
    assert result == []


def test_search_vec_uses_allowed_ids_in_where_clause(monkeypatch):
    from unittest.mock import Mock, ANY

    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: {"m1", "m6"})

    mock_collection = Mock()
    mock_collection.get.return_value = {"ids": ["chunk1"]}
    mock_collection.query.return_value = {
        "ids": [["chunk1"]],
        "metadatas": [[{"note_id": "m1", "project": "kage", "created_at": "2026-01-01", "content_path": "/x"}]],
        "distances": [[0.1]],
    }
    monkeypatch.setattr(cli, "_get_chroma", lambda: mock_collection)

    result = cli._search_vec([0.1] * 4, "kage", 5)

    mock_collection.get.assert_called_with(where={"note_id": {"$in": ANY}}, include=[])
    assert result[0][0] == "m1"


def test_search_vec_empty_collection_after_wall_filter(monkeypatch):
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: {"m1", "m2"})

    mock_collection = mock.Mock()
    mock_collection.get.return_value = {"ids": []}
    monkeypatch.setattr(cli, "_get_chroma", lambda: mock_collection)

    result = cli._search_vec([0.1] * 4, None, 10)
    assert result == []


def test_search_identity_threaded_to_search_vec(monkeypatch):
    monkeypatch.setattr(cli, "_config", lambda: {})
    monkeypatch.setattr(cli, "_embed", lambda text: [0.1] * 4)
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: set())
    result = cli._search("anything", None, 5, identity="neu")
    assert result == []


# ── Step 7: --identity flag + MCP identity param + _disclosure_gate Stage-1 ──

def test_remember_flag_writes_identity(monkeypatch, tmp_path):
    h = _mp_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    fake_coll = type("C", (), {"add": lambda self, **kw: None, "count": lambda self: 0, "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]}, "delete": lambda self, **kw: None})()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)
    result = CliRunner().invoke(cli.app, ["remember", "neu note", "-p", "hsi", "--identity", "neu", "-y"])
    assert result.exit_code == 0
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    ids_with_neu = {row[0] for row in conn.execute("SELECT mem_id FROM memory_identities WHERE identity='neu'")}
    conn.close()
    assert len(ids_with_neu) == 1


def test_recall_flag_threads_identity(monkeypatch, tmp_path):
    _mp_home(monkeypatch, tmp_path)
    captured = {}
    def fake_search(*args, **kwargs):
        captured.update(kwargs)
        return []
    monkeypatch.setattr(cli, "_search", fake_search)
    CliRunner().invoke(cli.app, ["recall", "kage", "--identity", "neu"])
    assert captured.get("identity") == "neu"


def test_ask_flag_threads_identity(monkeypatch, tmp_path):
    _mp_home(monkeypatch, tmp_path)
    captured = {}
    def fake_search(*args, **kwargs):
        captured.update(kwargs)
        return []
    monkeypatch.setattr(cli, "_search", fake_search)
    CliRunner().invoke(cli.app, ["ask", "what is kage?", "--identity", "neu"])
    assert captured.get("identity") == "neu"


def test_list_flag_respects_identity_wall(monkeypatch, tmp_path):
    _mp_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1] * 768)
    fake_coll = type("C", (), {"add": lambda self, **kw: None, "count": lambda self: 0, "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]}, "delete": lambda self, **kw: None})()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)
    cli._save("personal note", "kage", identities=["personal"])
    cli._save("neu note", "hsi", identities=["neu"])
    result = CliRunner().invoke(cli.app, ["list", "--identity", "personal"])
    assert result.exit_code == 0
    assert "personal note" in result.output
    result = CliRunner().invoke(cli.app, ["list", "--identity", "neu"])
    assert result.exit_code == 0
    assert "neu note" in result.output


def test_disclosure_gate_stage1_blocks_cross_identity(monkeypatch, tmp_path):
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_allowed_note_ids", lambda identity, project: {"allowed-note"})
    rows = [
        ("allowed-note", "p", "t", "path", "snip", None, None, None),
        ("blocked-note", "p", "t", "path", "snip", None, None, None),
    ]
    result_allowed, withheld = cli._disclosure_gate(rows, {}, identity="personal", project="kage")
    assert "allowed-note" in [r[0] for r in result_allowed]
    blocked = [w for w in withheld if w["note_id"] == "blocked-note"]
    assert len(blocked) == 1
    assert blocked[0]["reason"] == "identity_wall:personal"


# ── Cycle 10: session schema (Step 1) + session helpers (Step 2) ─────────────

class TestSessionSchema:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch, tmp_path):
        _patch_home(monkeypatch, tmp_path / ".kage")

    def test_sessions_table_exists(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        r = CliRunner()
        r.invoke(cli.app, ["init"])
        conn = sqlite3.connect(str(h / "indexes" / "kage.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        conn.close()
        assert any("sessions" in t for t in tables)

    def test_session_turns_table_exists(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        r = CliRunner()
        r.invoke(cli.app, ["init"])
        conn = sqlite3.connect(str(h / "indexes" / "kage.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        conn.close()
        assert any("session_turns" in t for t in tables)

    def test_sessions_columns(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        r = CliRunner()
        r.invoke(cli.app, ["init"])
        conn = sqlite3.connect(str(h / "indexes" / "kage.db"))
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(sessions)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()
        assert columns == ['session_id', 'created_at', 'identity', 'project', 'destination', 'deleted']

    def test_session_turns_columns(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        r = CliRunner()
        r.invoke(cli.app, ["init"])
        conn = sqlite3.connect(str(h / "indexes" / "kage.db"))
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(session_turns)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()
        assert columns == ['session_id', 'idx', 'parent_idx', 'role', 'content', 'note_ids', 'destination', 'model', 'reason', 'tokens', 'ts', 'deleted']

    def test_session_turns_parent_idx_nullable(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        r = CliRunner()
        r.invoke(cli.app, ["init"])
        conn = sqlite3.connect(str(h / "indexes" / "kage.db"))
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(session_turns)")
        for row in cursor.fetchall():
            if row[1] == "parent_idx":
                assert row[3] == 0
        conn.close()

    def test_session_turns_note_ids_default(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        r = CliRunner()
        r.invoke(cli.app, ["init"])
        conn = sqlite3.connect(str(h / "indexes" / "kage.db"))
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(session_turns)")
        for row in cursor.fetchall():
            if row[1] == "note_ids":
                assert row[4] is not None
                assert "'[]'" in row[4]
        conn.close()

    def test_schema_idempotent(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        r = CliRunner()
        r.invoke(cli.app, ["init"])
        r.invoke(cli.app, ["init"])
        conn = sqlite3.connect(str(h / "indexes" / "kage.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        conn.close()
        assert any("sessions" in t for t in tables)
        assert any("session_turns" in t for t in tables)

    def test_sessions_deleted_default_zero(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        r = CliRunner()
        r.invoke(cli.app, ["init"])
        conn = sqlite3.connect(str(h / "indexes" / "kage.db"))
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sessions(session_id,created_at,identity,destination) VALUES('s1','2026-01-01','personal','ollama')")
        cursor.execute("SELECT deleted FROM sessions WHERE session_id='s1'")
        result = cursor.fetchone()[0]
        conn.close()
        assert result == 0

    def test_session_turns_deleted_default_zero(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        r = CliRunner()
        r.invoke(cli.app, ["init"])
        conn = sqlite3.connect(str(h / "indexes" / "kage.db"))
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sessions(session_id,created_at,identity,destination) VALUES('s1','2026-01-01','personal','ollama')")
        cursor.execute("INSERT INTO session_turns(session_id,idx,role,content,destination,ts) VALUES('s1',0,'user','hello','ollama','2026-01-01')")
        cursor.execute("SELECT deleted FROM session_turns WHERE session_id='s1' AND idx=0")
        result = cursor.fetchone()[0]
        conn.close()
        assert result == 0


class TestSessionHelpers:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch, tmp_path):
        _patch_home(monkeypatch, tmp_path / ".kage")

    def test_session_create_returns_uuid_string(self, tmp_path, monkeypatch):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        session_id = cli._session_create("personal", None, "ollama")
        assert isinstance(session_id, str)
        assert len(session_id) == 36

    def test_session_create_persists_to_db(self, tmp_path, monkeypatch):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        session_id = cli._session_create("personal", None, "ollama")
        conn = sqlite3.connect(str(h / "indexes" / "kage.db"))
        row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        conn.close()
        assert row is not None
        assert row[2] == "personal"   # identity
        assert row[4] == "ollama"     # destination

    def test_session_load_returns_dict(self, tmp_path, monkeypatch):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        session_id = cli._session_create("personal", None, "ollama")
        result = cli._session_load(session_id)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"session_id", "created_at", "identity", "project", "destination", "deleted"}

    def test_session_load_returns_none_for_missing(self, tmp_path, monkeypatch):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        assert cli._session_load("nonexistent-id") is None

    def test_session_load_excludes_deleted(self, tmp_path, monkeypatch):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        session_id = cli._session_create("personal", None, "ollama")
        conn = sqlite3.connect(str(h / "indexes" / "kage.db"))
        conn.execute("UPDATE sessions SET deleted=1 WHERE session_id=?", (session_id,))
        conn.commit()
        conn.close()
        assert cli._session_load(session_id) is None

    def test_session_append_returns_zero_for_first_turn(self, tmp_path, monkeypatch):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        session_id = cli._session_create("personal", None, "ollama")
        idx = cli._session_append(session_id, "user", "hello", [], "ollama", None, None, None)
        assert idx == 0

    def test_session_append_increments_idx(self, tmp_path, monkeypatch):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        session_id = cli._session_create("personal", None, "ollama")
        idx1 = cli._session_append(session_id, "user", "hello", [], "ollama", None, None, None)
        idx2 = cli._session_append(session_id, "assistant", "world", [], "ollama", None, None, None)
        assert idx1 == 0
        assert idx2 == 1

    def test_session_append_serializes_note_ids(self, tmp_path, monkeypatch):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        session_id = cli._session_create("personal", None, "ollama")
        cli._session_append(session_id, "user", "hello", ["n1", "n2"], "ollama", None, None, None)
        conn = sqlite3.connect(str(h / "indexes" / "kage.db"))
        raw = conn.execute("SELECT note_ids FROM session_turns WHERE session_id=?", (session_id,)).fetchone()[0]
        conn.close()
        assert json.loads(raw) == ["n1", "n2"]

    def test_session_turns_returns_chronological(self, tmp_path, monkeypatch):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        session_id = cli._session_create("personal", None, "ollama")
        for content in ("a", "b", "c"):
            cli._session_append(session_id, "user", content, [], "ollama", None, None, None)
        turns = cli._session_turns(session_id)
        assert [t["content"] for t in turns] == ["a", "b", "c"]

    def test_session_turns_token_budget_drops_oldest(self, tmp_path, monkeypatch):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        session_id = cli._session_create("personal", None, "ollama")
        content = "x" * 400
        cli._session_append(session_id, "user", content, [], "ollama", None, None, None)
        cli._session_append(session_id, "assistant", content, [], "ollama", None, None, None)
        cli._session_append(session_id, "user", content, [], "ollama", None, None, None)
        turns = cli._session_turns(session_id, token_budget=150)
        assert len(turns) < 3
        assert turns[-1]["role"] == "user"


class TestGateConversation:
    @staticmethod
    def make_turn(idx, content, note_ids=None, role="user"):
        return {
            "idx": idx, "role": role, "content": content,
            "note_ids": note_ids or [], "destination": "claude",
            "model": None, "reason": None, "tokens": None, "ts": "t",
        }

    class FakeConn:
        def execute(self, sql, params):
            self._params = list(params)
            return self
        def fetchall(self):
            return [(nid, 0) for nid in self._params]
        def close(self): pass

    def test_empty_turns_returns_empty(self):
        safe, withheld = cli._gate_conversation([], {}, "personal", None)
        assert safe == [] and withheld == []

    def test_safe_turn_no_notes(self, monkeypatch):
        turn = self.make_turn(0, "hello world")
        monkeypatch.setattr(cli, "_allowed_note_ids", lambda *a: set())
        monkeypatch.setattr(cli, "_connect", lambda: self.FakeConn())
        safe, withheld = cli._gate_conversation([turn], {}, "personal", None)
        assert safe == [turn] and withheld == []

    def test_pii_in_content_withheld(self, monkeypatch):
        turn = self.make_turn(0, "4111 1111 1111 1111")
        monkeypatch.setattr(cli, "_allowed_note_ids", lambda *a: set())
        monkeypatch.setattr(cli, "_connect", lambda: self.FakeConn())
        safe, withheld = cli._gate_conversation([turn], {}, "personal", None)
        assert safe == []
        assert len(withheld) == 1
        assert withheld[0]["turn_idx"] == 0
        assert withheld[0]["reason"] == "pii_in_content"

    def test_provenance_identity_wall_withheld(self, monkeypatch):
        turn = self.make_turn(0, "hello", note_ids=["note-x"])
        monkeypatch.setattr(cli, "_allowed_note_ids", lambda *a: set())
        monkeypatch.setattr(cli, "_connect", lambda: self.FakeConn())
        safe, withheld = cli._gate_conversation([turn], {}, "personal", None)
        assert safe == []
        assert withheld[0]["reason"].startswith("provenance:identity_wall:")

    def test_provenance_allowed_note_safe(self, monkeypatch):
        turn = self.make_turn(0, "hello", note_ids=["note-x"])
        monkeypatch.setattr(cli, "_allowed_note_ids", lambda *a: {"note-x"})
        monkeypatch.setattr(cli, "_connect", lambda: self.FakeConn())
        safe, withheld = cli._gate_conversation([turn], {}, "personal", None)
        assert safe == [turn] and withheld == []

    def test_provenance_local_only_withheld(self, monkeypatch):
        class LocalConn:
            def execute(self, sql, params): return self
            def fetchall(self): return [("note-lo", 1)]
            def close(self): pass
        turn = self.make_turn(0, "hello", note_ids=["note-lo"])
        monkeypatch.setattr(cli, "_allowed_note_ids", lambda *a: {"note-lo"})
        monkeypatch.setattr(cli, "_connect", lambda: LocalConn())
        safe, withheld = cli._gate_conversation([turn], {}, "personal", None)
        assert safe == []
        assert withheld[0]["reason"].startswith("provenance:local_only:")

    def test_multiple_turns_filtered(self, monkeypatch):
        turn0 = self.make_turn(0, "safe content")
        turn1 = self.make_turn(1, "4111 1111 1111 1111")
        turn2 = self.make_turn(2, "safe content")
        monkeypatch.setattr(cli, "_allowed_note_ids", lambda *a: set())
        monkeypatch.setattr(cli, "_connect", lambda: self.FakeConn())
        safe, withheld = cli._gate_conversation([turn0, turn1, turn2], {}, "personal", None)
        assert [t["idx"] for t in safe] == [0, 2]
        assert withheld[0]["turn_idx"] == 1
        assert withheld[0]["reason"] == "pii_in_content"

    def test_withheld_does_not_affect_other_turns(self, monkeypatch):
        turn0 = self.make_turn(0, "safe", note_ids=["bad-note"])
        turn1 = self.make_turn(1, "also safe")
        monkeypatch.setattr(cli, "_allowed_note_ids", lambda *a: set())
        monkeypatch.setattr(cli, "_connect", lambda: self.FakeConn())
        safe, withheld = cli._gate_conversation([turn0, turn1], {}, "personal", None)
        assert [t["idx"] for t in safe] == [1]
        assert withheld[0]["turn_idx"] == 0
        assert withheld[0]["reason"].startswith("provenance:identity_wall:")


class TestSessionSwitch:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch, tmp_path):
        _patch_home(monkeypatch, tmp_path / ".kage")

    def test_switch_raises_on_unknown_session(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        monkeypatch.setattr(cli, "_gate_conversation", lambda *a, **kw: ([], []))
        with pytest.raises(ValueError):
            cli._session_switch("no-such", "claude", {}, "personal", None)

    def test_switch_updates_destination_in_db(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        monkeypatch.setattr(cli, "_gate_conversation", lambda *a, **kw: ([], []))
        monkeypatch.setattr(cli, "_allowed_note_ids", lambda *a: set())
        session_id = cli._session_create("personal", None, "ollama")
        cli._session_switch(session_id, "claude", {}, "personal", None)
        conn = sqlite3.connect(str(h / "indexes" / "kage.db"))
        result = conn.execute("SELECT destination FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        conn.close()
        assert result[0] == "claude"

    def test_switch_returns_new_destination(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        monkeypatch.setattr(cli, "_gate_conversation", lambda *a, **kw: ([], []))
        session_id = cli._session_create("personal", None, "ollama")
        dest, _, _ = cli._session_switch(session_id, "groq", {}, "personal", None)
        assert dest == "groq"

    def test_switch_re_gates_turns(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        monkeypatch.setattr(cli, "_gate_conversation", lambda *a, **kw: ([{"the": "turn"}], [{"withheld": True}]))
        monkeypatch.setattr(cli, "_allowed_note_ids", lambda *a: set())
        session_id = cli._session_create("personal", None, "ollama")
        cli._session_append(session_id, "user", "hello", [], "ollama", None, None, None)
        _, safe, withheld = cli._session_switch(session_id, "claude", {}, "personal", None)
        assert safe == [{"the": "turn"}]
        assert withheld == [{"withheld": True}]

    def test_switch_no_leak_invariant(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"

        CliRunner().invoke(cli.app, ["init"])
        monkeypatch.setattr(cli, "_allowed_note_ids", lambda *a: set())
        session_id = cli._session_create("personal", None, "ollama")
        cli._session_append(session_id, "user", "4111 1111 1111 1111", [], "ollama", None, None, None)
        _, safe, withheld = cli._session_switch(session_id, "claude", {}, "personal", None)
        assert len(safe) == 0
        assert len(withheld) == 1
        assert withheld[0]["reason"] == "pii_in_content"


class TestAnswerDispatcher:
    def _fake_post(self, response: dict):
        calls = []
        def fake(url, payload, **kw):
            calls.append((url, payload))
            return response
        return fake, calls

    def test_answer_ollama_calls_api_chat(self, monkeypatch):
        fake, calls = self._fake_post({"message": {"content": "  hello  "}})
        monkeypatch.setattr(cli, "_post_json", fake)
        result = list(cli._answer("q", [], "", "ollama", {}))
        assert len(calls) == 1
        assert calls[0][0].endswith("/api/chat")
        assert result == ["hello"]

    def test_answer_ollama_includes_history(self, monkeypatch):
        fake, calls = self._fake_post({"message": {"content": "x"}})
        monkeypatch.setattr(cli, "_post_json", fake)
        history = [{"role": "user", "content": "prev", "idx": 0, "note_ids": [],
                    "destination": "ollama", "model": None, "reason": None, "tokens": None, "ts": "t"}]
        list(cli._answer("q", history, "", "ollama", {}))
        payload = calls[0][1]
        assert any(m["role"] == "user" and m["content"] == "prev" for m in payload["messages"])

    def test_answer_ollama_injects_context(self, monkeypatch):
        fake, calls = self._fake_post({"message": {"content": "x"}})
        monkeypatch.setattr(cli, "_post_json", fake)
        list(cli._answer("q", [], "some context", "ollama", {}))
        payload = calls[0][1]
        user_msgs = [m for m in payload["messages"] if m["role"] == "user"]
        assert "some context" in user_msgs[-1]["content"]
        assert "q" in user_msgs[-1]["content"]

    def test_answer_no_context_sends_raw_question(self, monkeypatch):
        fake, calls = self._fake_post({"message": {"content": "x"}})
        monkeypatch.setattr(cli, "_post_json", fake)
        list(cli._answer("my question", [], "", "ollama", {}))
        payload = calls[0][1]
        user_msgs = [m for m in payload["messages"] if m["role"] == "user"]
        assert user_msgs[-1]["content"] == "my question"

    def test_answer_yields_once(self, monkeypatch):
        fake, _ = self._fake_post({"message": {"content": "x"}})
        monkeypatch.setattr(cli, "_post_json", fake)
        assert len(list(cli._answer("q", [], "", "ollama", {}))) == 1

    def test_answer_ollama_raises_unavailable_on_error(self, monkeypatch):
        def bad_post(url, payload, **kw):
            raise urllib.error.URLError("down")
        monkeypatch.setattr(cli, "_post_json", bad_post)
        with pytest.raises(cli.OllamaUnavailable):
            list(cli._answer("q", [], "", "ollama", {}))

    def test_answer_cloud_delegates_to_call_cloud_chat(self, monkeypatch):
        monkeypatch.setattr(cli, "_call_cloud_chat", lambda *a, **kw: "cloud answer")
        assert list(cli._answer("q", [], "", "claude", {})) == ["cloud answer"]

    def test_call_cloud_chat_unknown_provider_raises(self):
        with pytest.raises(cli.CloudError):
            cli._call_cloud_chat("no-such", "sys", [], {})

    def test_call_cloud_chat_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(cli.CloudError):
            cli._call_cloud_chat("claude", "sys", [], {})


class TestCondenseQuery:
    def test_long_question_returned_unchanged(self):
        question = " ".join(["a"] * 11)
        assert cli._condense_query([], question) == question

    def test_no_leading_pronoun_returned_unchanged(self):
        question = "Tell me more about it"
        assert cli._condense_query([], question) == question

    def test_proper_noun_returned_unchanged(self):
        question = "How does Python work?"
        history = [{"role": "assistant", "content": "Some previous content"}]
        assert cli._condense_query(history, question) == question

    def test_no_assistant_history_returned_unchanged(self):
        question = "how does it work?"
        history = [{"role": "user", "content": "something"}]
        assert cli._condense_query(history, question) == question

    def test_condenses_simple_followup(self):
        question = "how does it work?"
        history = [{"role": "assistant", "content": "This is about memory storage."}]
        result = cli._condense_query(history, question)
        assert result.startswith("This is about memory storage.")
        assert " — " in result
        assert result.endswith("how does it work?")

    def test_uses_last_assistant_turn(self):
        question = "what is it?"
        history = [
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "second answer"},
        ]
        result = cli._condense_query(history, question)
        assert result.startswith("second answer")
        assert " — " in result

    def test_truncates_long_context_to_120(self):
        question = "what is it?"
        history = [{"role": "assistant", "content": "x" * 200}]
        result = cli._condense_query(history, question)
        assert len(result.split(" — ")[0]) == 120
        assert result.endswith("what is it?")

    def test_pronoun_with_punctuation(self):
        question = "It is correct?"
        history = [{"role": "assistant", "content": "Some previous content"}]
        result = cli._condense_query(history, question)
        assert " — " in result
        assert result.endswith("It is correct?")

    def test_first_word_titlecase_not_treated_as_proper_noun(self):
        question = "What is it?"
        history = [{"role": "assistant", "content": "context"}]
        result = cli._condense_query(history, question)
        assert result.startswith("context")
        assert result.endswith("What is it?")


# ── Cycle 10: kage chat cockpit (Step 7) ──────────────────────────────────────

class TestChatCommand:
    def _setup(self, tmp_path, monkeypatch):
        h = tmp_path / ".kage"
        _patch_home(monkeypatch, h)
        CliRunner().invoke(cli.app, ["init"])

    def test_chat_exits_on_slash_exit(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        seq = iter(["/exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(seq))
        result = CliRunner().invoke(cli.app, ["chat"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "[kage] bye." in result.output

    def test_chat_exits_on_eof(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        def fake_input(_):
            raise EOFError
        monkeypatch.setattr("builtins.input", fake_input)
        result = CliRunner().invoke(cli.app, ["chat"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "[kage] bye." in result.output

    def test_chat_help_lists_commands(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        seq = iter(["/help", "/exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(seq))
        result = CliRunner().invoke(cli.app, ["chat"], catch_exceptions=False)
        assert "/use" in result.output
        assert "/new" in result.output
        assert "/scope" in result.output
        assert "/sources" in result.output
        assert "/history" in result.output

    def test_chat_new_creates_fresh_session(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        seq = iter(["/new", "/exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(seq))
        result = CliRunner().invoke(cli.app, ["chat"], catch_exceptions=False)
        assert "[kage] New session:" in result.output

    def test_chat_scope_shows_identity_project(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        seq = iter(["/scope", "/exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(seq))
        result = CliRunner().invoke(cli.app, ["chat"], catch_exceptions=False)
        assert "personal" in result.output
        assert "(all)" in result.output

    def test_chat_sources_empty_on_start(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        seq = iter(["/sources", "/exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(seq))
        result = CliRunner().invoke(cli.app, ["chat"], catch_exceptions=False)
        assert "No sources from last turn." in result.output

    def test_chat_history_empty_on_start(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        seq = iter(["/history", "/exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(seq))
        result = CliRunner().invoke(cli.app, ["chat"], catch_exceptions=False)
        assert "No history yet." in result.output

    def test_chat_unknown_command(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        seq = iter(["/bogus", "/exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(seq))
        result = CliRunner().invoke(cli.app, ["chat"], catch_exceptions=False)
        assert "Unknown command" in result.output

    def test_chat_normal_turn_appends_session(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        seq = iter(["what is kage?", "/exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(seq))
        monkeypatch.setattr("kage.cli._answer", lambda question, history, context, destination, cfg: iter(["hello world"]))
        monkeypatch.setattr("kage.cli._search", lambda *args, **kwargs: [])
        result = CliRunner().invoke(cli.app, ["chat"], catch_exceptions=False)
        assert "hello world" in result.output
        assert "tok]" in result.output

    def test_chat_use_switches_destination(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        seq = iter(["/use claude", "/exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(seq))
        monkeypatch.setattr("kage.cli._session_switch", lambda session_id, new_dest, cfg, identity, project: (new_dest, [], []))
        result = CliRunner().invoke(cli.app, ["chat"], catch_exceptions=False)
        assert "Switched to claude." in result.output


# ── Cycle 10: MCP session_id (Step 8) ─────────────────────────────────────────

def test_mcp_ask_session_not_found_returns_error(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    result = asyncio.run(mcp_server.kage_ask('hello', session_id='00000000-0000-0000-0000-000000000000'))
    assert result.get('answer') is None
    assert 'error' in result
    assert result.get('session_id') == '00000000-0000-0000-0000-000000000000'


def test_mcp_ask_session_stateless_unchanged(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, '_post_json', lambda url, payload, **kw: {'response': 'stateless ok'})
    result = asyncio.run(mcp_server.kage_ask('any question'))
    assert result['answer'] == 'stateless ok'
    assert result['provider'].startswith('local:')


def test_mcp_ask_session_ollama_returns_answer(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    session_id = cli._session_create('personal', None, 'ollama')
    monkeypatch.setattr(cli, '_answer', lambda question, history, context, destination, cfg: iter(['session answer']))
    monkeypatch.setattr(cli, '_search', lambda *a, **kw: [])
    result = asyncio.run(mcp_server.kage_ask('hello', session_id=session_id))
    assert result['answer'] == 'session answer'
    assert result['session_id'] == session_id
    assert result['provider'].startswith('local:')


def test_mcp_ask_session_appends_turns_to_db(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    session_id = cli._session_create('personal', None, 'ollama')
    monkeypatch.setattr(cli, '_answer', lambda question, history, context, destination, cfg: iter(['hello back']))
    monkeypatch.setattr(cli, '_search', lambda *a, **kw: [])
    asyncio.run(mcp_server.kage_ask('hello', session_id=session_id))
    turns = cli._session_turns(session_id, token_budget=10_000_000)
    assert len(turns) == 2
    assert turns[0]['role'] == 'user'
    assert turns[1]['role'] == 'assistant'
    assert turns[1]['content'] == 'hello back'


def test_mcp_ask_session_history_threaded(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    session_id = cli._session_create('personal', None, 'ollama')
    cli._session_append(session_id, 'assistant', 'prior answer', [], 'ollama', 'qwen3:14b', None, 10)
    captured: dict = {}
    def fake_answer(question, history, context, destination, cfg):
        captured['history'] = history
        return iter(['new answer'])
    monkeypatch.setattr(cli, '_answer', fake_answer)
    monkeypatch.setattr(cli, '_search', lambda *a, **kw: [])
    asyncio.run(mcp_server.kage_ask('follow up question', session_id=session_id))
    assert len(captured['history']) >= 1
    assert any(t['role'] == 'assistant' for t in captured['history'])


# ── Cycle 10.5 — Active Context ──────────────────────────────────────────────

class TestActiveContext:
    def _setup(self, monkeypatch, tmp_path):
        h = tmp_path / ".kage"
        _patch_home(monkeypatch, h)
        CliRunner().invoke(cli.app, ["init"])
        return h

    def test_read_active_returns_empty_when_missing(self, monkeypatch, tmp_path):
        h = self._setup(monkeypatch, tmp_path)
        assert cli._read_active() == {}

    def test_read_active_returns_empty_on_corrupt_json(self, monkeypatch, tmp_path):
        h = self._setup(monkeypatch, tmp_path)
        (h / "state.json").write_text("not valid json{")
        assert cli._read_active() == {}

    def test_write_active_creates_file(self, monkeypatch, tmp_path):
        h = self._setup(monkeypatch, tmp_path)
        cli._write_active({"identity": "neu"})
        assert (h / "state.json").exists()
        assert json.loads((h / "state.json").read_text()) == {"identity": "neu"}

    def test_resolve_context_explicit_wins(self, monkeypatch, tmp_path):
        h = self._setup(monkeypatch, tmp_path)
        (h / "state.json").write_text(json.dumps({"identity": "neu", "project": "hsi"}))
        identity, project, source = cli._resolve_context("personal", "other")
        assert identity == "personal"
        assert project == "other"
        assert source == "explicit"

    def test_resolve_context_sticky(self, monkeypatch, tmp_path):
        h = self._setup(monkeypatch, tmp_path)
        (h / "state.json").write_text(json.dumps({"identity": "neu", "project": "hsi"}))
        identity, project, source = cli._resolve_context(None, None)
        assert identity == "neu"
        assert project == "hsi"
        assert source == "sticky"

    def test_resolve_context_fallback(self, monkeypatch, tmp_path):
        h = self._setup(monkeypatch, tmp_path)
        identity, project, source = cli._resolve_context(None, None)
        assert identity == "personal"
        assert project is None
        assert source == "fallback"

    def test_kage_use_sets_context(self, monkeypatch, tmp_path):
        h = self._setup(monkeypatch, tmp_path)
        r = CliRunner()
        result = r.invoke(cli.app, ["use", "neu/kaggle-capstone"])
        assert result.exit_code == 0
        state = json.loads((h / "state.json").read_text())
        assert state["identity"] == "neu"
        assert state["project"] == "kaggle-capstone"

    def test_kage_where_shows_resolved_context(self, monkeypatch, tmp_path):
        h = self._setup(monkeypatch, tmp_path)
        r = CliRunner()
        r.invoke(cli.app, ["use", "neu/kaggle-capstone"])
        result = r.invoke(cli.app, ["where"])
        assert result.exit_code == 0
        assert "neu" in result.output
        assert "sticky" in result.output

    def test_wall_holds_under_active_context(self, monkeypatch, tmp_path):
        h = self._setup(monkeypatch, tmp_path)
        cli._write_active({"identity": "neu", "project": "kaggle-capstone"})
        neu_id = cli._save("kaggle capstone note", "kaggle-capstone", identities=["neu"])
        personal_id = cli._save("personal diary entry", None, identities=["personal"])
        personal_allowed = cli._allowed_note_ids("personal", None)
        neu_allowed = cli._allowed_note_ids("neu", "kaggle-capstone")
        assert personal_id in personal_allowed
        assert neu_id not in personal_allowed
        assert neu_id in neu_allowed


class TestArmShellTransport:
    _SHELL_CFG = {
        "arms": {
            "calendar": {
                "enabled": True,
                "transport": "shell",
                "command": "icalbuddy eventsToday",
                "identity": "personal",
                "permission": "read",
            }
        }
    }

    def test_call_arm_shell_returns_stdout(self, monkeypatch):
        monkeypatch.setattr(cli, "_config", lambda: self._SHELL_CFG)
        monkeypatch.setattr(cli, "_write_audit", lambda x: None)
        mock_proc = mock.Mock()
        mock_proc.stdout = "• Test event\n"
        mock_proc.returncode = 0
        monkeypatch.setattr(cli.subprocess, "run", lambda *a, **kw: mock_proc)
        result = asyncio.run(cli._call_arm("calendar", "whats on my calendar", "personal"))
        assert result == "• Test event"

    def test_call_arm_shell_empty_command_returns_none(self, monkeypatch):
        cfg = {"arms": {"calendar": {"enabled": True, "transport": "shell", "command": "", "identity": "personal", "permission": "read"}}}
        monkeypatch.setattr(cli, "_config", lambda: cfg)
        monkeypatch.setattr(cli, "_write_audit", lambda x: None)
        result = asyncio.run(cli._call_arm("calendar", "whats on my calendar", "personal"))
        assert result is None

    def test_call_arm_shell_exception_returns_none(self, monkeypatch):
        monkeypatch.setattr(cli, "_config", lambda: self._SHELL_CFG)
        monkeypatch.setattr(cli, "_write_audit", lambda x: None)
        def raise_fnf(*a, **kw): raise FileNotFoundError()
        monkeypatch.setattr(cli.subprocess, "run", raise_fnf)
        result = asyncio.run(cli._call_arm("calendar", "whats on my calendar", "personal"))
        assert result is None

    def test_call_arm_shell_empty_stdout_returns_none(self, monkeypatch):
        monkeypatch.setattr(cli, "_config", lambda: self._SHELL_CFG)
        monkeypatch.setattr(cli, "_write_audit", lambda x: None)
        mock_proc = mock.Mock()
        mock_proc.stdout = "  "
        mock_proc.returncode = 0
        monkeypatch.setattr(cli.subprocess, "run", lambda *a, **kw: mock_proc)
        result = asyncio.run(cli._call_arm("calendar", "whats on my calendar", "personal"))
        assert result is None

    def test_check_arm_health_shell_returncode_zero(self, monkeypatch):
        monkeypatch.setattr(cli, "_config", lambda: self._SHELL_CFG)
        mock_proc = mock.Mock()
        mock_proc.returncode = 0
        monkeypatch.setattr(cli.subprocess, "run", lambda *a, **kw: mock_proc)
        result = asyncio.run(cli._check_arm_health("calendar"))
        assert result is True

    def test_check_arm_health_shell_nonzero_returncode(self, monkeypatch):
        monkeypatch.setattr(cli, "_config", lambda: self._SHELL_CFG)
        mock_proc = mock.Mock()
        mock_proc.returncode = 1
        monkeypatch.setattr(cli.subprocess, "run", lambda *a, **kw: mock_proc)
        result = asyncio.run(cli._check_arm_health("calendar"))
        assert result is False


# ── Egress golden tests (Slice 1g) ──────────────────────────────────────────
# Invariant: withheld note content must NEVER appear in runtime.cloud.complete() payloads.
# RecordingCloud replaces the live seam; all_text() concatenates every complete() call.

def test_egress_golden_clean_note_reaches_cloud(monkeypatch, tmp_path):
    """Positive control: clean note content reaches the cloud seam."""
    _save_home(monkeypatch, tmp_path)
    note_id = cli._save("safe content about databases", "proj", embed=False)
    row = (note_id, "proj", "2026-01-01T00:00:00+00:00", f"memory/{note_id}.md", "snip", None, None, None)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [row])
    monkeypatch.setattr(cli, "_config", lambda: {"require_approval": False, "cloud_provider": "claude"})
    monkeypatch.setattr(cli, "_detect_arms", lambda *a, **kw: [])
    rec = RecordingCloud()
    monkeypatch.setattr(runtime, "cloud", rec)
    CliRunner().invoke(cli.app, ["ask", "--cloud", "what do you know?"])
    assert rec.calls, "RecordingCloud should have been called"
    assert "safe content about databases" in rec.all_text()


def test_egress_golden_local_only_withheld(monkeypatch, tmp_path):
    """local_only=True note must never reach the cloud sink."""
    _save_home(monkeypatch, tmp_path)
    clean_id = cli._save("safe content about databases", "proj", embed=False)
    secret_id = cli._save("SECRET local banking PIN 9999", "proj", embed=False, local_only=True)
    clean_row = (clean_id, "proj", "2026-01-01T00:00:00+00:00", f"memory/{clean_id}.md", "snip", None, None, None)
    secret_row = (secret_id, "proj", "2026-01-01T00:00:00+00:00", f"memory/{secret_id}.md", "snip", None, None, None)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [clean_row, secret_row])
    monkeypatch.setattr(cli, "_config", lambda: {"require_approval": False, "cloud_provider": "claude"})
    monkeypatch.setattr(cli, "_detect_arms", lambda *a, **kw: [])
    rec = RecordingCloud()
    monkeypatch.setattr(runtime, "cloud", rec)
    CliRunner().invoke(cli.app, ["ask", "--cloud", "what do you know?"])
    assert rec.calls, "cloud should have been called (clean note still goes through)"
    assert "safe content about databases" in rec.all_text(), "clean note must reach cloud"
    assert "SECRET local banking PIN 9999" not in rec.all_text(), "local_only content must be withheld"


def test_egress_golden_pii_withheld(monkeypatch, tmp_path):
    """Note containing PII (UPI ID) must never reach the cloud sink."""
    _save_home(monkeypatch, tmp_path)
    clean_id = cli._save("safe content about databases", "proj", embed=False)
    pii_id = cli._save("transfer to 9876543210@ybl for payment", "proj", embed=False)
    clean_row = (clean_id, "proj", "2026-01-01T00:00:00+00:00", f"memory/{clean_id}.md", "snip", None, None, None)
    pii_row = (pii_id, "proj", "2026-01-01T00:00:00+00:00", f"memory/{pii_id}.md", "snip", None, None, None)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [clean_row, pii_row])
    monkeypatch.setattr(cli, "_config", lambda: {"require_approval": False, "cloud_provider": "claude"})
    monkeypatch.setattr(cli, "_detect_arms", lambda *a, **kw: [])
    rec = RecordingCloud()
    monkeypatch.setattr(runtime, "cloud", rec)
    CliRunner().invoke(cli.app, ["ask", "--cloud", "what do you know?"])
    assert rec.calls
    assert "safe content about databases" in rec.all_text()
    assert "9876543210@ybl" not in rec.all_text(), "PII must be withheld from cloud"


def test_egress_golden_all_withheld_no_cloud_call(monkeypatch, tmp_path):
    """When ALL notes are withheld, runtime.cloud.complete must never be called."""
    _save_home(monkeypatch, tmp_path)
    secret_id = cli._save("SECRET local banking PIN 9999", "proj", embed=False, local_only=True)
    secret_row = (secret_id, "proj", "2026-01-01T00:00:00+00:00", f"memory/{secret_id}.md", "snip", None, None, None)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [secret_row])
    monkeypatch.setattr(cli, "_config", lambda: {"require_approval": False, "cloud_provider": "claude"})
    monkeypatch.setattr(cli, "_detect_arms", lambda *a, **kw: [])
    monkeypatch.setattr(cli, "_post_json", lambda *a, **kw: {"response": "ollama fallback"})
    rec = RecordingCloud()
    monkeypatch.setattr(runtime, "cloud", rec)
    CliRunner().invoke(cli.app, ["ask", "--cloud", "what do you know?"])
    assert not rec.calls, "cloud must NOT be called when all notes are withheld"


def test_egress_golden_identity_wall_withheld(monkeypatch, tmp_path):
    """Note owned by 'work' identity must not reach cloud when querying as 'personal'."""
    _save_home(monkeypatch, tmp_path)
    clean_id = cli._save("safe content about databases", "proj", embed=False)
    work_id = cli._save("WORK SECRET confidential memo", "proj", embed=False, identities=["work"])
    clean_row = (clean_id, "proj", "2026-01-01T00:00:00+00:00", f"memory/{clean_id}.md", "snip", None, None, None)
    work_row = (work_id, "proj", "2026-01-01T00:00:00+00:00", f"memory/{work_id}.md", "snip", None, None, None)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [clean_row, work_row])
    monkeypatch.setattr(cli, "_config", lambda: {"require_approval": False, "cloud_provider": "claude"})
    monkeypatch.setattr(cli, "_detect_arms", lambda *a, **kw: [])
    rec = RecordingCloud()
    monkeypatch.setattr(runtime, "cloud", rec)
    # ask with no --identity flag → _resolve_context falls back to "personal"
    CliRunner().invoke(cli.app, ["ask", "--cloud", "what do you know?"])
    assert rec.calls, "cloud should be called (clean personal note goes through)"
    assert "safe content about databases" in rec.all_text()
    assert "WORK SECRET confidential memo" not in rec.all_text(), "cross-identity note must be withheld"


def test_egress_golden_local_only_project_withheld(monkeypatch, tmp_path):
    """Note in a local_only_projects project must not reach cloud."""
    _save_home(monkeypatch, tmp_path)
    clean_id = cli._save("safe content about databases", "proj", embed=False)
    secret_id = cli._save("classified project notes", "secret-proj", embed=False)
    clean_row = (clean_id, "proj", "2026-01-01T00:00:00+00:00", f"memory/{clean_id}.md", "snip", None, None, None)
    secret_row = (secret_id, "secret-proj", "2026-01-01T00:00:00+00:00", f"memory/{secret_id}.md", "snip", None, None, None)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [clean_row, secret_row])
    monkeypatch.setattr(cli, "_config", lambda: {
        "require_approval": False,
        "cloud_provider": "claude",
        "local_only_projects": ["secret-proj"],
    })
    monkeypatch.setattr(cli, "_detect_arms", lambda *a, **kw: [])
    rec = RecordingCloud()
    monkeypatch.setattr(runtime, "cloud", rec)
    CliRunner().invoke(cli.app, ["ask", "--cloud", "what do you know?"])
    assert rec.calls, "cloud should be called (clean note goes through)"
    assert "safe content about databases" in rec.all_text()
    assert "classified project notes" not in rec.all_text(), "local_only_projects note must be withheld"


# ponytail: chat-path and arm-context golden tests deferred.
# _gate_conversation (chat) and arm-injected context (arm_context branch) are
# untested here. The gate functions themselves have unit tests; the missing coverage
# is the full gate→sink chain for those two paths. Add when Slice 4 extracts
# privacy.py and session.py — cleaner seam to mock at that point.
