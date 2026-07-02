"""Calendar write backend for kage using macOS EventKit.

This module provides the `EventKitBackend` class for creating macOS calendar events
via the EventKit framework (pyobjc). It is designed to be used only on macOS and
should not be imported on non-macOS platforms.

The class supports creating calendar events with a title, start and end time (in
ISO-8601 format), and an optional calendar name. If no calendar name is provided,
the default calendar for new events is used.

Note: This module uses lazy imports for EventKit and Foundation to avoid
platform-specific import errors on non-macOS systems.
"""
from __future__ import annotations
from datetime import datetime
import datetime as _dt
import secrets
from pathlib import Path

# ponytail: `runtime` is imported lazily inside the functions below, NOT at module
# top — runtime.py imports EventKitBackend from here, so a top-level import would be
# a circular import (confirmed: breaks when calendar_write is imported first).


class EventKitBackend:
    def __init__(self):
        pass

    def create(self, *, title: str, start: str, end: str, calendar_name: str | None = None) -> str:
        import EventKit as EK
        from Foundation import NSDate

        store = EK.EKEventStore.alloc().init()

        cal = None
        if calendar_name:
            for c in (store.calendarsForEntityType_(EK.EKEntityTypeEvent) or []):
                if c.title() == calendar_name:
                    cal = c
                    break
        if cal is None:
            cal = store.defaultCalendarForNewEvents()
        if cal is None:
            raise RuntimeError("no calendar available for new events")

        ev = EK.EKEvent.eventWithEventStore_(store)
        ev.setTitle_(title)
        ev.setStartDate_(NSDate.dateWithTimeIntervalSince1970_(datetime.fromisoformat(start).timestamp()))
        ev.setEndDate_(NSDate.dateWithTimeIntervalSince1970_(datetime.fromisoformat(end).timestamp()))
        ev.setCalendar_(cal)

        ok, err = store.saveEvent_span_error_(ev, EK.EKSpanThisEvent, None)
        if not ok:
            raise RuntimeError(f"calendar save failed: {err}")
        return ev.eventIdentifier()


def _proposals_dir() -> Path:
    from kage import runtime
    dir_path = Path(runtime.config.home) / "calendar" / "proposals"
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path

def _proposal_id() -> str:
    now = _dt.datetime.now().astimezone()
    return now.strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)

def _write_proposal(p: dict) -> Path:
    dir_path = _proposals_dir()
    path = dir_path / (p["id"] + ".md")
    frontmatter = "---\n"
    for key in ["id", "op", "status", "title", "start", "end", "calendar", "why", "created_at", "event_identifier"]:
        frontmatter += f"{key}: {p.get(key, '')}\n"
    frontmatter += "---\n\n"
    frontmatter += "# kage would " + p["op"] + ": \"" + p["title"] + "\"\n"
    frontmatter += p["start"] + " - " + p["end"] + " · calendar: " + (p["calendar"] if p["calendar"] else "(default)") + "\n"
    frontmatter += "why: " + p["why"]
    path.write_text(frontmatter)
    return path

def _read_proposal(path: Path) -> dict:
    text = path.read_text()
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("malformed proposal: no frontmatter")
    i = 1
    while i < len(lines) and lines[i] != "---":
        i += 1
    if i >= len(lines):
        raise ValueError("malformed proposal: unterminated frontmatter")
    proposal = {}
    for line in lines[1:i]:
        if not line:
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            proposal[k.strip()] = v.strip()
    return proposal

def propose_create(*, title: str, start: str, end: str, calendar: str | None = None, why: str = "") -> str:
    p = {
        "id": _proposal_id(),
        "op": "create",
        "status": "pending",
        "title": title,
        "start": start,
        "end": end,
        "calendar": calendar or "",
        "why": why,
        "created_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "event_identifier": ""
    }
    _write_proposal(p)
    return p["id"]

def get_queue() -> list[dict]:
    dir_path = _proposals_dir()
    proposals = []
    for path in sorted(dir_path.glob("*.md")):
        try:
            p = _read_proposal(path)
            if p.get("status") == "pending":
                proposals.append(p)
        except Exception:
            continue
    return proposals

def approve(proposal_id: str) -> dict:
    from kage import runtime
    from kage import privacy as _privacy
    path = _proposals_dir() / (proposal_id + ".md")
    if not path.exists():
        raise ValueError(f"no such proposal: {proposal_id}")
    p = _read_proposal(path)
    if p.get("status") != "pending":
        raise RuntimeError(f"proposal {proposal_id} is {p.get('status')}, not pending")
    for field in ("title", "start", "end"):
        if not p.get(field):
            raise ValueError(f"proposal {proposal_id} missing required field: {field}")
    if p.get("op") == "create":
        start_dt = _dt.datetime.fromisoformat(p["start"])
        now = _dt.datetime.now().astimezone()
        if start_dt.tzinfo is None:
            start_dt = start_dt.astimezone()
        if start_dt < now:
            raise ValueError(f"proposal {proposal_id} start is in the past: {p['start']}")
        ts = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            ident = runtime.calendar.create(title=p["title"], start=p["start"], end=p["end"], calendar_name=(p.get("calendar") or None))
        except Exception:
            _privacy._write_audit({"type": "calendar_write", "op": "create", "proposal_id": proposal_id, "status": "failed", "event_identifier": "", "success": False, "ts": ts})
            raise
        p["status"] = "executed"
        p["event_identifier"] = ident
        _write_proposal(p)
        _privacy._write_audit({"type": "calendar_write", "op": "create", "proposal_id": proposal_id, "status": "executed", "event_identifier": ident, "success": True, "ts": ts})
    else:
        raise RuntimeError(f"unsupported op: {p.get('op')}")
    return p

def reject(proposal_id: str) -> dict:
    from kage import privacy as _privacy
    path = _proposals_dir() / (proposal_id + ".md")
    if not path.exists():
        raise ValueError(f"no such proposal: {proposal_id}")
    p = _read_proposal(path)
    p["status"] = "rejected"
    _write_proposal(p)
    _privacy._write_audit({"type": "calendar_write", "op": p.get("op", "create"), "proposal_id": proposal_id, "status": "rejected", "event_identifier": "", "success": True, "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds")})
    return p
