"""Reversible PII substitution for Layer 3e dispatch (Cycle 21).

substitute() replaces PII spans with typed, numbered placeholders before cloud dispatch.
restore()    swaps them back in any string (typically the cloud response).

Pure functions — no I/O, no config, no kage imports.
"""
from __future__ import annotations
import re

_LABEL_RE = re.compile(r"[^A-Z0-9]+")


def _label(name: str) -> str:
    """'Credit/debit card' -> 'CREDIT_DEBIT_CARD'."""
    return _LABEL_RE.sub("_", name.upper()).strip("_")


def substitute(
    text: str,
    patterns: list[dict],
    *,
    existing_mapping: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    """Replace PII spans with [LABEL_N] placeholders. Returns (redacted_text, mapping).

    Processes patterns sequentially. Each [LABEL_N] placeholder never matches any PII
    regex, so sequential substitution is safe (no double-substitution).

    Pass existing_mapping from a prior call to continue numbering consistently across
    REPL turns. The returned mapping includes all existing_mapping entries plus new ones.
    """
    counters: dict[str, int] = {}
    if existing_mapping:
        for ph in existing_mapping:
            m = re.match(r"\[([A-Z0-9_]+)_(\d+)\]", ph)
            if m:
                lbl, n = m.group(1), int(m.group(2))
                counters[lbl] = max(counters.get(lbl, 0), n)
    mapping: dict[str, str] = dict(existing_mapping or {})

    for entry in patterns:
        try:
            compiled = re.compile(entry["pattern"])
        except re.error:
            continue
        lbl = _label(entry["name"])

        def _replacer(m: re.Match, _lbl: str = lbl) -> str:
            value = m.group(0)
            for ph, mapped_value in mapping.items():
                if mapped_value == value:
                    return ph
            counters[_lbl] = counters.get(_lbl, 0) + 1
            placeholder = f"[{_lbl}_{counters[_lbl]}]"
            mapping[placeholder] = value
            return placeholder

        text = compiled.sub(_replacer, text)

    return text, mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    """Swap [LABEL_N] placeholders back to real values."""
    for placeholder, real in mapping.items():
        text = text.replace(placeholder, real)
    return text
