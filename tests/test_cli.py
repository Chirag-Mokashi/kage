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


def test_call_cloud_claude_uses_anthropic_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls = []
    monkeypatch.setattr(cli, "_post_json", lambda url, payload, **kw: calls.append((url, kw)) or {"content": [{"text": "ans"}]})
    result = cli._call_cloud("claude", "sys", "msg", {})
    assert result == "ans"
    assert "anthropic.com" in calls[0][0]
    assert calls[0][1]["headers"]["x-api-key"] == "test-key"


def test_call_cloud_openai_uses_bearer_auth(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "oai-key")
    calls = []
    monkeypatch.setattr(cli, "_post_json", lambda url, payload, **kw: calls.append((url, kw)) or {"choices": [{"message": {"content": "ans"}}]})
    result = cli._call_cloud("openai", "sys", "msg", {})
    assert result == "ans"
    assert "openai.com/v1/chat/completions" in calls[0][0]
    assert calls[0][1]["headers"]["Authorization"] == "Bearer oai-key"


def test_call_cloud_groq_url_has_v1_path(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    calls = []
    monkeypatch.setattr(cli, "_post_json", lambda url, payload, **kw: calls.append(url) or {"choices": [{"message": {"content": "ans"}}]})
    cli._call_cloud("groq", "sys", "msg", {})
    assert calls[0] == "https://api.groq.com/openai/v1/chat/completions"


def test_call_cloud_perplexity_url_has_no_v1(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "ppl-key")
    calls = []
    monkeypatch.setattr(cli, "_post_json", lambda url, payload, **kw: calls.append(url) or {"choices": [{"message": {"content": "ans"}}]})
    cli._call_cloud("perplexity", "sys", "msg", {})
    assert calls[0] == "https://api.perplexity.ai/chat/completions"


def test_call_cloud_gemini_key_in_url(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    calls = []
    monkeypatch.setattr(cli, "_post_json", lambda url, payload, **kw: calls.append(url) or {"candidates": [{"content": {"parts": [{"text": "ans"}]}}]})
    result = cli._call_cloud("gemini", "sys", "msg", {})
    assert result == "ans"
    assert "?key=gem-key" in calls[0]
    assert "generateContent" in calls[0]


def test_call_cloud_gemini_safety_block_raises(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.setattr(cli, "_post_json", lambda *a, **kw: {"candidates": [{}]})
    with pytest.raises(cli.CloudError):
        cli._call_cloud("gemini", "sys", "msg", {})


def test_call_cloud_user_config_partial_override_keeps_defaults(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "oai-key")
    calls = []
    monkeypatch.setattr(cli, "_post_json", lambda url, payload, **kw: calls.append(payload) or {"choices": [{"message": {"content": "ans"}}]})
    cfg = {"providers": {"openai": {"model": "gpt-4o-mini"}}}
    cli._call_cloud("openai", "sys", "msg", cfg)
    assert calls[0]["model"] == "gpt-4o-mini"


def test_call_cloud_network_error_raises_cloud_error(monkeypatch):
    import urllib.error
    monkeypatch.setenv("OPENAI_API_KEY", "oai-key")
    def bad_post(*a, **kw): raise urllib.error.URLError("timeout")
    monkeypatch.setattr(cli, "_post_json", bad_post)
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
    for attr, val in {
        "KAGE_HOME": h, "MEMORY_DIR": h / "memory",
        "INDEX_DIR": h / "indexes", "DB_PATH": h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json", "CHROMA_DIR": h / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)
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

    result = mcp_server.kage_ask("where is the eiffel tower")
    assert result["answer"] == "Paris."
    assert isinstance(result["sources"], list)
    assert result["provider"].startswith("local:")


def test_mcp_ask_with_provider(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    cli._save("dogs are mammals", "test", embed=False)

    monkeypatch.setattr(cli, "_call_cloud", lambda name, sys, msg, cfg: "Yes, dogs are mammals.")

    result = mcp_server.kage_ask("are dogs mammals", provider="claude")
    assert result["answer"] == "Yes, dogs are mammals."
    assert result["provider"] == "claude"


def test_mcp_ask_cloud_error_returns_error_message(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)

    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: (_ for _ in ()).throw(cli.CloudError("bad key")))

    result = mcp_server.kage_ask("q", provider="openai")
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

    result = mcp_server.kage_ask("what is intro")
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

    result = mcp_server.kage_ask("q")      # _read_body raises OSError → text = "" → no source
    assert result["answer"] == "fallback answer"
    assert result["sources"] == []        # OSError path (lines 67-68) — no source added


def test_mcp_ask_local_unavailable_returns_error_dict(monkeypatch, tmp_path):
    _mcp_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])

    import urllib.error
    monkeypatch.setattr(cli, "_post_json",
                        lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError("down")))

    result = mcp_server.kage_ask("q")     # local Ollama down — lines 100-101
    assert result["answer"].startswith("Local model unavailable:")
    assert result["sources"] == []
    assert result["provider"] == "local"


# ── Coverage gap fill: cli.py 82% → 100% ────────────────────────────────────

# ── init edge cases ──────────────────────────────────────────────────────────

def test_init_rerun_shows_config_existed(monkeypatch, tmp_path):
    """Line 101: re-running init on an existing store must mark config as 'exists'."""
    h = tmp_path / ".kage"
    for attr, val in {
        "KAGE_HOME": h, "MEMORY_DIR": h / "memory",
        "INDEX_DIR": h / "indexes", "DB_PATH": h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json", "CHROMA_DIR": h / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)
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
    for attr, val in {
        "KAGE_HOME": h, "MEMORY_DIR": h / "memory",
        "INDEX_DIR": h / "indexes", "DB_PATH": h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json", "CHROMA_DIR": h / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)
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
    for attr, val in {
        "KAGE_HOME": h, "MEMORY_DIR": h / "memory",
        "INDEX_DIR": h / "indexes", "DB_PATH": h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json", "CHROMA_DIR": h / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)
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
    """Lines 361-362: _config must return {} when CONFIG_PATH doesn't exist."""
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "nonexistent.json")
    assert cli._config() == {}


def test_config_returns_empty_dict_on_invalid_json(monkeypatch, tmp_path):
    """Lines 361-362: _config must return {} on JSON parse error."""
    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{")
    monkeypatch.setattr(cli, "CONFIG_PATH", bad)
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
    monkeypatch.setattr(cli, "_post_json", lambda *a, **kw: (_ for _ in ()).throw(err))
    with pytest.raises(cli.OllamaUnavailable, match="HTTP 400"):
        cli._embed("test")


def test_embed_raises_on_non_400_http_error(monkeypatch):
    """Line 468: non-400 HTTPError must re-raise as OllamaUnavailable."""
    import urllib.error as _ue
    err = _ue.HTTPError(url="http://x", code=500, msg="Server Error", hdrs={}, fp=None)
    monkeypatch.setattr(cli, "_post_json", lambda *a, **kw: (_ for _ in ()).throw(err))
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
    """Line 790: list_ -p with no matching notes must include the project name in the message."""
    _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))
    cli._save("something", "other", embed=False)
    r = CliRunner().invoke(cli.app, ["list", "-p", "missing-proj"])
    assert r.exit_code == 0
    assert "Nothing saved yet" in r.output
    assert "missing-proj" in r.output


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
    for attr, val in {
        "KAGE_HOME": h, "MEMORY_DIR": h / "memory",
        "INDEX_DIR": h / "indexes", "DB_PATH": h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json", "CHROMA_DIR": h / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)
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
    for attr, val in {
        "KAGE_HOME": h, "MEMORY_DIR": h / "memory",
        "INDEX_DIR": h / "indexes", "DB_PATH": h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json", "CHROMA_DIR": h / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)
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
    result = mcp_server.kage_ask("what is my passport?", provider="groq")
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
    result = mcp_server.kage_ask("what about Python?", provider="groq")
    assert result["withheld_count"] == 0
    assert result["answer"] == "cloud answer"


def test_mcp_kage_ask_audit_written(monkeypatch, tmp_path):
    """kage_ask MCP tool must write an audit record on every cloud dispatch."""
    from kage import mcp_server
    h = _save_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_search", lambda *a, **kw: [])
    monkeypatch.setattr(cli, "_call_cloud", lambda *a, **kw: "answer")
    mcp_server.kage_ask("q", provider="groq")
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
