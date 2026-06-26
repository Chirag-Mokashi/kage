"""Tests for kage.librarian (Cycle 15, v0.16.0) — Layer 1 unit tests, no live LLM.

Isolation: every DB-touching test uses lib_env which patches runtime.store and
runtime.config to a temp directory, so ~/.kage is never touched.
"""

import os
import pytest
from unittest.mock import MagicMock

from kage import runtime
from kage.config import Config
from kage.store import Store
from kage.librarian import (
    _apply_migrations, _connect, _acquire_lockfile, _release_lockfile,
    _gate_text, distill_and_judge, ApprovalRequest,
    deposit_to_queue, request_approval, write_note, reject_approval,
    get_catalog_stats, _LOCKFILE,
)


@pytest.fixture
def lib_env(monkeypatch, tmp_path):
    """Isolated kage home — patches runtime.store and runtime.config to temp dir.
    Calls _apply_migrations so librarian tables (staging_queue, approval_queue,
    new columns) are present before any test touches the DB."""
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


def test_schema_migration_idempotent(lib_env):
    """_apply_migrations must be safe to call multiple times — idempotency is
    guaranteed by CREATE TABLE IF NOT EXISTS and try/except around ALTER TABLE.
    Core invariant: startup never fails on an existing DB."""
    conn = _connect()
    _apply_migrations(conn)  # second call
    _apply_migrations(conn)  # third call
    conn.close()


def test_deposit_idempotent(lib_env):
    """Depositing the same content twice returns the same staging id and leaves
    exactly one row — enforced by UNIQUE constraint on content_hash."""
    id1 = deposit_to_queue("the sky is blue", "scout")
    id2 = deposit_to_queue("the sky is blue", "scout")
    assert id1 == id2, "duplicate content must return same id"
    conn = _connect()
    count = conn.execute("SELECT COUNT(*) FROM staging_queue").fetchone()[0]
    conn.close()
    assert count == 1


def test_deposit_different_content(lib_env):
    """Two distinct content strings produce two staging_queue rows with different ids."""
    id1 = deposit_to_queue("fact A", "scout")
    id2 = deposit_to_queue("fact B", "scout")
    assert id1 != id2
    conn = _connect()
    count = conn.execute("SELECT COUNT(*) FROM staging_queue").fetchone()[0]
    conn.close()
    assert count == 2


def test_lockfile_stale_pid_cleanup():
    """_acquire_lockfile must reclaim a lockfile whose PID is dead.
    PID 99999 is extremely unlikely to be alive on any real system."""
    _LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
    _LOCKFILE.write_text("99999")
    try:
        acquired = _acquire_lockfile()
        assert acquired, "should reclaim stale lockfile (dead PID)"
        assert _LOCKFILE.exists()
        assert int(_LOCKFILE.read_text()) == os.getpid()
    finally:
        _release_lockfile()


def test_lockfile_live_pid_blocked():
    """_acquire_lockfile returns False when our own PID holds the lockfile.
    os.kill(os.getpid(), 0) succeeds, so the lock appears live."""
    _LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
    _LOCKFILE.write_text(str(os.getpid()))
    try:
        acquired = _acquire_lockfile()
        assert not acquired, "should not acquire when own PID holds the lock"
    finally:
        _release_lockfile()


def test_gate_text_strips_email():
    """_gate_text must redact email addresses before cloud dispatch.
    This is the first line of 3e privacy defence."""
    out = _gate_text("contact me at foo@bar.com for details", {})
    assert "foo@bar.com" not in out
    assert "[REDACTED_PII]" in out


def test_gate_text_clean_passthrough():
    """Clean text with no PII must pass through _gate_text unchanged."""
    original = "The eiffel tower is 330 metres tall."
    assert _gate_text(original, {}) == original


def test_gate_called_unconditionally(lib_env, monkeypatch):
    """_gate_text must be called on every distill_and_judge invocation — no bypass.
    Verified by patching _gate_text in the librarian namespace and asserting call count.
    A skip_gate parameter or env-var bypass would be a 3e violation."""
    import kage.librarian as _lib
    gate_calls = []

    def fake_gate(content, cfg):
        gate_calls.append(content)
        return content  # pass-through — just record the call

    monkeypatch.setattr(_lib, "_gate_text", fake_gate)

    class FakeCloud:
        def complete(self, *a, **kw):
            raise RuntimeError("cloud offline")

    monkeypatch.setattr(runtime, "cloud", FakeCloud())
    _lib.distill_and_judge("test content", "scout")
    assert len(gate_calls) == 1, f"expected 1 gate call, got {len(gate_calls)}"


def test_distill_and_judge_cloud_error_returns_hold(lib_env, monkeypatch):
    """Cloud failure must produce a safe HOLD result, never crash.
    Crashing would silently drop staging items with no user-visible signal."""
    class FakeCloud:
        def complete(self, *a, **kw):
            raise RuntimeError("simulated failure")

    monkeypatch.setattr(runtime, "cloud", FakeCloud())
    result = distill_and_judge("some content", "scout")
    assert result["quality"] == "HOLD"
    assert "dedup" in result
    assert "note" in result
    assert result["dedup"]["verdict"] == "DISTINCT"


def test_approval_request_dataclass():
    """ApprovalRequest fields must be accessible as named attributes, not dict keys.
    This is the typed contract between distill_and_judge output and the CLI card."""
    r = ApprovalRequest(id="x", action="promote", reason="test",
                        sanitized_preview="...", created_at="now")
    assert r.id == "x"
    assert r.action == "promote"
    assert r.reason == "test"


def test_request_approval_inserts_row(lib_env):
    """request_approval must insert into approval_queue and set staging status to
    'held' so the item is not re-processed on the next Librarian run."""
    staging_id = deposit_to_queue("a notable fact", "scout")
    note_json = {"title": "Notable Fact", "body": "A fact.", "tags": [],
                 "project": None, "identity": "personal", "source": "scout"}
    approval_id = request_approval(staging_id, "promote", "durable", note_json, "A fact.")
    assert approval_id
    conn = _connect()
    row = conn.execute("SELECT action FROM approval_queue WHERE id=?", (approval_id,)).fetchone()
    sq = conn.execute("SELECT status FROM staging_queue WHERE id=?", (staging_id,)).fetchone()
    conn.close()
    assert row is not None and row[0] == "promote"
    assert sq[0] == "held"


def test_write_note_writes_db_and_file(lib_env, monkeypatch):
    """write_note must INSERT into memories (DB-first) then create the markdown file.
    DB-first invariant: stale pointer (file missing) surfaces in kage reindex;
    a ghost file (no DB row) is undetectable and permanent."""
    monkeypatch.setattr(runtime, "embed",
                        type("E", (), {"embed": lambda self, *a, **kw: [0.1] * 384})())
    fake_coll = MagicMock()
    monkeypatch.setattr(runtime, "vector",
                        type("V", (), {"collection": lambda self, *a, **kw: fake_coll})())

    staging_id = deposit_to_queue("Paris is the capital of France", "scout")
    note_json = {"title": "Paris Capital Of France",
                 "body": "Paris is the capital of France.",
                 "tags": ["geo"], "project": None, "identity": "personal", "source": "scout"}
    approval_id = request_approval(staging_id, "promote", "geo fact", note_json,
                                   "Paris is the capital of France.")
    ok = write_note(approval_id)
    assert ok is True

    conn = _connect()
    row = conn.execute("SELECT id, state FROM memories WHERE source='scout'").fetchone()
    conn.close()
    assert row is not None, "memories row not written"
    mem_path = lib_env / "memory" / f"{row[0]}.md"
    assert mem_path.exists(), f"file not created at {mem_path}"
    assert "Paris Capital Of France" in mem_path.read_text()


def test_reject_approval_updates_queues(lib_env):
    """reject_approval must mark approval_queue decision='rejected' and update the
    linked staging_queue row. Returns True when the approval id exists."""
    staging_id = deposit_to_queue("rejected content", "user")
    note_json = {"title": "N", "body": "B", "tags": [], "project": None,
                 "identity": "personal", "source": "user"}
    approval_id = request_approval(staging_id, "promote", "test", note_json, "B")
    ok = reject_approval(approval_id, "not relevant")
    assert ok is True
    conn = _connect()
    aq = conn.execute("SELECT decision FROM approval_queue WHERE id=?", (approval_id,)).fetchone()
    sq = conn.execute("SELECT status FROM staging_queue WHERE id=?", (staging_id,)).fetchone()
    conn.close()
    assert aq[0] == "rejected"
    assert sq[0] == "rejected"


def test_write_note_inherits_project_from_staging(lib_env, monkeypatch):
    """write_note must copy project/identity from the staging row when note_json lacks them.
    distill_and_judge only returns {body, title, tags} — without this, every promoted note
    lands as project=None/identity=personal regardless of its actual partition context."""
    monkeypatch.setattr(runtime, "embed",
                        type("E", (), {"embed": lambda self, *a, **kw: [0.1] * 384})())
    monkeypatch.setattr(runtime, "vector",
                        type("V", (), {"collection": lambda self, *a, **kw: MagicMock()})())

    staging_id = deposit_to_queue("project-scoped fact", "scout",
                                  project="kage", identity="work")
    # note_json as distill_and_judge produces it — no project/identity
    note_json = {"title": "Project Scoped Fact", "body": "A work fact.",
                 "tags": ["kage"], "source": "scout"}
    approval_id = request_approval(staging_id, "promote", "scoped fact", note_json, "A work fact.")
    ok = write_note(approval_id)
    assert ok is True

    conn = _connect()
    row = conn.execute("SELECT project, id FROM memories ORDER BY rowid DESC LIMIT 1").fetchone()
    conn.close()
    assert row[0] == "kage", f"project not inherited from staging: {row[0]}"


def test_write_note_idempotent(lib_env, monkeypatch):
    """Calling write_note twice with the same approval_id must not create two notes.
    Second call must return True (idempotent) without inserting a duplicate memories row."""
    monkeypatch.setattr(runtime, "embed",
                        type("E", (), {"embed": lambda self, *a, **kw: [0.1] * 384})())
    monkeypatch.setattr(runtime, "vector",
                        type("V", (), {"collection": lambda self, *a, **kw: MagicMock()})())

    staging_id = deposit_to_queue("idempotency test fact", "scout")
    note_json = {"title": "Idempotency Test", "body": "Test body.", "tags": []}
    approval_id = request_approval(staging_id, "promote", "test", note_json, "Test body.")
    ok1 = write_note(approval_id)
    ok2 = write_note(approval_id)
    assert ok1 is True
    assert ok2 is True  # second call: idempotent, not crash

    conn = _connect()
    count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    conn.close()
    assert count == 1, f"double-call created {count} notes instead of 1"


def test_discard_staging_item(lib_env):
    """discard_staging_item must set staging_queue.status='discarded' so the item
    is not re-processed on subsequent Librarian runs. Returns True when id exists."""
    from kage.librarian import discard_staging_item
    staging_id = deposit_to_queue("ephemeral todo item", "session")
    ok = discard_staging_item(staging_id)
    assert ok is True
    conn = _connect()
    row = conn.execute("SELECT status FROM staging_queue WHERE id=?", (staging_id,)).fetchone()
    conn.close()
    assert row[0] == "discarded"


def test_annotate_tags_additive(lib_env, monkeypatch):
    """annotate_memory with field='tags' must APPEND the new tag, not replace existing ones.
    Tags are comma-separated in the DB and in frontmatter."""
    from kage.librarian import annotate_memory
    from unittest.mock import MagicMock

    monkeypatch.setattr(runtime, "embed",
                        type("E", (), {"embed": lambda self, *a, **kw: [0.1] * 384})())
    monkeypatch.setattr(runtime, "vector",
                        type("V", (), {"collection": lambda self, *a, **kw: MagicMock()})())

    staging_id = deposit_to_queue("Tagged fact", "scout")
    note_json = {"title": "Tagged Fact", "body": "Some body text.",
                 "tags": ["original"], "project": None, "identity": "personal", "source": "scout"}
    approval_id = request_approval(staging_id, "promote", "test", note_json, "Some body text.")
    write_note(approval_id)

    conn = _connect()
    row = conn.execute("SELECT id, tags FROM memories WHERE source='scout'").fetchone()
    conn.close()
    note_id, original_tags = row
    assert "original" in original_tags

    ok = annotate_memory(note_id, "tags", "new-tag")
    assert ok is True

    conn = _connect()
    updated = conn.execute("SELECT tags FROM memories WHERE id=?", (note_id,)).fetchone()[0]
    conn.close()
    assert "original" in updated, f"original tag lost after annotate: {updated}"
    assert "new-tag" in updated, f"new tag not added: {updated}"

    # Verify frontmatter also has both tags
    mem_path = lib_env / "memory" / f"{note_id}.md"
    content = mem_path.read_text()
    assert "original" in content
    assert "new-tag" in content


def test_get_catalog_stats_returns_expected_keys(lib_env):
    """get_catalog_stats must return the four keys that kage status and
    kage librarian status both depend on. A missing key is a contract violation."""
    stats = get_catalog_stats()
    for key in ("note_count", "queue_depth", "last_run", "notes_by_source"):
        assert key in stats, f"missing key: {key}"
    assert isinstance(stats["note_count"], int)
    assert isinstance(stats["queue_depth"], int)
    assert isinstance(stats["notes_by_source"], dict)
