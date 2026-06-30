# Cycle 21 — Layer 3e value substitution: the moat's true form (v0.21.0)

*Status: SHIPPED (v0.21.0, 3 cold reviews — branch cycle-19-sensitive-vault, not yet merged)*
*Date: 2026-06-30*

> **v3 changelog (cold review #2):**
> NEW BLOCKER — `redact.py` module listing omitted `existing_mapping` parameter and counter-seeding
>              logic. Merged the stub from the REPL section into the canonical module definition.
> MINOR — REPL cloud path: specified exactly where `substitute()` is called before `_answer()`.
> MINOR — Added `test_ask_arm_context_substituted` integration test for the B2 fix.
>
> **v2 changelog (cold review #1):**
> B1 — `_disclosure_gate` has TWO callers in `cli.py` (lines 977 + 1625) plus a shim at 444.
>       All three updated in scope. Return type explicitly widened.
> B2 — Arm context (injected into `system` prompt) not substituted. Fixed: substitute
>       `arm_context` after arm calls complete; merge into same `sub_mapping`.
> B3 — `_gate_conversation` still blocks turns whose stored content has real PII (because
>       `restore()` runs before `session_append`). Documented explicitly; deferred to Cycle 22.
> M1 — `_gate_text` is a one-way near-duplicate. Refactored to call `substitute()` internally.
> M2 — `restore()` is a no-op when the model paraphrases (correct behavior); documented.
> M3 — Fallback audit write (line 1111) added to the list of sites to update.

---

## What and why

The current Layer 3e gate **blocks** notes that contain PII — the entire note is withheld. The
structure and semantic content are lost too. This is the conservative safe choice, but it is not
the moat: a privacy *broker* should be able to send the cloud model the *meaning* of what you
know without sending the *data*.

The endgame (from blueprint §Layer 3e and memory `project_redaction_substitution_vision.md`)
is **reversible masking**:

```
  real value  →  typed placeholder  →  cloud dispatch
  [EMAIL_1]   ←  mapping lookup     ←  cloud response (placeholder echoed back)
```

Cloud sees `"my email is [EMAIL_1]"` — the structure, not the value. If the response says
`"Your email [EMAIL_1] is already registered"`, kage swaps it back before the user sees it.
`local_only` notes still block completely (that is a hard user choice, not a PII flag).

The result: notes that previously fell off the context window due to PII blocking now reach
the model. The moat is not "kage hides your data" — it is "kage lets AI reason *about* your
data without ever seeing it."

---

## Scope

### In scope

1. New pure module `src/kage/redact.py`:
   - `substitute(text, patterns) → (redacted_text, mapping)` — regex scan → numbered typed
     placeholders; mapping = `{placeholder: real_value}`
   - `restore(text, mapping) → str` — swap placeholders back in any string

2. `privacy.py` — `_disclosure_gate`: remove the `pii_hits → withheld` branch. PII detection
   becomes informational only (for audit logging). `local_only` flag and `identity_wall`
   continue to block. Return type widens to `tuple[list, list[dict], dict[str, list[str]]]`
   where the third element is `{note_id: [pii_pattern_names]}` for all rows that passed with
   PII present. **All three callers updated:**
   - `cli.py:444` shim (re-export) — type annotation updated
   - `cli.py:977` (`ask` command) — unpack 3-tuple
   - `cli.py:1625` (chat REPL) — unpack 3-tuple (was `rows, _ = ...`)

3. `pii.py` — `_gate_text`: refactored to call `redact.substitute()` internally instead of
   duplicating the scan loop. It drops the mapping (callers needing restoration use `substitute`
   directly). Removes the one-way duplication.

4. `cli.py` — `ask` command cloud path:
   - After context assembly (line 1062), call `substitute(context, all_patterns)` → `(context, sub_mapping)`.
   - After arm calls complete (line 1074), also call `substitute(arm_context, all_patterns, existing_mapping=sub_mapping)` → `(arm_context, sub_mapping)`. Both the note context and arm results are substituted before they enter `system` or `user_msg`.
   - After `_call_cloud` returns, call `restore(answer, sub_mapping)` before display.
   - Audit log gains `substitution_count` + `placeholder_labels` fields at **all four write sites**: lines 987, 1028, 1039, and 1111 (fallback dispatch).
   - Echo line changes: "PII detected — substituted N placeholder(s) before dispatch" instead of "withheld".

4. `cli.py` — `chat` REPL: mapping accumulates per session (one dict for all turns in the
   session); each new turn's substitution merges into the session mapping so `[EMAIL_1]`
   stays consistent across turns.

5. New test file `tests/test_redact.py` (6-8 tests, pure unit — no I/O).

6. New integration tests in `tests/test_cli.py` (2-3 tests verifying end-to-end gate change).

### Out of scope

- Tier B/C sensitivity cascade (NER, LLM-redactor) — deferred per blueprint
- Per-tool token budgets and PERMIT/MODIFY/ASK/DENY policy system — separate cycle
- Mapping persistence across process restarts — single-session only in v0.21
- `_gate_conversation` (chat history) substitution — existing behavior unchanged for now
- **User's question text** — the question typed by the user is NOT substituted before cloud dispatch (only note context and arm results are). Pre-existing gap: the question was never substituted in prior cycles either. If the user pastes a raw PII value into the question itself (e.g. "is 1234 5678 9012 my Aadhaar?"), it exits unmasked. The notes that answer the question are protected; the question framing is not. Deferred: question-level substitution (Cycle 22+).

---

## Module: `src/kage/redact.py`

```python
"""Reversible PII substitution for Layer 3e dispatch.

substitute() replaces PII spans with typed, numbered placeholders.
restore()    swaps them back in any string (typically the cloud response).

No I/O, no config — pure functions so tests never need monkeypatching.
"""
from __future__ import annotations
import re

_LABEL_RE = re.compile(r"[^A-Z0-9]+")

def _label(name: str) -> str:
    """'Credit/debit card' → 'CREDIT_DEBIT_CARD'."""
    return _LABEL_RE.sub("_", name.upper()).strip("_")


def substitute(
    text: str,
    patterns: list[dict],
    *,
    existing_mapping: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    """Replace PII spans with [LABEL_N] placeholders. Returns (redacted_text, mapping).

    Processes patterns sequentially left-to-right. Each pattern's placeholders
    are numbered independently; the [LABEL_N] format never matches any PII regex,
    so sequential substitution is safe (no double-substitution).

    existing_mapping: pass the mapping from a prior call to continue numbering
    consistently (e.g., across REPL turns). The returned mapping includes all
    existing_mapping entries plus any new ones found in this call.
    """
    # Seed counters from prior mapping so new substitutions continue numbering.
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
            counters[_lbl] = counters.get(_lbl, 0) + 1
            placeholder = f"[{_lbl}_{counters[_lbl]}]"
            mapping[placeholder] = m.group(0)
            return placeholder

        text = compiled.sub(_replacer, text)

    return text, mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    """Swap [LABEL_N] placeholders back to real values."""
    for placeholder, real in mapping.items():
        text = text.replace(placeholder, real)
    return text
```

---

## Change to `privacy.py` — `_disclosure_gate`

Remove lines 74-77 (the `pii_hits → withheld.append → continue` branch). Replace with:

```python
        pii_hits = _pii_scan(text, extra_pii)
        if pii_hits:
            # ponytail: PII recorded for audit; note passes — substitution happens at dispatch.
            # local_only is the hard block; PII alone no longer withholds.
            pii_map[note_id] = pii_hits
        allowed.append(row)
```

Return signature changes from `tuple[list, list[dict]]` to `tuple[list, list[dict], dict[str, list[str]]]`:

```python
def _disclosure_gate(...) -> tuple[list, list[dict], dict[str, list[str]]]:
    ...
    pii_map: dict[str, list[str]] = {}
    ...
    return allowed, withheld, pii_map
```

**Three callers to update:**
- `cli.py:444` shim: `return _privacy._disclosure_gate(rows, cfg, identity, project)` — type annotation
- `cli.py:977`: `allowed_rows, withheld, pii_map = _disclosure_gate(...)`
- `cli.py:1625`: `rows, _, pii_map = _disclosure_gate(...)` (was `rows, _ = ...`)

---

## Change to `cli.py` — ask command (cloud path)

At line 1062, after `context = "\n\n".join(context_parts)`:

```python
    sub_mapping: dict[str, str] = {}
    if cloud:
        from kage.redact import substitute
        from kage.pii import _PII_PATTERNS
        from kage.sensitive import load_vault
        vault_patterns = [{"name": f"SENSITIVE_{p['label']}", "pattern": p["pattern"]}
                          for p in load_vault().get("patterns", [])]
        context, sub_mapping = substitute(context, _PII_PATTERNS + vault_patterns)
        if sub_mapping:
            typer.echo(f"[kage] Substituted {len(sub_mapping)} PII span(s) before dispatch "
                       f"({', '.join(sorted(sub_mapping)[:3])}{'…' if len(sub_mapping) > 3 else ''})")
```

After `_call_cloud` returns `answer`:

```python
        if sub_mapping:
            from kage.redact import restore
            answer = restore(answer, sub_mapping)
```

Audit record gains `substitution_count` + `placeholder_labels` at **all four write sites**:
lines 987 (blocked_all_local), 1028 (denied_by_user), 1039 (dispatched), and 1111
(dispatched_fallback). Sites that fire before substitution occurs use `substitution_count=0`.

---

## Change to `pii.py` — `_gate_text` (M1 fix)

`_gate_text()` is a one-way near-duplicate of `substitute()`. Refactor it to call `substitute()`:

```python
def _gate_text(text: str) -> str:
    from kage.redact import substitute
    from kage.sensitive import load_vault
    vault_patterns = [{"name": f"SENSITIVE_{p['label']}", "pattern": p["pattern"]}
                      for p in load_vault().get("patterns", [])]
    redacted, _ = substitute(text, _PII_PATTERNS + vault_patterns)
    return redacted
```

The mapping is dropped — callers of `_gate_text` (Monitor, observe) don't need restoration.
One pattern-scanning source of truth.

---

## Change to `cli.py` — chat REPL

`substitute()` takes an optional `existing_mapping` param so counters continue across turns
(EMAIL_1 in turn 1 stays EMAIL_1 in turn 2's context). The REPL maintains a
`session_sub_mapping: dict[str, str] = {}` across turns. Each turn's cloud path:

```python
# After context assembly, before building user_msg / system:
context, session_sub_mapping = substitute(context, all_patterns, existing_mapping=session_sub_mapping)
if arm_context:
    arm_context, session_sub_mapping = substitute(arm_context, all_patterns, existing_mapping=session_sub_mapping)
# ... dispatch via _answer() ...
# After _answer() returns:
answer = restore(answer, session_sub_mapping)
```

The caller replaces `session_sub_mapping` with the returned value (which includes all prior
keys plus new ones) — no separate merge needed.

```python
def substitute(
    text: str,
    patterns: list[dict],
    *,
    existing_mapping: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    # Seed counters from existing_mapping keys (e.g. "[EMAIL_3]" → EMAIL counter at 3).
    # Return mapping INCLUDES all existing_mapping entries + new ones.
    ...
```

**Known gap (B3 — deferred Cycle 22):** The REPL restores real values in the answer before
storing the turn via `session_append` (otherwise the stored history is full of opaque
placeholders). This means `_gate_conversation` in subsequent turns scans stored content with
real PII values and blocks those turns. The effect: any REPL conversation where the assistant
echoes back PII will see that turn withheld in future history dispatch. Fixing this requires
either (a) storing turns with placeholders and only restoring at display, or (b) applying
substitution inside `_gate_conversation` itself. Deferred to Cycle 22.

---

## Test plan

### `tests/test_redact.py` (pure unit — 9 tests)

```
test_substitute_replaces_email                  — "my email is foo@bar.com" → "[EMAIL_N]"
test_substitute_returns_mapping                 — mapping has placeholder → original
test_restore_swaps_back                         — after restore, original text returns
test_substitute_two_emails_numbered             — EMAIL_1, EMAIL_2 separately
test_substitute_multi_pattern_types             — email + aadhaar in same text, distinct labels
test_substitute_existing_mapping_seeds_counter  — EMAIL_3 already in existing → next is EMAIL_4
test_substitute_existing_mapping_merges_keys    — returned mapping includes prior keys
test_restore_noop_on_empty_mapping              — restore(text, {}) == text
test_substitute_invalid_pattern_skipped         — malformed regex in list → silently skipped
```

### `tests/test_cli.py` additions (integration — 4 tests)

```
test_disclosure_gate_pii_no_longer_blocks     — row with PII now in allowed_rows + pii_map entry
test_ask_cloud_receives_placeholder            — _call_cloud sees [EMAIL_N], not real value
test_ask_response_restored_before_display      — answer shown has real value, not placeholder
test_ask_arm_context_substituted               — arm result PII redacted in system prompt dispatch
```

---

## Files changed

```
src/kage/redact.py          NEW — substitute() + restore()
src/kage/privacy.py         CHANGE — remove pii_hits block; add pii_map to return (3-tuple)
src/kage/pii.py             CHANGE — _gate_text() delegates to substitute(), drops mapping
src/kage/cli.py             CHANGE — 3 caller updates + substitute/restore at dispatch
tests/test_redact.py        NEW — 9 unit tests
tests/test_cli.py           CHANGE — 4 integration tests (net ~574 total)
```

---

## Rollback surface

`_disclosure_gate` currently blocks PII rows. After this cycle, those rows are allowed through.
If a user had relied on "PII in notes always stays local," that behavior changes — now PII
values *are* sent to cloud as placeholders. The real values are substituted locally before
dispatch; the placeholder is semantically meaningful but privacy-preserving. This is the
intended change but is a user-visible behavior shift worth documenting in the CHANGELOG.

---

## Ponytail notes

- `ponytail: substitute() is O(p × t) regex passes (p patterns, t text length). Fine for
  typical context sizes (~8k chars). Ceiling: noticeable above 200k chars. Upgrade: compile
  a |-joined union pattern for all labels.`
- `ponytail: restore() does linear string.replace() per placeholder. Ceiling: large mapping
  (>100 substitutions) on a long response. Upgrade: one pass with compiled union regex.`
- `ponytail: existing_mapping counter seeding reads all prior placeholders on each call.
  Ceiling: very long chat sessions. Upgrade: pass counters directly.`
