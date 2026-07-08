"""kage MCP server — exposes kage memory via stdio to Claude Code, Antigravity 2.0, and any MCP client."""

from __future__ import annotations

import datetime as _dt
import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from kage import cli as _cli

mcp = FastMCP("kage")


@mcp.tool()
def kage_recall(query: str, project: str | None = None, limit: int = 5, identity: str | None = None) -> list[dict]:
    """Search kage memory (identity + project partitioned, read-only).

    Returns ranked notes matching the query, filtered to the declared identity and project partition.
    """
    identity, project, source = _cli._resolve_context(identity, project)
    rows = _cli._search(query, project, limit, identity=identity)
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
def kage_remember(text: str, project: str | None = None, local: bool = False, identity: str | None = None) -> dict:
    """Save a note to kage memory.

    Write-gated: disabled by default. Enable by setting mcp_allow_writes: true
    in ~/.kage/config.json.
    Read-only identities cannot write. Set local=true to mark the note local-only (never sent to cloud providers).
    """
    from kage.identity import ReadOnlyIdentityError
    cfg = _cli._config()
    identity, project, source = _cli._resolve_context(identity, project)
    if not cfg.get("mcp_allow_writes", False):
        return {
            "saved": False,
            "id": None,
            "reason": "writes disabled — set mcp_allow_writes in config",
        }
    try:
        mem_id = _cli._save(text, project, local_only=local, identities=[identity])
    except ReadOnlyIdentityError:
        return {
            "saved": False,
            "id": None,
            "reason": "read-only identity cannot write"
        }
    return {"saved": True, "id": mem_id, "reason": "saved", "local_only": local}


@mcp.tool()
async def kage_ask(question: str, provider: str | None = None, project: str | None = None, identity: str | None = None, session_id: str | None = None) -> dict:
    """Answer a question using kage memory as context.

    Omit provider to use the local Ollama model. Specify a provider name
    (claude, openai, groq, etc.) to route through kage's cloud stack.
    The 3e disclosure gate runs automatically — local-only notes and PII are
    withheld from cloud dispatch. Counts are reported in the response.

    Pass session_id (from _session_create) to enable stateful multi-turn
    conversation. The session's pinned identity, project, and destination are
    used; question and answer are appended to session history. Omit session_id
    for stateless single-shot mode (existing behavior).
    """
    identity, project, source = _cli._resolve_context(identity, project)
    if session_id is not None:
        sess = _cli._session_load(session_id)
        if sess is None:
            return {"error": f"Session {session_id!r} not found", "answer": None, "session_id": session_id}
        s_identity = sess["identity"]
        s_project = sess["project"]
        s_destination = sess["destination"]
        cfg = _cli._config()
        history = _cli._session_turns(session_id)
        condensed = _cli._condense_query(history, question)
        rows = _cli._search(condensed, s_project, 5, any_terms=True, identity=s_identity)
        withheld_count = 0
        if s_destination != "ollama":
            all_turns = _cli._session_turns(session_id, token_budget=10_000_000)
            safe_turns, withheld_turns = _cli._gate_conversation(all_turns, cfg, s_identity, s_project)
            withheld_count = len(withheld_turns)
            rows, row_withheld, _ = _cli._disclosure_gate(rows, cfg, identity=s_identity, project=s_project)
            withheld_count += len(row_withheld)
            history_for_answer = safe_turns
        else:
            history_for_answer = history
        context_parts: list[str] = []
        source_ids: list[str] = []
        note_ids_this_turn: list[str] = []
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
                source_ids.append(note_id)
                note_ids_this_turn.append(note_id)
        context = "\n\n".join(context_parts)
        _mcp_sess_map: dict[str, str] = {}
        if s_destination != "ollama":
            from kage import gate
            condensed, _mcp_sess_map = gate.two_pass_gate(condensed, source="mcp", existing_mapping=_mcp_sess_map)
            _masked_hist: list[dict] = []
            for _t in history_for_answer:
                _mc, _mcp_sess_map = gate.two_pass_gate(_t["content"], source="mcp", existing_mapping=_mcp_sess_map)
                _masked_hist.append({**_t, "content": _mc})
            history_for_answer = _masked_hist
            context, _mcp_sess_map = gate.two_pass_gate(context, source="mcp", existing_mapping=_mcp_sess_map)
        try:
            answer = next(iter(_cli._answer(condensed, history_for_answer, context, s_destination, cfg)))
        except (_cli.OllamaUnavailable, _cli.CloudError) as exc:
            return {"error": str(exc), "answer": None, "session_id": session_id}
        if s_destination != "ollama" and _mcp_sess_map and answer:
            from kage.redact import restore as _rst
            answer = _rst(answer, _mcp_sess_map)
        if s_destination == "ollama":
            model_name = cfg.get("ollama_model", "qwen3:14b")
            used_provider = f"local:{model_name}"
        else:
            default_pcfg = _cli.DEFAULT_PROVIDERS.get(s_destination, {})
            user_pcfg = cfg.get("providers", {}).get(s_destination, {})
            pcfg = {**default_pcfg, **user_pcfg}
            model_name = pcfg.get("model", s_destination)
            used_provider = s_destination
        est_tokens = len(answer) // 4
        _cli._session_append(session_id, "user", question, note_ids_this_turn, s_destination, model_name, None, None)
        _cli._session_append(session_id, "assistant", answer, [], s_destination, model_name, None, est_tokens)
        return {
            "answer": answer,
            "sources": source_ids,
            "provider": used_provider,
            "withheld_count": withheld_count,
            "session_id": session_id,
        }

    rows = _cli._search(question, project, 5, any_terms=True, identity=identity)
    cfg = _cli._config()

    # 3e disclosure gate — MCP has no interactive prompt; auto-filter and report
    withheld_count = 0
    withheld_reasons: list[str] = []
    if provider:
        allowed_rows, withheld, _pii_map = _cli._disclosure_gate(rows, cfg, identity=identity, project=project)
        withheld_count = len(withheld)
        withheld_reasons = [w["reason"] for w in withheld]
        pii_hits = [p for ps in _pii_map.values() for p in ps]
        all_blocked = bool(withheld) and not allowed_rows
        outcome = "blocked_all_local_mcp" if all_blocked else "dispatched_mcp"
        _cli._write_audit({
            "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "provider": provider, "project": project,
            "identity_source": "mcp-client-asserted",
            "notes_retrieved": len(rows), "notes_withheld": withheld_count,
            "withheld_reasons": withheld_reasons, "pii_detected": pii_hits,
            "user_approved": None, "outcome": outcome,
        })
        if all_blocked:
            provider = None  # fall back to local Ollama; rows unchanged (local context)
        else:
            rows = allowed_rows  # only permitted context goes to cloud

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

    # Arm calls (Cycle 11) — async, safe because kage_ask is async def
    arm_names = _cli._detect_arms(question, identity)
    arm_results: list[str] = []
    for arm_name in arm_names:
        result = await _cli._call_arm(arm_name, question, identity)
        if result:
            arm_results.append(f"[{arm_name}]\n{result}")
    arm_context = "\n\n".join(arm_results) if arm_results else ""

    _mcp_sub_map: dict[str, str] = {}
    if provider:
        from kage import gate
        context, _mcp_sub_map = gate.two_pass_gate(context, source="mcp", existing_mapping=_mcp_sub_map)
        if arm_context:
            arm_context, _mcp_sub_map = gate.two_pass_gate(arm_context, source="mcp", existing_mapping=_mcp_sub_map)
        question, _mcp_sub_map = gate.two_pass_gate(question, source="mcp", existing_mapping=_mcp_sub_map)

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

    if provider:
        user_msg = question if arm_context else f"CONTEXT:\n{effective_context}\n\nQUESTION: {question}"
        try:
            answer = _cli._call_cloud(
                provider,
                system,
                user_msg,
                cfg,
            )
            if _mcp_sub_map:
                from kage.redact import restore as _rst
                answer = _rst(answer, _mcp_sub_map)
            used_provider = provider
        except _cli.CloudError as exc:
            return {"answer": str(exc), "sources": [], "provider": provider,
                    "withheld_count": withheld_count}
    else:
        model = cfg.get("model", "qwen3:14b")
        url = cfg.get("ollama_url", "http://localhost:11434") + "/api/generate"
        if effective_context:
            prompt = f"{system}\n\nCONTEXT (the user's notes):\n{effective_context}\n\nQUESTION: {question}"
        else:
            prompt = f"{system}\n\nQUESTION: {question}"
        try:
            out = _cli._post_json(url, {"model": model, "prompt": prompt, "stream": False, "options": {"num_ctx": cfg.get("ollama_num_ctx", 16384)}})
            _num_ctx = cfg.get("ollama_num_ctx", 16384)
            _peval = out.get("prompt_eval_count")
            if _peval is not None and _peval >= _num_ctx - 8:
                _cli._write_audit({
                    "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "type": "context_window_filled",
                    "prompt_eval_count": _peval, "num_ctx": _num_ctx,
                })
            answer = out.get("response", "").strip()
            used_provider = f"local:{model}"
        except Exception as exc:
            return {
                "answer": f"Local model unavailable: {exc}",
                "sources": [], "provider": "local", "withheld_count": withheld_count,
            }
    return {
        "answer": answer,
        "sources": sources,
        "provider": used_provider,
        "withheld_count": withheld_count,
        "withheld_reasons": withheld_reasons,
    }


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
