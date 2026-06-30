from __future__ import annotations
import datetime
import json
import os
import sqlite3
from pathlib import Path

KAGE_HOME = Path(os.environ.get("KAGE_HOME") or Path.home() / ".kage")

_CLASS_HINTS: dict[str, list[str]] = {
    "code":        ["function", "class", "import", "test", "def", "sql", "insert"],
    "research":    ["search", "fetch", "scrape", "source", "url"],
    "reasoning":   ["analyze", "compare", "explain", "design"],
    "multimodal":  ["image", "screenshot", "vision"],
    # "chat" is the fallback — see run_learning_pass
}

ALL_CLASSES = ["code", "research", "multimodal", "reasoning", "chat"]


def load_learned_prompt(task_class: str, home: Path = KAGE_HOME) -> str:
    path = home / "learned_prompts.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return ""
    entry = data.get(task_class)
    if not entry or "active" not in entry:
        return ""
    active_version = entry["active"]
    return entry["versions"].get(active_version, {}).get("prompt", "")


def _build_meta_prompt(corrections: list[str], task_class: str) -> str:
    return f"""Here are all corrections logged for {task_class} tasks in kage's dev workflow.
Each entry describes a mistake the local model (Qwen3 14B) made and the pattern
behind it. Read all entries carefully.

Write a concise set of rules (max 8 bullet points) that, if prepended to the
local model's system prompt, would prevent these mistakes from recurring.
Be specific — name the exact API, method, column, or pattern involved.
No vague advice. No general "be careful" rules.
Output ONLY the rules as a bulleted list. No preamble, no explanation.

--- CORRECTIONS ---
{chr(10).join(f"[{i+1}] {c}" for i, c in enumerate(corrections))}"""


def _count_total_corrections(home: Path = KAGE_HOME) -> int:
    db_path = home / "indexes" / "kage.db"
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        return conn.execute(
            "SELECT COUNT(*) FROM memories WHERE project = ?",
            ("kage-corrections",),
        ).fetchone()[0]
    except Exception:
        return 0
    finally:
        if conn:
            conn.close()


def _read_learn_state(home: Path = KAGE_HOME) -> dict:
    path = home / "learn_state.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _write_learn_state(state: dict, home: Path = KAGE_HOME) -> None:
    path = home / "learn_state.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.replace(tmp, path)


def run_learning_pass(
    task_class: str,
    call_cloud_fn,
    cfg: dict,
    home: Path = KAGE_HOME,
) -> tuple[str, str, list[str]]:
    db_path = home / "indexes" / "kage.db"
    rows = []
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT m.id, m.content_path "
            "FROM memory_fts "
            "JOIN memories m ON m.id = memory_fts.id "
            "WHERE memory_fts MATCH ? AND m.project = ? "
            "ORDER BY rank LIMIT ?",
            ('"correction" "log"', "kage-corrections", 200),
        ).fetchall()
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    if not rows:
        return ("", "", [])

    raw_corrections: list[tuple[str, str]] = []
    for note_id, rel_path in rows:
        try:
            text = (home / rel_path).read_text()
            raw_corrections.append((note_id, text))
        except OSError:
            continue

    if task_class == "chat":
        other_hints = {h for cls, hints in _CLASS_HINTS.items() for h in hints}
        matched = [(nid, txt) for nid, txt in raw_corrections
                   if not any(h in txt.lower() for h in other_hints)]
        if not matched:
            matched = raw_corrections
    else:
        hints = _CLASS_HINTS.get(task_class, [])
        matched = [(nid, txt) for nid, txt in raw_corrections
                   if any(h in txt.lower() for h in hints)]

    if not matched:
        return ("", "", [])

    source_note_ids = [nid for nid, _ in matched]
    correction_texts = [txt for _, txt in matched]
    provider_name = cfg.get("provider") or next(iter(cfg.get("providers", {"claude-sonnet": {}})))
    meta_prompt = _build_meta_prompt(correction_texts, task_class)
    full_trace = call_cloud_fn(provider_name, "", meta_prompt, cfg)

    lines = full_trace.splitlines()
    bullet_start = next((i for i, line in enumerate(lines) if line.strip().startswith("- ")), None)
    if bullet_start is None:
        prompt_rules = full_trace.strip()
    else:
        prompt_rules = "\n".join(lines[bullet_start:]).strip()

    return (prompt_rules, full_trace, source_note_ids)


def save_learned_prompt(
    task_class: str,
    prompt: str,
    trace: str,
    source_note_ids: list[str],
    correction_count: int,
    home: Path = KAGE_HOME,
) -> None:
    path = home / "learned_prompts.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}

    entry = data.get(task_class, {"active": None, "versions": {}})
    next_n = len(entry["versions"]) + 1
    version_key = f"v{next_n}"
    entry["versions"][version_key] = {
        "date": datetime.date.today().isoformat(),
        "correction_count": correction_count,
        "source_note_ids": source_note_ids,
        "prompt": prompt,
        "trace": trace,
    }
    entry["active"] = version_key
    data[task_class] = entry

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)
