"""warm_producers.py -- Slice 2 kernel producers for the Layer 3a warm tier.

Each producer wraps an already-shipped seam (arms/monitor/librarian) and
returns a WarmFact ready for warm.refresh(). Producers call the FIXED arm
name directly via arms._call_arm -- never arms._detect_arms, whose keyword
match on arbitrary prompt text is side-effecty and the wrong tool here.

capability_state is scoped to monitor.check_mcp_health() only -- doctor()
is a typer CLI command that prints directly (no reusable return value);
sharing its checks into the warm tier is a real refactor, deferred.
"""
from __future__ import annotations

import datetime as _dt
from typing import Callable

from kage import arms as _arms
from kage import guard as _guard
from kage import librarian as _librarian
from kage import monitor as _monitor
from kage import privacy as _privacy
from kage import warm
from kage.warm import WarmFact

# ponytail: fixed TTL per fact category, not adaptive. Ceiling: a fact can be
# up to this stale before the next page-fault refresh. Upgrade: per-identity
# or usage-derived TTL once real hit/miss data exists (see the pitch's
# miss-metric, Slice 6).
_TTL = {
    "timezone": 3600,
    "calendar_next": 900,
    "mail_flagged": 900,
    "pending_approvals": 120,
    "scout_state": 1800,
    "machine_state": 60,
    "frontmost_app": 300,
    "capability_state": 600,
    "interrupt_seed": 60,
}


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _make_fact(key: str, identity: str, value: str | None, provenance: str) -> WarmFact:
    """Sanitize `value` for injection (guard.sanitize_fact) before it ever
    enters warm.json. A flagged value is dropped (never stored), not just
    hidden at render time -- so the local file never holds attacker text.
    """
    if value:
        clean, findings = _guard.sanitize_fact(value)
        if findings:
            _privacy._write_audit({
                "type": "warm_fact_dropped",
                "key": key,
                "identity": identity,
                "reason": "injection_pattern",
                "ts": _now_iso(),
            })
            value = None
        else:
            value = clean
    return WarmFact(
        key=key, value=value, identity=identity, valid_from=_now_iso(),
        ttl_seconds=_TTL[key], provenance=provenance,
    )


def produce_timezone(identity: str) -> WarmFact:
    tz_name = _dt.datetime.now().astimezone().tzname()
    return _make_fact("timezone", identity, tz_name, "macos-tz")


async def produce_calendar_next(identity: str) -> WarmFact:
    try:
        text = await _arms._call_arm("calendar", "what is my next event today", identity)
    except Exception:
        text = None
    return _make_fact("calendar_next", identity, text, "calendar-arm")


async def produce_mail_flagged(identity: str) -> WarmFact:
    try:
        text = await _arms._call_arm("gmail", "any flagged or deadline emails", identity)
    except Exception:
        text = None
    return _make_fact("mail_flagged", identity, text, "gmail-arm")


def produce_pending_approvals(identity: str) -> WarmFact:
    try:
        pending = _librarian.list_pending_approvals()
        value = str(len(pending)) if pending else None
    except Exception:
        value = None
    return _make_fact("pending_approvals", identity, value, "librarian")


def produce_scout_state(identity: str) -> WarmFact:
    try:
        state = _monitor.read_pipeline_state()
        hours = state.get("hours_since_scout_run")
        depth = state.get("librarian_queue_depth")
        value = f"scout_last_run_hours_ago={hours} queue_depth={depth}" if "error" not in state else None
    except Exception:
        value = None
    return _make_fact("scout_state", identity, value, "monitor")


def produce_machine_state(identity: str) -> WarmFact:
    try:
        metrics = _monitor.read_system_metrics()
        value = f"cpu_pct={metrics.get('cpu_pct')} ram_mb={metrics.get('ram_mb')}"
    except Exception:
        value = None
    return _make_fact("machine_state", identity, value, "monitor")


def produce_frontmost_app(identity: str) -> WarmFact:
    try:
        events = _monitor.read_observe_log(hours=0.25)
        value = events[-1].get("ax_text") if events else None
    except Exception:
        value = None
    return _make_fact("frontmost_app", identity, value, "monitor-observe")


async def produce_capability_state(identity: str) -> WarmFact:
    try:
        health = await _monitor.check_mcp_health()
        degraded = [name for name, h in health.items() if h.get("status") != "healthy"]
        value = f"degraded={degraded}" if degraded else "all healthy" if health else None
    except Exception:
        value = None
    return _make_fact("capability_state", identity, value, "monitor")


def _read_unresolved_alerts(limit: int = 3) -> list[tuple]:
    conn = _monitor._connect()
    try:
        return conn.execute(
            "SELECT level, msg FROM monitor_alerts WHERE resolved=0 "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()


def produce_interrupt_seed(identity: str) -> WarmFact:
    try:
        rows = _read_unresolved_alerts()
        value = "; ".join(f"[{level}] {msg}" for level, msg in rows) if rows else None
    except Exception:
        value = None
    return _make_fact("interrupt_seed", identity, value, "monitor_alerts")


_SYNC_PRODUCERS: dict[str, Callable[[str], WarmFact]] = {
    "timezone": produce_timezone,
    "pending_approvals": produce_pending_approvals,
    "scout_state": produce_scout_state,
    "machine_state": produce_machine_state,
    "frontmost_app": produce_frontmost_app,
    "interrupt_seed": produce_interrupt_seed,
}

_ASYNC_PRODUCERS: dict[str, Callable] = {
    "calendar_next": produce_calendar_next,
    "mail_flagged": produce_mail_flagged,
    "capability_state": produce_capability_state,
}


async def refresh_kernel(
    path, identity: str, now: _dt.datetime | None = None, keys: set[str] | None = None,
) -> dict[str, str]:
    """Page-fault refresh: call a producer only if its fact is missing or
    expired. Returns {key: op} for facts actually touched this call -- a
    fact that is still warm is not reported (no work was done for it).
    `keys`, if given, restricts the refresh to that subset (e.g. the S-bar's
    _BAR_KEYS) so callers on a latency budget skip the heavy producers
    (machine_state pings Ollama; capability_state spawns MCP subprocesses).
    """
    now = now or _dt.datetime.now().astimezone()
    resident = {f.key: f for f in warm.active_facts(path, identity)}
    ops: dict[str, str] = {}

    sync_items = _SYNC_PRODUCERS.items() if keys is None else (
        (k, fn) for k, fn in _SYNC_PRODUCERS.items() if k in keys
    )
    async_items = _ASYNC_PRODUCERS.items() if keys is None else (
        (k, fn) for k, fn in _ASYNC_PRODUCERS.items() if k in keys
    )

    for key, fn in sync_items:
        existing = resident.get(key)
        if existing is not None and not existing.is_expired(now):
            continue
        ops[key] = warm.refresh(path, fn(identity))

    for key, fn in async_items:
        existing = resident.get(key)
        if existing is not None and not existing.is_expired(now):
            continue
        ops[key] = warm.refresh(path, await fn(identity))

    return ops


# ponytail: bar reads only the fast, TTL-amortized producers. machine_state
# pings Ollama (2s timeout) and capability_state spawns an MCP subprocess per
# arm -- both would add real latency to every ask/chat. calendar_next still
# spawns osascript on a cold fault (~1-3s), amortized by its 900s TTL; tests
# against a warm-context-on path must mock arms._call_arm.
_BAR_KEYS = {"calendar_next", "pending_approvals"}


def _day_part(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def render_s(
    identity: str,
    project: str | None,
    project_inferred: bool,
    facts: dict[str, str],
    now: _dt.datetime | None = None,
) -> str:
    """Assemble the ~60-token S-render context bar: identity/project first
    (stable for the session), then fact fields, then day-part, then `now`
    (5-min bucket) last -- stable to volatile, so the prefix is cache-stable
    across a run. Every field is sanitized via guard.sanitize_fact even
    though producer facts are already clean at ingestion (_make_fact) --
    an inferred .kage marker project value never passes through a producer,
    so this is its only sanitize gate. A flagged field is dropped and
    audited, never rendered.
    """
    now = now or _dt.datetime.now().astimezone()
    parts = [f"identity={identity}"]

    if project:
        clean, findings = _guard.sanitize_fact(project, source="warm-bar")
        if findings:
            _privacy._write_audit({
                "type": "warm_bar_dropped", "field": "project", "identity": identity,
                "ts": _now_iso(),
            })
        else:
            tag = "~" if project_inferred else ""
            parts.append(f"project={tag}{clean}")

    if facts.get("pending_approvals"):
        clean, findings = _guard.sanitize_fact(facts["pending_approvals"], source="warm-bar")
        if findings:
            _privacy._write_audit({
                "type": "warm_bar_dropped", "field": "pending_approvals", "identity": identity,
                "ts": _now_iso(),
            })
        else:
            parts.append(f"pending={clean}")

    if facts.get("calendar_next"):
        clean, findings = _guard.sanitize_fact(facts["calendar_next"], source="warm-bar")
        if findings:
            _privacy._write_audit({
                "type": "warm_bar_dropped", "field": "calendar_next", "identity": identity,
                "ts": _now_iso(),
            })
        else:
            parts.append(f"next={clean}")

    parts.append(_day_part(now.hour))

    bucket_minute = (now.minute // 5) * 5
    now_str = now.replace(minute=bucket_minute, second=0, microsecond=0).strftime("%H:%M")
    parts.append(f"now={now_str}")

    return " · ".join(parts)
