"""runtime — holds the live seam instances (Cycle 12).

Every module reads `runtime.<seam>` at CALL TIME, so swapping an attribute
(`runtime.cloud = RecordingCloud()`) reaches every caller in every module — the
property that dissolves the cli-monkeypatch coupling wall. Tests swap a seam via
`monkeypatch.setattr(runtime, "cloud", fake)`; production calls `reset()` at CLI
startup / MCP boot.

Seams land slice by slice: Slice 1 = cloud. Embedder/VectorIndex (Slice 2),
Store/Config (Slice 3) get added here as they're built.
"""

from __future__ import annotations

from kage.cloud import CloudClient

cloud: CloudClient = None  # type: ignore[assignment]  # set by reset() (called on import below)


def reset() -> None:
    """(Re)build all seams from current env. Idempotent; safe to call at startup."""
    global cloud
    cloud = CloudClient()


reset()
