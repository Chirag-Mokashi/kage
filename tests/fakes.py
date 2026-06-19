from __future__ import annotations

import threading
from typing import Any

from kage.embed import OllamaUnavailable


class FakeEmbedder:
    """Returns a fixed vector or raises OllamaUnavailable. Stateless → thread-safe."""

    def __init__(self, vec: list[float] | None = None, raise_err: bool = False) -> None:
        self._vec = vec or [0.1, 0.2, 0.3]
        self._raise = raise_err

    def embed(self, text: str, cfg: dict) -> list[float]:
        if self._raise:
            raise OllamaUnavailable("fake: down")
        return list(self._vec)

    def status(self, cfg: dict, model: str) -> tuple[bool, str]:
        if self._raise:
            return (False, "fake: down")
        return (True, "fake: ready")


def _matches_where(metadata: dict, where: dict | None) -> bool:
    """Evaluate a minimal Chroma where-clause against a metadata dict."""
    if not where:
        return True
    for field, condition in where.items():
        val = metadata.get(field)
        if isinstance(condition, dict):
            if "$in" in condition and val not in condition["$in"]:
                return False
            if "$eq" in condition and val != condition["$eq"]:
                return False
        else:
            if val != condition:
                return False
    return True


class _FakeChromaCollection:
    """In-memory chromadb-like collection. Thread-safe."""

    def __init__(self, embed_model: str = "fake") -> None:
        self.metadata: dict = {"embed_model": embed_model, "schema_version": "4"}
        # id -> (embedding, metadata_dict)
        self._store: dict[str, tuple[list[float], dict]] = {}
        self._lock = threading.Lock()

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        documents: list[str] | None = None,
        **kw: Any,
    ) -> None:
        with self._lock:
            for i, e, m in zip(ids, embeddings, metadatas):
                self._store[i] = (e, dict(m))

    def upsert(self, **kw: Any) -> None:
        self.add(**kw)

    def delete(self, ids: list[str] | None = None, **kw: Any) -> None:
        with self._lock:
            for i in (ids or []):
                self._store.pop(i, None)

    def get(
        self,
        where: dict | None = None,
        include: list[str] | None = None,
        **kw: Any,
    ) -> dict:
        with self._lock:
            matched = [k for k, (_, m) in self._store.items() if _matches_where(m, where)]
        return {"ids": matched}

    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int = 10,
        where: dict | None = None,
        include: list[str] | None = None,
        **kw: Any,
    ) -> dict:
        with self._lock:
            items = list(self._store.items())

        if not items or not query_embeddings:
            return {"ids": [[]], "metadatas": [[]], "distances": [[]]}

        q = query_embeddings[0]

        def dot(v: list[float]) -> float:
            return sum(a * b for a, b in zip(q, v))

        ranked = sorted(items, key=lambda x: dot(x[1][0]), reverse=True)
        if where:
            ranked = [(k, v) for k, v in ranked if _matches_where(v[1], where)]
        ranked = ranked[:n_results]

        return {
            "ids": [[k for k, _ in ranked]],
            "metadatas": [[v[1] for _, v in ranked]],
            "distances": [[0.0] * len(ranked)],
        }

    def count(self) -> int:
        with self._lock:
            return len(self._store)


class FakeVectorIndex:
    """Wraps _FakeChromaCollection. Thread-safe (collection is)."""

    def __init__(self, embed_model: str = "fake") -> None:
        self._coll = _FakeChromaCollection(embed_model)

    def collection(self, chroma_dir: Any, embed_model: str) -> _FakeChromaCollection:
        return self._coll


class RecordingCloud:
    """Records every complete() call payload for egress golden tests."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete(
        self,
        provider_name: str,
        system: str,
        messages: list[dict],
        cfg: dict,
    ) -> str:
        self.calls.append(
            {"provider": provider_name, "system": system, "messages": messages, "cfg": cfg}
        )
        return "fake answer"
