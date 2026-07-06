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
    get_catalog_stats, get_staging_queue, _LOCKFILE, _DISTILL_SYSTEM,
    _emit_ctm_note, _retrieve_ctm, list_pending_approvals,
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
    assert "[EMAIL_1]" in out


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
    row = conn.execute(
        "SELECT project, id FROM memories"
        " WHERE (project != 'kage-ctm-librarian' OR project IS NULL)"
        " ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
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
    count = conn.execute(
        "SELECT COUNT(*) FROM memories"
        " WHERE (project != 'kage-ctm-librarian' OR project IS NULL)"
    ).fetchone()[0]
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


def test_librarian_uses_cloud_provider_key(lib_env, monkeypatch, tmp_path):
    """distill_and_judge must resolve provider from cloud_provider, not default_provider."""
    import json as _json
    from unittest.mock import MagicMock
    from kage import librarian, runtime

    # Write config.json with cloud_provider but NO default_provider key
    (tmp_path / ".kage" / "config.json").write_text(
        _json.dumps({"cloud_provider": "openrouter-free"})
    )

    captured = {}
    def fake_complete(provider, _system, _messages, _cfg):
        captured["provider"] = provider
        return '{"decision": "promote", "reason": "test", "tags": []}'

    fake_cloud = MagicMock()
    fake_cloud.complete.side_effect = fake_complete
    monkeypatch.setattr(runtime, "cloud", fake_cloud)

    librarian.distill_and_judge("some content", "scout")

    assert captured.get("provider") == "openrouter-free"


def test_get_staging_queue_without_monitor_migration(lib_env):
    """get_staging_queue must not raise on a fresh DB where Monitor never ran."""
    # lib_env already called librarian._apply_migrations via _connect() internally.
    # Monitor's _apply_migrations is intentionally NOT called here.
    from kage.librarian import get_staging_queue
    result = get_staging_queue()   # must not raise sqlite3.OperationalError
    assert isinstance(result, list)


def test_get_staging_queue_respects_batch_size(lib_env):
    """get_staging_queue must cap results at librarian.batch_size from config."""
    import json as _json
    # Write config with batch_size=3
    (lib_env / "config.json").write_text(_json.dumps({"librarian": {"batch_size": 3}}))
    # Deposit 5 items
    for i in range(5):
        deposit_to_queue(f"item {i}", "test")
    result = get_staging_queue()
    assert len(result) == 3


def test_distill_and_judge_sleeps_with_delay(lib_env, monkeypatch):
    """distill_and_judge must call time.sleep(delay_seconds) when configured."""
    import json as _json
    import kage.librarian as _lib
    from unittest.mock import MagicMock
    from kage import runtime

    # Write config with delay_seconds=2
    (lib_env / "config.json").write_text(
        _json.dumps({"librarian": {"delay_seconds": 2}, "cloud_provider": "openrouter-free"})
    )

    # Mock cloud to return valid JSON
    fake_cloud = MagicMock()
    fake_cloud.complete.return_value = '{"decision": "promote", "reason": "test", "tags": []}'
    monkeypatch.setattr(runtime, "cloud", fake_cloud)

    # Capture sleep calls
    sleep_calls = []
    monkeypatch.setattr(_lib.time, "sleep", lambda s: sleep_calls.append(s))

    _lib.distill_and_judge("some content", "scout")

    assert sleep_calls == [2]


def test_librarian_gate_applies_vault_pattern(lib_env, monkeypatch):
    """librarian._gate_text must redact vault patterns without leaking the label (B3)."""
    import json as _json
    import pathlib

    (lib_env / "sensitive.json").write_text(_json.dumps({
        "patterns": [{"id": "cc3dd4ee", "label": "employer-name", "pattern": r"Initech", "added_at": "2026-06-29"}]
    }))
    home = lib_env.parent
    monkeypatch.setattr(pathlib.Path, "home", lambda: home)

    from kage.librarian import _gate_text
    result = _gate_text("I work at Initech on a secret project", {})

    assert "[REDACTED_1]" in result          # B3 fix: label never leaks
    assert "Initech" not in result
    assert "SENSITIVE" not in result and "employer-name" not in result


# ── Cycle 24 — EPM: rejection correction notes + distill_and_judge prepend ──

_VALID_JSON_EPM = (
    '{"dedup":{"verdict":"DISTINCT"},"contradiction":{"found":false},'
    '"quality":"HOLD","reason":"r","note":{"title":"T","body":"B","tags":[]},"staleness":[]}'
)


def test_reject_approval_emits_correction_note(lib_env):
    import pathlib
    staging_id = deposit_to_queue("rejected content", "user")
    note_json = {"title": "Bad PROMOTE", "body": "B", "tags": [], "project": None,
                 "identity": "personal", "source": "scout"}
    approval_id = request_approval(staging_id, "promote", "test", note_json, "B")
    ok = reject_approval(approval_id, "title was wrong")
    assert ok is True
    conn = _connect()
    rows = conn.execute(
        "SELECT id, content_path FROM memories WHERE project=?",
        ("kage-corrections-librarian",),
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    content = (pathlib.Path(runtime.config.home) / rows[0][1]).read_text()
    assert "Correction log — Librarian rejection:" in content
    assert "Bad PROMOTE" in content
    assert "title was wrong" in content


def test_reject_approval_missing_id_no_note(lib_env):
    ok = reject_approval("nonexistent-id", "reason")
    assert ok is False
    conn = _connect()
    count = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE project=?",
        ("kage-corrections-librarian",),
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_distill_and_judge_prepends_learned_rules(lib_env, monkeypatch):
    import json
    import pathlib
    learned = {
        "librarian": {
            "active": "v1",
            "versions": {
                "v1": {
                    "prompt": "- Never promote stale content",
                    "date": "2026-07-01",
                    "correction_count": 3,
                    "source_note_ids": [],
                    "trace": "",
                }
            },
        }
    }
    (lib_env / "learned_prompts.json").write_text(json.dumps(learned))
    (lib_env / "config.json").write_text(json.dumps({"cloud_provider": "claude"}))
    captured = {}

    def fake_complete(provider, system, messages, cfg):
        captured["system"] = system
        return _VALID_JSON_EPM

    monkeypatch.setattr(runtime.cloud, "complete", fake_complete)
    distill_and_judge("some content", "manual")
    assert "[kage learned librarian rules]" in captured["system"]
    assert "Never promote stale content" in captured["system"]
    assert _DISTILL_SYSTEM in captured["system"]


def test_distill_and_judge_no_learned_rules_unchanged(lib_env, monkeypatch):
    import json
    (lib_env / "config.json").write_text(json.dumps({"cloud_provider": "claude"}))
    captured = {}

    def fake_complete(provider, system, messages, cfg):
        captured["system"] = system
        return _VALID_JSON_EPM

    monkeypatch.setattr(runtime.cloud, "complete", fake_complete)
    distill_and_judge("content", "manual")
    assert captured["system"] == _DISTILL_SYSTEM


def test_distill_and_judge_epm_disabled_skips_rules(lib_env, monkeypatch):
    import json
    (lib_env / "learned_prompts.json").write_text(json.dumps({
        "librarian": {
            "active": "v1",
            "versions": {
                "v1": {
                    "prompt": "- Never skip review",
                    "date": "2026-07-01",
                    "correction_count": 3,
                    "source_note_ids": [],
                    "trace": "",
                }
            },
        }
    }))
    (lib_env / "config.json").write_text(json.dumps({
        "cloud_provider": "claude",
        "librarian": {"learning": {"epm_enabled": False}},
    }))
    captured = {}

    def fake_complete(provider, system, messages, cfg):
        captured["system"] = system
        return _VALID_JSON_EPM

    monkeypatch.setattr(runtime.cloud, "complete", fake_complete)
    distill_and_judge("some content", "manual")
    assert captured["system"] == _DISTILL_SYSTEM


# ── Cycle 25 CTM tests ────────────────────────────────────────────────────────

def test_write_note_emits_ctm_note(lib_env, monkeypatch):
    """write_note must emit exactly 1 CTM precedent row in memories after approval."""
    monkeypatch.setattr(runtime, "embed", type("E", (), {"embed": lambda self, *a, **kw: [0.1]*384})())
    monkeypatch.setattr(runtime, "vector", type("V", (), {"collection": lambda self, *a, **kw: MagicMock()})())
    staging_id = deposit_to_queue("a notable insight", "scout")
    note_json = {"title": "Notable Insight", "body": "Something useful.", "tags": []}
    approval_id = request_approval(staging_id, "promote", "good note", note_json, "Something useful.")
    ok = write_note(approval_id)
    assert ok is True
    conn = _connect()
    rows = conn.execute("SELECT id, content_path FROM memories WHERE project='kage-ctm-librarian'").fetchall()
    conn.close()
    assert len(rows) == 1
    content = (lib_env / rows[0][1]).read_text()
    assert "CTM log — Librarian approval:" in content


def test_write_note_double_approve_no_duplicate_ctm(lib_env, monkeypatch):
    """Calling write_note twice must produce only 1 CTM note (idempotency)."""
    monkeypatch.setattr(runtime, "embed", type("E", (), {"embed": lambda self, *a, **kw: [0.1]*384})())
    monkeypatch.setattr(runtime, "vector", type("V", (), {"collection": lambda self, *a, **kw: MagicMock()})())
    staging_id = deposit_to_queue("double test", "scout")
    note_json = {"title": "Double Test", "body": "body", "tags": []}
    approval_id = request_approval(staging_id, "promote", "r", note_json, "body")
    write_note(approval_id)
    write_note(approval_id)
    conn = _connect()
    count = conn.execute("SELECT COUNT(*) FROM memories WHERE project='kage-ctm-librarian'").fetchone()[0]
    conn.close()
    assert count == 1


def test_write_note_emit_failure_does_not_abort(lib_env, monkeypatch):
    """If _emit_ctm_note raises, write_note must still return True and write the main note."""
    monkeypatch.setattr(runtime, "embed", type("E", (), {"embed": lambda self, *a, **kw: [0.1]*384})())
    monkeypatch.setattr(runtime, "vector", type("V", (), {"collection": lambda self, *a, **kw: MagicMock()})())
    monkeypatch.setattr("kage.librarian._emit_ctm_note", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("ctm boom")))
    staging_id = deposit_to_queue("resilience test", "scout")
    note_json = {"title": "Resilience Test", "body": "body", "tags": []}
    approval_id = request_approval(staging_id, "promote", "r", note_json, "body")
    ok = write_note(approval_id)
    assert ok is True
    conn = _connect()
    count = conn.execute("SELECT COUNT(*) FROM memories WHERE (project != 'kage-ctm-librarian' OR project IS NULL)").fetchone()[0]
    conn.close()
    assert count == 1


def test_retrieve_ctm_empty_db_returns_empty(lib_env):
    """_retrieve_ctm must return [] when no CTM notes exist."""
    result = _retrieve_ctm("some content", {}, lib_env)
    assert result == []


def test_retrieve_ctm_skips_missing_file(lib_env):
    """_retrieve_ctm must return [] without raising when DB row exists but file is absent."""
    import uuid
    from datetime import datetime
    note_id = str(uuid.uuid4())
    rel_path = f"memory/{note_id}.md"  # intentionally not written to disk
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = _connect()
    conn.execute(
        "INSERT INTO memories (id, content_path, project, created_at, local_only, needs_embed, state)"
        " VALUES (?, ?, 'kage-ctm-librarian', ?, 0, 0, 'baseline')",
        (note_id, rel_path, ts),
    )
    conn.execute("INSERT INTO memory_fts (id, body) VALUES (?, ?)", (note_id, "CTM log"))
    conn.commit()
    conn.close()
    result = _retrieve_ctm("content", {}, lib_env)
    assert result == []


def test_retrieve_ctm_returns_recent_notes(lib_env):
    """_retrieve_ctm must return up to max_examples most recent CTM notes."""
    import uuid
    from datetime import datetime
    conn = _connect()
    for i in range(4):
        note_id = str(uuid.uuid4())
        rel_path = f"memory/{note_id}.md"
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        body = f"CTM log — Librarian approval: Note {i}. Source: scout. Action: PROMOTE. Reason: good."
        conn.execute(
            "INSERT INTO memories (id, content_path, project, created_at, local_only, needs_embed, state)"
            " VALUES (?, ?, 'kage-ctm-librarian', ?, 0, 0, 'baseline')",
            (note_id, rel_path, ts),
        )
        conn.execute("INSERT INTO memory_fts (id, body) VALUES (?, ?)", (note_id, body))
        conn.commit()
        fp = lib_env / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(f"---\nid: {note_id}\n---\n\n{body}\n")
    conn.close()
    result = _retrieve_ctm("content", {}, lib_env, max_examples=3)
    assert len(result) == 3
    for r in result:
        assert "CTM log" in r


def test_retrieve_ctm_gates_pii_before_returning(lib_env):
    """_retrieve_ctm must strip email addresses from CTM note content before returning."""
    import uuid
    from datetime import datetime
    note_id = str(uuid.uuid4())
    rel_path = f"memory/{note_id}.md"
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    body = (
        "CTM log — Librarian approval: contact note. Source: user. Action: PROMOTE. "
        "Reason: promoted for user@test.com."
    )
    conn = _connect()
    conn.execute(
        "INSERT INTO memories (id, content_path, project, created_at, local_only, needs_embed, state)"
        " VALUES (?, ?, 'kage-ctm-librarian', ?, 0, 0, 'baseline')",
        (note_id, rel_path, ts),
    )
    conn.execute("INSERT INTO memory_fts (id, body) VALUES (?, ?)", (note_id, body))
    conn.commit()
    conn.close()
    fp = lib_env / rel_path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(f"---\nid: {note_id}\n---\n\n{body}\n")
    result = _retrieve_ctm("content", {}, lib_env)
    assert len(result) == 1
    assert "user@test.com" not in result[0]
    assert "[EMAIL_1]" in result[0]


def test_distill_and_judge_injects_ctm_when_present(lib_env, monkeypatch):
    """distill_and_judge must prepend CTM precedents AND EPM rules; CTM index < EPM index."""
    import json, uuid
    from datetime import datetime
    note_id = str(uuid.uuid4())
    rel_path = f"memory/{note_id}.md"
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    body = "CTM log — Librarian approval: Good example. Source: scout. Action: PROMOTE. Reason: clear."
    conn = _connect()
    conn.execute(
        "INSERT INTO memories (id, content_path, project, created_at, local_only, needs_embed, state)"
        " VALUES (?, ?, 'kage-ctm-librarian', ?, 0, 0, 'baseline')",
        (note_id, rel_path, ts),
    )
    conn.execute("INSERT INTO memory_fts (id, body) VALUES (?, ?)", (note_id, body))
    conn.commit()
    conn.close()
    fp = lib_env / rel_path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(f"---\nid: {note_id}\n---\n\n{body}\n")
    (lib_env / "learned_prompts.json").write_text(json.dumps({
        "librarian": {"active": "v1", "versions": {"v1": {
            "prompt": "- Always check sources", "date": "2026-07-01",
            "correction_count": 5, "source_note_ids": [], "trace": "",
        }}}
    }))
    (lib_env / "config.json").write_text(json.dumps({"cloud_provider": "claude"}))
    captured = {}

    def fake_complete(provider, system, messages, cfg):
        captured["system"] = system
        return _VALID_JSON_EPM

    monkeypatch.setattr(runtime.cloud, "complete", fake_complete)
    distill_and_judge("test content", "manual")
    assert "[kage CTM precedents]" in captured["system"]
    assert "[kage learned librarian rules]" in captured["system"]
    assert captured["system"].index("[kage CTM precedents]") < captured["system"].index("[kage learned librarian rules]")


def test_distill_and_judge_ctm_disabled_skips_retrieval(lib_env, monkeypatch):
    """When ctm_enabled=False, CTM precedents must NOT appear in the system prompt."""
    import json, uuid
    from datetime import datetime
    note_id = str(uuid.uuid4())
    rel_path = f"memory/{note_id}.md"
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    body = "CTM log — Librarian approval: Should not appear. Source: scout. Action: PROMOTE. Reason: test."
    conn = _connect()
    conn.execute(
        "INSERT INTO memories (id, content_path, project, created_at, local_only, needs_embed, state)"
        " VALUES (?, ?, 'kage-ctm-librarian', ?, 0, 0, 'baseline')",
        (note_id, rel_path, ts),
    )
    conn.execute("INSERT INTO memory_fts (id, body) VALUES (?, ?)", (note_id, body))
    conn.commit()
    conn.close()
    fp = lib_env / rel_path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(f"---\nid: {note_id}\n---\n\n{body}\n")
    (lib_env / "config.json").write_text(json.dumps({
        "cloud_provider": "claude",
        "librarian": {"learning": {"ctm_enabled": False}},
    }))
    captured = {}

    def fake_complete(provider, system, messages, cfg):
        captured["system"] = system
        return _VALID_JSON_EPM

    monkeypatch.setattr(runtime.cloud, "complete", fake_complete)
    distill_and_judge("test content", "manual")
    assert "[kage CTM precedents]" not in captured["system"]

def test_write_note_blocks_read_only_identity(lib_env, monkeypatch):
    import json as _json
    (lib_env / "identities.json").write_text(_json.dumps({"identities": [{"label": "family", "class": "read-only", "accounts": [], "arm_overrides": {}}]}))
    monkeypatch.setattr(runtime, "embed", type("E", (), {"embed": lambda self, *a, **kw: [0.1] * 384})())
    fake_coll = MagicMock()
    monkeypatch.setattr(runtime, "vector", type("V", (), {"collection": lambda self, *a, **kw: fake_coll})())
    staging_id = deposit_to_queue("family content", "scout", identity="family")
    note_json = {"title": "Family Note", "body": "family content", "tags": [], "project": None, "identity": None, "source": "scout"}
    approval_id = request_approval(staging_id, "promote", "test", note_json, "family content")
    ok = write_note(approval_id)
    assert ok is False
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT decision FROM approval_queue WHERE id=?", (approval_id,))
    assert cur.fetchone()[0] == "rejected"
    cur.execute("SELECT COUNT(*) FROM memories WHERE project != 'kage-corrections-librarian'")
    assert cur.fetchone()[0] == 0
    conn.close()

def test_write_note_registry_corrupt_leaves_approval_undecided(lib_env, monkeypatch):
    (lib_env / "identities.json").write_text("{not valid json at all")
    monkeypatch.setattr(runtime, "embed", type("E", (), {"embed": lambda self, *a, **kw: [0.1] * 384})())
    fake_coll = MagicMock()
    monkeypatch.setattr(runtime, "vector", type("V", (), {"collection": lambda self, *a, **kw: fake_coll})())
    staging_id = deposit_to_queue("some content", "scout")
    note_json = {"title": "T", "body": "some content", "tags": [], "project": None, "identity": None, "source": "scout"}
    approval_id = request_approval(staging_id, "promote", "test", note_json, "some content")
    ok = write_note(approval_id)
    assert ok is False
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT decision FROM approval_queue WHERE id=?", (approval_id,))
    assert cur.fetchone()[0] is None
    conn.close()

def test_write_note_resolves_group_and_note_is_findable(lib_env, monkeypatch):
    import json as _json
    (lib_env / "identities.json").write_text(_json.dumps({"identities": [{"label": "personal-us", "class": "normal", "group": "personal", "accounts": [], "arm_overrides": {}}]}))
    monkeypatch.setattr(runtime, "embed", type("E", (), {"embed": lambda self, *a, **kw: [0.1] * 384})())
    fake_coll = MagicMock()
    monkeypatch.setattr(runtime, "vector", type("V", (), {"collection": lambda self, *a, **kw: fake_coll})())
    staging_id = deposit_to_queue("US personal fact", "scout", identity="personal-us")
    note_json = {"title": "US Fact", "body": "US personal fact", "tags": [], "project": None, "identity": None, "source": "scout"}
    approval_id = request_approval(staging_id, "promote", "test", note_json, "US personal fact")
    ok = write_note(approval_id)
    assert ok is True
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT mem_id, identity FROM memory_identities")
    row = cur.fetchone()
    assert row[1] == "personal"
    mem_id = row[0]
    store = runtime.store
    allowed = store.allowed_note_ids("personal", None)
    assert mem_id in allowed
    conn.close()


# ── list_pending_approvals (Cycle 29) ────────────────────────────────────────

def test_list_pending_approvals_returns_only_undecided(lib_env):
    staging_id = deposit_to_queue('some content', 'scout')
    note_json = {'title': 'Test', 'body': 'Body text', 'tags': []}
    approval_id1 = request_approval(staging_id, 'promote', 'good reason', note_json, 'preview')
    approval_id2 = request_approval(staging_id, 'promote', 'another reason', note_json, 'preview')
    conn = _connect()
    conn.execute("UPDATE approval_queue SET decision='approved' WHERE id=?", (approval_id1,))
    conn.commit()
    conn.close()
    result = list_pending_approvals()
    assert len(result) == 1
    assert result[0]['id'] == approval_id2


def test_list_pending_approvals_empty_when_all_decided(lib_env):
    staging_id = deposit_to_queue('some content', 'scout')
    note_json = {'title': 'Test', 'body': 'Body text', 'tags': []}
    approval_id = request_approval(staging_id, 'promote', 'good reason', note_json, 'preview')
    conn = _connect()
    conn.execute("UPDATE approval_queue SET decision='rejected' WHERE id=?", (approval_id,))
    conn.commit()
    conn.close()
    result = list_pending_approvals()
    assert len(result) == 0


def test_list_pending_approvals_dict_has_required_keys(lib_env):
    staging_id = deposit_to_queue('some content', 'scout')
    note_json = {'title': 'Test', 'body': 'Body text', 'tags': []}
    request_approval(staging_id, 'promote', 'good reason', note_json, 'preview')
    result = list_pending_approvals()
    assert len(result) == 1
    assert all(key in result[0] for key in ['id', 'action', 'reason', 'note_json', 'sanitized_preview', 'created_at'])
