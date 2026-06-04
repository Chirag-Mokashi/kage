"""kage CLI — v0.1 thin slice.

One headless engine, surfaced as a CLI (blueprint #91). v0.1 commands are
one-shot. Everything kage stores is local: plain markdown is the source of
truth (#70), SQLite is a derived index (#71).
"""

from __future__ import annotations

import datetime as _dt
import json
import secrets
import sqlite3
from pathlib import Path

import typer

app = typer.Typer(
    help="kage — your local context broker. Your notes, surfaced into your AI, on your machine.",
    add_completion=False,
    no_args_is_help=True,
)

# ── Layout ────────────────────────────────────────────────────────────────
KAGE_HOME = Path.home() / ".kage"
MEMORY_DIR = KAGE_HOME / "memory"          # 5A: markdown source of truth (#70)
INDEX_DIR = KAGE_HOME / "indexes"
DB_PATH = INDEX_DIR / "kage.db"            # 5B: derived SQLite index (#71)
CONFIG_PATH = KAGE_HOME / "config.json"

# v0.1 schema: memories + an FTS5 full-text index for `recall`.
# Partition filtering (the wall) lives in SQL per #99; v0.1 = single project tag.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id           TEXT PRIMARY KEY,
    content_path TEXT NOT NULL,
    project      TEXT,
    created_at   TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(id UNINDEXED, body);
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

    for d in (KAGE_HOME, MEMORY_DIR, INDEX_DIR):
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
                },
                indent=2,
            )
            + "\n"
        )
        created.append(CONFIG_PATH)

    db_is_new = not DB_PATH.exists()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
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
    return sqlite3.connect(DB_PATH)


def _new_id() -> str:
    """Sortable, unique id: 20260604T223719-a1b2c3."""
    return f"{_dt.datetime.now():%Y%m%dT%H%M%S}-{secrets.token_hex(3)}"


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

    mem_id = _new_id()
    created = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    rel_path = f"memory/{mem_id}.md"
    md_path = KAGE_HOME / rel_path

    # Markdown is the source of truth (#70): frontmatter + body.
    md_path.write_text(
        f"---\nid: {mem_id}\nproject: {project or ''}\ncreated_at: {created}\n---\n\n{text}\n"
    )

    # Derived index (#71): metadata row + FTS body.
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO memories (id, content_path, project, created_at) VALUES (?, ?, ?, ?)",
            (mem_id, rel_path, project, created),
        )
        conn.execute("INSERT INTO memory_fts (id, body) VALUES (?, ?)", (mem_id, text))
        conn.commit()
    finally:
        conn.close()

    typer.echo(f"  ✓ saved   {_disp(md_path)}   [{mem_id}]   (local)")


@app.command()
def recall(
    query: str = typer.Argument(..., help="What to search for."),
    project: str = typer.Option(None, "--project", "-p", help="Limit to a project (the partition wall)."),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results."),
) -> None:
    """Search your memory (full-text) and surface the best matches."""
    _require_init()

    terms = [t for t in query.split() if t]
    if not terms:
        typer.echo("Empty query.", err=True)
        raise typer.Exit(code=1)
    # Quote each term so FTS5 operators in user input can't break the query (AND across terms).
    match = " ".join('"' + t.replace('"', '""') + '"' for t in terms)

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
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    if not rows:
        typer.echo("No matches." + (f"  (project: {project})" if project else ""))
        raise typer.Exit()

    typer.echo(f"\n{len(rows)} match(es):\n")
    for mem_id, proj, created, path, snip in rows:
        typer.echo(f"  • [{proj or 'no-project'}] {snip}")
        typer.echo(f"    {created}   {_disp(KAGE_HOME / path)}   [{mem_id}]\n")


if __name__ == "__main__":
    app()
