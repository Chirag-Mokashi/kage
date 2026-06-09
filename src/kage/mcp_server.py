"""kage MCP server — exposes kage memory via stdio to Claude Code, Antigravity 2.0, and any MCP client."""

from __future__ import annotations

import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from kage import cli as _cli

mcp = FastMCP("kage")


@mcp.tool()
def kage_recall(query: str, project: str | None = None, limit: int = 5) -> list[dict]:
    """Search kage memory (project-partitioned, read-only).

    Returns ranked notes matching the query, filtered to the declared project partition.
    """
    rows = _cli._search(query, project, limit)
    return [
        {
            "id": row[0],
            "project": row[1] or "",
            "created": row[2],
            "excerpt": row[4] or "",
        }
        for row in rows
    ]


@mcp.tool()
def kage_remember(text: str, project: str | None = None) -> dict:
    """Save a note to kage memory.

    Write-gated: disabled by default. Enable by setting mcp_allow_writes: true
    in ~/.kage/config.json.
    """
    cfg = _cli._config()
    if not cfg.get("mcp_allow_writes", False):
        return {
            "saved": False,
            "id": None,
            "reason": "writes disabled — set mcp_allow_writes in config",
        }
    mem_id = _cli._save(text, project)
    return {"saved": True, "id": mem_id, "reason": "saved"}


@mcp.tool()
def kage_ask(question: str, provider: str | None = None, project: str | None = None) -> dict:
    """Answer a question using kage memory as context.

    Omit provider to use the local Ollama model. Specify a provider name
    (claude, openai, groq, etc.) to route through kage's cloud stack.
    """
    rows = _cli._search(question, project, 5, any_terms=True)
    context_parts: list[str] = []
    sources: list[str] = []
    for note_id, _proj, _created, path, _snip, section_title, char_start, char_end in rows:
        if char_start is not None and char_end is not None:
            text = _cli._read_section(path, char_start, char_end)
        else:
            try:
                text = _cli._read_body(path)
            except OSError:
                text = ""
        if text:
            context_parts.append(f"[{note_id}] {text}")
            sources.append(note_id)
    context = "\n\n".join(context_parts) or "(no relevant notes found)"
    system = (
        "You are kage, the user's personal memory assistant. "
        "Answer ONLY using the CONTEXT below — the user's own saved notes. "
        "If the answer is not in the context, say exactly: "
        "'I don't know — nothing in your notes covers this.' "
        "Do not use general knowledge. Be concise."
    )
    cfg = _cli._config()
    if provider:
        try:
            answer = _cli._call_cloud(
                provider,
                system,
                f"CONTEXT:\n{context}\n\nQUESTION: {question}",
                cfg,
            )
            used_provider = provider
        except _cli.CloudError as exc:
            return {"answer": str(exc), "sources": [], "provider": provider}
    else:
        model = cfg.get("model", "qwen3:14b")
        url = cfg.get("ollama_url", "http://localhost:11434") + "/api/generate"
        prompt = f"{system}\n\nCONTEXT (the user's notes):\n{context}\n\nQUESTION: {question}"
        try:
            out = _cli._post_json(url, {"model": model, "prompt": prompt, "stream": False})
            answer = out.get("response", "").strip()
            used_provider = f"local:{model}"
        except Exception as exc:
            return {
                "answer": f"Local model unavailable: {exc}",
                "sources": [],
                "provider": "local",
            }
    return {"answer": answer, "sources": sources, "provider": used_provider}


@mcp.tool()
def kage_status() -> dict:
    """Return a snapshot of the kage store: note count, project list, model, disk free."""
    conn = _cli._connect()
    try:
        total = conn.execute("SELECT count(*) FROM memories").fetchone()[0]
        projects = [
            row[0]
            for row in conn.execute(
                "SELECT COALESCE(project, '(no project)') FROM memories GROUP BY project"
            ).fetchall()
        ]
    finally:
        conn.close()
    cfg = _cli._config()
    model = cfg.get("model", "qwen3:14b")
    disk_target = _cli.KAGE_HOME if _cli.KAGE_HOME.exists() else Path.home()
    free_gb = shutil.disk_usage(disk_target).free / 1e9
    return {
        "memory_count": total,
        "projects": projects,
        "model": model,
        "disk_free": f"{free_gb:.1f} GB",
    }
