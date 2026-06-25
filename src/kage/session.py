from __future__ import annotations
import datetime as _dt
import json
import re
import secrets
import uuid
from kage import privacy as _privacy
from kage import runtime

_LEADING_PRONOUNS = {
    'it', 'its', 'they', 'them', 'their', 'this', 'that', 'these', 'those',
    'he', 'she', 'we', 'what', 'which', 'how', 'why', 'when', 'where', 'who',
}


def _session_create(identity: str, project: str | None, destination: str) -> str:
    session_id = str(uuid.uuid4())
    created_at = _dt.datetime.now().astimezone().isoformat(timespec='seconds')
    conn = None
    try:
        conn = runtime.store.connect()
        conn.execute(
            'INSERT INTO sessions(session_id, created_at, identity, project, destination) VALUES(?,?,?,?,?)',
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
        conn = runtime.store.connect()
        row = conn.execute(
            'SELECT session_id, created_at, identity, project, destination, deleted FROM sessions WHERE session_id=? AND deleted=0',
            (session_id,),
        ).fetchone()
        if not row:
            return None
        return dict(zip(['session_id', 'created_at', 'identity', 'project', 'destination', 'deleted'], row))
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
        conn = runtime.store.connect()
        next_idx = conn.execute(
            'SELECT COALESCE(MAX(idx), -1) FROM session_turns WHERE session_id=?',
            (session_id,),
        ).fetchone()[0] + 1
        ts = _dt.datetime.now().astimezone().isoformat(timespec='seconds')
        conn.execute(
            'INSERT INTO session_turns(session_id, idx, parent_idx, role, content, note_ids, destination, model, reason, tokens, ts) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
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
        conn = runtime.store.connect()
        rows = conn.execute(
            'SELECT idx, role, content, note_ids, destination, model, reason, tokens, ts FROM session_turns WHERE session_id=? AND deleted=0 ORDER BY idx ASC',
            (session_id,),
        ).fetchall()
        kept = []
        est_total = 0
        for row in reversed(rows):
            # ponytail: 4 chars/token approximation; real ratio is ~3.5–5 by content.
            # Ceiling: budget misfires on code-heavy or non-Latin sessions.
            # Upgrade: tiktoken for precise count.
            est = len(row[2]) // 4
            if est_total + est > token_budget:
                break
            est_total += est
            kept.append(row)
        kept.reverse()
        return [
            {
                'idx': r[0], 'role': r[1], 'content': r[2],
                'note_ids': json.loads(r[3]), 'destination': r[4],
                'model': r[5], 'reason': r[6], 'tokens': r[7], 'ts': r[8],
            }
            for r in kept
        ]
    finally:
        if conn:
            conn.close()


def _condense_query(history: list[dict], question: str) -> str:
    words = question.split()
    if len(words) > 10:
        return question
    first_word = re.sub(r'[^a-z]', '', words[0].lower())
    if first_word not in _LEADING_PRONOUNS:
        return question
    has_proper_noun = any(
        re.match(r'[A-Z][a-z]+', word) and word != words[0] and len(word) > 1
        for word in words
    )
    if has_proper_noun:
        return question
    last_assistant = next((t for t in reversed(history) if t['role'] == 'assistant'), None)
    if last_assistant is None:
        return question
    context_snippet = last_assistant['content'][:120].rstrip()
    return f'{context_snippet} — {question}'


def _new_id() -> str:
    return f'{_dt.datetime.now():%Y%m%dT%H%M%S}-{secrets.token_hex(3)}'


def _session_switch(
    session_id: str,
    new_destination: str,
    cfg: dict,
    identity: str,
    project: str | None,
) -> tuple[str, list[dict], list[dict]]:
    sess = _session_load(session_id)
    if sess is None:
        raise ValueError(f'Session {session_id!r} not found')
    conn = runtime.store.connect()
    try:
        conn.execute('UPDATE sessions SET destination=? WHERE session_id=?', (new_destination, session_id))
        conn.commit()
    finally:
        conn.close()
    turns = _session_turns(session_id, token_budget=10_000_000)
    safe_turns, withheld = _privacy._gate_conversation(turns, cfg, identity, project)
    return (new_destination, safe_turns, withheld)
