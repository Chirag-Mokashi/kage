"""runtime — holds the live seam instances (Cycle 12).

Every module reads `runtime.<seam>` at CALL TIME, so swapping an attribute
(`runtime.cloud = RecordingCloud()`) reaches every caller in every module — the
property that dissolves the cli-monkeypatch coupling wall. Tests swap a seam via
`monkeypatch.setattr(runtime, "cloud", fake)`; production calls `reset()` at CLI
startup / MCP boot.

Seams: Slice 1 = CloudClient. Slice 2 adds Embedder + VectorIndex.
Slice 3 (Store/Config) get added here as they're built.
"""

from __future__ import annotations

from kage.cloud import CloudClient
from kage.embed import Embedder
from kage.vector import VectorIndex

cloud: CloudClient = None  # type: ignore[assignment]  # set by reset() (called on import below)
embed: Embedder = None     # type: ignore[assignment]
vector: VectorIndex = None  # type: ignore[assignment]


def reset() -> None:
    """(Re)build all seams from current env. Idempotent; safe to call at startup."""
    global cloud, embed, vector
    cloud = CloudClient()
    embed = Embedder()
    vector = VectorIndex()


reset()
