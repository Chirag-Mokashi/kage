"""User-defined sensitive pattern vault for the Layer 3e privacy gate.

Manages ~/.kage/sensitive.json: load, save, add patterns, scan memory and
staging queue against built-in + vault patterns.
"""
from __future__ import annotations
import json, pathlib, re, uuid
from datetime import date


def load_vault() -> dict:
    path = pathlib.Path.home() / ".kage" / "sensitive.json"
    try:
        with path.open("r") as f:
            vault = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        vault = {"patterns": []}
    return vault


def save_vault(vault: dict) -> None:
    path = pathlib.Path.home() / ".kage" / "sensitive.json"
    with path.open("w") as f:
        json.dump(vault, f, indent=2)


def add_pattern(label: str, pattern: str) -> None:
    vault = load_vault()
    try:
        re.compile(pattern)
    except re.error:
        raise
    entry = {
        "id": uuid.uuid4().hex[:8],
        "label": label,
        "pattern": pattern,
        "added_at": date.today().strftime("%Y-%m-%d"),
    }
    vault["patterns"].append(entry)
    save_vault(vault)


def bootstrap(memory_dir: pathlib.Path) -> list[dict]:
    from kage.pii import _pii_scan
    result = []
    vault = load_vault()
    shimmed = [{"name": p["label"], "pattern": p["pattern"]} for p in vault.get("patterns", [])]
    for file in memory_dir.glob("*.md"):
        with file.open("r") as f:
            text = f.read()
        hits = _pii_scan(text, shimmed)
        if hits:
            result.append({"path": str(file), "hits": hits})
    return result


def scan_sensitive_patterns() -> dict:
    from kage.pii import _pii_scan
    from kage.librarian import get_staging_queue
    vault = load_vault()
    shimmed = [{"name": p["label"], "pattern": p["pattern"]} for p in vault.get("patterns", [])]
    queue = get_staging_queue()
    items = []
    for item in queue:
        hits = _pii_scan(item["content"], shimmed)
        if hits:
            items.append({"id": item["id"], "hits": hits})
    return {"flagged_count": len(items), "items": items}
