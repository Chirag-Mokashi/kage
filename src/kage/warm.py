"""warm.py -- Layer 3a warm-context tier: fact store + 4-op write discipline.

See docs/cycle-31-3a-warm-context.md. Slice 1: pure logic, no callers yet.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

# ponytail: only these keys keep a superseded_at audit trail on UPDATE (the
# pitch's "mutable two" -- timezone changes on travel, project changes on
# switch). Ceiling: every other fact is overwritten in place, so no history
# survives for high-churn facts (queue depth, day-part). Upgrade: add a key
# to AUDITED_KEYS if it ever needs an audit trail too.
AUDITED_KEYS = {"timezone", "project"}


@dataclass
class WarmFact:
    key: str
    value: str | None
    identity: str
    valid_from: str
    ttl_seconds: int
    provenance: str
    superseded_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WarmFact":
        return cls(**d)

    def is_expired(self, now: datetime) -> bool:
        age = (now - datetime.fromisoformat(self.valid_from)).total_seconds()
        return age >= self.ttl_seconds


def atomic_write_json(path: Path, data: dict) -> None:
    """Write `data` to `path` atomically with a unique per-writer tmp name.

    Two racing `kage` invocations must not interleave bytes into one shared
    tmp file before os.replace (NEW-6) -- a shared fixed tmp name only looks
    atomic because readers happen to try/except around partial writes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data, indent=2) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_store(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {"facts": []}


def _find_active(facts: list[dict], identity: str, key: str) -> tuple[int, dict] | None:
    for i, f in enumerate(facts):
        if f["identity"] == identity and f["key"] == key and f.get("superseded_at") is None:
            return i, f
    return None


def apply_write(facts: list[dict], new_fact: WarmFact) -> tuple[list[dict], str]:
    """Compare `new_fact` to the resident active fact (same identity+key).

    Applies exactly one of ADD / UPDATE / DELETE / NOOP and returns the
    updated facts list plus the op name.
    """
    facts = list(facts)
    found = _find_active(facts, new_fact.identity, new_fact.key)

    if new_fact.value is None:
        if found is None:
            return facts, "NOOP"
        idx, _ = found
        del facts[idx]
        return facts, "DELETE"

    if found is None:
        facts.append(new_fact.to_dict())
        return facts, "ADD"

    idx, resident = found
    if resident["value"] == new_fact.value:
        resident["valid_from"] = new_fact.valid_from
        facts[idx] = resident
        return facts, "NOOP"

    if new_fact.key in AUDITED_KEYS:
        resident["superseded_at"] = new_fact.valid_from
        facts[idx] = resident
        facts.append(new_fact.to_dict())
    else:
        facts[idx] = new_fact.to_dict()
    return facts, "UPDATE"


def refresh(path: Path, new_fact: WarmFact) -> str:
    """Load the store at `path`, apply the 4-op write for `new_fact`, write
    back atomically. Returns the op applied (ADD/UPDATE/DELETE/NOOP)."""
    store = load_store(path)
    facts, op = apply_write(store.get("facts", []), new_fact)
    store["facts"] = facts
    atomic_write_json(path, store)
    return op


def active_facts(path: Path, identity: str) -> list[WarmFact]:
    """Non-superseded facts for `identity`. Caller checks `is_expired` on
    each to decide whether a producer needs to refresh it."""
    store = load_store(path)
    return [
        WarmFact.from_dict(f)
        for f in store.get("facts", [])
        if f["identity"] == identity and f.get("superseded_at") is None
    ]


def get_alert_seed(path: Path, identity: str) -> str | None:
    """Read the current interrupt_seed fact's value, if any -- a reserved
    seam for a future alert/interrupt-rendering cycle (the keystone push/
    interrupt work). Pure read, no refresh, no rendering; nothing calls this
    yet. Returns None when there's no active alert seed for `identity`.
    """
    for fact in active_facts(path, identity):
        if fact.key == "interrupt_seed":
            return fact.value
    return None
