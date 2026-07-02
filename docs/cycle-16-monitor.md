# Cycle 16 — Monitor: kage's nervous system (ADK LlmAgent + observe.py, v0.17.0)

*Status: SHIPPED v0.17.0 (`460d60f`) — pitch v4 (2026-06-27). Four cold reviews — 2 BLOCKs + 5 WARNs resolved.*

*Brainstorm source: session 2026-06-27. All decisions pre-locked in this pitch. ActivityWatch deferred to v2. Screenpipe: optional, not a dependency. observe.py: IN SCOPE for Kaggle.*

---

## North star

> **Scout finds. Librarian curates. Monitor watches everything.**

Monitor is kage's ultimate observer — a standing background agent that reads every signal in the system (pipeline state, session logs, MCP server health, system metrics, AX tree context from observe.py) and synthesises them into a continuous health picture. It has no execution power except one: priority escalation. It cannot remember, approve, send, or trigger. It can only see, report, and surface blockers.

**Capstone role:** Monitor is the third and final ADK agent (Scout ✅, Librarian ✅, Monitor). The demo story: Scout deposits findings → Librarian curates them → Monitor watches both and tells you if anything is broken, slow, or drifting. Three agents, one pipeline, one observer.

---

## Architecture

```
  OBSERVATION SOURCES (Monitor reads, never polls blindly)
  ┌─────────────────────────────────────────────────────────────┐
  │  kage audit log      session turns, tool calls, arm calls   │
  │                      token usage, provider, latency         │
  │                      model switches — when, what, why       │
  │                      kage CLI commands run                  │
  ├─────────────────────────────────────────────────────────────┤
  │  pipeline state      Scout: last run, yield, tier split     │
  │  (SQLite reads)      Librarian: queue depth, backlog age,   │
  │                        promote/discard ratio, oldest item   │
  │                      Memory: note count, growth, by source  │
  ├─────────────────────────────────────────────────────────────┤
  │  MCP server health   ping every registered server           │
  │                      measure tool call latency              │
  │                      detect failures + degraded responses   │
  ├─────────────────────────────────────────────────────────────┤
  │  system metrics      Ollama up/down + response latency      │
  │                      CPU, RAM, disk (~/.kage/ tree)         │
  │                      ChromaDB + SQLite size                 │
  ├─────────────────────────────────────────────────────────────┤
  │  observe.py output   event-driven AX tree capture (new)     │
  │                      what app + content was focused         │
  │                      CaptureTrigger tag per event           │
  ├─────────────────────────────────────────────────────────────┤
  │  Antigravity context .antigravity.md + session files        │
  │                      kage audit log (Antigravity → kage MCP │
  │                      calls already flow through audit log)  │
  └─────────────────────────────────────────────────────────────┘
                          │  (all local reads, zero network except MCP pings)
  ┌───────────────────────▼─────────────────────────────────────┐
  │  LOCAL PASS (no LLM — continuous, lightweight)              │
  │  rule checks: queue depth > N, MCP server down,             │
  │  Scout not run in 48h, Ollama offline, disk > 90%           │
  │  → write_alert() directly, no LLM needed                   │
  └───────────────────────┬─────────────────────────────────────┘
                          │  accumulated signals
  ┌───────────────────────▼─────────────────────────────────────┐
  │  Monitor LlmAgent  (src/kage/monitor.py)                    │
  │  model: local (Qwen3 via Ollama) for observation pass       │
  │  model: cloud (Sonnet) for periodic digest — 3e gate first  │
  │                                                             │
  │  tools (FunctionTools — ADK auto-wraps):                    │
  │  ┌─ read_pipeline_state   — Scout/Librarian/Memory stats    │
  │  ├─ read_session_log      — turns, tokens, model switches   │
  │  ├─ read_observe_log      — AX tree events from observe.py  │
  │  ├─ check_mcp_health      — ping registered servers         │
  │  ├─ read_system_metrics   — CPU/RAM/disk/Ollama             │
  │  ├─ read_command_history  — kage CLI commands run           │
  │  ├─ read_antigravity_ctx  — .antigravity.md + audit calls   │
  │  ├─ write_alert           — escalate to monitor_alerts      │
  │  └─ set_item_priority     — bump staging_queue priority     │
  └───────────────────────┬─────────────────────────────────────┘
                          │
  ┌───────────────────────▼─────────────────────────────────────┐
  │  OUTPUTS                                                    │
  │  ~/.kage/monitor/state.json      continuous (UI seam)       │
  │  ~/.kage/monitor/YYYY-MM-DD.md   periodic digest (cloud)    │
  │  kage.db monitor_alerts table    surfaced in kage status    │
  └─────────────────────────────────────────────────────────────┘
```

---

## Arm architecture — external vs internal (new concept, Cycle 16)

kage now has two arm categories. This distinction is formalised in `src/kage/arms.py` as part of this cycle.

```
  External arms     Gmail, Calendar, browser, Playwright, etc.
                    User-configured in ~/.kage/config.json → "arms" section
                    _call_arm(arm_name, question, identity) routes these
                    Reach OUTSIDE kage — third-party services and MCP servers

  Internal arms     kage's own subsystems — always present, never user-configured
                    _call_internal_arm(arm_name, tool_name, input) routes these
                    Defined in a hardcoded registry inside arms.py
                    Reach INSIDE kage — kage tools, agent-to-agent communication
```

**Built-in internal arm registry** (hardcoded in `arms.py`, not in `~/.kage/config.json`):

```python
def _resolve_repo_root() -> str:
    # Walk up from arms.py: src/kage/arms.py → src/kage → src → repo root
    # config.home is ~/.kage — its parent is ~ (wrong). Use __file__ instead.
    return str(Path(__file__).resolve().parent.parent.parent)

_INTERNAL_ARMS = {
    "kage-mcp": {
        "transport": "stdio",
        "command": ["uv", "run", "--project", _resolve_repo_root(), "kage", "mcp", "serve"],
        "tools": ["kage_recall", "kage_remember", "kage_ask", "kage_status"],
        "description": "kage's own MCP server — agent-to-agent bus",
    }
}
```

`_resolve_repo_root()` walks up from `__file__` (i.e. `src/kage/arms.py` → three `.parent` calls → repo root containing `pyproject.toml`). **Do NOT use `runtime.config.home.parent`** — that resolves to `~`, not the kage project directory.

**`_call_internal_arm(arm_name, tool_name, input, timeout=10.0) -> dict`** — async function in `arms.py`:
- Looks up `arm_name` in `_INTERNAL_ARMS` (not `runtime.config` — no user setup required)
- Opens a stdio MCP session to the command
- Calls `tool_name` explicitly — no `preferred` heuristic, caller picks the tool
- Returns the tool result as a dict
- 10s timeout (internal arm should be fast — same machine)

**Who uses it now:** Monitor's `ping_kage_mcp()` tool calls `_call_internal_arm("kage-mcp", "kage_status", "status")`.

**Future (post-Kaggle):** Scout, Librarian, and Monitor each get an internal arm entry. Agent-to-agent calls (Monitor asks Librarian to flush queue, Scout asks Monitor for recent context) flow through `_call_internal_arm` — a real agent bus, not Python imports.

---

## observe.py — event-driven AX tree capture

A new module (`src/kage/observe.py`) that runs as a background daemon alongside kage. Inspired by Screenpipe's `CaptureTrigger` enum and ActivityWatch's heartbeat merge pattern, built in pure Python using PyObjC.

**What it captures:** AX tree text from the focused UI element + window title + app name. No screenshots. No video. No audio. No OCR. Accessibility TCC only — NOT Screen Recording.

**PyObjC dependency:** observe.py requires `pyobjc-framework-AppKit`, `pyobjc-framework-Quartz`, `pyobjc-framework-ApplicationServices`, `pyobjc-framework-ScriptingBridge`. These are macOS-only. Added to `pyproject.toml` as an optional dependency group `[macos]`. All PyObjC imports inside observe.py are **lazy** — placed inside `start_observer()` and the functions it calls, NOT at module top level. This means `import kage.observe` succeeds on any platform; only `start_observer()` fails (with a clear error) on non-Mac or when PyObjC is absent. Pure-logic functions (`_heartbeat_merge`, `_pii_strip`) have zero PyObjC imports and are importable everywhere.

**Secure field guard:** Skip any AX element where `kAXRoleAttribute` is `AXSecureTextField` or `kAXRoleDescriptionAttribute` contains "secure". This covers password manager fields and browser password inputs that are incorrectly exposed by Electron apps.

### Trigger model

```
  NSWorkspace notification   app switch → AppSwitch trigger
  (zero TCC, always works)   fires immediately, no polling

  AXObserver                 title change within same app → WindowFocus trigger
  (Accessibility TCC)        event-driven, not polled

  10s polling fallback       catches title changes that don't fire AX notifications
  (ActivityWatch pattern)    safety net for stubborn apps

  CGEventTap (optional)      TypingPause, ScrollStop triggers
  (Input Monitoring TCC)     graceful degrade if permission absent
```

### CaptureTrigger enum (stolen from Screenpipe)

```python
class CaptureTrigger(str, Enum):
    APP_SWITCH    = "app_switch"     # foreground app changed
    WINDOW_FOCUS  = "window_focus"   # title changed within same app
    TYPING_PAUSE  = "typing_pause"   # keyboard activity debounced
    SCROLL_STOP   = "scroll_stop"    # scroll cessation
    VISUAL_CHANGE = "visual_change"  # AX kAXValueChangedNotification on focused element
    IDLE          = "idle"           # fallback: nothing else fired
```

Stored per event. Monitor can filter: "show me all APP_SWITCH events in the last hour."

### Heartbeat merge (ActivityWatch pattern)

```python
def _heartbeat_merge(last: dict, new: dict, pulsetime: float) -> bool:
    """Extend last event's duration instead of creating a new row.
    max() guard prevents a late heartbeat from shrinking the event."""
    if last["app"] != new["app"] or last["window"] != new["window"]:
        return False
    gap_end = last["timestamp"] + last["duration"] + pulsetime
    if new["timestamp"] <= gap_end:
        new_dur = (new["timestamp"] - last["timestamp"]) + new["duration"]
        last["duration"] = max(last["duration"], new_dur)
        return True
    return False
```

Result: one continuous event per app session, not 720 identical rows per hour.

### AFK detection (4 lines, zero TCC)

```python
def _seconds_since_input() -> float:
    # import INSIDE function — lazy, never at module top
    from Quartz.CoreGraphics import (
        CGEventSourceSecondsSinceLastEventType,
        kCGEventSourceStateHIDSystemState, kCGAnyInputEventType,
    )
    return CGEventSourceSecondsSinceLastEventType(
        kCGEventSourceStateHIDSystemState, kCGAnyInputEventType)
```

Stop capturing when idle > `_AFK_THRESHOLD` (default: 180s).

### Electron app fix (VS Code, Antigravity IDE, Notion, Slack)

```python
def _enable_electron_ax(pid: int) -> None:
    """Electron builds AX DOM lazily. Set flag then wait 200ms."""
    app_el = AXUIElementCreateApplication(pid)
    AXUIElementSetAttributeValue(app_el, "AXEnhancedUserInterface", True)
    time.sleep(0.2)
```

Falls back to window title parsing if AX still returns empty after the wait.

### App-specific overrides

```
  Chrome / Brave    ScriptingBridge → full URL + exact title
  Safari            ScriptingBridge → full URL + exact title
  Incognito         blank event {app:"", title:""} — never skip
  Antigravity IDE   AXEnhancedUserInterface + title parse fallback
  Antigravity CLI   terminal context — reads terminal AX buffer
  .antigravity.md   always read when Antigravity is frontmost
```

### PII before storage

Regex strip on every event before writing to disk. No model needed:

```python
_PII_PATTERNS = [
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # email
    r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',                       # phone
    r'\b(sk-|AIza|ghp_|xoxb-)[A-Za-z0-9_-]{10,}\b',            # API keys
]
```

### Storage format

```jsonl
{"ts": 1751234567.89, "app": "Antigravity", "bundle": "com.google.antigravity",
 "window": "librarian.py — kage", "ax_text": "def distill_and_judge...",
 "trigger": "app_switch", "duration": 0, "project": "kage", "identity": "personal"}
```

Written to `~/.kage/observe/YYYY-MM-DD.jsonl`. One line per event. Heartbeat-merged in memory before write. Min gap between heartbeats: 0.5s (prevents window-resize floods).

### NSWorkspace run loop pattern (must be NSObject subclass)

```python
from AppKit import NSWorkspace, NSWorkspaceDidActivateApplicationNotification, NSObject
from PyObjCTools import AppHelper

class _AppSwitchObserver(NSObject):
    def handle_(self, notification):
        app = notification.userInfo()[NSWorkspaceApplicationKey]
        _on_app_switch(app.localizedName(), app.bundleIdentifier(), app.processIdentifier())

# Run loop must be on main thread. All other work on background threads.
AppHelper.runConsoleEventLoop(installInterrupt=True)
```

---

## state.json — UI seam (continuously updated)

Monitor writes `~/.kage/monitor/state.json` on every pass. This is a seam only — no UI is built in this cycle. Future UI reads this file instead of re-querying all subsystems.

```json
{
  "last_updated": "2026-06-27T14:23:11+05:30",
  "pipeline": {
    "scout_last_run": "2026-06-27T06:00:00+05:30",
    "scout_items_today": 12,
    "librarian_queue_depth": 3,
    "librarian_oldest_pending_hours": 2.1,
    "memory_count": 84,
    "memory_added_today": 3
  },
  "system": {
    "ollama_up": true,
    "ollama_latency_ms": 312,
    "disk_used_mb": 1024,
    "chroma_vectors": 4821
  },
  "mcp_servers": {
    "kage": {"status": "healthy", "latency_ms": 12},
    "gmail": {"status": "degraded", "latency_ms": 4200},
    "calendar": {"status": "healthy", "latency_ms": 45}
  },
  "session": {
    "active_project": "kage",
    "active_identity": "personal",
    "active_model": "claude",
    "model_switches_today": 2,
    "tokens_today": {"claude": 12400, "openrouter-free": 3200}
  },
  "alerts": [
    {"level": "warn", "msg": "gmail MCP server latency > 3s", "ts": "..."}
  ]
}
```

---

## Schema changes (additive-only)

### New `monitor_alerts` table

```sql
CREATE TABLE IF NOT EXISTS monitor_alerts (
    id         TEXT PRIMARY KEY,
    level      TEXT NOT NULL,   -- 'info' | 'warn' | 'error'
    msg        TEXT NOT NULL,
    source     TEXT NOT NULL,   -- which tool raised it
    created_at TEXT NOT NULL,
    resolved   INTEGER DEFAULT 0,
    resolved_at TEXT DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_ma_resolved ON monitor_alerts(resolved);
```

Surfaced in `kage status` under existing health display. Cleared by Monitor when condition resolves.

### `staging_queue` priority column (additive)

```sql
ALTER TABLE staging_queue ADD COLUMN priority INTEGER DEFAULT 0;
```

`set_item_priority` bumps this. Librarian's `get_staging_queue` ORDER BY is updated in **Step 2b** to respect priority.

---

## Pattern detection (what the cloud digest reasons about)

These are non-obvious signals the local pass cannot detect — they require reasoning across accumulated observations:

```
  Topic drift          Scout keeps surfacing "ADK" but no ADK notes exist
                       → "consider running kage remember on Scout digest"

  Backlog aging        3 Librarian items pending > 48h
                       → escalate priority, surface in status

  Project cold         no activity on project 'hsi' in 14 days
                       → "hsi context may be stale"

  Model switch pattern always switch away from openrouter-free when doing code tasks
                       → "consider setting claude as default for code sessions"

  Provider latency     Fireworks P95 latency 8x higher than last week
                       → "Fireworks degraded — check status page"

  Memory skew          94% of notes from scout, 2% from user direct
                       → "kage remember underused in recent sessions"

  MCP degradation      gmail arm averaging 4s response, up from 400ms
                       → write_alert level='warn'
```

---

## Antigravity integration

Since Antigravity connects to `kage mcp serve`, every tool call Antigravity makes already flows through kage's audit log. Monitor reads that log — no screen scraping of Antigravity needed.

```
  Priority 1   kage audit log   Antigravity tool calls, queries, results
  Priority 2   .antigravity.md  active project workspace context
  Priority 3   window title     "filename — project — Antigravity" (Electron fallback)
  Priority 4   AXEnhancedUserInterface + 200ms (only if content needed, rare)
```

`read_antigravity_ctx` tool reads `.antigravity.md` from the current project root (resolved via `_resolve_context()`) + last N audit log entries where `arm='antigravity-mcp'`.

---

## Screenpipe: optional, not a dependency

If Screenpipe is running at `localhost:3030`, Monitor gains a richer screen transcript. If not, observe.py covers everything needed. Check at startup:

```python
def _screenpipe_available() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:3030/health", timeout=1)
        return True
    except Exception:
        return False
```

No import, no dependency. Query only when available.

---

## ActivityWatch: deferred to v2

Leave seam: `_activitywatch_available()` check identical to Screenpipe pattern. `query_activitywatch` tool is a stub that returns `None` if AW not running. In v2: `pip install aw-client` + query `aw-watcher-window_{hostname}` bucket for AFK-filtered activity timeline.

---

## Build steps

*Cloud plans and reviews. Qwen3 writes all code and tests. Tests run local.*

---

### Step 0 — ADK verify

Confirm `google-adk[extensions]` still installed, `LlmAgent` and `InMemoryRunner(node=agent)` still work after any dep updates since Cycle 15. Takes 5 minutes. Produces no code.

---

### Step 1 — observe.py

`src/kage/observe.py` — the event-driven AX tree capture daemon.

Spec for Qwen3:
- `class CaptureTrigger(str, Enum)` — 6 values as above
- `class ObserveEvent` — dataclass: ts, app, bundle, window, ax_text, trigger, duration, project, identity. `to_dict()` method returns plain dict (ADK FunctionTool serialization requirement — never return raw dataclass)
- `_seconds_since_input()` — AFK via Quartz (4 lines)
- `_heartbeat_merge(last, new, pulsetime)` — extend duration, max() guard
- `_pii_strip(text)` — regex, 3 patterns
- `_enable_electron_ax(pid)` — AXEnhancedUserInterface + 200ms sleep
- `_read_ax_focused()` — AXUIElementCreateSystemWide + AXFocusedUIElement + AXValue/AXTitle
- `_get_browser_url(app_name)` — ScriptingBridge for Chrome/Safari, None otherwise
- `class _AppSwitchObserver(NSObject)` — handle_ method
- `_write_event(event)` — heartbeat-merge in memory, append to JSONL
- `_observe_loop()` — 10s polling fallback timer
- `start_observer()` — public entry point, starts run loop on main thread
- `read_observe_log(hours=1)` — public reader for Monitor tools; returns `list[dict]` (each ObserveEvent serialized via `.to_dict()`), NOT `list[ObserveEvent]`

**Graceful degrade:** if Accessibility TCC absent → log warning, return app name only (from NSWorkspace, zero TCC). Never crash, never block kage startup. Surface `AXIsProcessTrusted()` status in `kage doctor` (new check added in Step 6).

**Lazy PyObjC imports:** ALL `AppKit`, `PyObjCTools`, `Quartz`, `ApplicationServices`, `ScriptingBridge` imports must be inside `start_observer()` (or inside the functions it calls). Module top-level has ZERO PyObjC imports. `_heartbeat_merge` and `_pii_strip` have no PyObjC dependency and are importable on any platform.

---

### Step 2 — `_gate_text` in pii.py + schema migrations

**2a — Add `_gate_text` to `src/kage/pii.py`:**

`_gate_text` does not currently exist as a named export. Add it to `pii.py` so all agents can import it from a single canonical location:

```python
def _gate_text(text: str) -> str:
    """Strip PII patterns from text before cloud dispatch."""
    from kage.pii import _PII_PATTERNS  # already in same file — direct ref
    import re
    for pattern in _PII_PATTERNS:
        text = re.sub(pattern, "[REDACTED_PII]", text)
    return text
```

Import in monitor.py tool functions: `from kage.pii import _gate_text`. No cfg argument needed — patterns are module-level constants.

**2b — Schema migrations in `monitor.py` (new file):**

Add `_apply_migrations(conn)` to `monitor.py`:

```sql
CREATE TABLE IF NOT EXISTS monitor_alerts (...)
ALTER TABLE staging_queue ADD COLUMN priority INTEGER DEFAULT 0;
```

Idempotent. Both wrapped in try/except for existing-column safety.

**Ordering guard:** `monitor._connect()` calls `runtime.store.init_schema()` first (creates base tables including `staging_queue`) then monitor's own `_apply_migrations`. This ensures `kage monitor run` works even on a fresh install where `kage librarian run` has never been called.

### Step 2b — librarian.py: priority-aware sort (touches librarian.py)

Edit `librarian.py`'s `get_staging_queue` — there are **two** `ORDER BY created_at ASC` clauses (one for `status == "all"` branch, one for the filtered branch). Update **both**:

```python
# before: ORDER BY created_at ASC   (appears twice — update both occurrences)
# after:  ORDER BY priority DESC, created_at ASC
```

This is the only change to `librarian.py`. It makes Monitor's `set_item_priority` immediately visible to Librarian's drain order — the cross-agent coordination the Kaggle demo shows.

---

### Step 2c — Internal arm infrastructure (touches arms.py)

Add to `src/kage/arms.py`:

1. `_INTERNAL_ARMS` dict — hardcoded registry as specified in §Arm architecture
2. `_resolve_repo_root() -> Path` — `runtime.config.home.parent` (or walk up from `__file__` if config not yet initialised)
3. `async def _call_internal_arm(arm_name, tool_name, input, timeout=10.0) -> dict` — opens stdio MCP session to `_INTERNAL_ARMS[arm_name]["command"]`, calls `tool_name`, returns result dict; raises `ValueError` if arm_name unknown

The existing `_call_arm` (external arm routing) is unchanged. `_call_internal_arm` is a parallel function — no shared code path, no risk of accidentally routing an internal call through user config.

Add `_call_internal_arm` to the public exports of `arms.py` so `monitor.py` can import it cleanly.

---

### Step 3 — Monitor tools (10 functions)

All plain Python functions. ADK auto-wraps them as `FunctionTool`. Spec for Qwen3:

```
read_pipeline_state()       → dict: scout_*, librarian_*, memory_*
                              reads from kage.db (staging_queue, memories, scout run log)

read_session_log(hours=24)  → list[dict]: recent session turns
                              fields: ts, project, identity, provider, model,
                              tokens_in, tokens_out, latency_ms, arm_calls
                              includes model_switch events

read_observe_log(hours=1)   → list[dict] from ~/.kage/observe/*.jsonl
                              filtered by hours; lazy import: `from kage import observe`
                              inside function body, not at module top
                              calls _gate_text on ax_text field of EACH event before return

check_mcp_health()          → dict[server_name, {status, latency_ms, error}]
                              ASYNC function (ADK supports async FunctionTool)
                              reads registered arms from runtime.config
                              uses asyncio subprocess (shell arms) or asyncio TCP probe
                              (NOT _call_arm — avoids nested event loop deadlock)
                              timeout: 3s per server

read_system_metrics()       → dict: cpu_pct, ram_mb, disk_used_mb,
                              ollama_up, ollama_latency_ms, chroma_vectors,
                              sqlite_size_mb
                              uses psutil (already available) + Ollama ping

read_command_history(n=50)  → list[dict]: last N kage CLI invocations
                              reads from audit log (command, ts, duration_ms)

read_session_log(hours=24)  (cont.)
                              calls _gate_text on each turn's content before return

read_antigravity_ctx()      → dict: workspace_md (str), recent_mcp_calls (list)
                              reads .antigravity.md from cwd or project root
                              + last 20 audit entries where source='antigravity'
                              calls _gate_text on workspace_md before return

ping_kage_mcp()             → dict: {status, tools_available, latency_ms}
                              ASYNC — calls _call_internal_arm("kage-mcp", "kage_status", "status")
                              this is the Kaggle-required MCP protocol demonstration:
                              Monitor calls kage's own server through the internal arm
                              via the real MCP stdio protocol, not a Python import.
                              Satisfies "MCP server usage" judging criterion.

write_alert(level, msg,     → str: alert_id
            source)           inserts into monitor_alerts; level in info/warn/error

set_item_priority(          → bool
    staging_id, priority)     UPDATE staging_queue SET priority=? WHERE id=?
```

---

### Step 4 — ADK wiring (Workflow, two LlmAgents)

Monitor uses the same pattern as Scout: a `Workflow` with two `LlmAgent` nodes connected by edges. `SequentialAgent` is deprecated in the installed ADK — always use `Workflow`.

```
MonitorObserve  LlmAgent  model=qwen3 (local Ollama via _litellm_target)
                          tools: all 10 read tools + write_alert + set_item_priority
                          instruction: _MONITOR_OBSERVE_INSTRUCTION

MonitorDigest   LlmAgent  model=cfg["default_provider"] (cloud)
                          tools: (none — input is MonitorObserve's output via Workflow edge)
                          instruction: _MONITOR_DIGEST_INSTRUCTION
                          before_model_callback: _pii_seam (gates MonitorObserve output
                          through _gate_text before cloud sees it — same pattern as Scout)
```

```python
from google.adk.agents import LlmAgent
from google.adk.agents.workflow import Workflow, START

observe_agent = LlmAgent(name="MonitorObserve", ...)
digest_agent  = LlmAgent(name="MonitorDigest",  before_model_callback=_pii_seam, ...)

agent = Workflow(
    name="Monitor",
    edges=[(START, observe_agent), (observe_agent, digest_agent)],
)
```

`build_monitor(cfg)` returns this `Workflow`. `_run_once_impl(cfg)` drives `InMemoryRunner(node=agent, app_name="kage-monitor")`.

`_MONITOR_OBSERVE_INSTRUCTION` (MonitorObserve LlmAgent):

```
You are Monitor — kage's observer. Your job is to read pipeline state, session logs,
system health, and activity context, then:
1. Write alerts for any anomaly you detect (queue backlog, MCP server down, Ollama offline,
   Scout not run in 48h, disk > 90%).
2. Detect non-obvious patterns across accumulated signals (topic drift, model switch
   patterns, provider latency trends, project going cold).
3. Write a concise digest summarising findings.

You have NO execution power. You cannot approve, remember, send, or trigger anything.
write_alert and set_item_priority are your only writes.

Always call check_mcp_health, ping_kage_mcp, and read_pipeline_state first.
Call read_session_log to check for model switches and token usage.
Call read_observe_log to understand what the user was working on.
End your response with a structured summary of findings for MonitorDigest.
```

`_MONITOR_DIGEST_INSTRUCTION` (MonitorDigest LlmAgent):

```
You are MonitorDigest. You receive MonitorObserve's structured findings.
Write a ≤300-word human-readable digest: anomalies detected, patterns noticed,
recommendations. Do not repeat raw numbers — synthesise them into insight.
```

3e gate: MonitorObserve's summary string passes through `_gate_text` before being placed in MonitorDigest's context. Both agents use same `_litellm_target` pattern as Scout/Librarian.

---

### Step 5 — state.json writer

`_write_state_json(state: dict)` — writes `~/.kage/monitor/state.json` atomically (write to `.tmp`, rename). Called at the end of every `_run_once_impl`. Content matches the schema defined in §state.json above.

---

### Step 6 — CLI surface

Wire into `src/kage/cli.py` under `kage monitor`:

```
kage monitor run       _run_once_impl(cfg) — run one pass, write digest + state.json
kage monitor last      read ~/.kage/monitor/*.md sorted by name desc, print latest
kage monitor status    print state.json summary: health, queue, alerts, active model
kage monitor install   generate plist + load into launchd (see Step 7)
kage monitor uninstall launchctl bootout + delete plist
```

`kage status` (existing) gains one block: active alerts from `monitor_alerts` where `resolved=0`. In `cli.py`, find the `status` command (the `@app.command()` decorated function named `status`) and append the alert block after the existing health/provider output. Query: `SELECT level, msg, created_at FROM monitor_alerts WHERE resolved=0 ORDER BY created_at DESC LIMIT 5`. Print only if rows exist — no output when no alerts (silent = healthy).

**`kage doctor` addition:** add an Accessibility TCC check using `AXIsProcessTrusted()` (from `ApplicationServices`, lazy-imported). Print pass/fail: "Accessibility TCC: ✓ granted" or "Accessibility TCC: ✗ — grant in System Settings → Privacy → Accessibility → add Terminal (or the binary running kage). Note: launchd-launched processes require the grant to target the `uv` binary directly, not Terminal."

---

### Step 7 — `kage monitor install` (bootstrap command)

This cycle establishes the **agent bootstrap pattern** used by all three agents. Each agent gets an `install` / `uninstall` subcommand that generates and loads its launchd plist at runtime — no static template file, no manual path editing.

Add to `kage monitor` CLI group:

```
kage monitor install    generate plist with resolved paths, write to disk, load into launchd
kage monitor uninstall  launchctl bootout + delete plist
```

The `install` command generates the plist programmatically:

```python
def _generate_plist(uv_path: str, project_root: str, home: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.kage.monitor</string>
  <key>ProgramArguments</key>
  <array>
    <string>{uv_path}</string>
    <string>run</string><string>--project</string>
    <string>{project_root}</string>
    <string>kage</string><string>monitor</string><string>run</string>
  </array>
  <key>StartInterval</key><integer>300</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>{home}</string>
    <key>OLLAMA_HOST</key><string>http://localhost:11434</string>
  </dict>
  <key>StandardOutPath</key><string>{home}/.kage/logs/monitor.log</string>
  <key>StandardErrorPath</key><string>{home}/.kage/logs/monitor.err</string>
</dict></plist>"""
```

Called as:

```python
uv_path = shutil.which("uv")
if not uv_path:
    typer.echo("Error: uv not found on PATH. Install uv first.", err=True)
    raise typer.Exit(1)

project_root = _resolve_repo_root()   # from arms._resolve_repo_root()
home         = str(Path.home())
log_dir      = Path.home() / ".kage" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)          # launchd needs dir to exist

plist_path = Path.home() / ".config" / "kage" / "dev.kage.monitor.plist"
plist_path.parent.mkdir(parents=True, exist_ok=True)
plist_path.write_text(_generate_plist(uv_path, project_root, home))

# Unload first if already registered (idempotent reinstall)
subprocess.run(
    ["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path)],
    check=False,   # non-zero is fine if not currently loaded
)
subprocess.run(
    ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)],
    check=True,
)
typer.echo(f"Monitor installed. Runs every 5 minutes. Logs: {log_dir}")
```

For `kage monitor uninstall`, the exact bootout call is:
```python
subprocess.run(
    ["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path)],
    check=False,
)
plist_path.unlink(missing_ok=True)
```

**TCC note (launchd context):** Accessibility TCC granted to Terminal does NOT cover processes launched by `launchctl`. After `kage monitor install`, grant Accessibility to the `uv` binary in System Settings → Privacy & Security → Accessibility. `kage doctor` shows `AXIsProcessTrusted()` status to confirm.

**Pattern note:** Scout and Librarian will be retrofitted with `kage scout install` / `kage librarian install` using the same `_generate_plist` pattern. This is the standard agent bootstrap going forward.

---

### Step 8 — Tests

`tests/test_monitor.py` — unit tests, no live LLM, no live MCP servers.

Target: ~21 tests covering:

```
test_schema_migration_idempotent         monitor_alerts + priority column
test_write_alert_inserts_row             level, msg, source stored correctly
test_write_alert_resolved_default_false  resolved=0 on creation
test_set_item_priority_updates_row       staging_queue.priority updated
test_read_pipeline_state_keys            all expected keys present
test_read_system_metrics_keys            cpu_pct, ram_mb, disk_used_mb present
test_check_mcp_health_timeout            unreachable server → error status, no crash
                                         (mock asyncio probe, not live network)
test_call_internal_arm_unknown_name      ValueError on unknown arm name
test_internal_arm_registry_has_kage_mcp kage-mcp present in _INTERNAL_ARMS
test_ping_kage_mcp_returns_status        mock _call_internal_arm → status dict returned, no crash
test_read_observe_log_empty              no jsonl file → returns empty list
test_pii_strip_email                     email redacted before storage
test_pii_strip_api_key                   sk- prefix key redacted
test_pii_clean_passthrough               clean text unchanged
test_heartbeat_merge_extends_duration    same app+window → duration extends
test_heartbeat_merge_max_guard           late heartbeat does not shrink event
test_heartbeat_no_merge_different_app    different apps → no merge
test_capture_trigger_enum                all 6 values valid
test_state_json_written                  _write_state_json creates valid JSON file
test_generate_plist_contains_uv_path     _generate_plist output has correct uv path
test_generate_plist_valid_xml            output is parseable as plist XML
```

Fixture: `mon_env` — same pattern as `lib_env`, patches `runtime.store` and `runtime.config` to `tmp_path`.

**CI guard:** Tests importing observe.py functions that transitively use PyObjC must be decorated with `@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC macOS only")`. Pure-logic tests (`test_heartbeat_*`, `test_pii_*`, `test_capture_trigger_enum`) have no PyObjC dependency — they are importable and runnable on any platform without skipping.

---

## What Monitor does NOT do

```
  ✗  approve Librarian items
  ✗  trigger Scout runs
  ✗  write to permanent memory
  ✗  send notifications (deferred — dispatch arm, post-Kaggle)
  ✗  screen capture / screenshots (observe.py uses AX tree only)
  ✗  keyboard logging (CGEventTap optional, degrades gracefully)
  ✗  ActivityWatch integration (v2 seam only)
  ✗  Screenpipe hard dependency (optional query if running)
  ✗  UI (state.json is the seam — UI built post-Kaggle)
```

---

## Deferred (post-Kaggle)

- ActivityWatch v2 integration (`aw-client`, AFK timeline, app usage)
- Dispatch arm (ntfy + Telegram) — push Monitor alerts to phone
- observe.py CGEventTap (TypingPause, ScrollStop triggers) — needs Input Monitoring TCC
- Screenpipe integration if license clarifies
- VS Code extension / Antigravity extension for richer context
- Monitor-triggered Librarian priority queue flush

---

## Capstone story (three agents)

```
  SCOUT      runs on schedule (launchd 6am)
             fetches HN · arXiv · GitHub · Reddit · RSS
             ADK SequentialAgent: ScoutBroad (local) → ScoutIntegrate (cloud)
             deposits Tier 1 items to staging_queue

  LIBRARIAN  reads staging_queue
             ADK LlmAgent: distill_and_judge (3e gate + cloud)
             PROMOTE / HOLD / DISCARD — human approves every write
             sole writer to permanent memory

  MONITOR    watches both + system + session + MCP servers + screen context
             ADK Workflow: MonitorObserve (local) → MonitorDigest (cloud, 3e gate)
             ping_kage_mcp() → _call_internal_arm("kage-mcp", "kage_status") (Kaggle ✓)
             write_alert + set_item_priority — no other execution
             state.json: continuous snapshot (UI seam)
             ~/.kage/monitor/YYYY-MM-DD.md: periodic digest

  ARM BUS    External arms: _call_arm() → user-configured Gmail/Calendar/browser
             Internal arms: _call_internal_arm() → kage-mcp (always present)
             Agent-to-agent communication uses internal arm bus (post-Kaggle: Scout/Librarian arms)

  DATA FLOW
  Scout → staging_queue → Librarian → memory
                      ↑               ↑
                   Monitor reads both, surfaces anomalies
```

---

*Pitch v4. Four cold reviews complete (CR1: 3B/5W; CR2: 1B/7W; CR3: 5B/4W; CR4: 2B/5W resolved). 19 PASSes on final review. BUILD READY.*
