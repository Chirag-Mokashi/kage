from __future__ import annotations
import json
import os

from kage import runtime


def _read_active() -> dict:
    try:
        return json.loads(runtime.config.state_path.read_text())
    except (OSError, ValueError):
        return {}


def _write_active(state: dict) -> None:
    p = runtime.config.state_path
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.replace(tmp, p)


def _resolve_context(
    arg_identity: str | None,
    arg_project: str | None,
) -> tuple[str, str | None, str]:
    active = _read_active()
    if arg_identity:
        identity = arg_identity
        project = arg_project
        source = "explicit"
    elif active.get("identity"):
        identity = active.get("identity")
        project = arg_project if arg_project is not None else active.get("project")
        source = "sticky"
    else:
        identity = "personal"
        project = arg_project
        source = "fallback"
    return (identity, project, source)
