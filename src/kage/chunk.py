"""Note chunking — split a markdown body into retrieval chunks with char offsets.

Pure text logic: no I/O, no config, no DB. Header sections are kept whole when
small; oversized sections split recursively (paragraph -> sentence -> window).
Extracted from cli.py (audit WI-4); cli re-exports these names.
"""

from __future__ import annotations

import re

_CHUNK_TARGET  = 1500
_CHUNK_MIN     = 100
_CHUNK_OVERLAP = 150


def _split_on_headers(body: str) -> list[dict]:
    """Split body on ## / ### headers; return sections with char offsets. No size filtering."""
    chunks = []
    lines = body.splitlines()
    prev_header_pos = -1

    for i, line in enumerate(lines):
        if line.startswith("## ") or line.startswith("### "):
            if prev_header_pos != -1:
                char_start = sum(len(l) + 1 for l in lines[: prev_header_pos + 1])
                char_end = min(sum(len(l) + 1 for l in lines[:i]), len(body))
                if char_end - char_start >= 100:
                    chunks.append({
                        "title": lines[prev_header_pos].lstrip("#").strip(),
                        "char_start": char_start,
                        "char_end": char_end,
                    })
            prev_header_pos = i

    if prev_header_pos != -1:
        char_start = sum(len(l) + 1 for l in lines[: prev_header_pos + 1])
        char_end = len(body)
        if char_end - char_start >= 100:
            chunks.append({
                "title": lines[prev_header_pos].lstrip("#").strip(),
                "char_start": char_start,
                "char_end": char_end,
            })

    if not chunks:
        return [{"title": "", "char_start": 0, "char_end": len(body)}]

    return chunks


def _hard_windows(text: str, base: int, title: str) -> list[dict]:
    """Slice text into fixed-size windows of TARGET chars with OVERLAP."""
    result = []
    pos = 0
    while pos < len(text):
        end = min(pos + _CHUNK_TARGET, len(text))
        if end - pos >= _CHUNK_MIN:
            result.append({"title": title, "char_start": base + pos, "char_end": base + end})
        pos += _CHUNK_TARGET - _CHUNK_OVERLAP
    if not result:
        result.append({"title": title, "char_start": base, "char_end": base + len(text)})
    return result


def _window_by_pieces(pieces: list[str], text: str, base: int, title: str) -> list[dict]:
    """Group pieces (splits of text) into TARGET-sized windows with OVERLAP."""
    positions: list[int] = []
    cursor = 0
    for piece in pieces:
        pos = text.find(piece, cursor)
        if pos == -1:
            pos = cursor
        positions.append(pos)
        cursor = pos + len(piece)

    result: list[dict] = []
    i = 0
    while i < len(pieces):
        w_start = positions[i]
        w_end = positions[i] + len(pieces[i])
        j = i + 1
        while j < len(pieces):
            candidate_end = positions[j] + len(pieces[j])
            if candidate_end - w_start > _CHUNK_TARGET:
                break
            w_end = candidate_end
            j += 1
        if w_end - w_start >= _CHUNK_MIN:
            result.append({"title": title, "char_start": base + w_start, "char_end": base + w_end})
        if j >= len(pieces):
            break
        overlap_target = w_end - _CHUNK_OVERLAP
        next_i = j
        for k in range(j - 1, i, -1):
            if positions[k] <= overlap_target:
                next_i = k + 1
                break
        i = max(next_i, i + 1)
    return result


def _chunk_note(body: str) -> list[dict]:
    """Split a note body into retrieval chunks with char offsets into body.

    Header sections kept as-is when <= TARGET. Oversized sections (and
    headerless notes > TARGET) split recursively: paragraph -> sentence -> window.
    """
    # ponytail: the recursive split (paragraph -> sentence -> hard window) only
    # fires for sections > _CHUNK_TARGET (1500 chars). Most notes take the fast
    # path below; this depth is banked against corpus growth, not load-bearing today.
    sections = _split_on_headers(body)
    result = []
    for section in sections:
        char_start = section["char_start"]
        char_end = section["char_end"]
        text = body[char_start:char_end]
        if len(text) < _CHUNK_MIN:
            continue
        if len(text) <= _CHUNK_TARGET:
            result.append(section)
            continue
        pieces = [p for p in re.split(r'\n\n+', text) if p]
        if len(pieces) > 1:
            windows = _window_by_pieces(pieces, text, char_start, section["title"])
            if windows:
                result.extend(windows)
                continue
        pieces = [p for p in re.split(r'(?<=[.!?]) +', text) if p]
        if len(pieces) > 1:
            windows = _window_by_pieces(pieces, text, char_start, section["title"])
            if windows:
                result.extend(windows)
                continue
        result.extend(_hard_windows(text, char_start, section["title"]))
    if not result:
        result.append({"title": "", "char_start": 0, "char_end": len(body)})
    return result
