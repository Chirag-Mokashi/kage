from __future__ import annotations

import json

from kage import notes as _notes
from kage import runtime
from kage.pii import _pii_scan


def _write_audit(record: dict) -> None:
    """Append one JSON record to the audit log. Best-effort — never raises."""
    try:
        with open(runtime.config.audit_path, "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _disclosure_gate(rows: list, cfg: dict, identity: str = "personal", project: str | None = None) -> tuple[list, list[dict]]:
    """Filter rows before cloud dispatch. Returns (allowed_rows, withheld_list)."""
    if not rows:
        return [], []

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
            withheld.append({"note_id": note_id, "reason": "pii_detected", "pii_patterns": pii_hits})
            continue

        allowed.append(row)

    return allowed, withheld


def _gate_conversation(
    turns: list[dict],
    cfg: dict,
    identity: str,
    project: str | None,
) -> tuple[list[dict], list[dict]]:
    """Filter session turns before cloud dispatch."""
    if not turns:
        return [], []
    extra_pii = cfg.get("pii_patterns", [])
    identity_allowed = runtime.store.allowed_note_ids(identity, project)
    all_note_ids = list({nid for t in turns for nid in t["note_ids"]})
    lo_map: dict[str, bool] = {}
    if all_note_ids:
        conn = runtime.store.connect()
        try:
            placeholders = ",".join("?" * len(all_note_ids))
            lo_map = {
                r[0]: bool(r[1])
                for r in conn.execute(
                    f"SELECT id, local_only FROM memories WHERE id IN ({placeholders})",
                    all_note_ids,
                ).fetchall()
            }
        finally:
            conn.close()
    safe: list[dict] = []
    withheld: list[dict] = []
    for turn in turns:
        pii_hits = _pii_scan(turn["content"], extra_pii)
        if pii_hits:
            withheld.append({"turn_idx": turn["idx"], "reason": "pii_in_content", "pii_patterns": pii_hits})
            continue
        blocked = False
        for nid in turn["note_ids"]:
            if nid not in identity_allowed:
                withheld.append({"turn_idx": turn["idx"], "reason": f"provenance:identity_wall:{identity}", "pii_patterns": []})
                blocked = True
                break
            if lo_map.get(nid, False):
                withheld.append({"turn_idx": turn["idx"], "reason": f"provenance:local_only:{nid}", "pii_patterns": []})
                blocked = True
                break
        if blocked:
            continue
        safe.append(turn)
    return safe, withheld
