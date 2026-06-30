from kage.redact import substitute, restore, _label


def test_substitute_basic():
    text, mapping = substitute("contact test@example.com now", [
        {"name": "Email", "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"}
    ])
    assert text == "contact [EMAIL_1] now"
    assert mapping == {"[EMAIL_1]": "test@example.com"}


def test_substitute_multi_pattern():
    text, mapping = substitute("Call me at 9876543210 or email me at test@example.com", [
        {"name": "Phone", "pattern": r"\d{10}"},
        {"name": "Email", "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"}
    ])
    assert text == "Call me at [PHONE_1] or email me at [EMAIL_1]"
    assert mapping == {"[PHONE_1]": "9876543210", "[EMAIL_1]": "test@example.com"}


def test_substitute_existing_mapping():
    first_text, first_mapping = substitute("Email is test@example.com", [
        {"name": "Email", "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"}
    ])
    second_text, second_mapping = substitute("Email is test2@example.com", [
        {"name": "Email", "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"}
    ], existing_mapping=first_mapping)
    assert second_text == "Email is [EMAIL_2]"
    assert second_mapping == {"[EMAIL_1]": "test@example.com", "[EMAIL_2]": "test2@example.com"}


def test_substitute_bad_pattern():
    text, mapping = substitute("Email is test@example.com and phone is 9876543210", [
        {"name": "Invalid", "pattern": "[invalid"},
        {"name": "Email", "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"}
    ])
    assert text == "Email is [EMAIL_1] and phone is 9876543210"
    assert mapping == {"[EMAIL_1]": "test@example.com"}


def test_substitute_no_match():
    text, mapping = substitute("hello world", [
        {"name": "Email", "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"}
    ])
    assert text == "hello world"
    assert mapping == {}


def test_restore_basic():
    restored = restore("[EMAIL_1] said hi", {"[EMAIL_1]": "foo@bar.com"})
    assert restored == "foo@bar.com said hi"


def test_restore_empty_mapping():
    restored = restore("hello", {})
    assert restored == "hello"


def test_label_normalisation():
    assert _label("Credit/debit card") == "CREDIT_DEBIT_CARD"
    assert _label("API key in context") == "API_KEY_IN_CONTEXT"


def test_roundtrip():
    text, mapping = substitute("Email is test@example.com", [
        {"name": "Email", "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"}
    ])
    restored = restore(text, mapping)
    assert restored == "Email is test@example.com"
