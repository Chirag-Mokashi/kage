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
    assert "chunk(s) not yet embedded" in result.output


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
    rows = conn.execute(
        "SELECT c.needs_embed FROM chunks c JOIN memories m ON m.id = c.note_id WHERE m.project='bulk'"
    ).fetchall()
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
    monkeypatch.setattr(cli, "_search_vec", lambda *a, **kw: [("B", "p", "t", "b.md", 0.9, "", 0, 10)])
    monkeypatch.setattr(cli, "_read_body", lambda *a, **kw: "body")
    result = cli._search("hello", "p", 5)
    ids = [r[0] for r in result]
    assert "A" in ids
    assert "B" in ids


# ── _search_vec (Step 5) ────────────────────────────────────────────────────

def test_search_vec_returns_correct_shape(monkeypatch):
    # v0.4: rows are 8-tuples (note_id, project, created_at, path, score, title, cs, ce)
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
    assert captured["where"] == {"project": "projA"}


def test_search_vec_returns_empty_on_empty_collection(monkeypatch):
    class FakeCollection:
        def count(self): return 0
        def get(self, where=None, include=None): return {"ids": []}

    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeCollection())
    assert cli._search_vec([0.1], "p", 5) == []


def test_search_vec_no_where_when_project_is_none(monkeypatch):
    captured = {}

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
    assert captured["where"] is None


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
    mem_id = cli._save("some note", "test")
    conn = sqlite3.connect(h / "indexes" / "kage.db")
    # v0.4: embed status lives in chunks.needs_embed, not memories.needs_embed
    vals = [r[0] for r in conn.execute("SELECT needs_embed FROM chunks WHERE note_id=?", (mem_id,)).fetchall()]
    conn.close()
    assert all(v == 0 for v in vals)


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
    for attr, val in {
        "KAGE_HOME": h, "MEMORY_DIR": h / "memory",
        "INDEX_DIR": h / "indexes", "DB_PATH": h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json", "CHROMA_DIR": h / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)
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
    monkeypatch.setattr(cli, "_get_chroma", lambda: _fake_vec_coll([], [], [], total_count=0))
    assert cli._search_vec([0.1, 0.2], None, 10) == []


def test_search_vec_returns_8_tuples(monkeypatch):
    meta = {"note_id": "n1", "project": "proj", "created_at": "t", "content_path": "p.md",
            "section_title": "Intro", "char_start": 0, "char_end": 100}
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
    monkeypatch.setattr(cli, "_get_chroma", lambda: _fake_vec_coll(
        ["n1_c0", "n2_c0"], [meta_a, meta_b], [0.1, 0.2]
    ))
    result = cli._search_vec([0.1], None, 10)
    assert len(result) == 2


def test_search_vec_per_project_count_uses_get_not_count(monkeypatch):
    # count() returns 10, but per-project get() returns only 1 id
    # → n_results passed to query must be 1 (min(limit, 1)), not 10
    meta = {"note_id": "n1", "project": "proj", "created_at": "t", "content_path": "f.md",
            "section_title": "", "char_start": 0, "char_end": 50}
    queried_n = []

    class Coll:
        def count(self): return 10
        def get(self, where=None, include=None): return {"ids": ["n1_c0"]}
        def query(self, query_embeddings=None, n_results=None, where=None, include=None):
            queried_n.append(n_results)
            return {"ids": [["n1_c0"]], "metadatas": [[meta]], "distances": [[0.1]]}

    monkeypatch.setattr(cli, "_get_chroma", lambda: Coll())
    cli._search_vec([0.1], "proj", 10)
    assert queried_n[0] == 1   # capped at per-project count, not total count


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

    Uses a real embedded ChromaDB to verify that ChromaDB's `where` filter
    actually isolates projA notes from projB — not just that the kwarg is passed.
    """
    chroma_dir = tmp_path / "chroma"
    config_path = tmp_path / "config.json"
    config_path.write_text('{"embed_model": "nomic-embed-text"}')

    monkeypatch.setattr(cli, "CHROMA_DIR", chroma_dir)
    monkeypatch.setattr(cli, "CONFIG_PATH", config_path)

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
