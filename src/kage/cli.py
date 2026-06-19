"""kage CLI — v0.1 thin slice.

One headless engine, surfaced as a CLI (blueprint #91). v0.1 commands are
one-shot. Everything kage stores is local: plain markdown is the source of
truth (#70), SQLite is a derived index (#71).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import secrets
import shlex
import shutil
import sqlite3
import subprocess
import asyncio
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import asynccontextmanager
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import typer
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

from kage.embed import OllamaUnavailable  # re-export; tests use cli.OllamaUnavailable
from kage import runtime
from kage.context import _read_active, _write_active, _resolve_context  # noqa: F401
from kage import notes as _notes
from kage import privacy as _privacy


# CloudError + DEFAULT_PROVIDERS now live in kage.cloud (Cycle 12 Slice 1); re-export so
# cli.CloudError / cli.DEFAULT_PROVIDERS stay the public/test surface.
from kage.cloud import CloudError, DEFAULT_PROVIDERS  # noqa: E402,F401


app = typer.Typer(
    help="kage — your local context broker. Your notes, surfaced into your AI, on your machine.",
    add_completion=False,
    no_args_is_help=True,
)

_mcp_app = typer.Typer(help="MCP server commands.")
app.add_typer(_mcp_app, name="mcp")

_arm_app = typer.Typer(help="Arm (MCP client) commands.")
app.add_typer(_arm_app, name="arm")

# ── Layout ────────────────────────────────────────────────────────────────
KAGE_HOME = Path(os.environ.get("KAGE_HOME") or Path.home() / ".kage")  # override for relocation/tests
MEMORY_DIR = KAGE_HOME / "memory"          # 5A: markdown source of truth (#70)
INDEX_DIR = KAGE_HOME / "indexes"
DB_PATH = INDEX_DIR / "kage.db"            # 5B: derived SQLite index (#71)
CONFIG_PATH = KAGE_HOME / "config.json"
CHROMA_DIR  = KAGE_HOME / "chroma"

# ── Arm routing ───────────────────────────────────────────────────────────
# Arm names in config.json must match these keys exactly to trigger keyword routing.
ARM_KEYWORDS: dict[str, list[str]] = {
    "calendar": ["calendar", "schedule", "meeting", "event",
                 "appointment", "today", "tomorrow", "this week"],
    "gmail":    ["email", "mail", "inbox", "thread", "draft",
                 "unread", "reply", "newsletter", "attachment"],
}
_arm_tool_cache: dict[str, list] = {}  # warm across calls in one process


def _disp(p: Path) -> str:
    """Show a path relative to home, e.g. ~/.kage/memory."""
    try:
        return "~/" + str(p.relative_to(Path.home()))
    except ValueError:
        return str(p)



@app.callback()
def main() -> None:
    """kage — your local context broker. Run a subcommand (e.g. `kage init`)."""


@app.command()
def init() -> None:
    """Set up ~/.kage/ (config, memory store, index). Safe to re-run."""
    typer.echo("kage init — setting up your local context store\n")

    created: list[Path] = []
    existed: list[Path] = []

    for d in (KAGE_HOME, MEMORY_DIR, INDEX_DIR, CHROMA_DIR):
        if d.exists():
            existed.append(d)
        else:
            d.mkdir(parents=True, exist_ok=True)
            created.append(d)

    if CONFIG_PATH.exists():
        existed.append(CONFIG_PATH)
    else:
        CONFIG_PATH.write_text(
            json.dumps(
                {
                    "version": "0.1.0",
                    "created_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "memory_dir": "memory",
                    "db_path": "indexes/kage.db",
                    "embeddings": True,
                    "embed_model": "nomic-embed-text",
                },
                indent=2,
            )
            + "\n"
        )
        created.append(CONFIG_PATH)

    db_is_new = not DB_PATH.exists()
    runtime.store.init_schema()
    (created if db_is_new else existed).append(DB_PATH)

    for p in created:
        typer.echo(f"  ✓ created   {_disp(p)}   (local)")
    for p in existed:
        typer.echo(f"  • exists    {_disp(p)}")

    typer.echo(
        f"\n✓ kage is ready. Everything lives in {_disp(KAGE_HOME)} — "
        "100% on your Mac, nothing has left it."
    )
    typer.echo('  next:  kage remember "..."   ·   kage recall "..."   ·   kage status')


def _require_init() -> None:
    """Bail with a friendly message if kage hasn't been set up."""
    if not DB_PATH.exists():
        typer.echo("kage isn't set up yet. Run:  kage init", err=True)
        raise typer.Exit(code=1)


def _connect() -> sqlite3.Connection:
    return runtime.store.connect()


def _session_create(identity: str, project: str | None, destination: str) -> str:
    session_id = str(uuid.uuid4())
    created_at = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    conn = None
    try:
        conn = _connect()
        conn.execute(
            "INSERT INTO sessions(session_id, created_at, identity, project, destination) VALUES(?,?,?,?,?)",
            (session_id, created_at, identity, project, destination),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()
    return session_id


def _session_load(session_id: str) -> dict | None:
    conn = None
    try:
        conn = _connect()
        row = conn.execute(
            "SELECT session_id, created_at, identity, project, destination, deleted FROM sessions WHERE session_id=? AND deleted=0",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        return dict(zip(["session_id", "created_at", "identity", "project", "destination", "deleted"], row))
    finally:
        if conn:
            conn.close()


def _session_append(
    session_id: str,
    role: str,
    content: str,
    note_ids: list[str],
    destination: str,
    model: str | None,
    reason: str | None,
    tokens: int | None,
) -> int:
    conn = None
    try:
        conn = _connect()
        next_idx = conn.execute(
            "SELECT COALESCE(MAX(idx), -1) FROM session_turns WHERE session_id=?",
            (session_id,),
        ).fetchone()[0] + 1
        ts = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO session_turns(session_id, idx, parent_idx, role, content, note_ids, destination, model, reason, tokens, ts) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, next_idx, None, role, content, json.dumps(note_ids), destination, model, reason, tokens, ts),
        )
        conn.commit()
        return next_idx
    finally:
        if conn:
            conn.close()


def _session_turns(session_id: str, token_budget: int = 4000) -> list[dict]:
    conn = None
    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT idx, role, content, note_ids, destination, model, reason, tokens, ts FROM session_turns WHERE session_id=? AND deleted=0 ORDER BY idx ASC",
            (session_id,),
        ).fetchall()
        kept = []
        est_total = 0
        for row in reversed(rows):
            est = len(row[2]) // 4
            if est_total + est > token_budget:
                break
            est_total += est
            kept.append(row)
        kept.reverse()
        return [
            {
                "idx": r[0], "role": r[1], "content": r[2],
                "note_ids": json.loads(r[3]), "destination": r[4],
                "model": r[5], "reason": r[6], "tokens": r[7], "ts": r[8],
            }
            for r in kept
        ]
    finally:
        if conn:
            conn.close()


_LEADING_PRONOUNS = {
    "it", "its", "they", "them", "their", "this", "that", "these", "those",
    "he", "she", "we", "what", "which", "how", "why", "when", "where", "who",
}


def _condense_query(history: list[dict], question: str) -> str:
    words = question.split()
    if len(words) > 10:
        return question
    first_word = re.sub(r"[^a-z]", "", words[0].lower())
    if first_word not in _LEADING_PRONOUNS:
        return question
    has_proper_noun = any(
        re.match(r"[A-Z][a-z]+", word) and word != words[0] and len(word) > 1
        for word in words
    )
    if has_proper_noun:
        return question
    last_assistant = next((t for t in reversed(history) if t["role"] == "assistant"), None)
    if last_assistant is None:
        return question
    context_snippet = last_assistant["content"][:120].rstrip()
    return f"{context_snippet} — {question}"


def _new_id() -> str:
    """Sortable, unique id: 20260604T223719-a1b2c3."""
    return f"{_dt.datetime.now():%Y%m%dT%H%M%S}-{secrets.token_hex(3)}"


def _read_body(rel_path: str) -> str:
    return _notes._read_body(rel_path)


# Chunking lives in kage.chunk (audit WI-4). Re-exported here so cli.* stays the
# test/patch surface and in-module callers (_save, reindex) remain patchable.
from kage.chunk import (  # noqa: E402,F401  (re-export shim — used via cli.* in tests)
    _CHUNK_TARGET, _CHUNK_MIN, _CHUNK_OVERLAP,
    _split_on_headers, _hard_windows, _window_by_pieces, _chunk_note,
)

_RERANK_POOL   = 25
_reranker_cache: list = [False, None]   # [loaded_flag, instance_or_None]


def _read_section(content_path: str, char_start: int, char_end: int) -> str:
    return _notes._read_section(content_path, char_start, char_end)


def _save(
    text: str,
    project: str | None,
    source: str | None = None,
    embed: bool = True,
    local_only: bool = False,
    identities: list[str] | None = None,
    state: str | None = None,
) -> str:
    """Write a memory (markdown source-of-truth #70) + index it (#71). Returns its id."""
    cfg = _config()
    if not local_only and project and project in cfg.get("local_only_projects", []):
        local_only = True
    if state is None:
        state = "scoped" if project else "baseline"

    mem_id = _new_id()
    created = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    rel_path = f"memory/{mem_id}.md"
    front = f"---\nid: {mem_id}\nproject: {project or ''}\ncreated_at: {created}\n"
    if source:
        front += f"source: {source}\n"
    if local_only:
        front += "local_only: true\n"
    front += "identities:\n"
    for ident in (identities or ["personal"]):
        front += f"  - {ident}\n"
    front += f"state: {state}\n"
    (KAGE_HOME / rel_path).write_text(front + "---\n\n" + text.rstrip() + "\n")

    body = text.strip()
    chunks = _chunk_note(body)
    chunk_ids = [f"{mem_id}_c{i}" for i in range(len(chunks))]

    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO memories (id, content_path, project, created_at, local_only, state)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (mem_id, rel_path, project, created, int(local_only), state),
        )
        for ident in (identities or ["personal"]):
            conn.execute(
                "INSERT OR IGNORE INTO memory_identities(mem_id, identity) VALUES (?, ?)",
                (mem_id, ident),
            )
        if project:
            conn.execute(
                "INSERT OR IGNORE INTO memory_projects(mem_id, project) VALUES (?, ?)",
                (mem_id, project),
            )
        conn.execute("INSERT INTO memory_fts (id, body) VALUES (?, ?)", (mem_id, text))
        for i, chunk in enumerate(chunks):
            conn.execute(
                "INSERT INTO chunks (id, note_id, section_title, char_start, char_end, needs_embed) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (chunk_ids[i], mem_id, chunk["title"], chunk["char_start"], chunk["char_end"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if embed:
        for i, chunk in enumerate(chunks):
            chunk_id = chunk_ids[i]
            chunk_text = body[chunk["char_start"]:chunk["char_end"]]
            try:
                vec = _embed(chunk_text)
                coll = _get_chroma()
                coll.add(
                    ids=[chunk_id],
                    embeddings=[vec],
                    metadatas=[{
                        "note_id": mem_id,
                        "project": project or "",
                        "created_at": created,
                        "content_path": rel_path,
                        "section_title": chunk["title"],
                        "char_start": chunk["char_start"],
                        "char_end": chunk["char_end"],
                    }],
                )
                conn2 = _connect()
                try:
                    conn2.execute("UPDATE chunks SET needs_embed=0 WHERE id=?", (chunk_id,))
                    conn2.commit()
                finally:
                    conn2.close()
            except OllamaUnavailable:
                pass  # needs_embed=1 stays — kage reindex will pick it up

    return mem_id


def _allowed_note_ids(identity: str, project: str | None) -> set[str]:
    return runtime.store.allowed_note_ids(identity, project)


def _search_fts(query: str, project: str | None, limit: int, any_terms: bool = False, identity: str = "personal"):
    """Full-text search within the partition wall (#99). Rows: (id, project, created_at, content_path, snippet).

    any_terms=True ORs the terms (lenient — for natural-language questions in `ask`);
    default ANDs them (precise keyword search — for `recall`).
    """
    terms = [t for t in query.split() if t]
    if not terms:
        return []
    joiner = " OR " if any_terms else " "
    match = joiner.join('"' + t.replace('"', '""') + '"' for t in terms)
    sql = (
        "SELECT m.id, m.project, m.created_at, m.content_path, "
        "snippet(memory_fts, 1, '[', ']', ' … ', 12) AS snip "
        "FROM memory_fts JOIN memories m ON m.id = memory_fts.id "
        "WHERE memory_fts MATCH ? "
    )
    allowed = _allowed_note_ids(identity, project)
    if not allowed:
        return []
    placeholders = ",".join("?" * len(allowed))
    sql += f"AND m.id IN ({placeholders}) "
    params: list = [match, *allowed]
    sql += "ORDER BY rank LIMIT ?"
    params.append(limit)
    conn = _connect()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _search(query: str, project: str | None, limit: int, any_terms: bool = False, identity: str = "personal"):
    """Hybrid FTS5 + vector search; falls back to FTS5 when embeddings are off or Ollama is down."""
    if not query or not query.strip():
        return []
    cfg = _config()
    use_rerank = cfg.get("rerank", False)
    pool = max(limit * 2, _RERANK_POOL) if use_rerank else limit * 2
    if not cfg.get("embeddings", True):
        rows = [(*row, None, None, None) for row in _search_fts(query, project, limit, any_terms, identity)]
        return _rerank(rows, query, limit) if use_rerank else rows
    def run_fts(): return _search_fts(query, project, pool, any_terms, identity)
    def run_vec(): return _search_vec(_embed(query), project, pool, identity)
    with ThreadPoolExecutor(max_workers=2) as executor:
        fts_future = executor.submit(run_fts)
        vec_future = executor.submit(run_vec)
        fts_rows = fts_future.result()
        try:
            vec_rows = vec_future.result()
        except OllamaUnavailable:
            rows = [(*row, None, None, None) for row in fts_rows[:limit]]
            return _rerank(rows, query, limit) if use_rerank else rows
    candidate_limit = _RERANK_POOL if use_rerank else limit
    fused = _rrf_fuse(fts_rows, vec_rows)[:candidate_limit]
    fts_ids = {row[0] for row in fts_rows}
    vec_by_id = {row[0]: row for row in vec_rows}
    result = []
    for row in fused:
        if row[0] not in fts_ids:
            try:
                body = _read_body(row[3]).replace("\n", " ")
                excerpt = (body[:70] + "…") if len(body) > 70 else body
            except OSError:
                excerpt = ""
            row = (row[0], row[1], row[2], row[3], excerpt, row[5], row[6], row[7])
        else:
            vec_row = vec_by_id.get(row[0])
            section = (vec_row[5], vec_row[6], vec_row[7]) if vec_row else (None, None, None)
            row = (*row, *section)
        result.append(row)
    return _rerank(result, query, limit) if use_rerank else result


def _config() -> dict:
    return runtime.config.data


# _post_json lives in kage.http (Cycle 12 Slice 1). Call-time forwarder so in-cli
# callers and the ~39 cli._post_json test patches keep working during transition.
from kage import http as _http  # noqa: E402


def _post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 120) -> dict:
    return _http._post_json(url, payload, headers, timeout)


# Cloud dispatch lives in kage.cloud.CloudClient (Cycle 12 Slice 1). These call-time
# forwarders route to runtime.cloud — the swappable egress sink (RecordingCloud in tests) —
# while existing cli._call_cloud / cli._call_cloud_chat patches keep working unchanged.


def _call_cloud(provider_name: str, system: str, user_msg: str, cfg: dict) -> str:
    """Single-message dispatch — thin wrapper over _call_cloud_chat."""
    return _call_cloud_chat(provider_name, system, [{"role": "user", "content": user_msg}], cfg)


def _call_cloud_chat(provider_name: str, system: str, messages: list[dict], cfg: dict) -> str:
    """Multi-turn chat dispatch → the cloud egress sink (runtime.cloud.complete)."""
    return runtime.cloud.complete(provider_name, system, messages, cfg)


def _answer(
    question: str,
    history: list[dict],
    context: str,
    destination: str,
    cfg: dict,
) -> Iterator[str]:
    system_prompt = (
        "You are kage, a local context broker. Answer the user question using the provided context. "
        "Be concise and accurate. If the context does not contain relevant information, say so."
    )
    user_content = f"Context:\n{context}\n\nQuestion: {question}" if context else question
    messages = [
        {"role": t["role"], "content": t["content"]} for t in history
    ] + [{"role": "user", "content": user_content}]

    if destination == "ollama":
        ollama_url = cfg.get("ollama_url", "http://localhost:11434") + "/api/chat"
        model = cfg.get("ollama_model", "qwen3:14b")
        think = cfg.get("ollama_think", False)
        payload: dict = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream": False,
        }
        if think is not None:
            payload["think"] = think
        try:
            out = _post_json(ollama_url, payload)
            yield out["message"]["content"].strip()
        except (urllib.error.URLError, KeyError, TimeoutError) as exc:
            raise OllamaUnavailable(str(exc)) from exc
    else:
        yield _call_cloud_chat(destination, system_prompt, messages, cfg)


# ── Privacy gate (Layer 3e) ────────────────────────────────────────────────

# PII detection table + scanner live in kage.pii (audit WI-4). Re-exported so
# cli._PII_PATTERNS / cli._pii_scan stay the test surface (unit tests call them directly).
from kage.pii import _PII_PATTERNS, _pii_scan  # noqa: F401


def _write_audit(record: dict) -> None:
    _privacy._write_audit(record)


_session_approvals: dict[str, bool] = {}


def _disclosure_gate(rows: list, cfg: dict, identity: str = "personal", project: str | None = None) -> tuple[list, list[dict]]:
    return _privacy._disclosure_gate(rows, cfg, identity, project)


def _gate_conversation(
    turns: list[dict],
    cfg: dict,
    identity: str,
    project: str | None,
) -> tuple[list[dict], list[dict]]:
    return _privacy._gate_conversation(turns, cfg, identity, project)


def _session_switch(
    session_id: str,
    new_destination: str,
    cfg: dict,
    identity: str,
    project: str | None,
) -> tuple[str, list[dict], list[dict]]:
    """Switch a session to a new destination, enforcing the no-leak-on-switch invariant.

    Re-gates ALL turns against the new destination. Returns (new_destination, safe_turns, withheld)
    so the caller knows exactly which history is safe to send to the new provider.
    """
    sess = _session_load(session_id)
    if sess is None:
        raise ValueError(f"Session {session_id!r} not found")
    conn = _connect()
    try:
        conn.execute("UPDATE sessions SET destination=? WHERE session_id=?", (new_destination, session_id))
        conn.commit()
    finally:
        conn.close()
    turns = _session_turns(session_id, token_budget=10_000_000)
    safe_turns, withheld = _gate_conversation(turns, cfg, identity, project)
    return (new_destination, safe_turns, withheld)


def _rrf_fuse(fts_rows: list, vec_rows: list, k: int = 60) -> list:
    """Merge FTS5 and vector candidates via Reciprocal Rank Fusion; caller slices to limit."""
    fts_n, vec_n = len(fts_rows), len(vec_rows)
    fts_rank = {row[0]: i for i, row in enumerate(fts_rows)}
    vec_rank = {row[0]: i for i, row in enumerate(vec_rows)}
    rows_by_id = {row[0]: row for row in (*vec_rows, *fts_rows)}  # fts last → fts row wins for shared IDs

    scores: dict[str, float] = {}
    for mem_id in rows_by_id:
        r_fts = fts_rank.get(mem_id, fts_n)   # missing → large rank penalty
        r_vec = vec_rank.get(mem_id, vec_n)
        scores[mem_id] = 1.0 / (k + r_fts) + 1.0 / (k + r_vec)

    return [rows_by_id[mid] for mid in sorted(scores, key=scores.__getitem__, reverse=True)]


def _embed(text: str) -> list[float]:
    """Embed text via Ollama /api/embed; raises OllamaUnavailable on failure."""
    return runtime.embed.embed(text, _config())


def _get_chroma():
    cfg = _config()
    return runtime.vector.collection(CHROMA_DIR, cfg.get("embed_model", "nomic-embed-text"))


def _get_reranker():
    """Lazy-load bge-reranker-v2-m3; return None if sentence-transformers not installed."""
    if _reranker_cache[0]:
        return _reranker_cache[1]
    _reranker_cache[0] = True
    try:
        from sentence_transformers import CrossEncoder
        _reranker_cache[1] = CrossEncoder("BAAI/bge-reranker-v2-m3")
    except Exception:
        _reranker_cache[1] = None
    return _reranker_cache[1]


def _rerank(rows: list, query: str, top_n: int) -> list:
    reranker = _get_reranker()
    if reranker is None or not rows:
        return rows[:top_n]
    texts = []
    for row in rows:
        char_start, char_end = row[6], row[7]
        if char_start is not None and char_end is not None:
            try:
                body = _read_body(row[3])
                text = body[char_start:char_end][:512]
            except OSError:
                text = row[4] or ""
        else:
            text = row[4] or ""
        texts.append(text)
    pairs = [[query, t] for t in texts]
    scores = reranker.predict(pairs).tolist()
    ranked = sorted(zip(scores, rows), key=lambda x: x[0], reverse=True)
    return [r for _, r in ranked[:top_n]]


def _search_vec(query_vec: list[float], project: str | None, limit: int, identity: str = "personal") -> list:
    allowed = _allowed_note_ids(identity, project)
    if not allowed:
        return []
    collection = _get_chroma()
    where = {"note_id": {"$in": list(allowed)}}
    count = len(collection.get(where=where, include=[])["ids"])
    if count == 0:
        return []
    n_results = min(limit, count)
    results = collection.query(
        query_embeddings=[query_vec],
        n_results=n_results,
        where=where,
        include=["metadatas", "distances"],
    )
    ids = results["ids"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    # Deduplicate by note_id; keep best chunk (lowest distance = highest similarity) per note
    note_best: dict[str, tuple] = {}
    for mid, meta, dist in zip(ids, metadatas, distances):
        note_id = meta.get("note_id")
        if note_id not in note_best or dist < note_best[note_id][0]:
            note_best[note_id] = (dist, meta)

    return [
        (
            note_id,
            meta.get("project"),
            meta.get("created_at"),
            meta.get("content_path"),
            dist,
            meta.get("section_title"),
            meta.get("char_start"),
            meta.get("char_end"),
        )
        for note_id, (dist, meta) in note_best.items()
    ]


def _ollama_status(cfg: dict, model: str) -> tuple[bool, str]:
    """Is Ollama reachable and the model pulled? (advisory — only `ask` needs it)."""
    return runtime.embed.status(cfg, model)


@app.command(name="use")
def use_(
    context: str | None = typer.Argument(None, help="Identity or identity/project. Use --clear to reset."),
    clear: bool = typer.Option(False, "--clear", help="Reset active context to fallback (personal / no project)."),
) -> None:
    """Set the active identity and project so you don't have to pass --identity/--project on every call."""
    _require_init()
    if clear:
        _write_active({})
        typer.echo("  ✓ active context cleared  (fallback: personal / no project)")
        return
    if not context:
        typer.echo("Provide an identity (e.g. kage use neu  or  kage use neu/project).", err=True)
        raise typer.Exit(code=1)
    parts = context.split("/", 1)
    if len(parts) == 2 and "/" in parts[1]:
        typer.echo("Project name cannot contain '/'. Use: kage use identity/project", err=True)
        raise typer.Exit(code=1)
    identity = parts[0].strip()
    project = parts[1].strip() if len(parts) == 2 else None
    if not identity:
        typer.echo("Identity cannot be empty.", err=True)
        raise typer.Exit(code=1)
    active = _read_active()
    active["identity"] = identity
    if project is not None:
        active["project"] = project
    else:
        active.pop("project", None)
    _write_active(active)
    proj_display = f"/{project}" if project else ""
    typer.echo(f"  ✓ active context → {identity}{proj_display}")


@app.command()
def where() -> None:
    """Show the resolved active context and where it came from."""
    _require_init()
    identity, project, source = _resolve_context(None, None)
    proj_display = f"/{project}" if project else "  (no project)"
    typer.echo(f"\n  identity : {identity}")
    typer.echo(f"  project  : {project or '(none)'}")
    typer.echo(f"  source   : {source}")
    typer.echo(f"\n  resolved → {identity}{proj_display}  [{source}]\n")


@app.command()
def remember(
    text: str = typer.Argument(..., help="The note to remember."),
    project: str = typer.Option(None, "--project", "-p", help="Tag this memory to a project."),
    local: bool = typer.Option(False, "--local", help="Mark note local-only — never sent to cloud providers."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirm prompt (for scripts/tests)."),
    identity: str = typer.Option(None, "--identity", "-i", help="Identity this note belongs to (default: personal)."),
    state: str = typer.Option(None, "--state", help="State: scoped, baseline, or pending. Inferred if omitted."),
) -> None:
    """Save a note to memory (markdown + index). Confirms before writing (the wall, #16)."""
    _require_init()
    identity, project, source = _resolve_context(identity, project)

    # The wall (#16): show it and confirm BEFORE anything is written.
    typer.echo(f'\n  "{text}"')
    typer.echo(f"  project: {project or '(none)'}")
    typer.echo(f"  identity: {identity}")
    if local:
        typer.echo("  local-only: yes (will not be sent to cloud)")
    if not yes and not typer.confirm("Save this to memory?", default=True):
        typer.echo("Discarded — nothing saved.")
        raise typer.Exit()

    mem_id = _save(text, project, local_only=local, identities=[identity], state=state)
    suffix = "  [local-only]" if local else ""
    typer.echo(f"  ✓ saved   {_disp(KAGE_HOME / f'memory/{mem_id}.md')}   [{mem_id}]   (local){suffix}")


@app.command(name="import")
def import_(
    folder: Path = typer.Argument(..., help="Folder of .md/.txt files to bulk-add (recursive)."),
    project: str = typer.Option(None, "--project", "-p", help="Tag all imported notes (default: the folder name)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be imported; write nothing."),
    identity: str = typer.Option(None, "--identity", "-i", help="Identity for all imported notes (default: personal)."),
) -> None:
    """Bulk-add the .md/.txt files in a folder (curated by which folder you point at)."""
    _require_init()
    identity, project, source = _resolve_context(identity, project)

    folder = folder.expanduser()
    if not folder.is_dir():
        typer.echo(f"Not a folder: {folder}", err=True)
        raise typer.Exit(code=1)

    files = sorted(
        p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt"}
    )
    proj = project or folder.name

    if dry_run:
        typer.echo(f"\nDry run — would import {len(files)} file(s) into project '{proj}':")
        for p in files:
            typer.echo(f"  • {p.relative_to(folder)}")
        typer.echo("\n(no changes made)")
        raise typer.Exit()

    if not files:
        typer.echo(f"No .md/.txt files found in {folder}")
        raise typer.Exit()

    imported = 0
    for p in files:
        body = p.read_text(errors="replace").strip()
        if not body:
            continue
        _save(body, proj, source=str(p), embed=False, identities=[identity])
        imported += 1

    typer.echo(f"  ✓ imported {imported} note(s) into project '{proj}'   (local)")
    typer.echo("  → run: kage reindex to enable semantic search")


@app.command()
def reindex(
    force: bool = typer.Option(False, "--force", help="Rechunk and re-embed all notes from scratch."),
) -> None:
    """Embed pending chunks (or rechunk + re-embed everything with --force)."""
    _require_init()

    if force:
        import chromadb as _chromadb
        client = _chromadb.PersistentClient(path=str(CHROMA_DIR))
        try:
            client.delete_collection("chunks")
        except Exception:
            pass

        conn = _connect()
        try:
            conn.execute("DELETE FROM chunks")
            conn.commit()
            note_rows = conn.execute(
                "SELECT id, content_path, project, created_at FROM memories"
            ).fetchall()
        finally:
            conn.close()

        total = len(note_rows)
        if total == 0:
            typer.echo("  ✓ nothing to reindex")
            return

        try:
            coll = _get_chroma()
        except OllamaUnavailable:
            typer.echo("  ✗ start Ollama first: ollama serve", err=True)
            raise typer.Exit(code=1)

        for n, (mem_id, rel_path, project, created_at) in enumerate(note_rows, 1):
            typer.echo(f"  [{n}/{total}] {mem_id}")
            try:
                body = _read_body(rel_path)
            except OSError:
                typer.echo(f"  ⚠ missing file, skipping: {rel_path}", err=True)
                continue

            chunks = _chunk_note(body)
            chunk_ids = [f"{mem_id}_c{i}" for i in range(len(chunks))]

            conn = _connect()
            try:
                for i, chunk in enumerate(chunks):
                    conn.execute(
                        "INSERT INTO chunks (id, note_id, section_title, char_start, char_end, needs_embed) "
                        "VALUES (?, ?, ?, ?, ?, 1)",
                        (chunk_ids[i], mem_id, chunk["title"], chunk["char_start"], chunk["char_end"]),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

            for i, chunk in enumerate(chunks):
                chunk_text = body[chunk["char_start"]:chunk["char_end"]]
                try:
                    vec = _embed(chunk_text)
                except OllamaUnavailable:
                    typer.echo("  ✗ start Ollama first: ollama serve", err=True)
                    raise typer.Exit(code=1)
                coll.add(
                    ids=[chunk_ids[i]],
                    embeddings=[vec],
                    metadatas=[{
                        "note_id": mem_id,
                        "project": project or "",
                        "created_at": created_at or "",
                        "content_path": rel_path,
                        "section_title": chunk["title"],
                        "char_start": chunk["char_start"],
                        "char_end": chunk["char_end"],
                    }],
                )
                conn2 = _connect()
                try:
                    conn2.execute("UPDATE chunks SET needs_embed=0 WHERE id=?", (chunk_ids[i],))
                    conn2.commit()
                finally:
                    conn2.close()

        typer.echo(f"  ✓ reindexed {total} note(s)")

    else:
        conn = _connect()
        try:
            pending = conn.execute(
                "SELECT c.id, c.note_id, c.char_start, c.char_end, "
                "m.content_path, m.project, m.created_at, c.section_title "
                "FROM chunks c JOIN memories m ON m.id = c.note_id "
                "WHERE c.needs_embed = 1"
            ).fetchall()
        finally:
            conn.close()

        total = len(pending)
        if total == 0:
            typer.echo("  ✓ nothing to reindex")
            return

        try:
            coll = _get_chroma()
        except OllamaUnavailable:
            typer.echo("  ✗ start Ollama first: ollama serve", err=True)
            raise typer.Exit(code=1)

        for n, (chunk_id, note_id, char_start, char_end, rel_path, project, created_at, section_title) in enumerate(pending, 1):
            typer.echo(f"  [{n}/{total}] {chunk_id}")
            chunk_text = _read_section(rel_path, char_start, char_end)
            if not chunk_text:
                typer.echo(f"  ⚠ empty section, skipping: {rel_path}", err=True)
                continue
            try:
                vec = _embed(chunk_text)
            except OllamaUnavailable:
                typer.echo("  ✗ start Ollama first: ollama serve", err=True)
                raise typer.Exit(code=1)
            coll.add(
                ids=[chunk_id],
                embeddings=[vec],
                metadatas=[{
                    "note_id": note_id,
                    "project": project or "",
                    "created_at": created_at or "",
                    "content_path": rel_path,
                    "section_title": section_title or "",
                    "char_start": char_start,
                    "char_end": char_end,
                }],
            )
            conn2 = _connect()
            try:
                conn2.execute("UPDATE chunks SET needs_embed=0 WHERE id=?", (chunk_id,))
                conn2.commit()
            finally:
                conn2.close()

        typer.echo(f"  ✓ reindexed {total} chunk(s)")


@app.command(name="list")
def list_(
    project: str = typer.Option(None, "--project", "-p", help="Limit to a project."),
    limit: int = typer.Option(20, "--limit", "-n", help="Max to show."),
    identity: str = typer.Option(None, "--identity", "-i", help="Identity scope (default: personal)."),
) -> None:
    """List what kage has saved (most recent first) — so you can see before you search."""
    _require_init()
    identity, project, source = _resolve_context(identity, project)

    allowed = _allowed_note_ids(identity, project)
    if not allowed:
        typer.echo(f'Nothing saved yet. (identity: {identity})   Add one:  kage remember "..."')
        raise typer.Exit()

    placeholders = ",".join("?" * len(allowed))
    sql = f"SELECT id, project, created_at, content_path FROM memories WHERE id IN ({placeholders}) ORDER BY created_at DESC LIMIT ?"
    params: list = [*allowed, limit]

    conn = _connect()
    try:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(f"SELECT count(*) FROM memories WHERE id IN ({placeholders})", list(allowed)).fetchone()[0]
    finally:
        conn.close()

    if not rows:
        where = f"  (project: {project})" if project else ""
        typer.echo(f'Nothing saved yet.{where}   Add one:  kage remember "..."')
        raise typer.Exit()

    shown = f" (showing {len(rows)} of {total})" if len(rows) < total else ""
    typer.echo(f"\n{total} note(s){shown}:\n")
    for mem_id, proj, created, path in rows:
        preview = _read_body(path).replace("\n", " ")
        if len(preview) > 70:
            preview = preview[:70] + "…"
        typer.echo(f"  [{proj or 'no-project'}]  {preview}")
        typer.echo(f"     {created[:16].replace('T', ' ')}   {mem_id}\n")


@app.command()
def recall(
    query: str = typer.Argument(..., help="What to search for."),
    project: str = typer.Option(None, "--project", "-p", help="Limit to a project (the partition wall)."),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results."),
    pipe: bool = typer.Option(False, "--pipe", help="Copy the matched notes to the clipboard (paste into your AI)."),
    identity: str = typer.Option(None, "--identity", "-i", help="Identity scope (default: personal)."),
) -> None:
    """Search your memory (full-text) and surface the best matches."""
    _require_init()
    identity, project, source = _resolve_context(identity, project)

    if not query.split():
        typer.echo("Empty query.", err=True)
        raise typer.Exit(code=1)
    rows = _search(query, project, limit, identity=identity)

    if not rows:
        typer.echo("No matches." + (f"  (project: {project})" if project else ""))
        raise typer.Exit()

    if pipe:
        blocks = [
            f"## [{proj or 'no-project'}] {created}\n{_read_body(path)}"
            for _id, proj, created, path, _snip, *_ in rows
        ]
        payload = f'# Context from kage (query: "{query}")\n\n' + "\n\n".join(blocks) + "\n"
        try:
            subprocess.run(["pbcopy"], input=payload.encode(), check=True)
            typer.echo(
                f"✓ copied {len(rows)} note(s) to clipboard ({len(payload)} chars). "
                "Paste into your AI, then add your question."
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            typer.echo(payload)  # no pbcopy available — print it so you can copy manually
        raise typer.Exit()

    typer.echo(f"\n{len(rows)} match(es):\n")
    for mem_id, proj, created, path, snip, *_ in rows:
        typer.echo(f"  • [{proj or 'no-project'}] {snip}")
        typer.echo(f"    {created}   {_disp(KAGE_HOME / path)}   [{mem_id}]\n")


# ── Arm helpers (Cycle 11) ────────────────────────────────────────────────

# ── DORMANT (Cycle 11) — do not delete ──────────────────────────────────────
# Google OAuth + remote SSE arm transport (this token helper, the `sse` branch
# in _connect_arm, and arm_auth below). Kept importable & test-covered, NOT
# removed: Workspace Developer Preview rejects Gmail-domain accounts, so the SSE
# arms (Calendar/Gmail) never complete a live call. The live calendar arm uses
# the `shell` transport (icalbuddy) and needs none of this.
# FLIPS LIVE when: a valid google_oauth.refresh_token exists (via `kage arm auth`)
# AND an arm is enabled with transport "sse". Restoring OAuth from scratch later
# is the expensive path — that's why it stays.
async def _get_google_token() -> str:
    """Exchange Google OAuth refresh token for a short-lived access token."""
    cfg = _config()
    oauth = cfg.get("google_oauth", {})
    client_id = oauth.get("client_id", "")
    client_secret = oauth.get("client_secret", "")
    refresh_token = oauth.get("refresh_token", "")
    if not (client_id and client_secret and refresh_token):
        raise RuntimeError("google_oauth credentials missing — run: kage arm auth")
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]


@asynccontextmanager
async def _connect_arm(arm_name: str):
    """Yield (read, write) streams for the named arm (sse or stdio transport)."""
    arm = _config().get("arms", {}).get(arm_name, {})
    transport = arm.get("transport", "stdio")
    if transport == "sse":
        # DORMANT (Cycle 11) — see _get_google_token banner. Inert until a refresh_token exists.
        token = await _get_google_token()
        async with sse_client(
            url=arm["mcp_url"],
            headers={"Authorization": f"Bearer {token}"},
        ) as streams:
            yield streams
    else:
        server_params = StdioServerParameters(
            command=arm["mcp_command"],
            args=arm.get("mcp_args", []),
        )
        async with stdio_client(server_params) as streams:
            yield streams


def _serialize_arm_result(result) -> str | None:
    """Extract text from a CallToolResult. Returns None if error or empty."""
    if getattr(result, "isError", False):
        return None
    texts = [block.text for block in result.content if hasattr(block, "text")]
    return "\n".join(texts) if texts else None


def _select_tool(arm_name: str, question: str, tools: list) -> tuple[str, dict]:
    """Pick the best tool from the arm's tool list and build params."""
    preferred = {"calendar": "list_events", "gmail": "search_threads"}
    pref = preferred.get(arm_name)
    for t in tools:
        if t.name == pref:
            return t.name, {"query": question}
    if tools:
        return tools[0].name, {"query": question}
    raise RuntimeError(f"Arm {arm_name!r} has no tools")


async def _call_arm(arm_name: str, question: str, identity: str, timeout: float = 30.0) -> str | None:
    """Call one arm. Returns serialized text or None on any failure (graceful)."""
    ts = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    arm = _config().get("arms", {}).get(arm_name, {})
    if arm.get("transport") == "shell":
        cmd = arm.get("command", "")
        if not cmd:
            _write_audit({
                "type": "arm_call",
                "arm": arm_name,
                "tool": "shell",
                "identity": identity,
                "ts": ts,
                "success": False,
            })
            return None
        try:
            proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=timeout)
            data = proc.stdout.strip() or None
            _write_audit({
                "type": "arm_call",
                "arm": arm_name,
                "tool": "shell",
                "identity": identity,
                "ts": ts,
                "success": bool(data),
            })
            return data
        except Exception:
            _write_audit({
                "type": "arm_call",
                "arm": arm_name,
                "tool": "shell",
                "identity": identity,
                "ts": ts,
                "success": False,
            })
            return None
    try:
        async with asyncio.timeout(timeout):
            async with _connect_arm(arm_name) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    if arm_name not in _arm_tool_cache:
                        tools_result = await session.list_tools()
                        _arm_tool_cache[arm_name] = tools_result.tools
                    tool_name, params = _select_tool(
                        arm_name, question, _arm_tool_cache[arm_name]
                    )
                    result = await session.call_tool(tool_name, params)
                    data = _serialize_arm_result(result)
                    _write_audit({
                        "type": "arm_call",
                        "arm": arm_name,
                        "tool": tool_name,
                        "identity": identity,
                        "ts": ts,
                        "success": data is not None,
                    })
                    return data
    except Exception:
        _write_audit({
            "type": "arm_call",
            "arm": arm_name,
            "tool": "unknown",
            "identity": identity,
            "ts": ts,
            "success": False,
        })
        return None


def _detect_arms(question: str, identity: str) -> list[str]:
    """Return list of arm names to call (all matching in config order)."""
    arms = _config().get("arms", {})
    q = question.lower()
    return [
        name for name, arm in arms.items()
        if arm.get("enabled")
        and isinstance(arm.get("identity"), str)
        and arm["identity"] == identity
        and arm.get("permission") == "read"
        and any(kw in q for kw in ARM_KEYWORDS.get(name, []))
    ]


async def _check_arm_health(arm_name: str) -> bool:
    """Return True if the arm is reachable (shell: exit 0; MCP: initializes)."""
    arm = _config().get("arms", {}).get(arm_name, {})
    if arm.get("transport") == "shell":
        cmd = arm.get("command", "")
        if not cmd:
            return False
        try:
            proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=10.0)
            return proc.returncode == 0
        except Exception:
            return False
    try:
        async with asyncio.timeout(10.0):
            async with _connect_arm(arm_name) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await session.list_tools()
        return True
    except Exception:
        return False


# DORMANT (Cycle 11) — see _get_google_token banner. Inert until a refresh_token exists.
@_arm_app.command("auth")
def arm_auth() -> None:
    """One-time Google OAuth consent flow — stores refresh token in config."""
    cfg = _config()
    oauth = cfg.get("google_oauth", {})
    client_id = oauth.get("client_id", "")
    client_secret = oauth.get("client_secret", "")
    if not client_id or not client_secret:
        typer.echo(
            "✗ google_oauth.client_id and google_oauth.client_secret must be set in config.json first.\n"
            "  1. Google Cloud Console → APIs & Services → Credentials\n"
            "  2. Create OAuth client ID (type: Desktop app)\n"
            "  3. Add client_id and client_secret to ~/.kage/config.json under 'google_oauth'"
        )
        raise typer.Exit(code=1)
    scopes = " ".join([
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/gmail.readonly",
    ])
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}"
        "&redirect_uri=urn:ietf:wg:oauth:2.0:oob"
        "&response_type=code"
        f"&scope={urllib.parse.quote(scopes)}"
        "&access_type=offline"
        "&prompt=consent"
    )
    typer.echo(f"\nOpen this URL in your browser:\n\n  {auth_url}\n")
    code = typer.prompt("Paste the authorization code here")
    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        "grant_type": "authorization_code",
    }
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read())
    except Exception as exc:
        typer.echo(f"✗ Token exchange failed: {exc}")
        raise typer.Exit(code=1)
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        typer.echo("✗ No refresh_token in response — ensure prompt=consent in the auth URL.")
        raise typer.Exit(code=1)
    cfg.setdefault("google_oauth", {})
    cfg["google_oauth"]["refresh_token"] = refresh_token
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    typer.echo("✓ Refresh token saved to config.json — Google arms are ready.")


@app.command()
def ask(
    question: str = typer.Argument(..., help="Your question."),
    project: str = typer.Option(None, "--project", "-p", help="Limit context to a project."),
    cloud: bool = typer.Option(False, "--cloud", help="Use a cloud provider instead of the local model."),
    provider: str = typer.Option(None, "--provider", help="Cloud provider name (e.g. openai, groq, gemini). Overrides config cloud_provider."),
    think: bool = typer.Option(False, "--think", help="Let the local model reason first (slower, deeper)."),
    limit: int = typer.Option(5, "--limit", "-n", help="How many notes to pull as context."),
    no_sources: bool = typer.Option(False, "--no-sources", help="Suppress the Sources block."),
    always_ask: bool = typer.Option(False, "--always-ask", help="Re-prompt before each cloud dispatch (overrides session approval memory)."),
    identity: str = typer.Option(None, "--identity", "-i", help="Identity scope (default: personal)."),
) -> None:
    """Answer a question using your recalled notes — local model by default, --cloud to use a cloud provider."""
    _require_init()
    identity, project, source = _resolve_context(identity, project)

    rows = _search(question, project, limit, any_terms=True, identity=identity)
    cfg = _config()

    # 3e disclosure gate — runs before context assembly, cloud path only
    provider_name: str = ""
    if cloud:
        provider_name = provider or cfg.get("cloud_provider", "claude")
        allowed_rows, withheld = _disclosure_gate(rows, cfg, identity=identity, project=project)
        withheld_reasons = [w["reason"] for w in withheld]
        pii_hits = [p for w in withheld for p in w["pii_patterns"]]

        if withheld and not allowed_rows:
            # Case 2: all notes withheld → silent Ollama fallback
            typer.echo("[kage] All retrieved context is local-only.")
            for w in withheld[:3]:
                typer.echo(f"  · withheld: {w['note_id'][:16]}  ({w['reason']})")
            typer.echo("  · Answering with local Ollama only (no cloud call).\n")
            _write_audit({
                "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                "provider": provider_name, "project": project,
                "notes_retrieved": len(rows), "notes_withheld": len(withheld),
                "withheld_reasons": withheld_reasons, "pii_detected": pii_hits,
                "user_approved": None, "outcome": "blocked_all_local",
            })
            cloud = False
        else:
            user_approved = True
            require_approval = cfg.get("require_approval", True)
            session_remember = cfg.get("session_remember_approval", True)
            need_prompt = (
                require_approval
                and withheld
                and (always_ask or not session_remember or provider_name not in _session_approvals)
            )
            if need_prompt:
                pii_withheld = [w for w in withheld if w["pii_patterns"]]
                if pii_withheld:
                    typer.echo(
                        f"\n[kage] PII detected in {len(pii_withheld)} note(s) before dispatch to {provider_name}."
                    )
                else:
                    typer.echo(f"\n[kage] Preparing to send context to {provider_name}.")
                typer.echo(f"  · {len(allowed_rows) + len(withheld)} note(s) matched")
                for w in withheld:
                    pii_str = (
                        f" ({', '.join(w['pii_patterns'][:2])})" if w["pii_patterns"] else ""
                    )
                    typer.echo(f"  · withheld: {w['note_id'][:16]}  {w['reason']}{pii_str}")
                typer.echo(f"  · {len(allowed_rows)} note(s) will be included")
                user_approved = typer.confirm("\nProceed with partial context?", default=True)
            elif withheld:
                # already approved this session — notify but don't re-ask
                typer.echo(
                    f"[kage] {len(withheld)} note(s) withheld before dispatch to {provider_name}."
                )

            if not user_approved:
                typer.echo("[kage] Denied — falling back to local Ollama.\n")
                _write_audit({
                    "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "provider": provider_name, "project": project,
                    "notes_retrieved": len(rows), "notes_withheld": len(withheld),
                    "withheld_reasons": withheld_reasons, "pii_detected": pii_hits,
                    "user_approved": False, "outcome": "denied_by_user",
                })
                cloud = False
            else:
                if withheld and session_remember:
                    _session_approvals[provider_name] = True
                _write_audit({
                    "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "provider": provider_name, "project": project,
                    "notes_retrieved": len(rows), "notes_withheld": len(withheld),
                    "withheld_reasons": withheld_reasons, "pii_detected": pii_hits,
                    "user_approved": None if (withheld and not require_approval) else True,
                    "outcome": "dispatched",
                })
                rows = allowed_rows

    context_parts = []
    sources = []
    for note_id, proj, created, path, snip, section_title, char_start, char_end in rows:
        if char_start is not None and char_end is not None:
            text = _read_section(path, char_start, char_end)
        else:
            try:
                text = _read_body(path)
            except OSError:
                text = ""
        if text:
            context_parts.append(f"[{note_id}] {text}")
            sources.append((note_id, path, section_title))
    context = "\n\n".join(context_parts) or "(no relevant notes found)"

    # ── Arm calls (Cycle 11) ──────────────────────────────────────────────
    arm_names = _detect_arms(question, identity)
    arm_results: list[str] = []
    if arm_names:
        async def _arm_flow() -> None:
            for _arm_name in arm_names:
                _result = await _call_arm(_arm_name, question, identity)
                if _result:
                    arm_results.append(f"[{_arm_name}]\n{_result}")
        asyncio.run(_arm_flow())
    arm_context = "\n\n".join(arm_results) if arm_results else ""

    if arm_context:
        system = (
            "You are kage, the user's personal context broker.\n\n"
            f"MEMORY (user's saved notes):\n{context}\n\n"
            f"ARM DATA (live data from connected services):\n{arm_context}\n\n"
            "Answer using MEMORY and ARM DATA. Clearly distinguish:\n"
            "- facts from saved notes (cite 'from your notes')\n"
            "- live data from a connected service (cite 'from your calendar' or 'from your email')\n"
            "If neither contains the answer, say so explicitly."
        )
        effective_context = ""
    else:
        system = (
            "You are kage, the user's personal memory assistant. "
            "Answer ONLY using the CONTEXT below — the user's own saved notes. "
            "If the answer is not in the context, say exactly: "
            "'I don't know — nothing in your notes covers this.' "
            "Do not use general knowledge. Be concise."
        )
        effective_context = context
    thinking = ""

    if cloud:
        default_pcfg = DEFAULT_PROVIDERS.get(provider_name, {})
        user_pcfg = cfg.get("providers", {}).get(provider_name, {})
        pcfg = {**default_pcfg, **user_pcfg}
        model = pcfg.get("model", provider_name)
        typer.echo(f"· asking {model} via {provider_name} ({len(rows)} note(s) as context)…\n")
        user_msg = question if arm_context else f"CONTEXT:\n{effective_context}\n\nQUESTION: {question}"
        try:
            answer = _call_cloud(
                provider_name,
                system,
                user_msg,
                cfg,
            )
        except CloudError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(code=1)
    else:
        model = cfg.get("model", "qwen3:14b")
        url = cfg.get("ollama_url", "http://localhost:11434") + "/api/generate"
        typer.echo(f"· asking {model} ({len(rows)} note(s) as context)…\n")
        if effective_context:
            prompt = f"{system}\n\nCONTEXT (the user's notes):\n{effective_context}\n\nQUESTION: {question}"
        else:
            prompt = f"{system}\n\nQUESTION: {question}"
        try:
            out = _post_json(url, {"model": model, "prompt": prompt, "stream": False, "think": think})
        except urllib.error.URLError:
            typer.echo("Can't reach the local model. Is Ollama running? (`ollama serve`) — or use --cloud.", err=True)
            raise typer.Exit(code=1)
        answer = out.get("response", "").strip()
        thinking = out.get("thinking", "").strip() if think else ""

    if thinking:
        typer.echo(f"[thinking]\n{thinking}\n")
    typer.echo(answer or "(no answer returned)")

    if arm_context:
        typer.echo(f"\nSources: {', '.join(arm_names)} (live arm)")
    elif not no_sources and sources:
        typer.echo("\nSources:")
        for note_id, path, section_title in sources:
            label = f"§ {section_title}" if section_title else _disp(KAGE_HOME / path)
            typer.echo(f"  • {note_id}  {label}")


@app.command()
def forget(
    ident: str = typer.Argument(..., help="The note's id or a unique prefix (see `kage list`)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirm prompt."),
) -> None:
    """Delete a saved note — its markdown file and its index rows. Asks first."""
    _require_init()

    conn = _connect()
    try:
        matches = conn.execute(
            "SELECT id, project, content_path FROM memories WHERE id = ? OR id LIKE ?",
            (ident, ident + "%"),
        ).fetchall()

        if not matches:
            typer.echo(f"No note matches '{ident}'.  (see: kage list)", err=True)
            raise typer.Exit(code=1)
        if len(matches) > 1:
            typer.echo(f"'{ident}' matches {len(matches)} notes — be more specific:", err=True)
            for mid, proj, _ in matches:
                typer.echo(f"  {mid}  [{proj or 'no-project'}]")
            raise typer.Exit(code=1)

        mem_id, proj, path = matches[0]
        body = _read_body(path)
        preview = (body[:70] + "…") if len(body) > 70 else body
        typer.echo(f'\n  [{proj or "no-project"}] {preview}')
        typer.echo(f"  {mem_id}")
        if not yes and not typer.confirm("Forget this note? This permanently deletes it.", default=False):
            typer.echo("Kept — nothing deleted.")
            raise typer.Exit()

        (KAGE_HOME / path).unlink(missing_ok=True)  # remove the source of truth
        chunk_ids = [row[0] for row in conn.execute(
            "SELECT id FROM chunks WHERE note_id = ?", (mem_id,)
        ).fetchall()]
        conn.execute("DELETE FROM chunks WHERE note_id = ?", (mem_id,))
        conn.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
        conn.execute("DELETE FROM memory_fts WHERE id = ?", (mem_id,))  # and the index
        conn.commit()
    finally:
        conn.close()

    if chunk_ids:
        try:
            _get_chroma().delete(ids=chunk_ids)
        except OllamaUnavailable:
            typer.echo("  ⚠ vector index not updated — run: kage reindex", err=True)

    typer.echo(f"  ✓ forgotten   [{mem_id}]")


@app.command()
def status(
    audit: bool = typer.Option(False, "--audit", help="Show last N dispatch records from the audit log."),
    audit_n: int = typer.Option(10, "--n", help="Number of audit records to show (with --audit)."),
) -> None:
    """Show what kage holds and where it lives."""
    _require_init()

    _audit_path = KAGE_HOME / "audit.jsonl"
    if audit:
        if not _audit_path.exists():
            typer.echo(f"  no audit log yet — {_disp(_audit_path)}")
            return
        try:
            lines = _audit_path.read_text().strip().splitlines()
            records = [json.loads(line) for line in lines if line.strip()]
            last = records[-audit_n:]
            typer.echo(f"\n  Audit log ({len(last)} of {len(records)} record(s)):\n")
            for r in last:
                ts = r.get("ts", "")[:16].replace("T", " ")
                prov = r.get("provider", "?")
                retrieved = r.get("notes_retrieved", 0)
                wh = r.get("notes_withheld", 0)
                outcome = r.get("outcome", "?")
                typer.echo(
                    f"    {ts}  {prov:<12}  {retrieved} retrieved  {wh} withheld  [{outcome}]"
                )
            typer.echo("")
        except (OSError, ValueError):
            typer.echo("  ⚠ audit log unreadable")
        return

    conn = _connect()
    try:
        total = conn.execute("SELECT count(*) FROM memories").fetchone()[0]
        local_only_total = conn.execute(
            "SELECT count(*) FROM memories WHERE local_only = 1"
        ).fetchone()[0]
        by_proj = conn.execute(
            "SELECT COALESCE(project, '(no project)') AS p, count(*) AS c "
            "FROM memories GROUP BY p ORDER BY c DESC, p"
        ).fetchall()
    finally:
        conn.close()

    try:
        version = json.loads(CONFIG_PATH.read_text()).get("version", "?")
    except (OSError, ValueError):
        version = "?"
    db_kb = DB_PATH.stat().st_size / 1024 if DB_PATH.exists() else 0.0
    lo_suffix = f"  ({local_only_total} local-only)" if local_only_total else ""

    _ac_identity, _ac_project, _ac_source = _resolve_context(None, None)
    _ac_display = f"{_ac_identity}" + (f"/{_ac_project}" if _ac_project else "")

    typer.echo("\nkage status")
    typer.echo(f"  context  {_ac_display}  [{_ac_source}]")
    typer.echo(f"  store    {_disp(KAGE_HOME)}   (config v{version})")
    typer.echo(f"  memory   {total} note(s) across {len(by_proj)} project(s){lo_suffix}")
    for p, c in by_proj:
        typer.echo(f"             {c:>4}  {p}")
    typer.echo(f"  index    {_disp(DB_PATH)}   ({db_kb:.0f} KB)")
    _cfg = _config()
    provider_name = _cfg.get("cloud_provider", "claude")
    _default_pcfg = DEFAULT_PROVIDERS.get(provider_name, {})
    _user_pcfg = _cfg.get("providers", {}).get(provider_name, {})
    _pcfg = {**_default_pcfg, **_user_pcfg}
    cloud_model = _pcfg.get("model", provider_name)
    typer.echo(f"  model    {_cfg.get('model', 'qwen3:14b')} local · {cloud_model} via {provider_name} (--cloud)")
    free_gb = shutil.disk_usage(KAGE_HOME).free / 1e9
    typer.echo(f"  disk     {free_gb:.0f} GB free")
    arms_cfg = _cfg.get("arms", {})
    if arms_cfg:
        typer.echo("  arms")
        for arm_name, arm in arms_cfg.items():
            enabled = arm.get("enabled", False)
            transport = arm.get("transport", "stdio")
            permission = arm.get("permission", "read")
            mark = "✓" if enabled else "·"
            typer.echo(f"    {mark} {arm_name:<12}  {transport:<5}  {permission}")
    typer.echo("  ✓ everything local — nothing has left this Mac\n")


@app.command()
def doctor() -> None:
    """Check kage's setup and flag anything broken (with how to fix it)."""
    checks: list[tuple[bool, str, str]] = []  # (ok, label, fix-hint)

    store_ok = KAGE_HOME.exists() and MEMORY_DIR.exists() and INDEX_DIR.exists()
    checks.append((store_ok, "store layout (~/.kage)", "run: kage init"))

    try:
        json.loads(CONFIG_PATH.read_text())
        cfg_ok = True
    except (OSError, ValueError):
        cfg_ok = False
    checks.append((cfg_ok, "config.json readable", "run: kage init"))

    db_ok, idx_count = False, 0
    if DB_PATH.exists():
        try:
            conn = _connect()
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )}
            db_ok = {"memories", "memory_fts"} <= tables
            if db_ok:
                idx_count = conn.execute("SELECT count(*) FROM memories").fetchone()[0]
            conn.close()
        except sqlite3.Error:
            db_ok = False
    checks.append((db_ok, "database + schema", "run: kage init"))

    md_count = len(list(MEMORY_DIR.glob("*.md"))) if MEMORY_DIR.exists() else 0
    consistent = db_ok and md_count == idx_count
    checks.append((
        consistent,
        f"markdown ↔ index consistent ({md_count} files / {idx_count} rows)",
        "index drifted from the markdown — a `kage reindex` is the planned fix",
    ))

    free_gb = shutil.disk_usage(KAGE_HOME if KAGE_HOME.exists() else Path.home()).free / 1e9
    checks.append((free_gb >= 1.0, f"disk space ({free_gb:.1f} GB free)", "low disk — free up space"))

    typer.echo("\nkage doctor — checking your setup\n")
    all_ok = True
    for ok, label, fix in checks:
        typer.echo(f"  {'✓' if ok else '✗'} {label}")
        if not ok:
            typer.echo(f"      → {fix}")
        all_ok = all_ok and ok

    # Advisory — unembedded chunks (⚠ warning, not a hard failure).
    if db_ok:
        try:
            conn = _connect()
            pending = conn.execute("SELECT COUNT(*) FROM chunks WHERE needs_embed=1").fetchone()[0]
            conn.close()
            if pending > 0:
                typer.echo(f"  ⚠ {pending} chunk(s) not yet embedded → run: kage reindex")
        except sqlite3.Error:
            pass

    # Advisory — embedding model mismatch between config and ChromaDB collection.
    cfg = _config()
    config_model = cfg.get("embed_model", "nomic-embed-text")
    try:
        coll = _get_chroma()
        stored_model = (coll.metadata or {}).get("embed_model")
        stored_schema = (coll.metadata or {}).get("schema_version", "?")
        typer.echo(f"  ✓ vector index  schema v{stored_schema}  embed model: {stored_model or config_model}")
        if stored_model is not None and stored_model != config_model:
            typer.echo(f"  ✗ embedding model changed ({stored_model} → {config_model}) → run: kage reindex --force")
    except OllamaUnavailable:
        pass  # _get_chroma raises on mismatch — warning already printed by _get_chroma

    # Advisory — Ollama is needed only for `kage ask` (local); NOT a hard failure.
    model = cfg.get("model", "qwen3:14b")
    ok_ollama, detail = _ollama_status(cfg, model)
    typer.echo(f"  {'✓' if ok_ollama else '⚠'} local model: {detail}")
    if not ok_ollama:
        typer.echo(f"      → for `kage ask`: start Ollama (`ollama serve`) + `ollama pull {model}`")

    # Advisory — cloud provider key status
    user_providers = cfg.get("providers", {})
    all_provider_names = list(DEFAULT_PROVIDERS.keys())
    for name in user_providers:
        if name not in all_provider_names:
            all_provider_names.append(name)
    typer.echo("\n  Cloud providers:")
    for name in all_provider_names:
        default_pcfg = DEFAULT_PROVIDERS.get(name, {})
        user_pcfg = user_providers.get(name, {})
        pcfg = {**default_pcfg, **user_pcfg}
        env_var = pcfg.get("api_key_env", "")
        key_set = bool(os.environ.get(env_var, ""))
        mark = "✓" if key_set else "·"
        status_word = "set" if key_set else "not set"
        typer.echo(f"    {mark} {name:<12}  {env_var:<24}  {status_word}")

    # Advisory — MCP server package importable.
    try:
        import mcp as _mcp_pkg  # noqa: F401
        mcp_ok = True
    except ImportError:
        mcp_ok = False
    typer.echo(f"  {'✓' if mcp_ok else '⚠'} MCP server (mcp[cli]){'' if mcp_ok else ' — not installed'}")
    if not mcp_ok:
        typer.echo("      → pip install 'mcp[cli]'")

    # Advisory — privacy gate (Layer 3e) config
    local_only_projects = cfg.get("local_only_projects", [])
    if local_only_projects:
        typer.echo(f"  ✓ privacy gate  {len(local_only_projects)} local-only project(s) configured")
    else:
        typer.echo("  · privacy gate  no local_only_projects set (--local flag still works per note)")

    # Advisory — audit log writable
    audit_ok = True
    try:
        with open(KAGE_HOME / "audit.jsonl", "a"):
            pass
    except OSError:
        audit_ok = False
    typer.echo(f"  {'✓' if audit_ok else '⚠'} audit log  {_disp(KAGE_HOME / 'audit.jsonl')}")
    if not audit_ok:
        typer.echo("      → check write permissions on ~/.kage")

    # Advisory — arm health
    arms_cfg = cfg.get("arms", {})
    if arms_cfg:
        typer.echo("\n  Arms:")
        for arm_name, arm in arms_cfg.items():
            if not arm.get("enabled", False):
                typer.echo(f"    · {arm_name:<12}  disabled")
                continue
            ok = asyncio.run(_check_arm_health(arm_name))
            if ok:
                typer.echo(f"    ✓ {arm_name:<12}  reachable")
            else:
                arm_transport = arm.get("transport", "stdio")
                if arm_transport == "sse" and not cfg.get("google_oauth", {}).get("refresh_token"):
                    typer.echo(f"    ✗ {arm_name:<12}  missing google_oauth credentials (run: kage arm auth)")
                else:
                    typer.echo(f"    ✗ {arm_name:<12}  unreachable")

    if all_ok:
        typer.echo("\n✓ kage looks healthy.\n")
    else:
        typer.echo("\n✗ some checks failed — see fixes above.\n")
        raise typer.Exit(code=1)


def _migrate_identity_axis(dry_run: bool = False) -> dict:
    conn = _connect()
    try:
        if not dry_run:
            cur1 = conn.execute("INSERT OR IGNORE INTO memory_identities(mem_id, identity) SELECT id, 'personal' FROM memories")
            identities_added = cur1.rowcount
            cur2 = conn.execute("INSERT OR IGNORE INTO memory_projects(mem_id, project) SELECT id, project FROM memories WHERE project IS NOT NULL AND project != ''")
            projects_added = cur2.rowcount
            conn.execute("UPDATE memories SET state = 'baseline' WHERE (project IS NULL OR project = '') AND state = 'scoped'")
            conn.commit()
        else:
            identities_added = conn.execute("SELECT COUNT(*) FROM memories m WHERE NOT EXISTS (SELECT 1 FROM memory_identities mi WHERE mi.mem_id = m.id AND mi.identity = 'personal')").fetchone()[0]
            projects_added = conn.execute("SELECT COUNT(*) FROM memories m WHERE m.project IS NOT NULL AND m.project != '' AND NOT EXISTS (SELECT 1 FROM memory_projects mp WHERE mp.mem_id = m.id AND mp.project = m.project)").fetchone()[0]
    finally:
        conn.close()

    frontmatter_updated = 0
    md_files = sorted(MEMORY_DIR.glob("*.md"))
    for md_path in md_files:
        text = md_path.read_text()
        parts = text.split("---\n", 2)
        if len(parts) < 3:
            continue
        front = parts[1]
        if "identities:" in front:
            continue
        project_val = ""
        for line in front.splitlines():
            if line.startswith("project:"):
                project_val = line[len("project:"):].strip()
                break
        state_val = "scoped" if project_val else "baseline"
        new_front = front.rstrip("\n") + f"\nidentities:\n  - personal\nstate: {state_val}\n"
        if not dry_run:
            md_path.write_text("---\n" + new_front + "---\n" + parts[2])
        frontmatter_updated += 1

    return {
        "notes": len(md_files),
        "identities_added": identities_added,
        "projects_added": projects_added,
        "frontmatter_updated": frontmatter_updated,
    }


@app.command()
def migrate(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would change without writing."),
) -> None:
    if not dry_run:
        typer.echo("This will update frontmatter for all notes in ~/.kage/memory and populate the identity axis join tables.")
        typer.echo("Back up ~/.kage before proceeding.")
        if not typer.confirm("Continue?", default=False):
            raise typer.Exit()
    stats = _migrate_identity_axis(dry_run=dry_run)
    prefix = "[DRY RUN] " if dry_run else ""
    typer.echo(f"{prefix}Migration complete:")
    typer.echo(f"  notes found:          {stats['notes']}")
    typer.echo(f"  identities added:     {stats['identities_added']}")
    typer.echo(f"  projects added:       {stats['projects_added']}")
    typer.echo(f"  frontmatter updated:  {stats['frontmatter_updated']}")


@app.command()
def chat(
    project: str = typer.Option(None, "--project", "-p", help="Pin context to a project."),
    identity: str = typer.Option("personal", "--identity", "-i", help="Identity scope (pinned for session lifetime)."),
    provider: str = typer.Option(None, "--provider", help="Starting destination: provider name or leave blank for ollama."),
    limit: int = typer.Option(5, "--limit", "-n", help="Notes per turn."),
) -> None:
    """Dev/debug cockpit: stateful conversation with kage. Identity and project are pinned; destination is switchable via /use."""
    _require_init()
    cfg = _config()
    destination = provider or "ollama"
    session_id = _session_create(identity, project, destination)
    _last_sources: list = []
    typer.echo(f"kage chat  [{identity} · {project or 'all'} · {destination}]  /help for commands")
    typer.echo("-" * 60)
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            typer.echo("\n[kage] bye.")
            break
        if not raw:
            continue
        if raw.startswith("/"):
            parts = raw.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            if cmd == "/exit":
                typer.echo("[kage] bye.")
                break
            elif cmd == "/help":
                typer.echo("/help     show this")
                typer.echo("/exit     quit")
                typer.echo("/new      start a fresh session (identity+project stay pinned)")
                typer.echo("/use <p>  switch destination to provider p (or ollama)")
                typer.echo("/clear    clear screen")
                typer.echo("/scope    show current session scope")
                typer.echo("/sources  show sources from last turn")
                typer.echo("/history  show turn history")
            elif cmd == "/new":
                session_id = _session_create(identity, project, destination)
                _last_sources = []
                typer.echo(f"[kage] New session: {session_id[:8]}")
            elif cmd == "/use":
                if not arg:
                    typer.echo("[kage] Usage: /use <provider>  (e.g. /use claude, /use ollama)")
                    continue
                try:
                    new_dest, safe_turns, withheld = _session_switch(session_id, arg.strip(), cfg, identity, project)
                    destination = new_dest
                    typer.echo(f"[kage] Switched to {destination}.")
                    if withheld:
                        typer.echo(f"  · {len(withheld)} turn(s) withheld from new destination (privacy gate).")
                except ValueError as e:
                    typer.echo(f"[kage] Error: {e}")
            elif cmd == "/clear":
                typer.echo("\033[2J\033[H", nl=False)
            elif cmd == "/scope":
                session = _session_load(session_id)
                if session:
                    typer.echo(f"  identity   {identity}")
                    typer.echo(f"  project    {project or '(all)'}")
                    typer.echo(f"  dest       {destination}")
                    typer.echo(f"  session    {session_id[:8]}…")
            elif cmd == "/sources":
                if not _last_sources:
                    typer.echo("[kage] No sources from last turn.")
                else:
                    typer.echo("Sources (last turn):")
                    for note_id, path, section_title in _last_sources:
                        label = f"§ {section_title}" if section_title else _disp(KAGE_HOME / path)
                        typer.echo(f"  • {note_id}  {label}")
            elif cmd == "/history":
                turns = _session_turns(session_id, token_budget=10_000_000)
                if not turns:
                    typer.echo("[kage] No history yet.")
                for turn in turns:
                    content = turn["content"]
                    content_short = content[:60].replace(chr(10), " ")
                    typer.echo(f"  [{turn['idx']}] {turn['role']:9s} {content_short}{'…' if len(content) > 60 else ''}")
            else:
                typer.echo(f"[kage] Unknown command: {cmd}  (type /help)")
            continue
        history = _session_turns(session_id)
        condensed = _condense_query(history, raw)
        rows = _search(condensed, project, limit, any_terms=True, identity=identity)
        if destination != "ollama":
            all_turns = _session_turns(session_id, token_budget=10_000_000)
            safe_turns, withheld_turns = _gate_conversation(all_turns, cfg, identity, project)
            if withheld_turns:
                typer.echo(f"[kage] {len(withheld_turns)} turn(s) withheld from {destination} (privacy gate).")
            rows, _ = _disclosure_gate(rows, cfg, identity=identity, project=project)
            history_for_answer = safe_turns
        else:
            history_for_answer = history
        context_parts = []
        _last_sources = []
        note_ids_this_turn: list[str] = []
        for note_id, proj, created, path, snip, section_title, char_start, char_end in rows:
            if char_start is not None and char_end is not None:
                text = _read_section(path, char_start, char_end)
            else:
                try:
                    text = _read_body(path)
                except OSError:
                    text = ""
            if text:
                context_parts.append(f"[{note_id}] {text}")
                _last_sources.append((note_id, path, section_title))
                note_ids_this_turn.append(note_id)
        context = "\n\n".join(context_parts)
        try:
            answer = next(iter(_answer(condensed, history_for_answer, context, destination, cfg)))
        except OllamaUnavailable as e:
            typer.echo(f"[kage] Ollama unavailable: {e}", err=True)
            continue
        except CloudError as e:
            typer.echo(f"[kage] Cloud error: {e}", err=True)
            continue
        if destination == "ollama":
            model_name = cfg.get("ollama_model", "qwen3:14b")
        else:
            default_pcfg = DEFAULT_PROVIDERS.get(destination, {})
            user_pcfg = cfg.get("providers", {}).get(destination, {})
            pcfg = {**default_pcfg, **user_pcfg}
            model_name = pcfg.get("model", destination)
        est_tokens = len(answer) // 4
        _session_append(session_id, "user", raw, note_ids_this_turn, destination, model_name, None, None)
        _session_append(session_id, "assistant", answer, [], destination, model_name, None, est_tokens)
        typer.echo(answer)
        typer.echo(f"\n[{model_name} · {destination} · ~{est_tokens}tok]")


@_mcp_app.command("serve")
def mcp_serve() -> None:
    """Start the kage MCP server (stdio transport — for Claude Code, Antigravity 2.0, etc.)."""
    _require_init()
    try:
        from kage.mcp_server import mcp as _mcp
    except ImportError:
        typer.echo("MCP not installed — run: pip install 'mcp[cli]'", err=True)
        raise typer.Exit(code=1)
    _mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    app()
