from __future__ import annotations

import json
import urllib.error
import urllib.request

from kage.http import _post_json


class OllamaUnavailable(Exception):
    """Raised when Ollama is unreachable or times out."""


class Embedder:
    def embed(self, text: str, cfg: dict) -> list[float]:
        """Embed text via Ollama /api/embed; raises OllamaUnavailable on failure."""
        model = cfg.get("embed_model", "nomic-embed-text")
        url = cfg.get("ollama_url", "http://localhost:11434") + "/api/embed"
        try:
            # ponytail: 6000-char pre-clip (≈1500 tok) silently truncates long notes.
            # Ceiling: notes > 6000 chars get partial embeddings with no warning.
            # Upgrade: read actual ctx limit from /api/tags, or chunk + average-pool.
            out = _post_json(url, {"model": model, "input": text[:6000]}, timeout=10)
            return out["embeddings"][0]
        except urllib.error.HTTPError as e:
            if e.code == 400:
                raise OllamaUnavailable(f"embed input too long for model (HTTP 400)") from e
            raise OllamaUnavailable(str(e)) from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise OllamaUnavailable(str(e)) from e
        except (KeyError, IndexError) as e:
            raise OllamaUnavailable(f"unexpected embed response: {e}") from e

    def status(self, cfg: dict, model: str) -> tuple[bool, str]:
        """Is Ollama reachable and the model pulled? (advisory — only `ask` needs it)."""
        url = cfg.get("ollama_url", "http://localhost:11434") + "/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=4) as resp:
                names = {m.get("name", "") for m in json.loads(resp.read()).get("models", [])}
        except (urllib.error.URLError, TimeoutError, ValueError):
            return False, "Ollama not reachable"
        if model in names:
            return True, f"Ollama up, {model} ready"
        return False, f"Ollama up, but {model} not pulled"
