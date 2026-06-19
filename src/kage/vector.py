from __future__ import annotations

import typer

from kage.embed import OllamaUnavailable


class VectorIndex:
    def collection(self, chroma_dir, embed_model: str):
        import chromadb
        client = chromadb.PersistentClient(path=str(chroma_dir))
        collection = client.get_or_create_collection(
            name="chunks",
            metadata={"embed_model": embed_model, "schema_version": "4"},
        )
        stored_model = (collection.metadata or {}).get("embed_model")
        stored_schema = (collection.metadata or {}).get("schema_version")
        if stored_model is not None and stored_model != embed_model:
            typer.echo(
                f"  ⚠ embed model changed ({stored_model} → {embed_model}) — run: kage reindex --force",
                err=True,
            )
            raise OllamaUnavailable("embed model mismatch — run: kage reindex --force")
        if stored_schema is None or stored_schema != "4":
            typer.echo(
                f"  ⚠ schema version mismatch (v{stored_schema or 'unknown'} → v4) — run: kage reindex --force",
                err=True,
            )
            raise OllamaUnavailable("schema version mismatch — run: kage reindex --force")
        return collection
