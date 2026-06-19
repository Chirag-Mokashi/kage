"""Shared low-level HTTP helper (Cycle 12 Slice 1).

One urllib POST helper used by the cloud, embed, and Ollama paths. Kept as a
single function so the User-Agent fix lives in exactly one place (not duplicated
into each seam). cli re-exports `_post_json` as a call-time forwarder so existing
`cli._post_json` test patches keep working during the transition.
"""

from __future__ import annotations

import json
import urllib.request


def _post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "kage/0.5", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())
