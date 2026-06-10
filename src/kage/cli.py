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
import shutil
import sqlite3
import subprocess
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import typer

class OllamaUnavailable(Exception):
    """Raised when Ollama is unreachable or times out."""


class CloudError(Exception):
    """Raised when a cloud provider call fails."""


app = typer.Typer(
    help="kage — your local context broker. Your notes, surfaced into your AI, on your machine.",
    add_completion=False,
    no_args_is_help=True,
)

_mcp_app = typer.Typer(help="MCP server commands.")
app.add_typer(_mcp_app, name="mcp")

# ── Layout ────────────────────────────────────────────────────────────────
KAGE_HOME = Path(os.environ.get("KAGE_HOME") or Path.home() / ".kage")  # override for relocation/tests
MEMORY_DIR = KAGE_HOME / "memory"          # 5A: markdown source of truth (#70)
INDEX_DIR = KAGE_HOME / "indexes"
DB_PATH = INDEX_DIR / "kage.db"            # 5B: derived SQLite index (#71)
CONFIG_PATH = KAGE_HOME / "config.json"
CHROMA_DIR  = KAGE_HOME / "chroma"

# v0.1 schema: memories + an FTS5 full-text index for `recall`.
# Partition filtering (the wall) lives in SQL per #99; v0.1 = single project tag.
# v0.4 adds: chunks table for semantic chunking (char offsets into memory files).
_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id           TEXT PRIMARY KEY,
    content_path TEXT NOT NULL,
    project      TEXT,
    created_at   TEXT NOT NULL,
    needs_embed  INTEGER NOT NULL DEFAULT 1,
    local_only   INTEGER NOT NULL DEFAULT 0
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(id UNINDEXED, body);
CREATE TABLE IF NOT EXISTS chunks (
    id            TEXT PRIMARY KEY,
    note_id       TEXT NOT NULL,
    section_title TEXT NOT NULL DEFAULT '',
    char_start    INTEGER NOT NULL,
    char_end      INTEGER NOT NULL,
    needs_embed   INTEGER NOT NULL DEFAULT 1
);
"""


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
    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
        try:
            conn.execute("ALTER TABLE memories ADD COLUMN needs_embed INTEGER NOT NULL DEFAULT 1")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists in an existing DB
        try:
            conn.execute("ALTER TABLE memories ADD COLUMN local_only INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()
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
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _new_id() -> str:
    """Sortable, unique id: 20260604T223719-a1b2c3."""
    return f"{_dt.datetime.now():%Y%m%dT%H%M%S}-{secrets.token_hex(3)}"


def _read_body(rel_path: str) -> str:
    """Read a memory's body from its markdown file (source of truth), minus frontmatter."""
    text = (KAGE_HOME / rel_path).read_text()
    if text.startswith("---"):
        close = text.find("\n---", 3)
        if close != -1:
            text = text[close + 4 :]
    return text.strip()


def _chunk_note(body: str) -> list[dict]:
    """Split a note body into sections on ## / ### headers; return char-offset chunks."""
    chunks = []
    lines = body.splitlines()
    prev_header_pos = -1

    for i, line in enumerate(lines):
        if line.startswith("## ") or line.startswith("### "):
            if prev_header_pos != -1:
                char_start = sum(len(l) + 1 for l in lines[: prev_header_pos + 1])
                char_end = min(sum(len(l) + 1 for l in lines[:i]), len(body))
                if char_end - char_start >= 100:
                    chunks.append({
                        "title": lines[prev_header_pos].lstrip("#").strip(),
                        "char_start": char_start,
                        "char_end": char_end,
                    })
            prev_header_pos = i

    if prev_header_pos != -1:
        char_start = sum(len(l) + 1 for l in lines[: prev_header_pos + 1])
        char_end = len(body)
        if char_end - char_start >= 100:
            chunks.append({
                "title": lines[prev_header_pos].lstrip("#").strip(),
                "char_start": char_start,
                "char_end": char_end,
            })

    if not chunks:
        return [{"title": "", "char_start": 0, "char_end": len(body)}]

    return chunks


def _read_section(content_path: str, char_start: int, char_end: int) -> str:
    """Return the body slice [char_start:char_end] from a note; empty string on read error."""
    try:
        body = _read_body(content_path)
        return body[char_start:char_end]
    except OSError:
        return ""


def _save(
    text: str,
    project: str | None,
    source: str | None = None,
    embed: bool = True,
    local_only: bool = False,
) -> str:
    """Write a memory (markdown source-of-truth #70) + index it (#71). Returns its id."""
    cfg = _config()
    if not local_only and project and project in cfg.get("local_only_projects", []):
        local_only = True

    mem_id = _new_id()
    created = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    rel_path = f"memory/{mem_id}.md"
    front = f"---\nid: {mem_id}\nproject: {project or ''}\ncreated_at: {created}\n"
    if source:
        front += f"source: {source}\n"
    if local_only:
        front += "local_only: true\n"
    (KAGE_HOME / rel_path).write_text(front + "---\n\n" + text.rstrip() + "\n")

    body = text.strip()
    chunks = _chunk_note(body)
    chunk_ids = [f"{mem_id}_c{i}" for i in range(len(chunks))]

    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO memories (id, content_path, project, created_at, local_only)"
            " VALUES (?, ?, ?, ?, ?)",
            (mem_id, rel_path, project, created, int(local_only)),
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


def _search_fts(query: str, project: str | None, limit: int, any_terms: bool = False):
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
    params: list = [match]
    if project:  # the partition wall lives in SQL (#99)
        sql += "AND m.project = ? "
        params.append(project)
    sql += "ORDER BY rank LIMIT ?"
    params.append(limit)
    conn = _connect()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _search(query: str, project: str | None, limit: int, any_terms: bool = False):
    """Hybrid FTS5 + vector search; falls back to FTS5 when embeddings are off or Ollama is down."""
    if not any(t for t in query.split() if t):
        return []
    cfg = _config()
    if not cfg.get("embeddings", True):
        return [(*row, None, None, None) for row in _search_fts(query, project, limit, any_terms)]

    def run_fts():
        return _search_fts(query, project, limit * 2, any_terms)

    def run_vec():
        return _search_vec(_embed(query), project, limit * 2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        fts_future = executor.submit(run_fts)
        vec_future = executor.submit(run_vec)
        fts_rows = fts_future.result()
        try:
            vec_rows = vec_future.result()
        except OllamaUnavailable:
            return [(*row, None, None, None) for row in fts_rows[:limit]]

    fused = _rrf_fuse(fts_rows, vec_rows)[:limit]
    fts_ids = {row[0] for row in fts_rows}
    vec_by_id = {row[0]: row for row in vec_rows}
    result = []
    for row in fused:
        if row[0] not in fts_ids:
            # vec-only row: replace float score with readable excerpt, keep section fields
            try:
                body = _read_body(row[3]).replace("\n", " ")
                excerpt = (body[:70] + "…") if len(body) > 70 else body
            except OSError:
                excerpt = ""
            row = (row[0], row[1], row[2], row[3], excerpt, row[5], row[6], row[7])
        else:
            # fts row: merge section fields from vec row if available, else pad with None
            vec_row = vec_by_id.get(row[0])
            section = (vec_row[5], vec_row[6], vec_row[7]) if vec_row else (None, None, None)
            row = (*row, *section)
        result.append(row)
    return result


def _config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "kage/0.5", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


DEFAULT_PROVIDERS: dict[str, dict] = {
    "claude":     {"type": "claude",        "api_key_env": "ANTHROPIC_API_KEY",  "model": "claude-sonnet-4-6"},
    "openai":     {"type": "openai",        "api_key_env": "OPENAI_API_KEY",     "model": "gpt-4o"},
    "gemini":     {"type": "gemini",        "api_key_env": "GEMINI_API_KEY",     "model": "gemini-2.0-flash"},
    "groq":       {"type": "openai-compat", "api_key_env": "GROQ_API_KEY",       "model": "llama-3.3-70b-versatile",
                   "base_url": "https://api.groq.com/openai", "chat_path": "/v1/chat/completions"},
    "perplexity": {"type": "openai-compat", "api_key_env": "PERPLEXITY_API_KEY", "model": "llama-3.1-sonar-large-128k-online",
                   "base_url": "https://api.perplexity.ai",   "chat_path": "/chat/completions"},
}


def _call_cloud(provider_name: str, system: str, user_msg: str, cfg: dict) -> str:
    """Dispatch to a named cloud provider. Raises CloudError on any failure."""
    default_pcfg = DEFAULT_PROVIDERS.get(provider_name, {})
    user_pcfg = cfg.get("providers", {}).get(provider_name, {})
    if not default_pcfg and not user_pcfg:
        raise CloudError(
            f"Unknown provider '{provider_name}'. "
            f"Add providers.{provider_name} to ~/.kage/config.json"
        )
    pcfg = {**default_pcfg, **user_pcfg}
    key = os.environ.get(pcfg["api_key_env"], "")
    if not key:
        raise CloudError(f"{pcfg['api_key_env']} not set (provider: {provider_name})")
    ptype = pcfg.get("type", "openai-compat")
    model = pcfg.get("model", "")
    try:
        if ptype == "claude":
            out = _post_json(
                "https://api.anthropic.com/v1/messages",
                {"model": model, "max_tokens": 1024, "system": system,
                 "messages": [{"role": "user", "content": user_msg}]},
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            )
            return out["content"][0]["text"].strip()
        elif ptype in ("openai", "openai-compat"):
            base = pcfg.get("base_url", "https://api.openai.com")
            path = pcfg.get("chat_path", "/v1/chat/completions")
            out = _post_json(
                f"{base}{path}",
                {"model": model, "max_tokens": 1024,
                 "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user_msg}]},
                headers={"Authorization": f"Bearer {key}"},
            )
            return out["choices"][0]["message"]["content"].strip()
        elif ptype == "gemini":
            url = (
                f"https://generativelanguage.googleapis.com/v1beta"
                f"/models/{model}:generateContent?key={key}"
            )
            out = _post_json(url, {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": user_msg}]}],
            })
            candidates = out.get("candidates") or []
            if not candidates or "content" not in candidates[0]:
                raise CloudError(f"Gemini returned no content (provider: {provider_name})")
            return candidates[0]["content"]["parts"][0]["text"].strip()
        else:
            raise CloudError(f"Unknown provider type '{ptype}'")
    except (urllib.error.URLError, KeyError, IndexError, TimeoutError) as exc:
        raise CloudError(f"Provider '{provider_name}' request failed: {exc}") from exc


# ── Privacy gate (Layer 3e) ────────────────────────────────────────────────

_PII_PATTERNS: list[dict] = [
    # INDIAN IDENTITY DOCUMENTS
    {"name": "Aadhaar",          "pattern": r"\b\d{4}[\s-]\d{4}[\s-]\d{4}\b"},
    {"name": "PAN card",         "pattern": r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"},
    {"name": "Passport (IN)",    "pattern": r"\b[A-Z][0-9]{7}\b"},
    {"name": "Voter ID (IN)",    "pattern": r"\b[A-Z]{3}[0-9]{7}\b"},
    {"name": "Driving licence",  "pattern": r"\b[A-Z]{2}[0-9]{2}[\s-]?[0-9]{4,11}\b"},
    {"name": "GSTIN",            "pattern": r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"},
    {"name": "IFSC code",        "pattern": r"\b[A-Z]{4}0[A-Z0-9]{6}\b"},
    {"name": "Vehicle reg (IN)", "pattern": r"\b[A-Z]{2}[\s-]?\d{2}[\s-]?[A-Z]{1,2}[\s-]?\d{4}\b"},
    # CONTACT INFORMATION
    {"name": "Email",            "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"},
    {"name": "Phone (IN)",       "pattern": r"\b(\+91[\s-]?)?[6-9]\d{9}\b"},
    {"name": "Phone (intl)",     "pattern": r"\+[1-9]\d{1,14}\b"},
    {"name": "Indian PIN code",  "pattern": r"(?i)\bpin\s*(?:code)?\s*[:=]?\s*[1-9][0-9]{5}\b"},
    # FINANCIAL
    {"name": "Credit/debit card", "pattern": r"\b(?:\d{4}[\s-]?){3}\d{4}\b"},
    {"name": "UPI ID",           "pattern": r"\b[a-zA-Z0-9._-]+@[a-zA-Z]+\b"},
    {"name": "CVV",              "pattern": r"(?i)cvv\s*[:=]\s*\d{3,4}"},
    # CREDENTIALS AND KEYS
    {"name": "Password field",   "pattern": r"(?i)(password|passwd|pwd|secret)\s*[:=]\s*\S+"},
    {"name": "OpenAI key",       "pattern": r"\bsk-[A-Za-z0-9]{20,}\b"},
    {"name": "Google key",       "pattern": r"\bAIza[A-Za-z0-9_-]{35}\b"},
    {"name": "GitHub PAT",       "pattern": r"\bghp_[A-Za-z0-9]{36}\b"},
    {"name": "GitHub OAuth",     "pattern": r"\bgho_[A-Za-z0-9]{36}\b"},
    {"name": "AWS access key",   "pattern": r"\bAKIA[0-9A-Z]{16}\b"},
    {"name": "Bearer token",     "pattern": r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"},
    {"name": "JWT token",        "pattern": r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"},
    {"name": "SSH private key",  "pattern": r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"},
    {"name": ".env secret",      "pattern": r"(?i)\b(SECRET|TOKEN|KEY|PASS)\s*=\s*\S{8,}"},
    # NETWORK AND SYSTEM
    {"name": "IPv4 address",     "pattern": r"\b(?:\d{1,3}\.){3}\d{1,3}\b"},
    {"name": "IPv6 address",     "pattern": r"\b([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"},
    {"name": "MAC address",      "pattern": r"([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}"},
    # LOCATION
    {"name": "GPS coordinates",  "pattern": r"-?\d{1,3}\.\d{4,},\s*-?\d{1,3}\.\d{4,}"},
]


def _pii_scan(text: str, extra_patterns: list[dict] | None = None) -> list[str]:
    """Scan text for PII patterns; return list of matched pattern names (empty = clean)."""
    hits = []
    for entry in (_PII_PATTERNS + (extra_patterns or [])):
        try:
            if re.search(entry["pattern"], text):
                hits.append(entry["name"])
        except re.error:
            pass  # skip malformed user-supplied patterns
    return hits


def _write_audit(record: dict) -> None:
    """Append one JSON record to the audit log. Best-effort — never raises."""
    try:
        with open(KAGE_HOME / "audit.jsonl", "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


_session_approvals: dict[str, bool] = {}


def _disclosure_gate(rows: list, cfg: dict) -> tuple[list, list[dict]]:
    """Filter rows before cloud dispatch. Returns (allowed_rows, withheld_list).

    withheld_list entries: {"note_id": str, "reason": str, "pii_patterns": list[str]}
    Per-provider trust tiers are deferred (v2).
    """
    if not rows:
        return [], []

    note_ids = [row[0] for row in rows]
    local_only_projects: list[str] = cfg.get("local_only_projects", [])
    extra_pii: list[dict] = cfg.get("pii_patterns", [])

    conn = _connect()
    try:
        placeholders = ",".join("?" * len(note_ids))
        lo_map: dict[str, bool] = {
            r[0]: bool(r[1])
            for r in conn.execute(
                f"SELECT id, local_only FROM memories WHERE id IN ({placeholders})",
                note_ids,
            ).fetchall()
        }
    finally:
        conn.close()

    allowed: list = []
    withheld: list[dict] = []
    for row in rows:
        note_id: str = row[0]
        project: str | None = row[1]

        if lo_map.get(note_id, False):
            withheld.append({"note_id": note_id, "reason": "local_only:flag", "pii_patterns": []})
            continue

        if project and project in local_only_projects:
            withheld.append({
                "note_id": note_id,
                "reason": f"local_only:project:{project}",
                "pii_patterns": [],
            })
            continue

        path, char_start, char_end = row[3], row[6], row[7]
        if char_start is not None and char_end is not None:
            text = _read_section(path, char_start, char_end)
        else:
            try:
                text = _read_body(path)
            except OSError:
                text = ""

        pii_hits = _pii_scan(text, extra_pii)
        if pii_hits:
            withheld.append({"note_id": note_id, "reason": "pii_detected", "pii_patterns": pii_hits})
            continue

        allowed.append(row)

    return allowed, withheld


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
    cfg = _config()
    model = cfg.get("embed_model", "nomic-embed-text")
    url = cfg.get("ollama_url", "http://localhost:11434") + "/api/embed"
    try:
        out = _post_json(url, {"model": model, "input": text[:6000]}, timeout=10)
        return out["embeddings"][0]
    except urllib.error.HTTPError as e:
        if e.code == 400:
            raise OllamaUnavailable(f"embed input too long for model (HTTP 400)") from e
        raise OllamaUnavailable(str(e)) from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise OllamaUnavailable(str(e)) from e
    except (KeyError, IndexError) as e:
        raise OllamaUnavailable(f"unexpected embed response: {e}") from e


def _get_chroma():
    import chromadb
    cfg = _config()
    embed_model = cfg.get("embed_model", "nomic-embed-text")
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(
        name="chunks",
        metadata={"embed_model": embed_model, "schema_version": "4"},
    )
    stored_model = (collection.metadata or {}).get("embed_model")
    stored_schema = (collection.metadata or {}).get("schema_version")
    if stored_model is not None and stored_model != embed_model:
        typer.echo(
            f"  ⚠ embed model changed ({stored_model} → {embed_model}) — run: kage reindex --force",
            err=True,
        )
        raise OllamaUnavailable("embed model mismatch — run: kage reindex --force")
    if stored_schema is None or stored_schema != "4":
        typer.echo(
            f"  ⚠ schema version mismatch (v{stored_schema or 'unknown'} → v4) — run: kage reindex --force",
            err=True,
        )
        raise OllamaUnavailable("schema version mismatch — run: kage reindex --force")
    return collection


def _search_vec(query_vec: list[float], project: str | None, limit: int) -> list:
    collection = _get_chroma()
    if project:
        count = len(collection.get(where={"project": project}, include=[])["ids"])
    else:
        count = collection.count()
    if count == 0:
        return []
    n_results = min(limit, count)
    where = {"project": project} if project else None
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
    url = cfg.get("ollama_url", "http://localhost:11434") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=4) as resp:
            names = {m.get("name", "") for m in json.loads(resp.read()).get("models", [])}
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False, "Ollama not reachable"
    if model in names:
        return True, f"Ollama up, {model} ready"
    return False, f"Ollama up, but {model} not pulled"


@app.command()
def remember(
    text: str = typer.Argument(..., help="The note to remember."),
    project: str = typer.Option(None, "--project", "-p", help="Tag this memory to a project."),
    local: bool = typer.Option(False, "--local", help="Mark note local-only — never sent to cloud providers."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirm prompt (for scripts/tests)."),
) -> None:
    """Save a note to memory (markdown + index). Confirms before writing (the wall, #16)."""
    _require_init()

    # The wall (#16): show it and confirm BEFORE anything is written.
    typer.echo(f'\n  "{text}"')
    typer.echo(f"  project: {project or '(none)'}")
    if local:
        typer.echo("  local-only: yes (will not be sent to cloud)")
    if not yes and not typer.confirm("Save this to memory?", default=True):
        typer.echo("Discarded — nothing saved.")
        raise typer.Exit()

    mem_id = _save(text, project, local_only=local)
    suffix = "  [local-only]" if local else ""
    typer.echo(f"  ✓ saved   {_disp(KAGE_HOME / f'memory/{mem_id}.md')}   [{mem_id}]   (local){suffix}")


@app.command(name="import")
def import_(
    folder: Path = typer.Argument(..., help="Folder of .md/.txt files to bulk-add (recursive)."),
    project: str = typer.Option(None, "--project", "-p", help="Tag all imported notes (default: the folder name)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be imported; write nothing."),
) -> None:
    """Bulk-add the .md/.txt files in a folder (curated by which folder you point at)."""
    _require_init()

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
        _save(body, proj, source=str(p), embed=False)
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
) -> None:
    """List what kage has saved (most recent first) — so you can see before you search."""
    _require_init()

    sql = "SELECT id, project, created_at, content_path FROM memories"
    params: list = []
    if project:
        sql += " WHERE project = ?"
        params.append(project)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    conn = _connect()
    try:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute("SELECT count(*) FROM memories").fetchone()[0]
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
) -> None:
    """Search your memory (full-text) and surface the best matches."""
    _require_init()

    if not query.split():
        typer.echo("Empty query.", err=True)
        raise typer.Exit(code=1)
    rows = _search(query, project, limit)

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
) -> None:
    """Answer a question using your recalled notes — local model by default, --cloud to use a cloud provider."""
    _require_init()

    rows = _search(question, project, limit, any_terms=True)
    cfg = _config()

    # 3e disclosure gate — runs before context assembly, cloud path only
    provider_name: str = ""
    if cloud:
        provider_name = provider or cfg.get("cloud_provider", "claude")
        allowed_rows, withheld = _disclosure_gate(rows, cfg)
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

    system = (
        "You are kage, the user's personal memory assistant. "
        "Answer ONLY using the CONTEXT below — the user's own saved notes. "
        "If the answer is not in the context, say exactly: "
        "'I don't know — nothing in your notes covers this.' "
        "Do not use general knowledge. Be concise."
    )
    thinking = ""

    if cloud:
        default_pcfg = DEFAULT_PROVIDERS.get(provider_name, {})
        user_pcfg = cfg.get("providers", {}).get(provider_name, {})
        pcfg = {**default_pcfg, **user_pcfg}
        model = pcfg.get("model", provider_name)
        typer.echo(f"· asking {model} via {provider_name} ({len(rows)} note(s) as context)…\n")
        try:
            answer = _call_cloud(
                provider_name,
                system,
                f"CONTEXT:\n{context}\n\nQUESTION: {question}",
                cfg,
            )
        except CloudError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(code=1)
    else:
        model = cfg.get("model", "qwen3:14b")
        url = cfg.get("ollama_url", "http://localhost:11434") + "/api/generate"
        typer.echo(f"· asking {model} ({len(rows)} note(s) as context)…\n")
        prompt = f"{system}\n\nCONTEXT (the user's notes):\n{context}\n\nQUESTION: {question}"
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

    if not no_sources and sources:
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

    typer.echo("\nkage status")
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

    if all_ok:
        typer.echo("\n✓ kage looks healthy.\n")
    else:
        typer.echo("\n✗ some checks failed — see fixes above.\n")
        raise typer.Exit(code=1)


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
