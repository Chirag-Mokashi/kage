"""
Store layer for the Cycle 27 two-pass privacy gate.

Handles allowlist and privacy queue operations, including loading, saving,
and managing entries. Uses lazy imports to avoid circular dependencies.
"""

from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from datetime import datetime
import json
import os

from kage.redact import substitute
from kage.pii import _PII_PATTERNS
from datetime import datetime

# redact._label() outputs for high-value secrets that must NEVER be allowlisted
# (footgun guard). Enforced at `kage allow add`; the gate also uses it to never-queue these.
_UN_ALLOWLISTABLE = frozenset({
    "SSH_PRIVATE_KEY", "CREDIT_DEBIT_CARD", "AWS_ACCESS_KEY", "OPENAI_ANTHROPIC_KEY",
    "API_KEY_IN_CONTEXT", "SECRET_TOKEN_IN_CONTEXT", "GOOGLE_KEY", "GITHUB_PAT",
    "GITHUB_OAUTH", "BEARER_TOKEN", "JWT_TOKEN", "ENV_SECRET", "DB_CONNECTION_STRING",
    "PASSWORD_FIELD", "CVV",
})

def _normalize(value: str) -> str:
    return value.strip().lower()

def _stores_dir() -> Path:
    from kage import runtime
    return Path(runtime.config.home)

def load_allowlist() -> dict:
    try:
        with open(_stores_dir() / "allowlist.json", "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return {"values": []}

def save_allowlist(data: dict) -> None:
    with open(_stores_dir() / "allowlist.json", "w") as f:
        json.dump(data, f, indent=2)

def add_allow(label: str, value: str) -> None:
    data = load_allowlist()
    entry = {
        "id": uuid4().hex[:8],
        "label": label,
        "value": value,
        "added_at": datetime.now().strftime("%Y-%m-%d")
    }
    data["values"].append(entry)
    save_allowlist(data)

def remove_allow(entry_id: str) -> bool:
    data = load_allowlist()
    original_length = len(data["values"])
    data["values"] = [entry for entry in data["values"] if entry["id"] != entry_id]
    if len(data["values"]) < original_length:
        save_allowlist(data)
        return True
    return False

def allowlist_values() -> set[str]:
    data = load_allowlist()
    return {_normalize(entry["value"]) for entry in data["values"]}

def load_queue() -> list[dict]:
    """Read the privacy queue; skip malformed lines. Missing file -> []."""
    entries: list[dict] = []
    try:
        with open(_stores_dir() / "privacy_queue.jsonl", "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except (FileNotFoundError, OSError):
        return []
    return entries

def append_queue(entry: dict) -> None:
    path = _stores_dir() / "privacy_queue.jsonl"
    os.makedirs(path.parent, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")

def save_queue(entries: list[dict]) -> None:
    """Rewrite the entire privacy queue (used after review to update statuses)."""
    path = _stores_dir() / "privacy_queue.jsonl"
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

def queue_values() -> set[str]:
    queue = load_queue()
    return {_normalize(entry.get("value", "")) for entry in queue}

def _load_vault() -> dict:
    try:
        with open(_stores_dir() / "sensitive.json", "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return {"patterns": []}

def two_pass_gate(text: str, *, interactive: bool = False, source: str = "", existing_mapping: dict | None = None) -> tuple[str, dict]:
    """Two-pass Layer 3e gate (Cycle 27).

    Pass 1 (silent): vault values -> generic [REDACTED_N] placeholder (label never leaks).
    Pass 2: generic _PII_PATTERNS. New hits are fail-closed redacted + queued for review;
    allowlisted values are un-redacted (kept cleartext); high-value secrets are never queued.
    Returns (masked_text, mapping) so the caller can restore() the cloud response.
    """
    vault = _load_vault()
    allow = allowlist_values()
    queued = queue_values()

    vault_shim = [{"name": "REDACTED", "pattern": p["pattern"]} for p in vault.get("patterns", [])]
    text, mapping = substitute(text, vault_shim, existing_mapping=existing_mapping)

    pre_keys = set(mapping)
    text, mapping = substitute(text, _PII_PATTERNS, existing_mapping=mapping)

    for ph in list(mapping):
        if ph in pre_keys:
            continue
        value = mapping[ph]
        prefix = ph[1:-1].rsplit("_", 1)[0]
        norm = _normalize(value)
        if norm in allow:
            text = text.replace(ph, value)
            del mapping[ph]
        elif prefix in _UN_ALLOWLISTABLE:
            continue
        elif norm in queued:
            continue
        else:
            append_queue({
                "value": value,
                "type": prefix,
                "placeholder": ph,
                "source": source,
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                "status": "pending",
            })
            queued.add(norm)

    return text, mapping
