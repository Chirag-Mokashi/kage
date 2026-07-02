# Cycle 15 — Librarian: kage's sole memory writer (ADK LlmAgent, v0.16.0)

*Status: SHIPPED v0.16.0 (`c4aeca4`) — pitch v4 (v3 + Step 0 ADK import fix, verified vs google-adk 2.3.0).*

*Brainstorm source: 25-section brainstorm in memory (`project_librarian_brainstorm.md`). All decisions pre-locked; this pitch expresses them as an executable build plan.*

---

## North star

> **Scout finds. You decide. Librarian remembers.**

Librarian is kage's sole writer to permanent memory: a standing background agent that curates, deduplicates, and distills information from all sources — Scout runs, sessions, imports — into atomic notes across all identity × project spaces, and never commits anything without your approval.

Today `kage remember` is the only way facts enter permanent memory. With Librarian, every Scout run and every `kage chat` session becomes a potential input — Librarian decides what's worth keeping, surfaces a crisp approval card, and only writes when you say yes. This is the line from passive backend to active learning system.

**Capstone role:** Librarian is the second of three ADK agents (Scout ✅, Librarian, Monitor). The capstone demo story: Scout deposits findings to a staging queue → Librarian processes the queue, distills and judges each item → Monitor observes both. Three agents, three distinct roles, clear data flow.

---

## Architecture

```
                    EVENT TRIGGERS
  ┌──────────────────────────────────────────────────────┐
  │ kage remember/import → annotation hook               │
  │ kage chat close      → session distillation trigger  │
  │ kage scout run done  → queue items + staleness check │
  │ launchd nightly 2am  → full queue + staleness scan   │
  │ kage librarian review → on-demand                    │
  └──────────────────┬───────────────────────────────────┘
                     │
         ┌───────────▼─────────────────────────────────┐
         │  SQLite staging_queue (durability layer)      │
         │  source: 'scout' | 'session' | 'import'      │
         │  status: 'pending' | 'held'                  │
         └───────────┬─────────────────────────────────┘
                     │
         ┌───────────▼─────────────────────────────────────────┐
         │  Librarian LlmAgent  (src/kage/librarian.py)        │
         │  model: cloud (Sonnet) via LiteLlm                  │
         │  instruction: _LIBRARIAN_INSTRUCTION (inline const)  │
         │                                                      │
         │  tools (FunctionTools — ADK auto-wraps):             │
         │  ┌─ get_staging_queue    — fetch pending items       │
         │  ├─ locate_memory        — SQLite FTS metadata lookup│
         │  ├─ distill_and_judge    — 3e gate + cloud 5-output  │
         │  ├─ deposit_to_queue     — idempotent staging        │
         │  ├─ annotate_memory      — tags/flags/superseded_by  │
         │  ├─ stage_for_deletion   — flag (never deletes)      │
         │  ├─ request_approval     — emit ApprovalRequest      │
         │  ├─ write_note           — post-approval write       │
         │  └─ get_catalog_stats    — feeds kage status         │
         └───────────┬─────────────────────────────────────────┘
                     │
         ┌───────────▼─────────────────────────────────────────┐
         │  ApprovalRequest queue  (approval cards)            │
         │  id, action, reason, sanitized_preview              │
         │  kage librarian approve <id> / reject <id>          │
         └───────────┬─────────────────────────────────────────┘
                     │  (user approves)
         ┌───────────▼─────────────────────────────────────────┐
         │  Permanent memory                                    │
         │  ~/.kage/memory/<project>/<slug>.md  (source of     │
         │  truth) + kage.db FTS5 + ChromaDB (derived)         │
         └─────────────────────────────────────────────────────┘

Threading.Lock + ~/.kage/librarian.lock + SQLite WAL:
one write slot in-process, one process machine-wide.
```

---

## Two-tier memory model

```
TIER 1 — EPHEMERAL (inputs, not permanent)
├── Scout corpus + seen cache  (~/.kage/scout/)
├── kage.db session_turns      (raw chat history)
└── staging_queue              (kage.db, pending decisions)

TIER 2 — PERMANENT (Librarian is sole writer)
└── ~/.kage/memory/ + FTS5 + ChromaDB
```

Only Librarian promotes Tier 1 → Tier 2. `kage remember` and single-file `kage import` are direct-write shortcuts (Tier 3: user-initiated, Librarian annotates after). `kage forget` is also user-initiated and bypasses Librarian entirely.

---

## Distillation output schema (Q5 — locked)

One cloud call per item produces five outputs. This is the entire Librarian judgment in a single round-trip:

```json
{
  "dedup": {
    "verdict": "DISTINCT | DUPLICATE | SUPERSEDES",
    "supersedes_path": null
  },
  "contradiction": {
    "found": false,
    "existing_path": null,
    "description": null
  },
  "quality": "PROMOTE | HOLD | DISCARD",
  "reason": "one sentence — shown verbatim in the approval card",
  "note": {
    "title": "...",
    "body": "...(markdown, ~500 words max, one atomic fact)...",
    "tags": []
  },
  "staleness": ["path/to/possibly_stale_note.md"]
}
```

**Routing logic** (deterministic, after the cloud call):
- `dedup.verdict == DUPLICATE` → route to DISCARD (ignore quality)
- `dedup.verdict == SUPERSEDES` → route to PROMOTE + set `superseded_by` on old note
- `contradiction.found == true` → route to HOLD (reason = description of contradiction)
- otherwise → use `quality` field (PROMOTE / HOLD / DISCARD)

Fields Librarian fills from context (not LLM output): `source`, `project`, `identity`, `created_at`, `recalled_count=0`.

---

## Schema changes (additive-only — no breaking changes)

### Six new columns on `memories` table

```sql
ALTER TABLE memories ADD COLUMN source TEXT DEFAULT 'user';
ALTER TABLE memories ADD COLUMN recalled_count INTEGER DEFAULT 0;
ALTER TABLE memories ADD COLUMN last_recalled TEXT DEFAULT NULL;
ALTER TABLE memories ADD COLUMN librarian_flag TEXT DEFAULT 'none';
ALTER TABLE memories ADD COLUMN superseded_by TEXT DEFAULT NULL;
ALTER TABLE memories ADD COLUMN tags TEXT DEFAULT NULL;
```

All additive. Missing values default safely. `librarian_flag` values: `'none'`, `'suggest_delete'`, `'archived'`. `recalled_count` incremented on every `kage recall` hit. `tags` is a comma-separated string (matches how kage currently handles tags); also written to markdown frontmatter.

### New `staging_queue` table

```sql
CREATE TABLE IF NOT EXISTS staging_queue (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source      TEXT NOT NULL,
    project     TEXT DEFAULT NULL,
    identity    TEXT DEFAULT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    decision    TEXT,
    reason      TEXT,
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sq_status ON staging_queue(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sq_hash ON staging_queue(content_hash, status);
```

`status` values: `'pending'`, `'held'`, `'approved'`, `'rejected'`, `'discarded'`.  
`decision` values: `'promote'`, `'hold'`, `'discard'` (Librarian decisions), `'approve'`, `'reject'` (user decisions).

`project` and `identity` are captured at deposit time (from `_resolve_context()` for session items, NULL for Scout items which have no specific project). `write_note` reads them from the approval_queue's `note_json`, not from `_resolve_context()` at write time — avoids the "wrong project at 2am launchd" bug.

Idempotency: `content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]`. Duplicate pending/held → skip.

### New `approval_queue` table

```sql
CREATE TABLE IF NOT EXISTS approval_queue (
    id              TEXT PRIMARY KEY,
    staging_id      TEXT,
    note_id         TEXT,
    action          TEXT NOT NULL,
    reason          TEXT NOT NULL,
    sanitized_preview TEXT NOT NULL,
    note_json       TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    decided_at      TEXT,
    decision        TEXT,
    FOREIGN KEY (staging_id) REFERENCES staging_queue(id)
);
```

`action` values: `'promote'`, `'delete'`, `'move'`, `'merge'`.
`staging_id` is NULL for `action='delete'` and `action='merge'` (operations on existing permanent notes that have no staging row). `note_id` is NULL for `action='promote'` (the note doesn't exist yet). Exactly one of `staging_id` or `note_id` is non-NULL per row.

---

## Build steps

*Cloud (Sonnet) plans and reviews. Qwen3 writes all code and tests. Tests run local.*

---

### Step 0 — Verify ADK and google-adk version

Quick sanity check before building. Verify `google-adk[extensions]` is installed (already done for Scout), confirm `LlmAgent` import, confirm `InMemoryRunner(node=agent, app_name=...)` still works. Takes 5 minutes. Produces no code — just a green terminal.

```python
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
print("ADK ready")
```

---

### Step 1 — Schema migration + bootstrap

**File:** `src/kage/store.py`

Add the three schema blocks (5 ALTER TABLE + staging_queue + approval_queue) to `Store.init_schema()`. Each ALTER TABLE in its own try/except OperationalError (existing pattern — see lines 79–94 in `store.py`).

**File:** `src/kage/librarian.py` (new file)

Write `_bootstrap_catalog()`:
- Opens `~/.kage/memory/` recursively, finds all `.md` files
- For each: reads frontmatter by scanning for `---\n...\n---\n` block (stdlib only — see pattern below)
- Backfills `source = 'user'` if NULL, `recalled_count = 0` if NULL
- Logs to `audit.jsonl` with `{"event": "librarian_bootstrap", ...}`

Also write `_connect() -> sqlite3.Connection` as a thin wrapper around `runtime.store.connect()` that also calls `_apply_migrations()` (the ALTER TABLE block, idempotent).

**No new dependency.** Use the same manual string-manipulation pattern as `_save()` in `cli.py:203`. Frontmatter is written as an f-string block; fields are updated by regex line substitution (see Step 2 `annotate_memory` for the exact pattern). Do NOT add `python-frontmatter` to `pyproject.toml` — avoids a new dep with no stdlib fallback.

---

### Step 2 — Core tools (all local, no LLM, no cloud)

**File:** `src/kage/librarian.py`

Write these six functions. Each is a plain Python function; ADK auto-wraps as `FunctionTool` when passed in `tools=[]` to `LlmAgent`.

```python
def get_staging_queue(status: str = "pending") -> list[dict]:
    """Return staging queue items with given status. status: 'pending'|'held'|'all'"""
    # SELECT * FROM staging_queue WHERE status = ? (or all) ORDER BY created_at ASC

def locate_memory(query: str, identity: str | None = None, project: str | None = None) -> list[dict]:
    """FTS metadata lookup — WHERE is this topic? Returns path, source, flag, counts.
    Hits memory_fts on body (memory_fts indexes id UNINDEXED + body only — no title/tags columns).
    Returns location metadata NOT note content. Title-level FTS is a future enhancement."""
    # FTS query:
    # SELECT m.id, m.content_path, m.source, m.librarian_flag, m.superseded_by,
    #        m.recalled_count, m.last_recalled
    # FROM memories m
    # JOIN memory_fts fts ON fts.id = m.id
    # JOIN memory_identities mi ON mi.mem_id = m.id   ← required for identity filter
    # WHERE memory_fts MATCH ?
    #   AND (identity is None OR mi.identity = ?)
    #   AND (project is None OR EXISTS (
    #       SELECT 1 FROM memory_projects mp WHERE mp.mem_id = m.id AND mp.project = ?
    #   ))
    # ORDER BY m.recalled_count DESC

def deposit_to_queue(content: str, source: str, reason: str = "",
                     project: str | None = None, identity: str | None = None) -> str:
    """Idempotent deposit. Returns item id (existing or new). source: 'scout'|'session'|'import'.
    project and identity captured at deposit time (not at write time) to survive launchd delay."""
    # content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    # Check for existing pending/held with same hash → return existing id (skip)
    # INSERT with project, identity columns

def annotate_memory(note_id: str, field: str, value: str) -> bool:
    """Write tags/flags/superseded_by autonomously (Tier 1 — no approval needed).
    Allowed fields: 'tags' (additive — appends to comma-separated list), 'librarian_flag', 'superseded_by'.
    Updates both SQLite row AND markdown frontmatter (manual string manipulation — no python-frontmatter).

    Frontmatter update pattern (safe for all fields):
      text = path.read_text()
      end_idx = text.index('\n---\n', 4)          # find closing --- of frontmatter block
      front = text[4:end_idx]                     # frontmatter content (between the two ---)
      body = text[end_idx + 5:]                   # everything after closing ---\n
      if re.search(rf'^{re.escape(field)}:', front, re.MULTILINE):
          front = re.sub(rf'^{re.escape(field)}: .*', f'{field}: {new_value}', front, re.MULTILINE)
      else:
          front = front.rstrip('\n') + f'\n{field}: {new_value}\n'
      path.write_text('---\n' + front + '---\n' + body)

    SQLite update for 'tags' (COALESCE for NULL-safe append):
      UPDATE memories SET tags = COALESCE(tags || ',', '') || ? WHERE id = ?
    SQLite update for other fields: UPDATE memories SET {field} = ? WHERE id = ?
    Returns True on success."""

def stage_for_deletion(note_id: str, reason: str) -> str:
    """Flag note as suggest_delete. Does NOT delete. Returns approval_queue id."""
    # INSERT into approval_queue with action='delete', reason=reason
    # UPDATE memories SET librarian_flag='suggest_delete' WHERE id=note_id

def get_catalog_stats() -> dict:
    """Return catalog stats for kage status: note_count, queue_depth, last_run, notes_by_source."""
    # SELECT COUNT(*) FROM memories
    # SELECT COUNT(*) FROM staging_queue WHERE status='pending'
    # Read ~/.kage/librarian_last_run (ISO timestamp written on each --run-once completion)
    # SELECT source, COUNT(*) FROM memories GROUP BY source
```

---

### Step 3 — distill_and_judge (the only cloud-touching tool)

**File:** `src/kage/librarian.py`

This is the core. Write `distill_and_judge(content: str, source: str) -> dict`.

**3e gate (mandatory, never bypassed):**
```python
def _gate_text(content: str, cfg: dict) -> str:
    """Strip PII from raw text before cloud dispatch. Returns sanitized version.
    Passes cfg extra_patterns so user-configured PII rules are enforced too."""
    from kage.pii import _PII_PATTERNS
    import re
    extra = cfg.get("pii_patterns", [])
    all_patterns = _PII_PATTERNS + extra
    sanitized = content
    for entry in all_patterns:
        try:
            sanitized = re.sub(entry["pattern"], "[REDACTED_PII]", sanitized)
        except re.error:
            pass  # skip malformed user patterns (same guard as _pii_scan)
    return sanitized
```

No `skip_gate` param. No env var bypass. `_gate_text(content, cfg)` is called unconditionally at the top of `distill_and_judge`. Single-pass redaction — no pre-scan needed.

**System prompt (distillation call):**
```
You are Librarian, kage's memory curation agent.

Given a content item and its source, produce a single JSON object with exactly
these five keys: dedup, contradiction, quality, reason, note, staleness.

dedup.verdict: DISTINCT | DUPLICATE | SUPERSEDES
  - DUPLICATE: this information already exists in memory (same fact)
  - SUPERSEDES: this information updates/replaces an existing note (provide its path)
  - DISTINCT: genuinely new

contradiction.found: true if this content contradicts an existing note.
  If true, provide existing_path and a one-sentence description.

quality: PROMOTE | HOLD | DISCARD
  PROMOTE: valuable, actionable, durable fact worth adding to permanent memory
  HOLD: uncertain relevance — surface to user for decision
  DISCARD: ephemeral, redundant, or too low-quality to keep

reason: one sentence, shown verbatim in the approval card. Plain English.

note.body: markdown, one atomic fact only (~200-500 words). Be terse.
note.title: 5-8 words, sentence case.
note.tags: list of 2-5 lowercase keywords.

staleness: list of ~/.kage/memory/ relative paths that this new content makes
  potentially stale. Empty list if none.

Respond with raw JSON only. No prose, no code fences.
```

**Candidate retrieval for dedup/contradiction:**
Before calling the cloud, call `locate_memory(query=title_guess)` to pull the top-5 most similar existing notes. Pass their titles and paths (NOT their bodies) in the system prompt context. The LLM uses these to judge DUPLICATE / SUPERSEDES / contradiction. This keeps egress bounded — no note bodies leave.

**Cloud call:** use `_call_cloud` from `kage.cli` or `kage.cloud` — same pattern as rest of kage. Provider: `runtime.config.data.get("default_provider", "claude")`. Parse response as JSON. If JSON parse fails, return `{"quality": "HOLD", "reason": "parse error — review manually", ...}` (graceful degradation, no crash).

**Token log:** write to `~/.kage/librarian/log/YYYY-MM-DD.jsonl` (same pattern as Scout's `_token_log`):
```json
{"ts": "...", "source": "scout", "prompt_tokens": 412, "completion_tokens": 89, "model": "claude-sonnet-4-6"}
```

---

### Step 4 — write_note + request_approval (HITL gate)

**File:** `src/kage/librarian.py`

Write the two approval-path functions:

```python
def request_approval(staging_id: str, action: str, reason: str,
                     note_json: dict, sanitized_preview: str) -> str:
    """Emit a typed ApprovalRequest. Librarian pauses; user approves via CLI.
    Returns approval_queue id. action: 'promote'|'delete'|'move'|'merge'"""
    # INSERT into approval_queue
    # UPDATE staging_queue SET status='held', decision='hold' WHERE id=staging_id

def write_note(approval_id: str) -> bool:
    """Post-approval: write note to permanent memory. Called after user approves.
    Sequence: file write → memories INSERT → FTS5 INSERT → ChromaDB add
              → staging row update → approval row update → lock release → audit.
    Crash-recoverable: if any DB step fails after file write, kage reindex reconciles."""
    # 1. Read note_json from approval_queue WHERE id=approval_id
    # 2. Generate slug (no new dep):
    #    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    #    mem_id = slug + '-' + uuid4().hex[:8]
    # 3. INSERT into memories FIRST (with all 6 new catalog columns incl. tags, source).
    #    Write DB row before file — if file write fails, stale pointer surfaces in
    #    `kage reindex` as "⚠ missing file, skipping" (cli.py:682) rather than a ghost file.
    # 4. Write ~/.kage/memory/<project>/<mem_id>.md (frontmatter f-string, same pattern as _save()):
    #    front = f"---\nid: {mem_id}\ntitle: {title}\nproject: {project}\ncreated_at: {ts}\n"
    #    front += f"source: {source}\ntags: {','.join(tags)}\nidentities:\n  - {identity}\n---\n\n"
    # 5. INSERT into memory_fts (id, body=note_body)
    # 6. Embed and add to ChromaDB: coll.add(...) — use collection.add() NOT upsert
    #    (same as cli.py:256/710/766). Crash recovery regenerates IDs via kage reindex.
    # 7. UPDATE staging_queue SET status='approved', decided_at=now
    # 8. UPDATE approval_queue SET decision='approved', decided_at=now
    # 9. _write_audit({"event": "librarian_write", "note_id": ..., "source": ..., "ts": ...})
```

**`ApprovalRequest` is a typed dataclass** (not a dict) — this is the renderer-agnostic contract (CLI card now, web card later):
```python
@dataclass
class ApprovalRequest:
    id: str
    action: str          # 'promote' | 'delete' | 'move' | 'merge'
    reason: str          # one sentence from distill_and_judge
    sanitized_preview: str  # first 200 chars of sanitized note body
    created_at: str
```

---

### Step 5 — ADK wiring

**File:** `src/kage/librarian.py`

Write `build_librarian(cfg: dict) -> LlmAgent` and `_run_once(cfg: dict) -> str`.

```python
# Module-level imports (top of librarian.py):
import asyncio, hashlib, json, os, pathlib, re, sqlite3, threading, uuid
from datetime import datetime
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.genai import types
from kage import runtime
from kage.cloud import DEFAULT_PROVIDERS  # defined in cloud.py:24; scout.py re-exports it
from kage.privacy import _write_audit

_LOCKFILE = pathlib.Path.home() / ".kage" / "librarian.lock"
_LIBRARIAN_LAST_RUN = pathlib.Path.home() / ".kage" / "librarian_last_run"
_LOCK = threading.Lock()

# ponytail: copy _LITELLM_PREFIX inline rather than importing scout._LITELLM_PREFIX —
# importing a private symbol from scout.py creates hidden coupling; 4 lines is cheaper.
_LITELLM_PREFIX = {"claude": "anthropic", "openai": "openai", "gemini": "gemini", "openai-compat": "openai"}

def _litellm_target(provider: str, cfg: dict) -> tuple[str, str | None, str | None]:
    """kage provider config → (litellm_model, api_key|None, api_base|None). Mirrors scout.py."""
    pcfg = {**DEFAULT_PROVIDERS.get(provider, {}), **cfg.get("providers", {}).get(provider, {})}
    if "model" not in pcfg:
        raise ValueError(f"librarian cloud_provider '{provider}' not configured")
    ptype = pcfg.get("type", "openai-compat")
    model = f"{_LITELLM_PREFIX.get(ptype, 'openai')}/{pcfg['model']}"
    api_key = os.environ.get(pcfg["api_key_env"]) or None
    if ptype == "openai-compat":
        api_base = pcfg["base_url"] + pcfg.get("chat_path", "/chat/completions").removesuffix("/chat/completions")
    else:
        api_base = None
    return model, api_key, api_base

def build_librarian(cfg: dict) -> LlmAgent:
    """Build the Librarian LlmAgent with all 9 tools."""
    provider = cfg.get("librarian", {}).get("cloud_provider",
               cfg.get("default_provider", "claude"))
    model_str, api_key, api_base = _litellm_target(provider, cfg)
    kwargs = {"model": model_str}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    return LlmAgent(
        name="Librarian",
        model=LiteLlm(**kwargs),
        instruction=_LIBRARIAN_INSTRUCTION,  # inline string constant (see below)
        tools=[
            get_staging_queue,
            locate_memory,
            distill_and_judge,
            deposit_to_queue,
            annotate_memory,
            stage_for_deletion,
            request_approval,
            write_note,
            get_catalog_stats,
        ],
        output_key="librarian_summary",
    )

def _run_once_impl(cfg: dict) -> str:
    """Synchronous entry point for --run-once batch. Returns summary string."""
    agent = build_librarian(cfg)
    runner = InMemoryRunner(node=agent, app_name="kage-librarian")
    return asyncio.run(_run_once_async(runner))

async def _run_once_async(runner: InMemoryRunner) -> str:
    session = await runner.session_service.create_session(
        app_name="kage-librarian", user_id="kage", session_id=str(uuid.uuid4())
    )
    async for _ in runner.run_async(
        user_id="kage",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[
            types.Part(text="Process the staging queue. Review pending items, "
                             "distill and judge each one, request approval for promotes, "
                             "and update the catalog.")
        ]),
    ):
        pass  # drain stream — output lands in session state via output_key, not events
    # The original session object is NOT mutated after run_async — must re-fetch (Scout pattern).
    refreshed = await runner.session_service.get_session(
        app_name="kage-librarian", user_id="kage", session_id=session.id
    )
    return refreshed.state.get("librarian_summary") or "done"
```

**`_LIBRARIAN_INSTRUCTION` is an inline string constant** (same pattern as Scout's `_BROAD_INSTRUCTION` / `_INTEGRATE_INSTRUCTION`). No `src/kage/skills/` directory needed — avoids specifying an unverified loading path and a package include config change. The instruction text is the curation policy defined below; assign it at module level:

```python
_LIBRARIAN_INSTRUCTION = """...(full curation policy here)..."""
```

**Instruction content:**
```markdown
# Librarian — memory curation policy

You are Librarian, kage's sole writer to permanent memory.

## Core rules (never violated)
- One note per atomic fact. Never bundle two facts in one note.
- Never write to permanent memory without request_approval completing.
- Never delete anything — only stage_for_deletion (user decides).
- Gate text with _gate_text before any cloud call (done inside distill_and_judge — do not call distill_and_judge on already-sanitized content twice).

## Per-run process
1. get_staging_queue() — fetch pending items
2. For each item:
   a. distill_and_judge(content, source) — get the five-output judgment
   b. Route per the dedup/contradiction/quality routing rules
   c. PROMOTE → request_approval(action='promote', ...)
   d. HOLD → update staging status to held with reason
   e. DISCARD → update staging status to discarded
   f. If staleness list non-empty → annotate_memory for each stale path
3. get_catalog_stats() — report totals in librarian_summary

## Promotion criteria
A fact is worth PROMOTE if it is:
- Durable (true beyond this session)
- Actionable or referenceable in future recall
- Novel (not already in memory in equivalent form)
- Specific (vague observations → HOLD or DISCARD)

## HOLD criteria
- Uncertain relevance (not sure if durable)
- Decision pending (deferred in a session)
- Contradicts existing note (contradiction.found=true)

## DISCARD criteria
- Ephemeral (true only right now)
- Exact duplicate (dedup.verdict=DUPLICATE)
- Too vague to be useful in recall
```

---

### Step 6 — Write-race safety

**File:** `src/kage/librarian.py`

Add the four-layer write-race protection. Wrap `_run_once` and every write path.

The module-level constants `_LOCK`, `_LOCKFILE`, and `_LIBRARIAN_LAST_RUN` are already defined in Step 5's module-level block. `_acquire_lockfile` and `_release_lockfile` are:

```python
def _acquire_lockfile() -> bool:
    """Advisory lockfile — returns True if acquired, False if another process holds it."""
    if _LOCKFILE.exists():
        try:
            pid = int(_LOCKFILE.read_text().strip())
            os.kill(pid, 0)   # POSIX: raises OSError if process dead
            return False       # process alive → lock held
        except (ValueError, OSError):
            pass  # stale lock — process dead, safe to overwrite
    _LOCKFILE.write_text(str(os.getpid()))
    return True

def _release_lockfile() -> None:
    try:
        _LOCKFILE.unlink(missing_ok=True)
    except OSError:
        pass
```

Wrap `_run_once_impl` with the public `run()` entry point:
```python
def run(cfg: dict) -> str:
    with _LOCK:  # in-process: one coroutine at a time
        if not _acquire_lockfile():
            return "another Librarian process is running — skipping"
        try:
            result = _run_once_impl(cfg)
            _LIBRARIAN_LAST_RUN.write_text(datetime.utcnow().isoformat())
            return result
        finally:
            _release_lockfile()
```

**`_connect()` wrapper** — Librarian needs its own `_connect()` that adds `busy_timeout`:
```python
def _connect() -> sqlite3.Connection:
    """SQLite connection with WAL + busy_timeout for write-safe operation.
    store.connect() sets WAL but NOT busy_timeout — add it here."""
    conn = runtime.store.connect()
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
```
`store.connect()` (store.py:68) sets only `PRAGMA journal_mode=WAL` — the `busy_timeout` is NOT set there. Always use `librarian._connect()`, never `runtime.store.connect()` directly inside `librarian.py`.

ChromaDB `PersistentClient` is NOT multi-process safe. The lockfile is load-bearing for ChromaDB: without it, concurrent Librarian + Scout + chat write paths can corrupt the index. The lockfile ensures only one process writes ChromaDB at a time.

---

### Step 7 — CLI surface

**File:** `src/kage/cli.py` (new `_librarian_app` Typer sub-app, same pattern as `_scout_app`)

Eight subcommands:

```python
@_librarian_app.command("review")
def librarian_review(held: bool = typer.Option(False, "--held")):
    """Process staging queue now. --held re-evaluates held items."""

@_librarian_app.command("approve")
def librarian_approve(approval_id: str):
    """Approve a pending ApprovalRequest by id."""
    # write_note(approval_id) + print confirmation

@_librarian_app.command("reject")
def librarian_reject(approval_id: str, reason: str = typer.Option("", "--reason")):
    """Reject a pending ApprovalRequest."""
    # UPDATE approval_queue SET decision='rejected', decided_at=now
    # UPDATE staging_queue SET status='rejected'

@_librarian_app.command("queue")
def librarian_queue():
    """Show queue counts (pending/held/approved) and recent items."""

@_librarian_app.command("locate")
def librarian_locate(query: str):
    """Metadata lookup — where is this topic in memory?"""
    # calls locate_memory(query) and prints path table

@_librarian_app.command("scan")
def librarian_scan():
    """Full staleness scan on-demand (time-decay + Scout-triggered)."""

@_librarian_app.command("status")
def librarian_status():
    """Catalog stats: note count, queue depth, last run, notes by source."""
    # calls get_catalog_stats()
```

Register: `app.add_typer(_librarian_app, name="librarian")` in `cli.py` (same location as `_scout_app`).

**`kage status` integration:** call `get_catalog_stats()` inside the existing `kage status` handler and append:
```
memory notes : 47 (scout: 12, user: 31, session: 4)
queue depth  : 3 pending, 1 held
librarian    : last run 2026-06-25T02:01:44
```

**`kage doctor` check:** one new check: `librarian.lock` is not stale + ChromaDB dir is writable. Pass/fail.

---

### Step 8 — Session distillation trigger

**Two-pass design:**

**Pass 1 (local, Qwen3, inside `kage chat` close path):**
- Fires when session ends with ≥ 5 exchanges
- Runs on the full raw `session_turns` from SQLite
- Produces a structured pre-summary JSON:
  ```json
  {
    "decisions": ["decided X because Y"],
    "deferred": ["deferred Z until condition W"],
    "rejected": ["rejected A — reason B"],
    "key_context": "one paragraph of background",
    "conclusions": [{"fact": "...", "rationale": "..."}]
  }
  ```
- Calls Ollama directly via `_post_json` (NOT `_call_cloud` — Ollama is not in `DEFAULT_PROVIDERS`):
  ```python
  ollama_url = cfg.get("ollama_url", "http://localhost:11434") + "/api/chat"
  model = cfg.get("ollama_model", "qwen3:14b")
  payload = {"model": model, "messages": [{"role": "system", "content": PRESUMMARY_SYSTEM},
             {"role": "user", "content": transcript}], "stream": False}
  out = _post_json(ollama_url, payload)   # same helper as _answer() cli.py:415
  pre_summary = out["message"]["content"]
  ```
  (`_post_json` is already re-exported in cli.py — importable from `kage.http` or `kage.cli`)
- Stores pre-summary in `staging_queue` with `source='session'`, `project` and `identity` from session row
- Raw transcript stays in SQLite permanently (audit). Pre-summary is ephemeral.

**Pass 2 (Librarian, cloud Sonnet):**
- Librarian's normal distillation run picks up `source='session'` items from the queue
- `distill_and_judge` receives the pre-summary (not raw transcript) → produces atomic notes
- Each `decisions` entry → two notes (decision note + rationale note)
- Each `deferred` entry → HOLD in staging queue with reason "decision pending: ..."
- Each `rejected` entry → one note (rejected decisions are worth remembering)

**Hook location in cli.py:** the chat REPL exits via three paths — the session close is NOT a single clean hook point. Write a `_close_session(session_id: str, cfg: dict) -> None` helper that handles distillation trigger, and call it at all three exit paths:

1. **EOF / KeyboardInterrupt** (`except (EOFError, KeyboardInterrupt)` → `break` then falls out of `while True:`) — add `_close_session(session_id, cfg)` after the `while True:` loop
2. **`/exit` command** — add `_close_session(session_id, cfg)` immediately before the `break` in the `/exit` branch
3. **`/new` command** — add `_close_session(old_session_id, cfg)` before reassigning `session_id` to the new session

`_close_session(session_id, cfg)` is fire-and-forget — runs Pass 1 in a daemon thread to avoid blocking the CLI:
```python
def _close_session(session_id: str, cfg: dict) -> None:
    def _work():
        # read session_turns, count exchanges, if >= 5 → Pass 1 → deposit_to_queue
        ...
    t = threading.Thread(target=_work, daemon=True)
    t.start()
    typer.echo("[kage] session queued for distillation")
```
Daemon=True: thread doesn't prevent process exit if user Ctrl-Cs immediately after. Pass 1 Ollama inference (10–30s) happens in the background; CLI returns immediately.

---

### Step 9 — Launchd + --run-once

**File:** `~/.kage/launchd/com.kage.librarian.plist` (written by `kage librarian install-launchd` or noted in README)

Same pattern as Scout's plist. Nightly 2am, `kage librarian --run-once`, stdout/stderr to `~/.kage/logs/librarian.log`.

**Entry point:** `kage librarian --run-once` (or `kage librarian review` suffices for capstone — the plist is post-capstone).

**Stop conditions (in `_run_once_impl`):**
- `max_items_per_run`: `runtime.config.data.get("librarian_max_items_per_run", 20)`. If queue has more, process first 20 and stop.
  - ponytail: Note that per-item cloud cost = 2 calls (LlmAgent routing + `distill_and_judge`). Default 20 items = up to 40 cloud calls per run. For free-tier providers (50–1000 req/day), this is meaningful. Users can lower `librarian_max_items_per_run` in config.
- Max runtime: 30 min (wall-clock check in the async loop)
- On hitting either limit: write `{"event": "librarian_limit_hit", "items_processed": N}` to audit log

**Crash recovery:** on `_run_once` startup, query `staging_queue` for items with `status='held'` and `created_at < now - 24h` and no `reviewed_at` — these are orphaned by a crash. Log them; don't auto-process (user may have been the one to pause them). Just surface in `kage librarian queue --held` output.

---

### Step 10 — Tests

*Qwen3 writes all tests. Cloud reviews. Run with `uv run pytest`.*

**Layer 1 — Unit tests (no LLM, always CI)** `tests/test_librarian.py`

- `test_deposit_idempotent`: deposit same content twice → same id returned, one row in queue
- `test_deposit_different_content`: deposit two distinct items → two rows
- `test_lockfile_stale_pid_cleanup`: write lockfile with dead PID → `_acquire_lockfile` removes it and returns True
- `test_lockfile_live_pid_blocked`: write lockfile with `os.getpid()` (this process) → `_acquire_lockfile` returns False
- `test_routing_duplicate_discards`: given `distill_and_judge` returning `{"dedup": {"verdict": "DUPLICATE"}, ...}` → item routed to DISCARD (mock the function, test the router)
- `test_routing_contradiction_holds`: `contradiction.found=True` → status='held'
- `test_routing_promote_creates_approval`: `quality=PROMOTE` → approval_queue gets one row
- `test_annotate_tags_additive`: `annotate_memory(id, 'tags', 'new-tag')` on note with existing tags → tag appended, not replaced (both in frontmatter and SQLite)
- `test_schema_migration_idempotent`: call `init_schema()` twice → no crash (ALTER TABLE already exists → caught)
- `test_gate_text_strips_email`: `_gate_text("contact me at foo@bar.com")` → `[REDACTED_PII]` in output
- `test_gate_text_clean_passthrough`: clean text → returned unchanged
- `test_approval_request_dataclass`: `ApprovalRequest` fields are accessible as attributes

**Layer 2 — Golden-set replay (mocked LLM, always CI)**

Mock `distill_and_judge` with pre-recorded responses (stored in `tests/fixtures/librarian/`):
- `fixtures/promote_distinct.json` — DISTINCT + PROMOTE → write_note called
- `fixtures/duplicate_discard.json` — DUPLICATE → staging status=discarded, no approval_queue row
- `fixtures/supersedes_promote.json` — SUPERSEDES(old_path) → promote + annotate_memory on old path
- `fixtures/contradiction_hold.json` — contradiction.found=True → staging status=held

**Layer 3 — Smoke test (live LLM, local only, `KAGE_LIVE_TESTS=1`)**

- Deposit one item to staging queue
- Call `_run_once(cfg)`
- Assert approval_queue has ≥ 1 row OR staging_queue item has status='held' or 'discarded'
- (Any of the three outcomes is valid — just not stuck in 'pending')

**3e gate integration test (Layer 1):**
- Assert `distill_and_judge` function signature has no `skip_gate` parameter
- Assert `_gate_text` is called unconditionally inside `distill_and_judge` (monkeypatch `_gate_text`, call `distill_and_judge` with any content, assert `_gate_text` was called)

---

## Decisions summary

| # | Decision | Rationale |
|---|---|---|
| 1 | Single `LlmAgent`, not `Workflow` | Per-item judgment is conditional branching — Workflow is for multi-node pipelines |
| 2 | Librarian is STANDALONE, not inside Scout's Workflow | Would hardwire them and break every trigger path that isn't "Scout just ran" |
| 3 | ADK `LoopAgent` left as seam | ponytail: single LlmAgent handles small queues; upgrade when Monitor signals backlog |
| 4 | 3e gate lives INSIDE `distill_and_judge` (not caller) | Gate is non-negotiable; placing it inside the function makes bypass impossible |
| 5 | Candidate titles (not bodies) sent to cloud for dedup | Bounded egress; bodies stay local; gate still applies to the item content |
| 6 | No `hold_count` | User postponing is intentional. AI forcing a deadline violates HITL |
| 7 | Session distillation two-pass | Qwen3 pre-summarizes locally (any length); Sonnet distills the pre-summary (bounded) |
| 8 | Lockfile is load-bearing (not advisory) | ChromaDB PersistentClient is NOT multi-process safe — lockfile is the only guard |
| 9 | `max_items_per_run` placeholder (default 20) | Real token budget belongs to Monitor brainstorm (circular dep); placeholder avoids overclaiming |
| 10 | `write_note` crash-recoverable via `kage reindex` | File write is first; if DB update fails, reindex restores consistency |

---

## Capstone minimum scope (July 6 deadline)

Must ship for judges:
- `staging_queue` schema + `deposit_to_queue` (idempotent)
- `distill_and_judge` (3e gate + cloud call — five outputs in one)
- PROMOTE / HOLD / DISCARD routing
- `write_note` (post-approval write to permanent memory)
- `request_approval` typed gate (HITL — direct scoring criterion)
- `kage librarian review` / `approve` / `reject` / `queue` / `locate` CLI
- `_LIBRARIAN_INSTRUCTION` inline string constant (curation policy — judges score instruction quality directly)
- `locate_memory` (Scout pre-check)
- Scout-triggered staleness signals
- Layer 1 + Layer 2 tests (CI-green)

Post-capstone (do not block on these):
- Session distillation trigger (Step 8)
- Launchd plist (Step 9)
- `kage doctor` check
- Bootstrap catalog scan
- `kage librarian scan` full implementation (stub for capstone)
- LoopAgent upgrade
- OTel trace seam

---

## Seams left open (do not close in v1)

- **ADK OpenTelemetry export** — don't suppress traces; future dashboard reads agent observability from OTel directly
- **`_token_log` JSONL** — Monitor aggregates across Scout + Librarian; pattern is locked, format is `{"ts", "source", "prompt_tokens", "completion_tokens", "model"}`
- **`ApprovalRequest` as typed dataclass** — CLI is one renderer; web/desktop card is another; zero internal changes when the UI arrives
- **`before_model_callback` on the LlmAgent** — 3e v2 reversible masking replaces `_gate_text` at the model-request boundary, same as Scout's `_pii_seam`. The seam point is `build_librarian()`; add `before_model_callback=_pii_seam` now even if `_pii_seam` is a pass-through
- **`kage_locate` + `kage_queue_status` MCP tools** — add to `mcp_server.py` when Librarian ships, so Odysseus/external MCP clients can query the catalog

---

## File manifest

```
src/kage/librarian.py          — new (all Librarian logic; _LIBRARIAN_INSTRUCTION inline)
src/kage/store.py              — modify: schema migration (6 ALTER TABLE + 2 new tables)
src/kage/cli.py                — modify: _librarian_app sub-app + kage status hook + _close_session
tests/test_librarian.py        — new (Layer 1 + 2 tests)
tests/fixtures/librarian/      — new dir (Layer 2 golden fixtures)
pyproject.toml                 — version bump 0.15.0 → 0.16.0
```

---

*v1 — cloud-authored (Sonnet 4.6, 2026-06-26). Cold review pending.*

> **v3 changelog (cold review #2, independent subagent, 2026-06-26):** 3 blockers, 4 majors, 6 minors caught.
> - **(Blocker) Crash recovery claim false** — `kage reindex` scans `memories` table rows, NOT the filesystem; a file written before DB insert = permanent ghost. Fixed: reverse write order — INSERT into memories FIRST (stale pointer if file write fails; surfaces in `kage reindex` line 682 warning); write file second.
> - **(Blocker) Pass 1 Ollama call crashes** — `_call_cloud("ollama", ...)` raises `CloudError("Unknown provider 'ollama'")` — Ollama is not in `DEFAULT_PROVIDERS`. Fixed: use `_post_json(ollama_url, payload)` directly (same pattern as `_answer()` cli.py:404-415).
> - **(Blocker) Absent-field frontmatter insertion regex corrupts file** — `re.sub(r'^---$', ...)` replaces the OPENING `---` or all `---` lines including body thematic breaks. Fixed: use index-based split on `'\n---\n'` end marker; insert field before closing `---`.
> - **(Major) `staging_queue` missing `project` and `identity` columns** — `write_note` at 2am launchd won't know which project/identity to write to. Fixed: add `project TEXT DEFAULT NULL, identity TEXT DEFAULT NULL` to `staging_queue`; captured at `deposit_to_queue` time.
> - **(Major) `stage_for_deletion` violates `approval_queue.staging_id NOT NULL`** — deletion targets are existing permanent notes, not staging items; no staging row exists. Fixed: make `staging_id` nullable; add `note_id TEXT DEFAULT NULL` column for delete/merge ops.
> - **(Major) `_close_session` blocks CLI for 30-60s** — Pass 1 is synchronous Ollama inference. Fixed: run in `threading.Thread(daemon=True)`, return immediately.
> - **(Major) `sha256(content.encode())[:16]` is invalid Python** — `sha256` is not a builtin; HASH object is not subscriptable. Fixed: `hashlib.sha256(content.encode()).hexdigest()[:16]`; `hashlib` added to imports.
> - **(Minor) Ponytail comment contradicts import** — said "copy, don't import" then imported from scout private namespace. Fixed: `DEFAULT_PROVIDERS` from `kage.cloud` (where defined); `_LITELLM_PREFIX` defined inline (4-line dict copy, no cross-module private import).
> - **(Minor) Module imports block incomplete** — missing `hashlib`, `json`, `sqlite3`. Added.
> - **(Minor) Schema header says "Five new columns" — specifies six**. Fixed to "Six".
> - **(Minor) `annotate_memory` tags append needs COALESCE** — `NULL || ',' || 'tag'` = NULL in SQLite. Fixed: `COALESCE(tags || ',', '') || new_tag`.
> - **(Minor) `locate_memory` identity filter underspecified** — needs `JOIN memory_identities`. Added explicit JOIN.


> **v2 changelog (cold review #1, independent subagent, 2026-06-26):** 3 blockers, 4 majors, 6 minors caught.
> - **(Blocker) `_litellm_target` wrong call signature and result misuse** — takes `(provider, cfg)` not `(cfg)`, returns `(model_str, api_key, api_base)` 3-tuple not a model object; `LiteLlm(**kwargs)` must be constructed from the tuple (conditional api_key/api_base). Fixed in Step 5.
> - **(Blocker) `locate_memory` FTS references nonexistent columns** — `memory_fts` indexes `id UNINDEXED, body` only; no `title` or `tags` columns exist. Fixed: FTS on `body` only; title-level lookup noted as future enhancement.
> - **(Blocker) `python-frontmatter` not in pyproject.toml** — removed dependency; use same manual string-manipulation pattern as `_save()` in `cli.py:203-212`. Fixed in Step 1 and Step 4.
> - **(Major) `busy_timeout=5000` falsely claimed as already set** — `store.connect()` sets only WAL; added `PRAGMA busy_timeout=5000` to Librarian's `_connect()` wrapper.
> - **(Major) `_LOCKFILE_LAST_RUN` undefined** — defined as module-level constant; `datetime` import added.
> - **(Major) `collection.upsert` doesn't exist in kage** — changed to `collection.add()` (existing pattern); crash recovery via `kage reindex` already handles the idempotency case.
> - **(Major) `annotate_memory` for `tags` has no SQLite column** — added 6th `ALTER TABLE ADD COLUMN tags TEXT DEFAULT NULL`; tag update writes both frontmatter and SQLite.
> - **(Minor) `_gate_text` ignores cfg extra_patterns** — fixed to pass `cfg.get("pii_patterns", [])` through.
> - **(Minor) Session distillation has 3 exit points not 1** — `_close_session()` helper specified, called at all three chat-close paths.
> - **(Minor) Double cloud calls per item not surfaced** — noted in `max_items_per_run` comment; LlmAgent routing + `distill_and_judge` = 2 calls per item.
> - **(Minor) Skill file loading unspecified** — switched to inline `_LIBRARIAN_INSTRUCTION` string constant (Scout pattern); no skills/ dir needed.
> - **(Minor) `slugify` unspecified** — inline regex specified.
> - **(Minor) Step-level capstone/deferred markers missing** — [CAPSTONE] / [POST-CAPSTONE] added per step.
