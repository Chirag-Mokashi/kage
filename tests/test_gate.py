import json
from pathlib import Path
import pytest
from kage import runtime, gate
from kage.config import Config

@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "config", Config(tmp_path))
    return tmp_path

def test_add_and_load_allowlist(home):
    gate.add_allow("PUBLIC", "octocat@github.test")
    allowlist = gate.load_allowlist()["values"]
    assert len(allowlist) == 1
    assert gate.allowlist_values() == {"octocat@github.test"}

def test_allowlist_normalizes(home):
    gate.add_allow("PUBLIC", "Octocat@GitHub.TEST")
    assert "octocat@github.test" in gate.allowlist_values()

def test_remove_allow(home):
    gate.add_allow("PUBLIC", "octocat@github.test")
    allowlist = gate.load_allowlist()["values"]
    id_to_remove = allowlist[0]["id"]
    assert gate.remove_allow(id_to_remove) is True
    assert gate.allowlist_values() == set()
    assert gate.remove_allow("nope") is False

def test_append_and_load_queue(home):
    gate.append_queue({"value": "a@b.test"})
    gate.append_queue({"value": "c@d.test"})
    queue = gate.load_queue()
    assert len(queue) == 2
    assert gate.queue_values() == {"a@b.test", "c@d.test"}

def test_load_queue_skips_malformed(home):
    queue_file = home / "privacy_queue.jsonl"
    queue_file.write_text(json.dumps({"value": "a@b.test"}) + "\nnot json{{{ \n" + json.dumps({"value": "c@d.test"}))
    queue = gate.load_queue()
    assert len(queue) == 2
    assert queue[0]["value"] == "a@b.test"
    assert queue[1]["value"] == "c@d.test"

def test_load_queue_missing_file(home):
    queue = gate.load_queue()
    assert queue == []

def test_vault_value_masked_no_label_leak(home):
    vault_file = home / "sensitive.json"
    vault_file.write_text(json.dumps({"patterns": [{"label": "burner", "pattern": "evil@burner\\.test"}]}))
    masked, _ = gate.two_pass_gate("contact evil@burner.test")
    assert "evil@burner.test" not in masked
    assert "burner" not in masked.lower()
    assert "[REDACTED_1]" in masked

def test_new_hit_redacted_and_queued(home):
    masked, _ = gate.two_pass_gate("email new@person.test")
    assert "new@person.test" not in masked
    queue = gate.load_queue()
    assert len(queue) == 1
    assert queue[0]["value"] == "new@person.test"
    assert queue[0]["type"] == "EMAIL"
    assert queue[0]["status"] == "pending"

def test_allowlisted_value_kept_cleartext(home):
    gate.add_allow("P", "keep@public.test")
    masked, _ = gate.two_pass_gate("reach keep@public.test")
    assert "keep@public.test" in masked
    assert gate.load_queue() == []

def test_un_allowlistable_never_queued(home):
    masked, _ = gate.two_pass_gate("key AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in masked
    assert gate.load_queue() == []

def test_dedup_same_value_one_entry(home):
    masked, _ = gate.two_pass_gate("a@dup.test")
    masked, _ = gate.two_pass_gate("a@dup.test")
    queue = gate.load_queue()
    assert len(queue) == 1

def test_returns_mapping_for_restore(home):
    masked, mapping = gate.two_pass_gate("hi bob@x.test")
    assert any(key in mapping for key in mapping if mapping[key] == "bob@x.test")
    from kage.redact import restore
    restored = restore(masked, mapping)
    assert "bob@x.test" in restored
