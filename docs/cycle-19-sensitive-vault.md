# Cycle 19 — Sensitive Vault (P01)

*v3 — 2026-06-29 (post cold review #2 — 2 new BLOCKERs fixed)*
*Status: PITCH — 2 cold reviews complete, ready to build*

---

## Problem

kage's built-in `_PII_PATTERNS` (30+ regex) covers standard identity documents,
credentials, and contact info. But every user has private content that doesn't fit
generic patterns — a family member's name, an employer's internal project codename,
a home address fragment, an account number in a non-standard format. Today there is
no way to tell kage "this string must never leave the device," and no way to audit
which existing notes already contain sensitive content.

---

## What P01 IS / is NOT

**IS:**
- A user-editable pattern vault (`~/.kage/sensitive.json`) for custom sensitive strings
- A bootstrap scanner that audits existing memory against both built-in + vault patterns
- A Monitor tool that flags pending staging items before they reach cloud
- Three CLI commands: `kage sensitive scan`, `kage sensitive add`, `kage sensitive list`

**IS NOT:**
- A replacement for the existing `_PII_PATTERNS` (those stay unchanged, always on)
- An encryption layer or secret manager
- A per-note flag stored in the DB (flagged output is ephemeral — printed, not persisted)

---

## Key Facts from Reading the Code

These shape the implementation:

1. **`pii._gate_text(text)`** — used in scout's ADK `_pii_seam` callback. Applies
   only built-in patterns. Vault must be hooked here.

2. **`librarian._gate_text(content, cfg)`** — used in `distill_and_judge`. Already
   reads `cfg.get("pii_patterns", [])` as extra patterns. Vault hook goes here too.

3. **`privacy._pii_scan(text, extra_pii)`** — used in `_disclosure_gate` (the
   `kage ask` path). `extra_pii` comes from config today; NOT changing for P01
   (privacy gate already warns the user; vault integration here is v2).

4. **`_pii_scan` in `pii.py`** already accepts `extra_patterns`. The seam exists;
   we're just wiring a file-backed source of patterns into it.

---

## Design Decisions

### D1 — Vault format

```json
{
  "patterns": [
    {"id": "a1b2c3d4", "label": "chirag-address", "pattern": "Koramangala", "added_at": "2026-06-29"}
  ]
}
```

No `flagged_notes` field — scan results are ephemeral (printed, not stored). Rationale:
storing flagged note IDs creates a stale cache problem as notes are edited. Print on
demand; the bootstrap is fast enough to re-run.

**Key constraint:** `_pii_scan` in `pii.py` reads `entry["name"]` from each pattern
dict. Vault entries use `"label"` instead. Every call site that passes vault entries
to `_pii_scan` MUST shim them: `{"name": p["label"], "pattern": p["pattern"]}`.
This applies to `bootstrap` and `scan_sensitive_patterns` in `sensitive.py`.
The `_gate_text` paths do their own `re.sub` loop (not via `_pii_scan`) so they
read `p["pattern"]` and `p["label"]` directly — no shim needed there.

### D2 — Vault location

`~/.kage/sensitive.json` — next to `config.json`. Not inside `indexes/` (that's
ChromaDB territory) and not inside `memory/` (that's note content).

### D3 — Redaction label

Vault-pattern hits use `[SENSITIVE:<label>]` (distinct from `[REDACTED_PII]`). The
user can tell which system fired: built-in PII gate vs their own custom pattern.

### D4 — Gate integration scope

Four paths run text through PII/gate logic. P01 wires two; two are deferred:

| Path | Function | P01? |
|------|----------|------|
| Scout ADK callback | `pii._gate_text` | YES — Step 2 |
| Librarian distill | `librarian._gate_text` | YES — Step 3 |
| `kage ask` retrieval | `privacy._disclosure_gate` → `_pii_scan` | NO — v2 |
| `kage chat` turns | `privacy._gate_conversation` → `_pii_scan` | NO — v2 |

The ask and chat paths use `_pii_scan` with `extra_pii` from config only. Vault
patterns are not enforced there in P01. Users must be told this explicitly (see Out
of Scope and CLI note in Step 5).

### D5 — Monitor tool

`scan_sensitive_patterns()` (in `sensitive.py`) is a sync function: reads pending
staging queue items, runs `_pii_scan` (built-in + vault), returns
`{"flagged_count": N, "items": [...]}`. Added to `observe_tools` in `build_monitor`
via inline import inside the function. Monitor calls it alongside other health
checks — no separate scheduling needed.

### D6 — CLI UX

```
kage sensitive list                    # show vault patterns
kage sensitive add <label> <pattern>   # add a user pattern (regex or literal)
kage sensitive scan                    # scan ~/.kage/memory/*.md and print hits
```

No `remove` command in v1. User edits `sensitive.json` directly with a text editor
(it's a simple JSON array). Adding remove as a subcommand is v2.

---

## Implementation Steps

### Step 1 — `src/kage/sensitive.py` (new module)

Functions:
- `load_vault() -> dict` — reads `sensitive.json`, returns `{"patterns": []}` on miss
- `save_vault(vault: dict)` — writes back
- `add_pattern(label: str, pattern: str)` — appends to vault; validates regex first (raises `re.error` on invalid)
- `bootstrap(memory_dir: Path) -> list[dict]` — scans `*.md` via `_pii_scan`, returns `[{path, hits}]`
- `scan_sensitive_patterns() -> dict` — scans pending staging queue via `_pii_scan`, returns `{"flagged_count": N, "items": [...]}`

Note the function is named **`scan_sensitive_patterns`** (not `check_sensitive_patterns`)
to avoid a name collision with the monitor wrapper in Step 4.

Integration note: `bootstrap` and `scan_sensitive_patterns` import `_pii_scan`
from `kage.pii` and `get_staging_queue` from `kage.librarian` inline (avoids
circular imports — sensitive.py must not be imported at module level by pii.py).

`_pii_scan` shim for vault entries (required everywhere `_pii_scan` receives vault
patterns — see D1):
```python
shimmed = [{"name": p["label"], "pattern": p["pattern"]} for p in vault.get("patterns", [])]
hits = _pii_scan(text, shimmed)
```

### Step 2 — `pii._gate_text` integration

Add vault pattern application after the built-in loop:

```python
def _gate_text(text: str) -> str:
    for entry in _PII_PATTERNS:
        try:
            text = re.sub(entry["pattern"], "[REDACTED_PII]", text)
        except re.error:
            pass
    try:
        from kage.sensitive import load_vault
        for p in load_vault().get("patterns", []):
            text = re.sub(p["pattern"], f"[SENSITIVE:{p['label']}]", text, flags=re.IGNORECASE)
    except Exception:
        pass  # vault missing or malformed — fail open, not fail closed
    return text
```

The `except Exception` is intentional: if sensitive.py can't load the vault (first
run, malformed JSON, permissions error), the gate still applies built-in patterns.
Never fail closed on a missing vault.

### Step 3 — `librarian._gate_text` integration

`librarian._gate_text` applies `[REDACTED_PII]` for all entries in `all_patterns`.
Adding vault patterns to that list would also emit `[REDACTED_PII]` — violating D3.
Handle vault patterns in a separate pass with `[SENSITIVE:<label>]`.

**Exact edit:** replace line 342 (`return sanitized`) with the block below:

```python
    # vault patterns: separate pass so they emit [SENSITIVE:<label>], not [REDACTED_PII]
    try:
        from kage.sensitive import load_vault
        for p in load_vault().get("patterns", []):
            try:
                sanitized = re.sub(p["pattern"], f"[SENSITIVE:{p['label']}]", sanitized, flags=re.IGNORECASE)
            except re.error:
                pass
    except Exception:
        pass
    return sanitized
```

The existing `return sanitized` on line 342 is removed — the block above ends with
the new `return sanitized`. There must be exactly ONE `return sanitized` after this edit.

### Step 4 — `monitor.py` — add `scan_sensitive_patterns` tool

No wrapper needed. In `build_monitor`, **replace** the existing `observe_tools = [...]`
list with this block (adds the inline import before it and appends `scan_sensitive_patterns`):

```python
    from kage.sensitive import scan_sensitive_patterns
    observe_tools = [
        read_pipeline_state, read_session_log, read_observe_log, check_mcp_health,
        read_system_metrics, read_command_history, read_antigravity_ctx, ping_kage_mcp,
        write_alert, set_item_priority, scan_sensitive_patterns,
    ]
```

The inline import (lazy load inside the function, not at module level) defers
loading `sensitive.py` until Monitor is first built. The existing `observe_tools`
list is the one being replaced — do not insert a second definition.

### Step 5 — `cli.py` — `kage sensitive` subcommands

Three subcommands under `sensitive`:

```
kage sensitive list
kage sensitive add <label> <pattern>
kage sensitive scan
```

`sensitive scan` calls `bootstrap(Path(runtime.config.home) / "memory")` and prints
each flagged file with its hit patterns. If nothing flagged: "No sensitive patterns
found in memory."

`sensitive list` appends a one-line notice: "Note: vault patterns are enforced in
scout and librarian paths only. `kage ask` and `kage chat` do not apply vault
patterns in this release." This makes the P01 scope limit visible to the user
without requiring them to read the pitch.

`sensitive add` catches `re.error` from `re.compile(pattern)` and prints a
user-readable message (`Error: invalid regex — <message>`). Never let a raw
traceback reach the terminal.

`sensitive list` prints each pattern row as: `[<id>]  <label>  →  <pattern>`.

---

## Test Surface

New file: `tests/test_sensitive.py`

| Test | What it checks |
|------|----------------|
| `test_load_vault_missing` | Returns `{"patterns": []}` when file absent |
| `test_add_pattern_persists` | add_pattern writes to JSON and reloads correctly |
| `test_add_pattern_invalid_regex` | Raises `re.error` on bad regex; reload vault confirms pattern NOT persisted |
| `test_bootstrap_flags_builtin_pii` | bootstrap finds Aadhaar-shaped content in memory |
| `test_bootstrap_flags_vault_pattern` | bootstrap finds user-defined pattern hit |
| `test_bootstrap_clean` | Empty memory dir → empty result |
| `test_gate_text_applies_vault_pattern` | `_gate_text` redacts vault pattern with `[SENSITIVE:<label>]` |
| `test_scan_sensitive_patterns_flags_pii` | scan_sensitive_patterns flags staging item with PII |

Additional test in `test_librarian.py`:
- `test_librarian_gate_applies_vault_pattern` — calls `librarian._gate_text(content, cfg)`
  directly (not via `distill_and_judge`) with `sensitive.json` written to `lib_env`'s
  kage_home; asserts output contains `[SENSITIVE:<label>]`, not `[REDACTED_PII]`

---

## Open Questions (cold review targets)

1. ~~Regex validation~~ — **CLOSED**: `add_pattern` raises `re.error` internally;
   CLI catches it and prints user-readable message. No raw tracebacks.

2. **Vault load on every `_gate_text` call**: no caching. At one disk read per cloud dispatch, this is fine for P01. Flag if profiling ever shows it mattering.

3. **`check_sensitive_patterns` return shape**: returning `{"flagged_count": N, "items": [{"id": ..., "hits": [...]}]}`. Is this granular enough for Monitor's digest prompt to act on?

4. **`sensitive scan` output format**: plain text list per file, or JSON? JSON is machine-readable but ugly in terminal. Plain text for v1.

5. **Circular import risk**: `sensitive.py` imports from `pii.py` (via `_pii_scan`) and `librarian.py` (via `get_staging_queue`). Both are inline imports. `pii._gate_text` imports from `sensitive.py` inline. Since Python caches modules, the inline import on second call is just a dict lookup — no performance concern.

---

## Out of Scope for P01

- `kage sensitive remove <id>` — v2; edit JSON directly for now
- Vault pattern integration into `kage ask` (`privacy._disclosure_gate`) and `kage chat`
  (`privacy._gate_conversation`) — both deferred to v2. **Important:** vault patterns
  are NOT enforced in the ask or chat paths in P01. A pattern added via `kage sensitive
  add` will not block cloud dispatch through `kage ask` or `kage chat`. Only the scout
  (`pii._gate_text`) and librarian (`librarian._gate_text`) paths redact vault patterns.
  `kage sensitive list` prints a notice making this scope limit explicit to the user.
- Encrypted vault — not kage's job; OS keychain handles this if needed
- Per-note `sensitive` flag in the `memories` DB — v2

---

*Cold reviews needed: 1 pitch, 1 code, 1 test — before PR.*
