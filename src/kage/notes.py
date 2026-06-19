from __future__ import annotations

from kage import runtime


def _read_body(rel_path: str) -> str:
    """Read a memory body from its markdown file, stripping frontmatter."""
    text = (runtime.config.home / rel_path).read_text()
    if text.startswith("---"):
        close = text.find("\n---", 3)
        if close != -1:
            text = text[close + 4:]
    return text.strip()


def _read_section(content_path: str, char_start: int, char_end: int) -> str:
    """Return body slice [char_start:char_end]; empty string on read error."""
    try:
        body = _read_body(content_path)
        return body[char_start:char_end]
    except OSError:
        return ""
