"""PII detection table + scanner for the Layer 3e privacy gate.

Static pattern data and a pure regex scan — no I/O, no config. The gate logic
that *uses* these (_disclosure_gate, _gate_conversation) stays in cli.py.
Extracted from cli.py (audit WI-4); cli re-exports these names.
"""

from __future__ import annotations

import re

_PII_PATTERNS: list[dict] = [
    # INDIAN IDENTITY DOCUMENTS
    {"name": "Aadhaar",          "pattern": r"\b\d{4}[\s-]\d{4}[\s-]\d{4}\b"},
    {"name": "PAN card",         "pattern": r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"},
    {"name": "Passport (IN)",    "pattern": r"\b[A-Z][0-9]{7}\b"},
    {"name": "Voter ID (IN)",    "pattern": r"\b[A-Z]{3}[0-9]{7}\b"},
    {"name": "Driving licence",  "pattern": r"\b[A-Z]{2}[0-9]{2}[\s-]?[0-9]{4,11}\b"},
    {"name": "GSTIN",            "pattern": r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"},
    {"name": "IFSC code",        "pattern": r"\b[A-Z]{4}0[A-Z0-9]{6}\b"},
    {"name": "Vehicle reg (IN)", "pattern": r"\b[A-Z]{2}[\s-]?\d{2}[\s-]?[A-Z]{1,2}[\s-]?\d{4}\b"},
    # CONTACT INFORMATION
    {"name": "Email",            "pattern": r"(?<!\[)[^\s@\[\]]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"},
    {"name": "Phone (IN)",       "pattern": r"\b(\+91[\s-]?)?[6-9]\d{9}\b"},
    {"name": "Phone (intl)",     "pattern": r"\+[1-9]\d{1,14}\b"},
    {"name": "Indian PIN code",  "pattern": r"(?i)\bpin\s*(?:code)?\s*[:=]?\s*[1-9][0-9]{5}\b"},
    # FINANCIAL
    {"name": "Credit/debit card", "pattern": r"\b(?:\d{4}[\s-]?){3}\d{4}\b"},
    {"name": "UPI ID",           "pattern": r"\b[a-zA-Z0-9._-]{2,}@[a-zA-Z]{2,}\b(?!\.[a-zA-Z])"},
    {"name": "CVV",              "pattern": r"(?i)cvv\s*[:=]\s*\d{3,4}"},
    # CREDENTIALS AND KEYS
    {"name": "Password field",   "pattern": r"(?i)(password|passwd|pwd|secret|token)\s*[:=]\s*[^\s\[]+"},
    {"name": "OpenAI/Anthropic key", "pattern": r"\bsk-[A-Za-z0-9_-]{32,}"},
    {"name": "API key in context",      "pattern": r"(?i)\w*api[\s_-]?key\s*[\"']?\s*[:=]\s*[\"']?\s*[^\s\[]{8,}"},
    {"name": "Secret/token in context", "pattern": r"(?i)\b(?:secret|access|auth)[\s_-]?(?:key|token)\s*[\"']?\s*[:=]\s*[\"']?\s*[^\s\[]{8,}"},
    {"name": "Google key",       "pattern": r"\bAIza[A-Za-z0-9_-]{35}\b"},
    {"name": "GitHub PAT",       "pattern": r"\bghp_[A-Za-z0-9]{36}\b"},
    {"name": "GitHub OAuth",     "pattern": r"\bgho_[A-Za-z0-9]{36}\b"},
    {"name": "AWS access key",   "pattern": r"\bAKIA[0-9A-Z]{16}\b"},
    {"name": "Bearer token",     "pattern": r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"},
    {"name": "JWT token",        "pattern": r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"},
    {"name": "SSH private key",  "pattern": r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"},
    {"name": ".env secret",      "pattern": r"(?i)\b(SECRET|TOKEN|KEY|PASS)\s*=\s*[^\s\[]{8,}"},
    {"name": "DB connection string", "pattern": r"\w+://[^:\s\[]+:[^@\s\[]+@[^\s\[]+"},
    # NETWORK AND SYSTEM
    # IPv4 removed (audit WI-3): private IPs aren't sensitive and it false-matched
    # 4-part version strings like 1.2.3.4. IPv6/MAC kept (distinctive, low FP).
    {"name": "IPv6 address",     "pattern": r"\b([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"},
    {"name": "MAC address",      "pattern": r"([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}"},
    # LOCATION
    {"name": "GPS coordinates",  "pattern": r"-?\d{1,3}\.\d{4,},\s*-?\d{1,3}\.\d{4,}"},
]


def _gate_text(text: str) -> str:
    """Strip PII from text before cloud dispatch. No cfg — uses built-in patterns only."""
    from kage.redact import substitute
    try:
        from kage.sensitive import load_vault
        vault_patterns = [{"name": f"SENSITIVE_{p['label']}", "pattern": p["pattern"]}
                          for p in load_vault().get("patterns", [])]
    except Exception:
        vault_patterns = []
    redacted, _ = substitute(text, _PII_PATTERNS + vault_patterns)
    return redacted


def _pii_scan(text: str, extra_patterns: list[dict] | None = None) -> list[str]:
    """Scan text for PII patterns; return list of matched pattern names (empty = clean)."""
    # ponytail: O(p) regex passes per text (p=28 patterns). Fine for typical notes.
    # Ceiling: noticeable on notes > 50k chars in a long session.
    # Upgrade: compile |-joined union and scan once.
    hits = []
    for entry in (_PII_PATTERNS + (extra_patterns or [])):
        try:
            if re.search(entry["pattern"], text):
                hits.append(entry["name"])
        except re.error:
            pass  # skip malformed user-supplied patterns
    return hits
