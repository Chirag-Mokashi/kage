from __future__ import annotations

import json

from kage import notes as _notes
from kage import runtime
from kage.pii import _pii_scan

_ALWAYS_LOCAL_PROJECTS: frozenset[str] = frozenset({"kage-corrections"})


def _write_audit(record: dict) -> None:
    """Append one JSON record to the audit log. Best-effort — never raises."""
    try:
        with open(runtime.config.audit_path, "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _disclosure_gate(rows: list, cfg: dict, identity: str = "personal", project: str | None = None) -> tuple[list, list[dict], dict[str, list[str]]]:
    """Filter rows before cloud dispatch. Returns (allowed_rows, withheld_list, pii_map).

    pii_map: {note_id: [pii_pattern_names]} for notes that passed WITH PII present.
    PII no longer causes withholding (Cycle 21) — substitution happens at dispatch.
    """
    if not rows:
        return [], [], {}

    note_ids = [row[0] for row in rows]
    local_only_projects: list[str] = cfg.get("local_only_projects", [])
    extra_pii: list[dict] = cfg.get("pii_patterns", [])

    identity_allowed = runtime.store.allowed_note_ids(identity, project)

    conn = runtime.store.connect()
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
    pii_map: dict[str, list[str]] = {}
    for row in rows:
        note_id: str = row[0]
        project_val: str | None = row[1]

        if note_id not in identity_allowed:
            withheld.append({"note_id": note_id, "reason": f"identity_wall:{identity}", "pii_patterns": []})
            continue

        if lo_map.get(note_id, False):
            withheld.append({"note_id": note_id, "reason": "local_only:flag", "pii_patterns": []})
            continue

        if project_val and project_val in local_only_projects:
            withheld.append({
                "note_id": note_id,
                "reason": f"local_only:project:{project_val}",
                "pii_patterns": [],
            })
            continue

        if project_val and project_val in _ALWAYS_LOCAL_PROJECTS:
            withheld.append({
                "note_id": note_id,
                "reason": f"local_only:always_local:{project_val}",
                "pii_patterns": [],
            })
            continue

        path, char_start, char_end = row[3], row[6], row[7]
        if char_start is not None and char_end is not None:
            text = _notes._read_section(path, char_start, char_end)
        else:
            try:
                text = _notes._read_body(path)
            except OSError:
                text = ""

        pii_hits = _pii_scan(text, extra_pii)
        if pii_hits:
            # ponytail: PII no longer withholds — substitution happens at dispatch (Cycle 21).
            # local_only and identity_wall remain hard blocks.
            pii_map[note_id] = pii_hits
        allowed.append(row)

    return allowed, withheld, pii_map


def _gate_conversation(
    turns: list[dict],
    cfg: dict,  # noqa: ARG001 — kept for call-site compatibility; pii_patterns removed in Cycle 23 S1
    identity: str,
    project: str | None,
) -> tuple[list[dict], list[dict]]:
    """Filter session turns before cloud dispatch."""
    if not turns:
        return [], []
    identity_allowed = runtime.store.allowed_note_ids(identity, project)
    all_note_ids = list({nid for t in turns for nid in t["note_ids"]})
    meta_map: dict[str, tuple[bool, str | None]] = {}
    if all_note_ids:
        conn = runtime.store.connect()
        try:
            placeholders = ",".join("?" * len(all_note_ids))
            meta_map = {
                r[0]: (bool(r[1]), r[2])
                for r in conn.execute(
                    f"SELECT id, local_only, project FROM memories WHERE id IN ({placeholders})",
                    all_note_ids,
                ).fetchall()
            }
        finally:
            conn.close()
    safe: list[dict] = []
    withheld: list[dict] = []
    for turn in turns:
        blocked = False
        for nid in turn["note_ids"]:
            if nid not in identity_allowed:
                withheld.append({"turn_idx": turn["idx"], "reason": f"provenance:identity_wall:{identity}", "pii_patterns": []})
                blocked = True
                break
            if meta_map.get(nid, (False, None))[0]:
                withheld.append({"turn_idx": turn["idx"], "reason": f"provenance:local_only:{nid}", "pii_patterns": []})
                blocked = True
                break
            proj = meta_map.get(nid, (False, None))[1]
            if proj and proj in _ALWAYS_LOCAL_PROJECTS:
                withheld.append({"turn_idx": turn["idx"], "reason": f"provenance:always_local:{proj}", "pii_patterns": []})
                blocked = True
                break
        if blocked:
            continue
        safe.append(turn)
    return safe, withheld
