"""Registry CRUD for ~/.kage/identities.json (Cycle 28)."""

from __future__ import annotations
from pathlib import Path
import json


def _stores_dir() -> Path:
    # lazy import to avoid circular deps
    from kage import runtime
    return Path(runtime.config.home)


def load_identities() -> dict:
    try:
        with open(_stores_dir() / "identities.json") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"identities": []}
    except Exception as e:
        import sys
        print(f"[kage] warning: identities.json unreadable ({e}), read-only wall inactive", file=sys.stderr)
        return {"identities": []}


def save_identities(data: dict) -> None:
    with open(_stores_dir() / "identities.json", "w") as f:
        json.dump(data, f, indent=2)


def get_identity(label: str) -> dict | None:
    for entry in load_identities()["identities"]:
        if entry["label"] == label:
            return entry
    return None


def active_class(label: str) -> str:
    entry = get_identity(label)
    if entry is None:
        return "normal"
    return entry.get("class", "normal")


def identity_arm_overrides(label: str, arm_name: str) -> dict:
    entry = get_identity(label)
    if entry is None:
        return {}
    return entry.get("arm_overrides", {}).get(arm_name, {})


def set_class(label: str, new_class: str) -> None:
    if new_class not in {"normal", "read-only"}:
        raise ValueError(f"Invalid class '{new_class}'. Must be 'normal' or 'read-only'.")
    data = load_identities()
    for entry in data["identities"]:
        if entry["label"] == label:
            entry["class"] = new_class
            save_identities(data)
            return
    raise ValueError(f"Identity '{label}' not found in registry.")


def add_account(label: str, account: str) -> None:
    data = load_identities()
    for entry in data["identities"]:
        if entry["label"] == label:
            if account not in entry.get("accounts", []):
                entry.setdefault("accounts", []).append(account)
                save_identities(data)
            return
    raise ValueError(f"Identity '{label}' not found in registry.")
