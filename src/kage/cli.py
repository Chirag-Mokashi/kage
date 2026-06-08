"""kage CLI — v0.1 thin slice.

One headless engine, surfaced as a CLI (blueprint #91). v0.1 commands are
one-shot. Everything kage stores is local: plain markdown is the source of
truth (#70), SQLite is a derived index (#71).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
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


app = typer.Typer(
    help="kage — your local context broker. Your notes, surfaced into your AI, on your machine.",
    add_completion=False,
    no_args_is_help=True,
)

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
    needs_embed  INTEGER NOT NULL DEFAULT 1
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


def _save(text: str, project: str | None, source: str | None = None, embed: bool = True) -> str:
    """Write a memory (markdown source-of-truth #70) + index it (#71). Returns its id."""
    mem_id = _new_id()
    created = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    rel_path = f"memory/{mem_id}.md"
    front = f"---\nid: {mem_id}\nproject: {project or ''}\ncreated_at: {created}\n"
    if source:
        front += f"source: {source}\n"
    (KAGE_HOME / rel_path).write_text(front + "---\n\n" + text.rstrip() + "\n")

    body = text.strip()
    chunks = _chunk_note(body)
    chunk_ids = [f"{mem_id}_c{i}" for i in range(len(chunks))]

    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO memories (id, content_path, project, created_at) VALUES (?, ?, ?, ?)",
            (mem_id, rel_path, project, created),
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
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


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
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirm prompt (for scripts/tests)."),
) -> None:
    """Save a note to memory (markdown + index). Confirms before writing (the wall, #16)."""
    _require_init()

    # The wall (#16): show it and confirm BEFORE anything is written.
    typer.echo(f'\n  "{text}"')
    typer.echo(f"  project: {project or '(none)'}")
    if not yes and not typer.confirm("Save this to memory?", default=True):
        typer.echo("Discarded — nothing saved.")
        raise typer.Exit()

    mem_id = _save(text, project)
    typer.echo(f"  ✓ saved   {_disp(KAGE_HOME / f'memory/{mem_id}.md')}   [{mem_id}]   (local)")


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
    cloud: bool = typer.Option(False, "--cloud", help="Use Claude (Anthropic) instead of the local model."),
    think: bool = typer.Option(False, "--think", help="Let the local model reason first (slower, deeper)."),
    limit: int = typer.Option(5, "--limit", "-n", help="How many notes to pull as context."),
    no_sources: bool = typer.Option(False, "--no-sources", help="Suppress the Sources block."),
) -> None:
    """Answer a question using your recalled notes — local model by default, --cloud for Claude."""
    _require_init()

    rows = _search(question, project, limit, any_terms=True)

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
    cfg = _config()
    thinking = ""

    if cloud:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            typer.echo("--cloud needs ANTHROPIC_API_KEY in your environment.", err=True)
            raise typer.Exit(code=1)
        model = cfg.get("cloud_model", "claude-sonnet-4-6")
        typer.echo(f"· asking {model} ({len(rows)} note(s) as context)…\n")
        try:
            out = _post_json(
                "https://api.anthropic.com/v1/messages",
                {
                    "model": model,
                    "max_tokens": 1024,
                    "system": system,
                    "messages": [{"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION: {question}"}],
                },
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            )
            answer = out["content"][0]["text"].strip()
        except (urllib.error.URLError, KeyError, IndexError, TimeoutError) as e:
            typer.echo(f"Cloud request failed: {e}", err=True)
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
def status() -> None:
    """Show what kage holds and where it lives."""
    _require_init()

    conn = _connect()
    try:
        total = conn.execute("SELECT count(*) FROM memories").fetchone()[0]
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

    typer.echo("\nkage status")
    typer.echo(f"  store    {_disp(KAGE_HOME)}   (config v{version})")
    typer.echo(f"  memory   {total} note(s) across {len(by_proj)} project(s)")
    for p, c in by_proj:
        typer.echo(f"             {c:>4}  {p}")
    typer.echo(f"  index    {_disp(DB_PATH)}   ({db_kb:.0f} KB)")
    _cfg = _config()
    typer.echo(f"  model    {_cfg.get('model', 'qwen3:14b')} local · {_cfg.get('cloud_model', 'claude-sonnet-4-6')} via --cloud")
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

    if all_ok:
        typer.echo("\n✓ kage looks healthy.\n")
    else:
        typer.echo("\n✗ some checks failed — see fixes above.\n")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
