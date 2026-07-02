from __future__ import annotations

import threading
from typing import Any

from kage.cloud import CloudClient


def _matches_where(metadata: dict, where: dict | None) -> bool:
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
    def __init__(self, embed_model: str = "fake") -> None:
        self.metadata: dict = {"embed_model": embed_model, "schema_version": "4"}
        self._store: dict[str, tuple[list[float], dict]] = {}
        self._lock = threading.Lock()

    def add(self, ids, embeddings, metadatas, documents=None, **kw: Any) -> None:
        with self._lock:
            for i, e, m in zip(ids, embeddings, metadatas):
                self._store[i] = (e, dict(m))

    def upsert(self, **kw: Any) -> None:
        self.add(**kw)

    def delete(self, ids: list[str] | None = None, **kw: Any) -> None:
        with self._lock:
            for i in (ids or []):
                self._store.pop(i, None)

    def get(self, where=None, include=None, **kw: Any) -> dict:
        with self._lock:
            matched = [k for k, (_, m) in self._store.items() if _matches_where(m, where)]
        return {"ids": matched}

    def query(self, query_embeddings, n_results=10, where=None, include=None, **kw: Any) -> dict:
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


class FakeEmbedder:
    def __init__(self, vec=None, raises=None, status_val=None):
        self._vec = vec if vec is not None else [0.1]
        self._raises = raises
        self._status = status_val

    def embed(self, text: str, cfg: dict) -> list[float]:
        if self._raises is not None:
            raise self._raises
        return list(self._vec)

    def status(self, cfg: dict, model: str) -> tuple[bool, str]:
        if self._status is not None:
            return self._status
        return True, "fake embedder up"


class FakeVectorIndex:
    def __init__(self, collection=None, raises=None):
        self._coll = collection
        self._raises = raises

    def collection(self, chroma_dir: Any, embed_model: str):
        if self._raises is not None:
            raise self._raises
        return self._coll


class RecordingCloud(CloudClient):
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete(self, _provider_name: str, system: str, messages: list[dict], _cfg: dict) -> str:
        self.calls.append({"system": system, "messages": list(messages)})
        return "FAKE_ANSWER"

    def all_text(self) -> str:
        parts: list[str] = []
        for call in self.calls:
            parts.append(call["system"])
            for msg in call["messages"]:
                parts.append(msg.get("content", ""))
        return "\n".join(parts)


class FakeCalendarBackend:
    def __init__(self):
        self.calls = []

    def create(self, *, title, start, end, calendar_name=None) -> str:
        self.calls.append({"title": title, "start": start, "end": end, "calendar_name": calendar_name})
        return f"fake-evt-{len(self.calls)}"
