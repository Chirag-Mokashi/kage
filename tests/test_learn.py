import pytest
import sqlite3
import json
from kage.learn import (
    load_learned_prompt,
    _build_meta_prompt,
    _count_total_corrections,
    _read_learn_state,
    _write_learn_state,
    run_learning_pass,
    save_learned_prompt,
    _count_corrections,
    _build_librarian_meta_prompt,
    run_librarian_learning_pass,
)


def _make_db(home, notes):
    db = home / "indexes" / "kage.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    mem_dir = home / "memory"
    mem_dir.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("""CREATE TABLE memories (
        id TEXT PRIMARY KEY, content_path TEXT, project TEXT,
        created_at TEXT, local_only INTEGER DEFAULT 0, state TEXT DEFAULT 'scoped')""")
    conn.execute("CREATE VIRTUAL TABLE memory_fts USING fts5(id UNINDEXED, body)")
    for note_id, project, text in notes:
        rel = f"memory/{note_id}.md"
        (mem_dir / f"{note_id}.md").write_text(text)
        conn.execute("INSERT INTO memories VALUES (?,?,?,?,0,'scoped')",
                     (note_id, rel, project, "2026-06-30T00:00:00"))
        conn.execute("INSERT INTO memory_fts VALUES (?,?)", (note_id, text))
    conn.commit()
    conn.close()


def test_load_learned_prompt_missing_file(tmp_path):
    result = load_learned_prompt("code", home=tmp_path)
    assert result == ""


def test_load_learned_prompt_returns_active(tmp_path):
    (tmp_path / "learned_prompts.json").write_text(
        json.dumps({
            "code": {
                "active": "v1",
                "versions": {
                    "v1": {"date": "2026-06-30", "correction_count": 5,
                           "source_note_ids": [], "prompt": "- Never invent signatures", "trace": "full trace"}
                }
            }
        })
    )
    result = load_learned_prompt("code", home=tmp_path)
    assert result == "- Never invent signatures"


def test_load_learned_prompt_no_active_key(tmp_path):
    (tmp_path / "learned_prompts.json").write_text(
        json.dumps({
            "code": {
                "versions": {
                    "v1": {"date": "2026-06-30", "correction_count": 5,
                           "source_note_ids": [], "prompt": "- Some rule", "trace": "trace"}
                }
            }
        })
    )
    result = load_learned_prompt("code", home=tmp_path)
    assert result == ""


def test_build_meta_prompt_contains_task_class():
    corrections = ["Error: used wrong method", "Error: wrong column name"]
    result = _build_meta_prompt(corrections, "code")
    assert "code" in result
    assert "[1]" in result
    assert "[2]" in result
    assert "--- CORRECTIONS ---" in result


def test_count_total_corrections_no_db(tmp_path):
    result = _count_total_corrections(home=tmp_path)
    assert result == 0


def test_count_total_corrections_counts_project(tmp_path):
    _make_db(tmp_path, [
        ("n1", "kage-corrections", "correction log step 1"),
        ("n2", "kage-corrections", "correction log step 2"),
        ("n3", "other-project", "some other note"),
    ])
    result = _count_total_corrections(home=tmp_path)
    assert result == 2


def test_read_learn_state_missing(tmp_path):
    result = _read_learn_state(home=tmp_path)
    assert result == {}


def test_write_read_learn_state_roundtrip(tmp_path):
    state = {"last_learn_correction_count": 42}
    _write_learn_state(state, home=tmp_path)
    result = _read_learn_state(home=tmp_path)
    assert result == state
    assert not (tmp_path / "learn_state.json.tmp").exists()


def test_run_learning_pass_no_db(tmp_path):
    cfg = {"providers": {"my-provider": {}}}
    calls = []
    def fake_cloud(provider, system, user_msg, cfg_arg):
        calls.append(1)
        return "- rule"
    result = run_learning_pass("code", fake_cloud, cfg, home=tmp_path)
    assert result == ("", "", [])
    assert calls == []


def test_run_learning_pass_no_matches(tmp_path):
    _make_db(tmp_path, [
        ("n1", "kage-corrections", "correction log step 1: used wrong def"),
    ])
    cfg = {"providers": {"my-provider": {}}}
    calls = []
    def fake_cloud(provider, system, user_msg, cfg_arg):
        calls.append(1)
        return "- rule"
    result = run_learning_pass("multimodal", fake_cloud, cfg, home=tmp_path)
    assert result == ("", "", [])
    assert calls == []


def test_run_learning_pass_filters_by_class(tmp_path):
    _make_db(tmp_path, [
        ("n1", "kage-corrections", "correction log step 1: wrong def signature used"),
        ("n2", "kage-corrections", "correction log step 2: image not found in path"),
    ])
    cfg = {"providers": {"my-provider": {}}}
    captured = {}
    def fake_cloud(provider, system, user_msg, cfg_arg):
        captured["provider"] = provider
        captured["user_msg"] = user_msg
        return "- Never invent function signatures"

    prompt, trace, ids = run_learning_pass("code", fake_cloud, cfg, home=tmp_path)
    assert prompt == "- Never invent function signatures"
    assert "n1" in ids
    assert "n2" not in ids
    assert captured["provider"] == "my-provider"


def test_run_learning_pass_calls_cloud_correctly(tmp_path):
    _make_db(tmp_path, [
        ("n1", "kage-corrections", "correction log step 1: wrong def used"),
    ])
    cfg = {"providers": {"test-provider": {}}}
    call_args = []
    def fake_cloud(provider, system, user_msg, cfg_arg):
        call_args.append((provider, system, user_msg, cfg_arg))
        return "- rule"

    run_learning_pass("code", fake_cloud, cfg, home=tmp_path)
    assert len(call_args) == 1
    assert call_args[0][0] == "test-provider"
    assert call_args[0][1] == ""
    assert "correction log" in call_args[0][2]
    assert call_args[0][3] is cfg


def test_run_learning_pass_extracts_bullets(tmp_path):
    _make_db(tmp_path, [
        ("n1", "kage-corrections", "correction log step 1: wrong def used"),
    ])
    cfg = {"providers": {"p": {}}}
    def fake_cloud(provider, system, user_msg, cfg_arg):
        return "Here are the rules:\n\n- Rule one\n- Rule two"

    prompt, trace, _ = run_learning_pass("code", fake_cloud, cfg, home=tmp_path)
    assert prompt == "- Rule one\n- Rule two"
    assert trace == "Here are the rules:\n\n- Rule one\n- Rule two"


def test_run_learning_pass_chat_fallback(tmp_path):
    _make_db(tmp_path, [
        ("n1", "kage-corrections", "correction log step 1: wrong def signature"),
        ("n2", "kage-corrections", "correction log step 2: general tone issue"),
    ])
    cfg = {"providers": {"p": {}}}
    def fake_cloud(provider, system, user_msg, cfg_arg):
        return "- rule"

    _, _, ids = run_learning_pass("chat", fake_cloud, cfg, home=tmp_path)
    assert "n2" in ids
    assert "n1" not in ids


def test_save_learned_prompt_creates_v1(tmp_path):
    save_learned_prompt(
        task_class="code",
        prompt="- Never invent signatures",
        trace="full trace here",
        source_note_ids=["n1", "n2"],
        correction_count=10,
        home=tmp_path,
    )
    data = json.loads((tmp_path / "learned_prompts.json").read_text())
    assert "code" in data
    assert data["code"]["active"] == "v1"
    assert data["code"]["versions"]["v1"]["prompt"] == "- Never invent signatures"
    assert data["code"]["versions"]["v1"]["trace"] == "full trace here"
    assert data["code"]["versions"]["v1"]["source_note_ids"] == ["n1", "n2"]
    assert data["code"]["versions"]["v1"]["correction_count"] == 10
    assert "date" in data["code"]["versions"]["v1"]


def test_save_learned_prompt_increments_version(tmp_path):
    save_learned_prompt("code", "- rule v1", "trace1", [], 5, home=tmp_path)
    save_learned_prompt("code", "- rule v2", "trace2", [], 10, home=tmp_path)
    data = json.loads((tmp_path / "learned_prompts.json").read_text())
    assert data["code"]["active"] == "v2"
    assert "v1" in data["code"]["versions"]
    assert "v2" in data["code"]["versions"]
    assert data["code"]["versions"]["v1"]["prompt"] == "- rule v1"
    assert data["code"]["versions"]["v2"]["prompt"] == "- rule v2"


def test_save_learned_prompt_atomic(tmp_path):
    save_learned_prompt("code", "- rule", "trace", [], 5, home=tmp_path)
    assert not (tmp_path / "learned_prompts.json.tmp").exists()


def test_save_learned_prompt_has_trace(tmp_path):
    save_learned_prompt("reasoning", "- Check logic", "long reasoning trace text", ["id1"], 3, home=tmp_path)
    data = json.loads((tmp_path / "learned_prompts.json").read_text())
    assert data["reasoning"]["versions"]["v1"]["trace"] == "long reasoning trace text"


# ── Cycle 24 — _count_corrections / _build_librarian_meta_prompt / run_librarian_learning_pass ──

def test_count_corrections_parameterized(tmp_path):
    _make_db(tmp_path, [
        ("lib-1", "kage-corrections-librarian", "Correction log — Librarian rejection: Bad PROMOTE. Source: scout. Reason: stale."),
        ("lib-2", "kage-corrections-librarian", "Correction log — Librarian rejection: Wrong HOLD. Source: scout. Reason: new content."),
        ("code-1", "other-project", "Correction log — Step 1: Wrong import."),
    ])
    assert _count_corrections("kage-corrections-librarian", home=tmp_path) == 2
    assert _count_corrections("other-project", home=tmp_path) == 1


def test_build_librarian_meta_prompt_structure():
    corrections = ["Rejected PROMOTE for stale source", "Wrong HOLD on new content"]
    result = _build_librarian_meta_prompt(corrections)
    assert "--- CORRECTIONS ---" in result
    assert "[1]" in result and "[2]" in result
    assert "task_class" not in result
    assert "PROMOTE" in result or "verdict" in result


def test_run_librarian_learning_pass_no_db(tmp_path):
    fake_cloud = lambda *a, **kw: "- rule one"
    result = run_librarian_learning_pass("kage-corrections-librarian", fake_cloud, {}, home=tmp_path)
    assert result == ("", "", [])


def test_run_librarian_learning_pass_reads_correct_project(tmp_path):
    _make_db(tmp_path, [
        ("lib-1", "kage-corrections-librarian", "Correction log — Librarian rejection: Bad PROMOTE. Source: scout. Reason: stale."),
        ("code-1", "kage-corrections", "Correction log — Step 1: Wrong import."),
    ])
    fake_cloud = lambda *a, **kw: "- rule from librarian corrections"
    prompt, trace, ids = run_librarian_learning_pass("kage-corrections-librarian", fake_cloud, {}, home=tmp_path)
    assert prompt.startswith("- rule from librarian corrections")
    assert "lib-1" in ids
    assert "code-1" not in ids


def test_run_librarian_learning_pass_fts_wording_matches(tmp_path):
    _make_db(tmp_path, [
        ("lib-1", "kage-corrections-librarian", "Correction log — Librarian rejection: Bad dedup. Source: manual. Reason: already exists."),
    ])
    fake_cloud = lambda *a, **kw: "- no duplicates"
    prompt, trace, ids = run_librarian_learning_pass("kage-corrections-librarian", fake_cloud, {}, home=tmp_path)
    assert len(ids) == 1


def test_run_librarian_learning_pass_empty_when_no_fts_match(tmp_path):
    _make_db(tmp_path, [
        ("lib-1", "kage-corrections-librarian", "this note has no matching tokens"),
    ])
    fake_cloud = lambda *a, **kw: "- rule"
    result = run_librarian_learning_pass("kage-corrections-librarian", fake_cloud, {}, home=tmp_path)
    assert result == ("", "", [])
