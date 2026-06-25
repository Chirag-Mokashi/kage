from __future__ import annotations

import json
import os
import pathlib


class Config:
    def __init__(self, home: pathlib.Path):
        self.home = home
        self.db_path = home / "indexes" / "kage.db"
        self.chroma_dir = home / "chroma"
        self.state_path = home / "state.json"
        self.audit_path = home / "audit.jsonl"
        self._config_path = home / "config.json"

    @classmethod
    def from_env(cls) -> "Config":
        home = pathlib.Path(os.environ.get("KAGE_HOME") or pathlib.Path.home() / ".kage")
        return cls(home)

    @property
    def data(self) -> dict:
        try:
            return json.loads(self._config_path.read_text())
        except (OSError, ValueError):
            return {}

