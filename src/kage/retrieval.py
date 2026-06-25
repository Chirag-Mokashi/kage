from __future__ import annotations

from kage import notes as _notes

_RERANK_POOL = 25
_reranker_cache: list = [False, None]  # [loaded_flag, instance_or_None]


def _rrf_fuse(fts_rows: list, vec_rows: list, k: int = 60) -> list:
    """Merge FTS5 and vector candidates via Reciprocal Rank Fusion; caller slices to limit."""
    fts_n, vec_n = len(fts_rows), len(vec_rows)
    fts_rank = {row[0]: i for i, row in enumerate(fts_rows)}
    vec_rank = {row[0]: i for i, row in enumerate(vec_rows)}
    rows_by_id = {row[0]: row for row in (*vec_rows, *fts_rows)}  # fts last → fts row wins for shared IDs

    scores: dict[str, float] = {}
    for mem_id in rows_by_id:
        r_fts = fts_rank.get(mem_id, fts_n)   # missing → large rank penalty
        r_vec = vec_rank.get(mem_id, vec_n)
        scores[mem_id] = 1.0 / (k + r_fts) + 1.0 / (k + r_vec)

    return [rows_by_id[mid] for mid in sorted(scores, key=scores.__getitem__, reverse=True)]


def _get_reranker():
    """Lazy-load bge-reranker-v2-m3; return None if sentence-transformers not installed."""
    if _reranker_cache[0]:
        return _reranker_cache[1]
    _reranker_cache[0] = True
    try:
        from sentence_transformers import CrossEncoder
        _reranker_cache[1] = CrossEncoder("BAAI/bge-reranker-v2-m3")
    except Exception:
        _reranker_cache[1] = None
    return _reranker_cache[1]


def _rerank(rows: list, query: str, top_n: int) -> list:
    reranker = _get_reranker()
    if reranker is None or not rows:
        return rows[:top_n]
    texts: list[str] = []
    # ponytail: 1 file read per candidate (≤ _RERANK_POOL=25). Same file read once
    # per chunk even when multiple chunks from the same note are in candidates.
    # Upgrade: group by note_path, read once, slice all chunks.
    for row in rows:
        char_start, char_end = row[6], row[7]
        if char_start is not None and char_end is not None:
            try:
                body = _notes._read_body(row[3])
                text = body[char_start:char_end][:512]
            except OSError:
                text = row[4] or ""
        else:
            text = row[4] or ""
        texts.append(text)
    pairs = [(query, t) for t in texts]
    scores = reranker.predict(pairs).tolist()  # type: ignore[arg-type]
    ranked = sorted(zip(scores, rows), key=lambda x: x[0], reverse=True)
    return [r for _, r in ranked[:top_n]]
