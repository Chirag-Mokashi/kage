import json, pathlib, re
import pytest


def test_load_vault_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    (tmp_path / ".kage").mkdir()
    from kage.sensitive import load_vault
    assert load_vault() == {"patterns": []}


def test_add_pattern_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    (tmp_path / ".kage").mkdir()
    from kage.sensitive import add_pattern, load_vault
    add_pattern("my-label", r"\bsecret\b")
    vault = load_vault()
    assert len(vault["patterns"]) == 1
    p = vault["patterns"][0]
    assert p["label"] == "my-label"
    assert p["pattern"] == r"\bsecret\b"
    assert len(p["id"]) == 8


def test_add_pattern_invalid_regex(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    (tmp_path / ".kage").mkdir()
    from kage.sensitive import add_pattern, load_vault
    with pytest.raises(re.error):
        add_pattern("bad", "[invalid")
    assert load_vault()["patterns"] == []


def test_bootstrap_flags_builtin_pii(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    (tmp_path / ".kage").mkdir()
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "note.md").write_text("My Aadhaar is 1234 5678 9012")
    from kage.sensitive import bootstrap
    results = bootstrap(memory_dir)
    assert len(results) == 1
    assert "Aadhaar" in results[0]["hits"]


def test_bootstrap_flags_vault_pattern(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    kage_home = tmp_path / ".kage"
    kage_home.mkdir()
    (kage_home / "sensitive.json").write_text(json.dumps({
        "patterns": [{"id": "aa1bb2cc", "label": "project-x", "pattern": r"ProjectX", "added_at": "2026-06-29"}]
    }))
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "note.md").write_text("Working on ProjectX today")
    from kage.sensitive import bootstrap
    results = bootstrap(memory_dir)
    assert len(results) == 1
    assert "project-x" in results[0]["hits"]


def test_bootstrap_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    (tmp_path / ".kage").mkdir()
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    from kage.sensitive import bootstrap
    assert bootstrap(memory_dir) == []


def test_gate_text_applies_vault_pattern(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    kage_home = tmp_path / ".kage"
    kage_home.mkdir()
    (kage_home / "sensitive.json").write_text(json.dumps({
        "patterns": [{"id": "aa1bb2cc", "label": "home-addr", "pattern": r"Koramangala", "added_at": "2026-06-29"}]
    }))
    from kage.pii import _gate_text
    result = _gate_text("I live in Koramangala")
    assert "[SENSITIVE:home-addr]" in result
    assert "Koramangala" not in result


def test_scan_sensitive_patterns_flags_pii(tmp_path, monkeypatch):
    from kage import runtime
    from kage.store import Store
    from kage.config import Config
    from kage.librarian import _apply_migrations, deposit_to_queue

    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    kage_home = tmp_path / ".kage"
    kage_home.mkdir()
    (kage_home / "indexes").mkdir()
    db_path = kage_home / "indexes" / "kage.db"
    store = Store(db_path)
    store.init_schema()
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "config", Config(kage_home))
    conn = store.connect()
    _apply_migrations(conn)
    conn.commit()
    conn.close()

    deposit_to_queue("My Aadhaar is 1234 5678 9012", "test")

    from kage.sensitive import scan_sensitive_patterns
    result = scan_sensitive_patterns()
    assert result["flagged_count"] >= 1
    assert any("Aadhaar" in item["hits"] for item in result["items"])
