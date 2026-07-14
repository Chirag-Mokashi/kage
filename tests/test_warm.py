from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from kage import warm
from kage.warm import WarmFact


def _fact(key="timezone", value="America/New_York", identity="personal",
          valid_from="2026-07-09T08:00:00", ttl_seconds=3600,
          provenance="macos-location", superseded_at=None):
    return WarmFact(
        key=key, value=value, identity=identity, valid_from=valid_from,
        ttl_seconds=ttl_seconds, provenance=provenance,
        superseded_at=superseded_at,
    )


def test_warmfact_to_dict_from_dict_roundtrip():
    fact = _fact()
    assert WarmFact.from_dict(fact.to_dict()) == fact


def test_is_expired_false_within_ttl():
    fact = _fact(valid_from="2026-07-09T08:00:00", ttl_seconds=3600)
    now = datetime.fromisoformat("2026-07-09T08:30:00")
    assert fact.is_expired(now) is False


def test_is_expired_true_past_ttl():
    fact = _fact(valid_from="2026-07-09T08:00:00", ttl_seconds=3600)
    now = datetime.fromisoformat("2026-07-09T09:30:00")
    assert fact.is_expired(now) is True


def test_atomic_write_json_writes_and_creates_parent_dir(tmp_path):
    path = tmp_path / "state" / "warm.json"
    warm.atomic_write_json(path, {"facts": []})
    assert path.exists()
    assert warm.load_store(path) == {"facts": []}


def test_atomic_write_json_leaves_no_tmp_files_behind(tmp_path):
    path = tmp_path / "warm.json"
    warm.atomic_write_json(path, {"facts": []})
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_load_store_missing_file_returns_empty_facts(tmp_path):
    path = tmp_path / "does-not-exist.json"
    assert warm.load_store(path) == {"facts": []}


def test_load_store_malformed_json_returns_empty_facts(tmp_path):
    path = tmp_path / "warm.json"
    path.write_text("{not valid json")
    assert warm.load_store(path) == {"facts": []}


def test_apply_write_add_when_no_resident():
    facts, op = warm.apply_write([], _fact())
    assert op == "ADD"
    assert len(facts) == 1
    assert facts[0]["value"] == "America/New_York"


def test_apply_write_noop_bumps_valid_from_on_unchanged_value():
    resident = _fact(valid_from="2026-07-09T08:00:00").to_dict()
    new_fact = _fact(valid_from="2026-07-09T09:00:00")
    facts, op = warm.apply_write([resident], new_fact)
    assert op == "NOOP"
    assert len(facts) == 1
    assert facts[0]["valid_from"] == "2026-07-09T09:00:00"


def test_apply_write_update_audited_key_keeps_superseded_history():
    resident = _fact(key="timezone", value="Asia/Kolkata").to_dict()
    new_fact = _fact(key="timezone", value="America/New_York",
                      valid_from="2026-07-09T09:00:00")
    facts, op = warm.apply_write([resident], new_fact)
    assert op == "UPDATE"
    assert len(facts) == 2
    old = next(f for f in facts if f["value"] == "Asia/Kolkata")
    new = next(f for f in facts if f["value"] == "America/New_York")
    assert old["superseded_at"] == "2026-07-09T09:00:00"
    assert new["superseded_at"] is None


def test_apply_write_update_non_audited_key_replaces_in_place():
    resident = _fact(key="queue_depth", value="2").to_dict()
    new_fact = _fact(key="queue_depth", value="5",
                      valid_from="2026-07-09T09:00:00")
    facts, op = warm.apply_write([resident], new_fact)
    assert op == "UPDATE"
    assert len(facts) == 1
    assert facts[0]["value"] == "5"
    assert facts[0]["superseded_at"] is None


def test_apply_write_delete_when_value_none_and_resident_exists():
    resident = _fact().to_dict()
    new_fact = _fact(value=None)
    facts, op = warm.apply_write([resident], new_fact)
    assert op == "DELETE"
    assert facts == []


def test_apply_write_noop_when_value_none_and_no_resident():
    facts, op = warm.apply_write([], _fact(value=None))
    assert op == "NOOP"
    assert facts == []


def test_refresh_end_to_end_add_then_noop(tmp_path):
    path = tmp_path / "warm.json"
    op1 = warm.refresh(path, _fact(valid_from="2026-07-09T08:00:00"))
    assert op1 == "ADD"
    op2 = warm.refresh(path, _fact(valid_from="2026-07-09T08:30:00"))
    assert op2 == "NOOP"
    store = warm.load_store(path)
    assert len(store["facts"]) == 1
    assert store["facts"][0]["valid_from"] == "2026-07-09T08:30:00"


def test_active_facts_filters_by_identity_and_excludes_superseded(tmp_path):
    path = tmp_path / "warm.json"
    warm.atomic_write_json(path, {"facts": [
        _fact(identity="personal", key="a").to_dict(),
        _fact(identity="school", key="b").to_dict(),
        _fact(identity="personal", key="c", superseded_at="2026-07-09T09:00:00").to_dict(),
    ]})
    result = warm.active_facts(path, "personal")
    assert {f.key for f in result} == {"a"}


def test_get_alert_seed_returns_value_when_present(tmp_path):
    path = tmp_path / "warm.json"
    warm.refresh(path, _fact(key="interrupt_seed", value="[warn] scout stalled"))
    assert warm.get_alert_seed(path, "personal") == "[warn] scout stalled"


def test_get_alert_seed_returns_none_when_absent(tmp_path):
    path = tmp_path / "warm.json"
    assert warm.get_alert_seed(path, "personal") is None


def test_get_alert_seed_scoped_to_identity(tmp_path):
    path = tmp_path / "warm.json"
    warm.refresh(path, _fact(key="interrupt_seed", value="school alert", identity="school"))
    assert warm.get_alert_seed(path, "personal") is None
    assert warm.get_alert_seed(path, "school") == "school alert"
