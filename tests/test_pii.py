import re
from kage.pii import _PII_PATTERNS
from kage.redact import substitute, restore

EMAIL_PAT = next(p["pattern"] for p in _PII_PATTERNS if p["name"] == "Email")
PWD_PAT   = next(p["pattern"] for p in _PII_PATTERNS if p["name"] == "Password field")
DB_PAT    = next(p["pattern"] for p in _PII_PATTERNS if p["name"] == "DB connection string")


def test_email_detects_real():
    assert re.search(EMAIL_PAT, "contact user@example.com now")


def test_email_detects_unicode():
    assert re.search(EMAIL_PAT, "send to üser@example.com")


def test_email_ignores_placeholder():
    # [EMAIL_1]@x.com must not be matched — placeholder-safe guard
    assert not re.search(EMAIL_PAT, "[EMAIL_1]@example.com")


def test_password_detects_token():
    assert re.search(PWD_PAT, "token: hunter2", re.IGNORECASE)


def test_password_ignores_placeholder_value():
    # [^\s\[]+ stops at [ so password: [EMAIL_1] must not match
    assert not re.search(PWD_PAT, "password: [EMAIL_1]", re.IGNORECASE)


def test_db_matches_postgres():
    assert re.search(DB_PAT, "postgres://user:pass@localhost/mydb")


def test_db_ignores_plain_url():
    assert not re.search(DB_PAT, "https://example.com/x")


def test_roundtrip_placeholder_safe():
    # Corpus contains a pre-existing [AADHAAR_1] placeholder (label type not minted
    # by any match in this corpus, so no numbering collision) plus real PII.
    # restore(substitute(corpus)) must equal corpus exactly.
    corpus = "password: [AADHAAR_1]\ntoken: a@b.com and password: hunter2"
    result, mapping = substitute(corpus, _PII_PATTERNS)
    assert restore(result, mapping) == corpus
