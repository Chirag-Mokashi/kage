"""Monitor — kage's observer ADK agent (Cycle 16, v0.17.0).

Two-pass Workflow: MonitorObserve (local Qwen3) reads all signals and writes alerts;
MonitorDigest (cloud) synthesises into a human-readable ≤300-word digest.
3e gate via _pii_seam before_model_callback on MonitorDigest.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
import urllib.request

import os

from kage import runtime
from kage.arms import _call_internal_arm, _INTERNAL_ARMS, _SHELL_INTERPRETERS
from kage.cloud import DEFAULT_PROVIDERS
from kage.pii import _gate_text


# ── DB helpers ────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    runtime.store.init_schema()
    conn = runtime.store.connect()
    _apply_migrations(conn)
    conn.commit()
    return conn


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Idempotent schema additions for Monitor."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_alerts (
            id          TEXT PRIMARY KEY,
            level       TEXT NOT NULL,
            msg         TEXT NOT NULL,
            source      TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            resolved    INTEGER DEFAULT 0,
            resolved_at TEXT DEFAULT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ma_resolved ON monitor_alerts(resolved)")
    try:
        conn.execute("ALTER TABLE staging_queue ADD COLUMN priority INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists


# ── Tool functions (ADK FunctionTool auto-wrap) ───────────────────────────────

def read_pipeline_state() -> dict:
    """Read Scout, Librarian, and Memory state from kage.db."""
    try:
        conn = _connect()
        try:
            scout_row = conn.execute(
                "SELECT created_at, notes_fetched FROM scout_runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            scout_last_run = scout_row[0] if scout_row else None
            scout_items_today = scout_row[1] if scout_row else 0
        except sqlite3.OperationalError:
            # scout_runs table doesn't exist yet (Scout never run)
            scout_last_run, scout_items_today = None, 0

        queue_depth = conn.execute(
            "SELECT COUNT(*) FROM staging_queue WHERE status='pending'"
        ).fetchone()[0]

        oldest = conn.execute(
            "SELECT created_at FROM staging_queue WHERE status='pending' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        oldest_pending_hours = 0.0
        if oldest:
            try:
                ts = datetime.fromisoformat(oldest[0])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                oldest_pending_hours = round(
                    (datetime.now(timezone.utc) - ts).total_seconds() / 3600, 1
                )
            except Exception:
                pass

        memory_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        memory_added_today = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE created_at LIKE ?", (f"{today}%",)
        ).fetchone()[0]
        conn.close()
        return {
            "scout_last_run": scout_last_run,
            "scout_items_today": scout_items_today,
            "librarian_queue_depth": queue_depth,
            "librarian_oldest_pending_hours": oldest_pending_hours,
            "memory_count": memory_count,
            "memory_added_today": memory_added_today,
        }
    except Exception as e:
        return {"error": str(e)}


def read_session_log(hours: float = 24.0) -> list[dict]:
    """Read recent session turns from kage.db. Applies _gate_text to content field."""
    try:
        conn = _connect()
        cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
        cutoff_str = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
        rows = conn.execute(
            "SELECT * FROM session_turns WHERE ts >= ? ORDER BY ts DESC LIMIT 200",
            (cutoff_str,),
        ).fetchall()
        desc = conn.execute("SELECT * FROM session_turns LIMIT 0").description
        cols = [d[0] for d in desc] if desc else []
        conn.close()
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            if d.get("content"):
                d["content"] = _gate_text(d["content"])
            result.append(d)
        return result
    except Exception as e:
        return [{"error": str(e)}]


def read_observe_log(hours: float = 1.0) -> list[dict]:
    """Read AX tree events from observe.py log. Applies _gate_text to ax_text."""
    # lazy import — PyObjC only needed at runtime on macOS
    from kage import observe
    events = observe.read_observe_log(hours=hours)
    for ev in events:
        if ev.get("ax_text"):
            ev["ax_text"] = _gate_text(ev["ax_text"])
    return events


async def check_mcp_health() -> dict:
    """Ping registered MCP servers. Returns {name: {status, latency_ms}}."""
    arms = runtime.config.data.get("arms", {})
    result: dict[str, Any] = {}
    for name, arm in arms.items():
        if not arm.get("enabled"):
            continue
        t0 = time.monotonic()
        try:
            async with asyncio.timeout(3.0):
                if arm.get("transport") == "shell":
                    cmd = arm.get("command", "")
                    if cmd:
                        import shlex
                        try:
                            parts = shlex.split(cmd)
                        except ValueError:
                            result[name] = {"status": "error", "error": "bad command syntax", "latency_ms": 0}
                            continue
                        if not parts or parts[0].rsplit("/", 1)[-1] in _SHELL_INTERPRETERS:
                            result[name] = {"status": "blocked", "error": "interpreter", "latency_ms": 0}
                            continue
                        proc = await asyncio.create_subprocess_exec(
                            *parts, "--help",
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        await proc.wait()
                        latency_ms = round((time.monotonic() - t0) * 1000)
                        result[name] = {
                            "status": "healthy" if proc.returncode == 0 else "degraded",
                            "latency_ms": latency_ms,
                        }
                    else:
                        result[name] = {"status": "error", "error": "no command", "latency_ms": 0}
                elif arm.get("transport") == "stdio":
                    mcp_cmd = arm.get("mcp_command", "")
                    if mcp_cmd:
                        parts = mcp_cmd.split()
                        proc = await asyncio.create_subprocess_exec(
                            *parts,
                            stdin=asyncio.subprocess.PIPE,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        init_msg = (
                            '{"jsonrpc":"2.0","id":1,"method":"initialize",'
                            '"params":{"protocolVersion":"2024-11-05","capabilities":{},'
                            '"clientInfo":{"name":"kage-health","version":"1"}}}\n'
                        )
                        proc.stdin.write(init_msg.encode())
                        await proc.stdin.drain()
                        line = await proc.stdout.readline()
                        proc.kill()
                        await proc.wait()
                        try:
                            resp = json.loads(line)
                            ok = "result" in resp
                        except Exception:
                            ok = False
                        latency_ms = round((time.monotonic() - t0) * 1000)
                        result[name] = {
                            "status": "healthy" if ok else "degraded",
                            "latency_ms": latency_ms,
                        }
                    else:
                        result[name] = {"status": "error", "error": "no mcp_command", "latency_ms": 0}
                else:
                    result[name] = {"status": "unknown", "latency_ms": 0}
        except asyncio.TimeoutError:
            result[name] = {"status": "timeout", "latency_ms": 3000}
        except Exception as e:
            result[name] = {"status": "error", "error": str(e), "latency_ms": 0}
    return result


def read_system_metrics() -> dict:
    """Read CPU, RAM, disk, Ollama, ChromaDB, SQLite sizes."""
    metrics: dict[str, Any] = {}
    metrics["cpu_pct"] = psutil.cpu_percent(interval=0.5)
    metrics["ram_mb"] = round(psutil.virtual_memory().used / 1024 / 1024)
    kage_dir = Path(runtime.config.home)
    try:
        total = sum(f.stat().st_size for f in kage_dir.rglob("*") if f.is_file())
        metrics["disk_used_mb"] = round(total / 1024 / 1024, 1)
    except Exception:
        metrics["disk_used_mb"] = 0
    t0 = time.monotonic()
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        metrics["ollama_up"] = True
        metrics["ollama_latency_ms"] = round((time.monotonic() - t0) * 1000)
    except Exception:
        metrics["ollama_up"] = False
        metrics["ollama_latency_ms"] = -1
    try:
        db_path = kage_dir / "indexes" / "kage.db"
        metrics["sqlite_size_mb"] = round(db_path.stat().st_size / 1024 / 1024, 2) if db_path.exists() else 0
    except Exception:
        metrics["sqlite_size_mb"] = 0
    try:
        chroma_dir = Path(runtime.config.home) / "indexes" / "chroma"
        embed_model = runtime.config.data.get("embed_model", "nomic-embed-text")
        coll = runtime.vector.collection(chroma_dir, embed_model)
        metrics["chroma_vectors"] = coll.count()
    except Exception:
        metrics["chroma_vectors"] = 0
    return metrics


def read_command_history(n: int = 50) -> list[dict]:
    """Read last N kage CLI invocations from the audit log."""
    try:
        audit_path = Path(runtime.config.home) / "audit.jsonl"
        if not audit_path.exists():
            return []
        lines = audit_path.read_text().splitlines()
        result = []
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                if entry.get("type") == "command":
                    result.append(entry)
                    if len(result) >= n:
                        break
            except Exception:
                continue
        return list(reversed(result))
    except Exception as e:
        return [{"error": str(e)}]


def read_antigravity_ctx() -> dict:
    """Read .antigravity.md from project root + last 20 audit entries from Antigravity."""
    ctx: dict[str, Any] = {"workspace_md": "", "recent_mcp_calls": []}
    try:
        project = runtime.config.data.get("project", "")
        candidates = [Path.cwd() / ".antigravity.md", Path.home() / ".antigravity.md"]
        if project:
            candidates.insert(0, Path.home() / "Projects" / project / ".antigravity.md")
        for p in candidates:
            if p.exists():
                ctx["workspace_md"] = _gate_text(p.read_text())
                break
    except Exception:
        pass
    try:
        audit_path = Path(runtime.config.home) / "audit.jsonl"
        if audit_path.exists():
            lines = audit_path.read_text().splitlines()
            calls: list[dict] = []
            for line in reversed(lines):
                try:
                    entry = json.loads(line)
                    if entry.get("source") == "antigravity" or entry.get("arm") == "antigravity-mcp":
                        calls.append(entry)
                        if len(calls) >= 20:
                            break
                except Exception:
                    continue
            ctx["recent_mcp_calls"] = list(reversed(calls))
    except Exception:
        pass
    return ctx


async def ping_kage_mcp() -> dict:
    """Call kage's own MCP server via _call_internal_arm. Satisfies Kaggle MCP criterion."""
    t0 = time.monotonic()
    try:
        result = await _call_internal_arm("kage-mcp", "kage_status", "status", timeout=10.0)
        latency_ms = round((time.monotonic() - t0) * 1000)
        return {
            "status": "healthy",
            "tools_available": _INTERNAL_ARMS["kage-mcp"]["tools"],
            "latency_ms": latency_ms,
            "output": result.get("output", ""),
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "latency_ms": -1}


def write_alert(level: str, msg: str, source: str) -> str:
    """Insert an alert into monitor_alerts. level: info | warn | error. Returns alert id."""
    if level not in ("info", "warn", "error"):
        level = "info"
    msg = _gate_text(msg)
    alert_id = str(uuid.uuid4())
    conn = _connect()
    conn.execute(
        "INSERT INTO monitor_alerts (id, level, msg, source, created_at) VALUES (?, ?, ?, ?, ?)",
        (alert_id, level, msg, source, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return alert_id


def set_item_priority(staging_id: str, priority: int) -> bool:
    """Bump a staging_queue item's priority so Librarian drains it sooner."""
    try:
        conn = _connect()
        conn.execute(
            "UPDATE staging_queue SET priority=? WHERE id=?", (priority, staging_id)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ── state.json writer ─────────────────────────────────────────────────────────

def _write_state_json(state: dict) -> None:
    """Atomically write state.json to ~/.kage/monitor/state.json."""
    monitor_dir = Path(runtime.config.home) / "monitor"
    monitor_dir.mkdir(parents=True, exist_ok=True)
    tmp = monitor_dir / "state.json.tmp"
    dest = monitor_dir / "state.json"
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.rename(dest)


# ── plist generation (Step 7) ─────────────────────────────────────────────────

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


def _generate_observe_plist(uv_path: str, project_root: str, home: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.kage.monitor.observe</string>
  <key>ProgramArguments</key>
  <array>
    <string>{uv_path}</string>
    <string>run</string><string>--project</string>
    <string>{project_root}</string>
    <string>kage</string><string>monitor</string><string>observe</string>
  </array>
  <key>StartInterval</key><integer>300</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>{home}</string>
    <key>OLLAMA_HOST</key><string>http://localhost:11434</string>
  </dict>
  <key>StandardOutPath</key><string>{home}/.kage/logs/monitor-observe.log</string>
  <key>StandardErrorPath</key><string>{home}/.kage/logs/monitor-observe.err</string>
</dict></plist>"""


def _generate_digest_plist(uv_path: str, project_root: str, home: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.kage.monitor.digest</string>
  <key>ProgramArguments</key>
  <array>
    <string>{uv_path}</string>
    <string>run</string><string>--project</string>
    <string>{project_root}</string>
    <string>kage</string><string>monitor</string><string>digest</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>{home}</string>
    <key>OLLAMA_HOST</key><string>http://localhost:11434</string>
  </dict>
  <key>StandardOutPath</key><string>{home}/.kage/logs/monitor-digest.log</string>
  <key>StandardErrorPath</key><string>{home}/.kage/logs/monitor-digest.err</string>
</dict></plist>"""


# ── ADK Workflow ──────────────────────────────────────────────────────────────

_MONITOR_OBSERVE_INSTRUCTION = (
    "You are Monitor — kage's observer. Your job is to read pipeline state, session logs, "
    "system health, and activity context, then:\n"
    "1. Write alerts for any anomaly you detect (queue backlog, MCP server down, Ollama "
    "offline, Scout not run in 48h, disk > 90%).\n"
    "2. Detect non-obvious patterns across accumulated signals (topic drift, model switch "
    "patterns, provider latency trends, project going cold).\n"
    "3. Write a concise digest summarising findings.\n\n"
    "You have NO execution power. You cannot approve, remember, send, or trigger anything. "
    "write_alert and set_item_priority are your only writes.\n\n"
    "Always call check_mcp_health, ping_kage_mcp, and read_pipeline_state first. "
    "Call read_session_log to check for model switches and token usage. "
    "Call read_observe_log to understand what the user was working on. "
    "End your response with a structured summary of findings for MonitorDigest."
)

_MONITOR_DIGEST_INSTRUCTION = (
    "You are MonitorDigest. You receive MonitorObserve's structured findings. "
    "Write a ≤300-word human-readable digest: anomalies detected, patterns noticed, "
    "recommendations. Do not repeat raw numbers — synthesise them into insight."
)


def _pii_seam(callback_context: Any, llm_request: Any) -> None:
    """before_model_callback: gate MonitorObserve output through _gate_text before cloud."""
    if llm_request.contents:
        for content in llm_request.contents:
            if hasattr(content, "parts"):
                for part in content.parts:
                    if hasattr(part, "text") and part.text:
                        part.text = _gate_text(part.text)
    return None


_LITELLM_PREFIX = {"claude": "anthropic", "openai": "openai", "gemini": "gemini", "openai-compat": "openai"}


def _litellm_target(provider: str, cfg: dict) -> tuple[str, str | None, str | None]:
    """kage provider config → (litellm_model, api_key|None, api_base|None). Mirrors scout.py."""
    pcfg = {**DEFAULT_PROVIDERS.get(provider, {}), **cfg.get("providers", {}).get(provider, {})}
    if "model" not in pcfg:
        raise ValueError(
            f"monitor cloud_provider '{provider}' not configured — add providers.{provider} to ~/.kage/config.json"
        )
    ptype = pcfg.get("type", "openai-compat")
    model = f"{_LITELLM_PREFIX.get(ptype, 'openai')}/{pcfg['model']}"
    api_key = os.environ.get(pcfg["api_key_env"]) or None
    if ptype == "openai-compat":
        api_base = pcfg["base_url"] + pcfg.get("chat_path", "/chat/completions").removesuffix("/chat/completions")
    else:
        api_base = None
    return model, api_key, api_base


def build_monitor(cfg: dict):
    """Return ADK Workflow with MonitorObserve → MonitorDigest."""
    from google.adk.agents import LlmAgent
    from google.adk.models.lite_llm import LiteLlm
    from google.adk.workflow import Workflow, START

    from kage.sensitive import scan_sensitive_patterns
    observe_tools = [
        read_pipeline_state, read_session_log, read_observe_log, check_mcp_health,
        read_system_metrics, read_command_history, read_antigravity_ctx, ping_kage_mcp,
        write_alert, set_item_priority, scan_sensitive_patterns,
    ]
    local_model = cfg.get("local_model", "qwen3:14b")
    observe_agent = LlmAgent(
        name="MonitorObserve",
        model=LiteLlm(model=f"ollama_chat/{local_model}"),
        instruction=_MONITOR_OBSERVE_INSTRUCTION,
        tools=observe_tools,
    )
    provider = cfg.get("monitor", {}).get("cloud_provider", cfg.get("cloud_provider", "openrouter-free"))
    model_str, api_key, api_base = _litellm_target(provider, cfg)
    digest_kwargs: dict = {"model": model_str}
    if api_key:
        digest_kwargs["api_key"] = api_key
    if api_base:
        digest_kwargs["api_base"] = api_base
    digest_agent = LlmAgent(
        name="MonitorDigest",
        model=LiteLlm(**digest_kwargs),
        instruction=_MONITOR_DIGEST_INSTRUCTION,
        before_model_callback=_pii_seam,
        output_key="monitor_digest",
    )
    return Workflow(
        name="Monitor",
        edges=[(START, observe_agent), (observe_agent, digest_agent)],
    )


def build_monitor_observe(cfg: dict):
    """Return ADK Workflow with MonitorObserve only (local Qwen3, 24/7)."""
    from google.adk.agents import LlmAgent
    from google.adk.models.lite_llm import LiteLlm
    from google.adk.workflow import Workflow, START

    from kage.sensitive import scan_sensitive_patterns
    observe_tools = [
        read_pipeline_state, read_session_log, read_observe_log, check_mcp_health,
        read_system_metrics, read_command_history, read_antigravity_ctx, ping_kage_mcp,
        write_alert, set_item_priority, scan_sensitive_patterns,
    ]
    local_model = cfg.get("local_model", "qwen3:14b")
    observe_agent = LlmAgent(
        name="MonitorObserve",
        model=LiteLlm(model=f"ollama_chat/{local_model}"),
        instruction=_MONITOR_OBSERVE_INSTRUCTION,
        tools=observe_tools,
        output_key="monitor_findings",
    )
    return Workflow(name="kage_monitor_obs", edges=[(START, observe_agent)])


def build_monitor_digest(cfg: dict):
    """Return ADK Workflow with MonitorDigest only (cloud, once daily)."""
    from google.adk.agents import LlmAgent
    from google.adk.models.lite_llm import LiteLlm
    from google.adk.workflow import Workflow, START

    provider = cfg.get("monitor", {}).get("cloud_provider", cfg.get("cloud_provider", "openrouter-free"))
    model_str, api_key, api_base = _litellm_target(provider, cfg)
    digest_kwargs: dict = {"model": model_str}
    if api_key:
        digest_kwargs["api_key"] = api_key
    if api_base:
        digest_kwargs["api_base"] = api_base
    digest_agent = LlmAgent(
        name="MonitorDigest",
        model=LiteLlm(**digest_kwargs),
        instruction=_MONITOR_DIGEST_INSTRUCTION,
        before_model_callback=_pii_seam,
        output_key="monitor_digest",
    )
    return Workflow(name="kage_monitor_dig", edges=[(START, digest_agent)])


def _run_once_impl(cfg: dict) -> str:
    """Run one Monitor pass. Returns the digest text."""
    from google.adk.runners import InMemoryRunner
    import google.genai.types as genai_types

    agent = build_monitor(cfg)
    runner = InMemoryRunner(node=agent, app_name="kage-monitor")
    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text="Run a full monitoring pass and produce a digest.")],
    )
    session = asyncio.run(
        runner.session_service.create_session(app_name="kage-monitor", user_id="kage")
    )
    list(runner.run(user_id="kage", session_id=session.id, new_message=content))
    session = asyncio.run(runner.session_service.get_session(
        app_name="kage-monitor", user_id="kage", session_id=session.id
    ))
    digest = (session.state.get("monitor_digest") or "") if session else ""

    monitor_dir = Path(runtime.config.home) / "monitor"
    monitor_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    (monitor_dir / f"{today}.md").write_text(digest)
    _write_state_json({
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "digest_preview": digest[:200] if digest else "",
    })
    return digest


def _observe_impl(cfg: dict) -> None:
    """Run one MonitorObserve pass and append findings to today's JSONL file."""
    from google.adk.runners import InMemoryRunner
    import google.genai.types as genai_types

    agent = build_monitor_observe(cfg)
    runner = InMemoryRunner(node=agent, app_name="kage-monitor-obs")
    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text="Run a monitoring observation pass.")],
    )
    session = asyncio.run(
        runner.session_service.create_session(app_name="kage-monitor-obs", user_id="kage")
    )
    list(runner.run(user_id="kage", session_id=session.id, new_message=content))
    session = asyncio.run(runner.session_service.get_session(
        app_name="kage-monitor-obs", user_id="kage", session_id=session.id
    ))
    findings = (session.state.get("monitor_findings") or "") if session else ""

    monitor_dir = Path(runtime.config.home) / "monitor"
    monitor_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    obs_path = monitor_dir / f"observations-{today}.jsonl"
    record = {"ts": datetime.now().astimezone().isoformat(), "findings": findings}
    with obs_path.open("a") as f:
        f.write(json.dumps(record) + "\n")
    _write_state_json({"last_observe": record["ts"], "latest_findings": findings[:500]})


def _maybe_trigger_learn(home: Path) -> None:
    """Fire `kage learn --all` / `--librarian` when 7+ new corrections accumulated since last run."""
    import subprocess
    from kage.learn import _count_total_corrections, _count_corrections, _read_learn_state, _write_learn_state
    state = _read_learn_state(home=home)
    total = _count_total_corrections(home=home)
    if total - state.get("last_learn_correction_count", 0) >= 7:
        subprocess.run(["kage", "learn", "--all"], check=False)
        state = {**state, "last_learn_correction_count": total}
    lib_total = _count_corrections("kage-corrections-librarian", home=home)
    if lib_total - state.get("last_librarian_learn_count", 0) >= 7:
        subprocess.run(["kage", "learn", "--librarian"], check=False)
        state = {**state, "last_librarian_learn_count": lib_total}
    _write_learn_state(state, home=home)


def _digest_impl(cfg: dict) -> None:
    """Read today's observations and run MonitorDigest to produce daily .md."""
    from google.adk.runners import InMemoryRunner
    import google.genai.types as genai_types

    monitor_dir = Path(runtime.config.home) / "monitor"
    monitor_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    obs_path = monitor_dir / f"observations-{today}.jsonl"

    if not obs_path.exists():
        digest_input = "No observations recorded today."
    else:
        lines = obs_path.read_text().splitlines()
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        if not records:
            digest_input = "No observations recorded today."
        else:
            parts, total = [], 0
            for i, r in enumerate(reversed(records)):
                chunk = f"Observation run {len(records)-i} ({r['ts']}): {r['findings']}\n---\n"
                if total + len(chunk) > 50_000:
                    break
                parts.append(chunk)
                total += len(chunk)
            digest_input = "".join(reversed(parts)) or "No observations recorded today."

    agent = build_monitor_digest(cfg)
    runner = InMemoryRunner(node=agent, app_name="kage-monitor-dig")
    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=digest_input)],
    )
    session = asyncio.run(
        runner.session_service.create_session(app_name="kage-monitor-dig", user_id="kage")
    )
    list(runner.run(user_id="kage", session_id=session.id, new_message=content))
    session = asyncio.run(runner.session_service.get_session(
        app_name="kage-monitor-dig", user_id="kage", session_id=session.id
    ))
    digest = (session.state.get("monitor_digest") or "") if session else ""

    (monitor_dir / f"{today}.md").write_text(digest)
    _write_state_json({
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "digest_preview": digest[:200] if digest else "",
    })

    _maybe_trigger_learn(Path(runtime.config.home))
