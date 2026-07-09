from __future__ import annotations
import json
import os
from dataclasses import dataclass
from pathlib import Path

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


@dataclass
class AxisResolution:
    value: str | None
    confidence: str  # "declared" | "inferred" | "fallback"
    provenance: str


@dataclass
class Resolution:
    identity: AxisResolution
    project: AxisResolution


_KAGE_MARKER_FILENAME = ".kage"


def _find_kage_marker_project(start: Path) -> str | None:
    """Walk up from `start` looking for a `.kage` marker file containing a
    `project=<name>` line. Stops at the first marker found or at the user's
    home directory (never walks above it) -- same shape as `.git` discovery,
    not a library. Caller gates this on the `project_inference` config flag.
    """
    home = Path.home().resolve()
    current = start.resolve()
    while True:
        marker = current / _KAGE_MARKER_FILENAME
        if marker.is_file():
            try:
                for line in marker.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("project="):
                        return line.split("=", 1)[1].strip() or None
            except OSError:
                return None
            return None
        if current == home or current.parent == current:
            return None
        current = current.parent


def _resolve_context_rich(
    arg_identity: str | None,
    arg_project: str | None,
) -> Resolution:
    """Rich per-axis resolution for the 3 warm consumers (ask/chat/remember).
    IDENTITY is declared-only (flag > sticky > fallback), NEVER inferred --
    the two-axis invariant (a wrong identity guess mistags writes). PROJECT
    may be inferred: explicit flag > .kage marker (if project_inference is
    enabled) > sticky > fallback/none.
    """
    active = _read_active()

    if arg_identity:
        identity_res = AxisResolution(arg_identity, "declared", "flag")
    elif active.get("identity"):
        identity_res = AxisResolution(active["identity"], "declared", "sticky")
    else:
        identity_res = AxisResolution("personal", "fallback", "fallback")

    if arg_project is not None:
        project_res = AxisResolution(arg_project, "declared", "flag")
    else:
        marker_project = None
        if runtime.config.data.get("project_inference", False):
            marker_project = _find_kage_marker_project(Path.cwd())
        if marker_project:
            project_res = AxisResolution(marker_project, "inferred", "kage-marker")
        elif active.get("project"):
            project_res = AxisResolution(active["project"], "declared", "sticky")
        else:
            project_res = AxisResolution(None, "fallback", "fallback")

    return Resolution(identity=identity_res, project=project_res)


def _mark_project_inferred(inferred: bool) -> None:
    """Record whether the most recent project resolution was inferred (not
    declared) -- Slice 6's miss-metric sensor. `kage use` checks and clears
    the pending flag to log a correction when an explicit override follows
    an inference, feeding the same kage-corrections log `kage learn`
    consumes. `_project_inference_total` is the hit-rate denominator shown
    by `kage status`.
    """
    if not inferred:
        return
    active = _read_active()
    active["_project_inferred_pending"] = True
    active["_project_inference_total"] = active.get("_project_inference_total", 0) + 1
    _write_active(active)
