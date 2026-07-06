"""Registry CRUD for ~/.kage/identities.json (Cycle 28)."""

from __future__ import annotations
from pathlib import Path
import json


class RegistryCorruptError(Exception):
    """Raised when identities.json exists but cannot be parsed (bad JSON, permission
    error, etc.). Distinct from 'file simply doesn't exist' (FileNotFoundError case,
    which stays fail-open — a fresh install legitimately has no registry yet)."""


class ReadOnlyIdentityError(ValueError):
    """Raised when a write is attempted as a read-only identity."""


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
        raise RegistryCorruptError(f"identities.json unreadable: {e}") from e


def save_identities(data: dict) -> None:
    with open(_stores_dir() / "identities.json", "w") as f:
        json.dump(data, f, indent=2)


def get_identity(label: str) -> dict | None:
    for entry in load_identities()["identities"]:
        if entry["label"] == label:
            return entry
    return None


def active_class(label: str) -> str:
    try:
        entry = get_identity(label)
    except RegistryCorruptError:
        return "read-only"
    if entry is None:
        return "normal"
    return entry.get("class", "normal")


def identity_arm_overrides(label: str, arm_name: str) -> dict:
    try:
        entry = get_identity(label)
    except RegistryCorruptError:
        return {}
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


def active_group(label: str) -> str:
    try:
        entry = get_identity(label)
    except RegistryCorruptError:
        return label
    if entry is None:
        return label
    return entry.get("group", label)


def resolve_write_identity(label: str) -> str:
    """Group-resolve a label for tagging a memory write; raise if read-only.
    EVERY writer to memory_identities MUST route its tag through this function.
    Built on get_identity() directly (NOT active_class/active_group) so that a
    RegistryCorruptError propagates AS ITSELF, uncaught — callers must be able to
    distinguish 'you may not write' (ReadOnlyIdentityError) from 'the registry is
    currently unreadable' (RegistryCorruptError) and handle them differently.
    """
    entry = get_identity(label) or {}
    if entry.get("class", "normal") == "read-only":
        raise ReadOnlyIdentityError(f"read-only identity '{label}' cannot write to memory")
    return entry.get("group", label)
