"""End-to-end tests for the kage CLI.

Black-box: each test runs the real `kage` command in a subprocess with an
isolated KAGE_HOME (a temp dir), so the user's real ~/.kage is never touched.
Covers the smoke path + the two invariants that guard correctness:
the save-wall (#16) and the project partition wall (#99).
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import urllib.error

import chromadb

import pytest
from typer.testing import CliRunner

from kage import cli


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
    for attr, val in {
        "KAGE_HOME": h, "MEMORY_DIR": h / "memory",
        "INDEX_DIR": h / "indexes", "DB_PATH": h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json", "CHROMA_DIR": h / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)
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
    assert "2 note(s) not yet embedded" in result.output


def test_doctor_warns_on_embed_model_mismatch(monkeypatch, tmp_path):
    """doctor must warn when config embed_model differs from ChromaDB collection metadata."""
    h = tmp_path / ".kage"
    for attr, val in {
        "KAGE_HOME": h, "MEMORY_DIR": h / "memory",
        "INDEX_DIR": h / "indexes", "DB_PATH": h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json", "CHROMA_DIR": h / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)
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
    for attr, val in {
        "KAGE_HOME": home,
        "MEMORY_DIR": home / "memory",
        "INDEX_DIR": home / "indexes",
        "DB_PATH": home / "indexes" / "kage.db",
        "CONFIG_PATH": home / "config.json",
        "CHROMA_DIR": home / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)

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
    rows = conn.execute("SELECT needs_embed FROM memories WHERE project='bulk'").fetchall()
    conn.close()
    assert len(rows) == 2
    assert all(row[0] == 1 for row in rows)


def test_import_prints_reindex_hint(monkeypatch, tmp_path):
    """import_ must print the reindex hint after bulk import completes."""
    home = tmp_path / ".kage"
    for attr, val in {
        "KAGE_HOME": home,
        "MEMORY_DIR": home / "memory",
        "INDEX_DIR": home / "indexes",
        "DB_PATH": home / "indexes" / "kage.db",
        "CONFIG_PATH": home / "config.json",
        "CHROMA_DIR": home / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)

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
    for attr, val in {
        "KAGE_HOME": home,
        "MEMORY_DIR": home / "memory",
        "INDEX_DIR": home / "indexes",
        "DB_PATH": home / "indexes" / "kage.db",
        "CONFIG_PATH": home / "config.json",
    }.items():
        monkeypatch.setattr(cli, attr, val)

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
    def fake_fts(query, project, limit, any_terms=False):
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
    monkeypatch.setattr(cli, "_search_vec", lambda *a, **kw: [("B", "p", "t", "b.md", 0.9)])
    result = cli._search("hello", "p", 5)
    ids = [r[0] for r in result]
    assert "A" in ids
    assert "B" in ids


# ── _search_vec (Step 5) ────────────────────────────────────────────────────

def test_search_vec_returns_correct_shape(monkeypatch):
    class FakeCollection:
        def count(self): return 2
        def query(self, **kwargs):
            return {
                "ids": [["id1", "id2"]],
                "metadatas": [[
                    {"project": "p", "created_at": "t", "content_path": "c.md"},
                    {"project": "p", "created_at": "t", "content_path": "d.md"},
                ]],
                "distances": [[0.1, 0.2]],
            }

    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeCollection())
    result = cli._search_vec([0.1, 0.2], "p", 5)
    assert len(result) == 2
    assert len(result[0]) == 5   # (id, project, created_at, content_path, score)


def test_search_vec_applies_project_filter(monkeypatch):
    captured = {}

    class FakeCollection:
        def count(self): return 1
        def query(self, **kwargs):
            captured["where"] = kwargs.get("where")
            return {"ids": [["id1"]], "metadatas": [[{"project": "projA", "created_at": "t", "content_path": "c.md"}]], "distances": [[0.1]]}

    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeCollection())
    cli._search_vec([0.1], "projA", 5)
    assert captured["where"] == {"project": "projA"}


def test_search_vec_returns_empty_on_empty_collection(monkeypatch):
    class FakeCollection:
        def count(self): return 0

    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeCollection())
    assert cli._search_vec([0.1], "p", 5) == []


def test_search_vec_no_where_when_project_is_none(monkeypatch):
    captured = {}

    class FakeCollection:
        def count(self): return 1
        def query(self, **kwargs):
            captured["where"] = kwargs.get("where")
            return {"ids": [["id1"]], "metadatas": [[{"project": None, "created_at": "t", "content_path": "c.md"}]], "distances": [[0.1]]}

    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeCollection())
    cli._search_vec([0.1], None, 5)
    assert captured["where"] is None


# ── _get_chroma (Step 4) ────────────────────────────────────────────────────

def test_get_chroma_returns_collection(monkeypatch):
    class FakeCollection:
        metadata = {"embed_model": "nomic-embed-text"}

    class FakePersistentClient:
        def __init__(self, path):
            pass
        def get_or_create_collection(self, name, **kwargs):
            return FakeCollection()

    monkeypatch.setattr(chromadb, "PersistentClient", FakePersistentClient)
    result = cli._get_chroma()
    assert result.metadata == {"embed_model": "nomic-embed-text"}


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
    monkeypatch.setattr(cli, "_post_json", lambda url, payload, **kw: {"embeddings": [[0.1, 0.2, 0.3]]})
    assert cli._embed("hello") == [0.1, 0.2, 0.3]


def test_embed_truncates_long_input(monkeypatch):
    captured = {}
    def fake_post(url, payload, **kw):
        captured["payload"] = payload
        return {"embeddings": [[0.1]]}
    monkeypatch.setattr(cli, "_post_json", fake_post)
    cli._embed("x" * 40000)
    assert len(captured["payload"]["input"]) == 6000


def test_embed_raises_on_urlerror(monkeypatch):
    def raise_it(*a, **kw):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(cli, "_post_json", raise_it)
    with pytest.raises(cli.OllamaUnavailable):
        cli._embed("test")


def test_embed_raises_on_timeout(monkeypatch):
    def raise_it(*a, **kw):
        raise TimeoutError()
    monkeypatch.setattr(cli, "_post_json", raise_it)
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


def test_wal_mode_enabled(tmp_path):
    h = tmp_path / ".kage"
    run(["init"], h)
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_save_sets_needs_embed_to_0_when_ollama_up(monkeypatch, tmp_path):
    h = tmp_path / ".kage"
    for attr, val in {
        "KAGE_HOME": h, "MEMORY_DIR": h / "memory",
        "INDEX_DIR": h / "indexes", "DB_PATH": h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json",
    }.items():
        monkeypatch.setattr(cli, attr, val)
    CliRunner().invoke(cli.app, ["init"])
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1, 0.2])
    fake_coll = type("C", (), {
        "add": lambda self, **kw: None,
        "count": lambda self: 0,
        "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]},
        "delete": lambda self, **kw: None,
    })()
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)
    cli._save("some note", "test")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    result = conn.execute("SELECT needs_embed FROM memories LIMIT 1").fetchone()
    conn.close()
    assert result[0] == 0


def test_save_sets_needs_embed_to_1_when_ollama_down(monkeypatch, tmp_path):
    h = tmp_path / ".kage"
    for attr, val in {
        "KAGE_HOME": h, "MEMORY_DIR": h / "memory",
        "INDEX_DIR": h / "indexes", "DB_PATH": h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json",
    }.items():
        monkeypatch.setattr(cli, attr, val)
    CliRunner().invoke(cli.app, ["init"])
    def embed_down(*a, **kw): raise cli.OllamaUnavailable("down")
    monkeypatch.setattr(cli, "_embed", embed_down)
    cli._save("some note", "test")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    result = conn.execute("SELECT needs_embed FROM memories LIMIT 1").fetchone()
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


# ── reindex (Step 9) ────────────────────────────────────────────────────────

def _reindex_home(monkeypatch, tmp_path):
    """Set up an isolated in-process kage home and return (home, runner)."""
    h = tmp_path / ".kage"
    for attr, val in {
        "KAGE_HOME": h, "MEMORY_DIR": h / "memory",
        "INDEX_DIR": h / "indexes", "DB_PATH": h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json", "CHROMA_DIR": h / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)
    r = CliRunner()
    r.invoke(cli.app, ["init"])
    return h, r


def test_reindex_embeds_pending_notes(monkeypatch, tmp_path):
    """reindex must embed all needs_embed=1 notes and set needs_embed=0."""
    h, r = _reindex_home(monkeypatch, tmp_path)

    added = []
    fake_coll = type("C", (), {
        "add": lambda self, **kw: added.extend(kw["ids"]),
        "upsert": lambda self, **kw: None,
        "count": lambda self: 0,
        "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]},
        "delete": lambda self, **kw: None,
        "metadata": {"embed_model": "nomic-embed-text"},
    })()
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1, 0.2])
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)

    cli._save("note one", "proj", embed=False)
    cli._save("note two", "proj", embed=False)

    conn = sqlite3.connect(h / "indexes" / "kage.db")
    assert conn.execute("SELECT COUNT(*) FROM memories WHERE needs_embed=1").fetchone()[0] == 2
    conn.close()

    result = r.invoke(cli.app, ["reindex"])
    assert result.exit_code == 0

    conn = sqlite3.connect(h / "indexes" / "kage.db")
    assert conn.execute("SELECT COUNT(*) FROM memories WHERE needs_embed=1").fetchone()[0] == 0
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
        "metadata": {"embed_model": "nomic-embed-text"},
    })()
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1, 0.2])
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)

    cli._save("note", "proj", embed=False)

    assert r.invoke(cli.app, ["reindex"]).exit_code == 0
    result = r.invoke(cli.app, ["reindex"])
    assert result.exit_code == 0
    assert "nothing to reindex" in result.output


def test_reindex_force_reembeds_all(monkeypatch, tmp_path):
    """reindex --force must upsert ALL notes, not just needs_embed=1."""
    h, r = _reindex_home(monkeypatch, tmp_path)

    upserted = []
    fake_coll = type("C", (), {
        "add": lambda self, **kw: None,
        "upsert": lambda self, **kw: upserted.extend(kw["ids"]),
        "count": lambda self: 1,
        "query": lambda self, **kw: {"ids": [[]], "metadatas": [[]], "distances": [[]]},
        "delete": lambda self, **kw: None,
        "metadata": {"embed_model": "nomic-embed-text"},
    })()
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1, 0.2])
    monkeypatch.setattr(cli, "_get_chroma", lambda: fake_coll)

    # save with embed=True path mocked → needs_embed=0
    cli._save("already embedded note", "proj")

    conn = sqlite3.connect(h / "indexes" / "kage.db")
    assert conn.execute("SELECT COUNT(*) FROM memories WHERE needs_embed=0").fetchone()[0] == 1
    conn.close()

    result = r.invoke(cli.app, ["reindex", "--force"])
    assert result.exit_code == 0
    assert len(upserted) == 1


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

    Uses a real embedded ChromaDB to verify that ChromaDB's `where` filter
    actually isolates projA notes from projB — not just that the kwarg is passed.
    """
    chroma_dir = tmp_path / "chroma"
    config_path = tmp_path / "config.json"
    config_path.write_text('{"embed_model": "nomic-embed-text"}')

    monkeypatch.setattr(cli, "CHROMA_DIR", chroma_dir)
    monkeypatch.setattr(cli, "CONFIG_PATH", config_path)

    client = chromadb.PersistentClient(path=str(chroma_dir))
    coll = client.get_or_create_collection("memories", metadata={"embed_model": "nomic-embed-text"})
    coll.add(
        ids=["note-A"],
        embeddings=[[1.0, 0.0, 0.0]],
        metadatas=[{"project": "projA", "created_at": "t", "content_path": "memory/note-A.md"}],
    )
    coll.add(
        ids=["note-B"],
        embeddings=[[0.0, 1.0, 0.0]],
        metadatas=[{"project": "projB", "created_at": "t", "content_path": "memory/note-B.md"}],
    )

    result = cli._search_vec([1.0, 0.0, 0.0], "projA", 5)
    ids = [r[0] for r in result]
    assert "note-A" in ids
    assert "note-B" not in ids   # partition wall must hold in the vector path


# ── Step 12: forget vector sync ──────────────────────────────────────────────

def _step12_home(monkeypatch, tmp_path):
    """Shared helper: isolated in-process kage home, fully init'd."""
    h = tmp_path / ".kage"
    for attr, val in {
        "KAGE_HOME": h, "MEMORY_DIR": h / "memory",
        "INDEX_DIR": h / "indexes", "DB_PATH": h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json", "CHROMA_DIR": h / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)
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
    assert mem_id in deleted_ids   # vector must be removed


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
        ("note-A", "proj", "t", "memory/note-A.md", 0.95)  # float score — vec-only result
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
        ("note-X", "proj", "t", "memory/note-X.md", 0.9)  # markdown does NOT exist
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
        ("A", "p", "t", "a.md", 0.9),
        ("B", "p", "t", "b.md", 0.8),
        ("C", "p", "t", "c.md", 0.7),
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
    assert "missing file" in result.output  # warning printed
    assert mem_id not in added_ids          # ChromaDB.add must NOT be called for orphan


def test_reindex_force_uses_upsert_not_add(monkeypatch, tmp_path):
    """reindex --force must call upsert(), not add() — duplicate IDs would error on add."""
    h, r = _step12_home(monkeypatch, tmp_path)

    calls = {"add": 0, "upsert": 0}

    class FakeColl:
        metadata = {"embed_model": "nomic-embed-text"}
        def add(self, **kw): calls["add"] += 1
        def upsert(self, **kw): calls["upsert"] += 1
        def count(self): return 1
        def query(self, **kw): return {"ids": [[]], "metadatas": [[]], "distances": [[]]}
        def delete(self, **kw): pass

    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: [0.1])
    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeColl())

    cli._save("already embedded note", "proj")  # needs_embed=0 after save

    calls["add"] = calls["upsert"] = 0  # reset after save
    result = r.invoke(cli.app, ["reindex", "--force"])
    assert result.exit_code == 0
    assert calls["upsert"] == 1   # --force must use upsert
    assert calls["add"] == 0      # add must NOT be called on --force


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
