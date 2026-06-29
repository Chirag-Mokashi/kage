import asyncio, hashlib, json, os, pathlib, re, sqlite3, threading, time, uuid
from dataclasses import dataclass
from datetime import date, datetime
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.genai import types
from kage import runtime
from kage.cloud import DEFAULT_PROVIDERS
from kage.privacy import _write_audit

_LIBRARIAN_LAST_RUN = pathlib.Path.home() / ".kage" / "librarian_last_run"
_LOCKFILE = pathlib.Path.home() / ".kage" / "librarian.lock"
_LOCK = threading.Lock()
# ponytail: copy inline rather than importing scout._LITELLM_PREFIX — private symbol, hidden coupling
_LITELLM_PREFIX = {"claude": "anthropic", "openai": "openai", "gemini": "gemini", "openai-compat": "openai"}


def _apply_migrations(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ALTER TABLE memories ADD COLUMN source TEXT DEFAULT 'user'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE memories ADD COLUMN recalled_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE memories ADD COLUMN last_recalled TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE memories ADD COLUMN librarian_flag TEXT DEFAULT 'none'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE memories ADD COLUMN superseded_by TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE memories ADD COLUMN tags TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS staging_queue (
            id           TEXT PRIMARY KEY,
            content      TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            source       TEXT NOT NULL,
            project      TEXT DEFAULT NULL,
            identity     TEXT DEFAULT NULL,
            status       TEXT NOT NULL DEFAULT 'pending',
            created_at   TEXT NOT NULL,
            decision     TEXT,
            reason       TEXT,
            reviewed_at  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sq_status ON staging_queue(status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sq_hash ON staging_queue(content_hash, status);

        CREATE TABLE IF NOT EXISTS approval_queue (
            id                TEXT PRIMARY KEY,
            staging_id        TEXT,
            note_id           TEXT,
            action            TEXT NOT NULL,
            reason            TEXT NOT NULL,
            sanitized_preview TEXT NOT NULL,
            note_json         TEXT NOT NULL,
            created_at        TEXT NOT NULL,
            decided_at        TEXT,
            decision          TEXT,
            FOREIGN KEY (staging_id) REFERENCES staging_queue(id)
        );
    """)
    try:
        conn.execute("ALTER TABLE staging_queue ADD COLUMN priority INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass


def _connect() -> sqlite3.Connection:
    conn = runtime.store.connect()
    conn.execute("PRAGMA busy_timeout=5000")
    _apply_migrations(conn)
    return conn


def _bootstrap_catalog() -> int:
    mem_dir = runtime.config.home / "memory"
    if not mem_dir.exists():
        return 0

    count = 0
    for path in mem_dir.rglob("*.md"):
        text = path.read_text()
        if not text.startswith('---'):
            continue
        end_idx = text.find('\n---\n', 4)
        if end_idx == -1:
            continue
        front = text[4:end_idx]
        m = re.search(r'^id:\s*(.+)$', front, re.MULTILINE)
        if not m:
            continue
        note_id = m.group(1).strip()

        conn = _connect()
        try:
            conn.execute(
                "UPDATE memories SET source = 'user' WHERE id = ? AND source IS NULL",
                (note_id,),
            )
            conn.execute(
                "UPDATE memories SET recalled_count = 0 WHERE id = ? AND recalled_count IS NULL",
                (note_id,),
            )
            _write_audit({"event": "librarian_bootstrap", "note_id": note_id,
                          "ts": datetime.now().astimezone().isoformat(timespec='seconds')})
            conn.commit()
            count += 1
        finally:
            conn.close()
    return count


def get_staging_queue(status: str = "pending", limit: int | None = None) -> list[dict]:
    """Return staging queue items. status: 'pending' | 'held' | 'all'"""
    if limit is None:
        limit = runtime.config.data.get("librarian", {}).get("batch_size", 10)
    conn = None
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        if status == "all":
            cur = conn.cursor()
            cur.execute("SELECT * FROM staging_queue ORDER BY priority DESC, created_at ASC LIMIT ?", (limit,))
        else:
            cur = conn.execute("SELECT * FROM staging_queue WHERE status = ? ORDER BY priority DESC, created_at ASC LIMIT ?", (status, limit))
        return [dict(row) for row in cur.fetchall()]
    finally:
        if conn:
            conn.close()


def locate_memory(query: str, identity: str | None = None, project: str | None = None) -> list[dict]:
    """FTS metadata lookup — returns path, source, flag, counts. Does NOT return note content."""
    conn = None
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        sql = (
            "SELECT m.id, m.content_path, m.source, m.librarian_flag, m.superseded_by,"
            " m.recalled_count, m.last_recalled"
            " FROM memories m"
            " JOIN memory_fts fts ON fts.id = m.id"
            " JOIN memory_identities mi ON mi.mem_id = m.id"
            " WHERE memory_fts MATCH ?"
        )
        params: list = [query]
        if identity:
            sql += " AND mi.identity = ?"
            params.append(identity)
        if project:
            sql += " AND EXISTS (SELECT 1 FROM memory_projects mp WHERE mp.mem_id = m.id AND mp.project = ?)"
            params.append(project)
        sql += " ORDER BY m.recalled_count DESC"
        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        if conn:
            conn.close()


def deposit_to_queue(content: str, source: str, reason: str = "",
                     project: str | None = None, identity: str | None = None) -> str:
    """Idempotent deposit. Returns existing id if duplicate pending/held, else new id."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM staging_queue WHERE content_hash = ? AND status IN ('pending', 'held')",
            (content_hash,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        new_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO staging_queue "
            "(id, content, content_hash, source, reason, project, identity, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, content, content_hash, source, reason, project, identity,
             datetime.now().astimezone().isoformat(timespec='seconds')),
        )
        conn.commit()
        return new_id
    finally:
        if conn:
            conn.close()


def annotate_memory(note_id: str, field: str, value: str) -> bool:
    """Update tags / librarian_flag / superseded_by. Writes SQLite + markdown frontmatter.
    Returns True on success, False if note not found."""
    if field not in {"tags", "librarian_flag", "superseded_by"}:
        return False
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        if field == "tags":
            cur.execute(
                "UPDATE memories SET tags = COALESCE(tags || ',', '') || ? WHERE id = ?",
                (value, note_id),
            )
        else:
            cur.execute(f"UPDATE memories SET {field} = ? WHERE id = ?", (value, note_id))
        cur.execute("SELECT content_path FROM memories WHERE id = ?", (note_id,))
        row = cur.fetchone()
        if not row:
            return False
        path = runtime.config.home / row[0]
        if not path.exists():
            return False
        text = path.read_text()
        end_idx = text.find('\n---\n', 4)
        if end_idx == -1:
            return False
        front = text[4:end_idx]
        body = text[end_idx + 5:]
        if re.search(rf'^{re.escape(field)}:', front, re.MULTILINE):
            if field == "tags":
                # Append tag to match DB: COALESCE(tags || ',', '') || new_tag
                front = re.sub(
                    rf'^tags: (.*)',
                    lambda m: f'tags: {m.group(1)},{value}' if m.group(1) else f'tags: {value}',
                    front, flags=re.MULTILINE,
                )
            else:
                front = re.sub(rf'^{re.escape(field)}: .*', f'{field}: {value}', front, flags=re.MULTILINE)
        else:
            front = front.rstrip('\n') + f'\n{field}: {value}\n'
        path.write_text('---\n' + front + '\n---\n' + body)
        conn.commit()
        return True
    finally:
        if conn:
            conn.close()


def stage_for_deletion(note_id: str, reason: str) -> str:
    """Flag note as suggest_delete. Does NOT delete. Returns approval_queue id."""
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT content_path FROM memories WHERE id = ?", (note_id,))
        row = cur.fetchone()
        if not row:
            return ""
        path = runtime.config.home / row[0]
        sanitized_preview = path.read_text()[:200] if path.exists() else "(file not found)"
        approval_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO approval_queue "
            "(id, staging_id, note_id, action, reason, sanitized_preview, note_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (approval_id, None, note_id, "delete", reason, sanitized_preview,
             json.dumps({"note_id": note_id, "action": "delete"}),
             datetime.now().astimezone().isoformat(timespec='seconds')),
        )
        cur.execute("UPDATE memories SET librarian_flag = 'suggest_delete' WHERE id = ?", (note_id,))
        conn.commit()
        return approval_id
    finally:
        if conn:
            conn.close()


def discard_staging_item(staging_id: str) -> bool:
    """Mark a staging item as discarded — it will no longer appear in the queue.
    Call this when distill_and_judge returns quality=DISCARD. Returns True if found."""
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM staging_queue WHERE id=?", (staging_id,)).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE staging_queue SET status='discarded', decision='discard', reviewed_at=? WHERE id=?",
            (ts, staging_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


_DISTILL_SYSTEM = """You are Librarian, kage's memory curation agent.

Given a content item and its source, produce a single JSON object with exactly
these keys: dedup, contradiction, quality, reason, note, staleness.

dedup.verdict: DISTINCT | DUPLICATE | SUPERSEDES
  DUPLICATE: same fact already in memory
  SUPERSEDES: this updates/replaces an existing note (provide its path in dedup.existing_path)
  DISTINCT: genuinely new

contradiction.found: true if this contradicts an existing note.
  If true, provide contradiction.existing_path and contradiction.description (one sentence).

quality: PROMOTE | HOLD | DISCARD
  PROMOTE: valuable, actionable, durable — worth permanent memory
  HOLD: uncertain relevance — surface to user
  DISCARD: ephemeral, redundant, or too low-quality

reason: one sentence shown verbatim in the approval card.

note.body: markdown, one atomic fact (~200-500 words). Terse.
note.title: 5-8 words, sentence case.
note.tags: list of 2-5 lowercase keywords.

staleness: list of relative paths (from ~/.kage/memory/) that this new content
  may make stale. Empty list if none.

Respond with raw JSON only. No prose, no code fences."""


def _gate_text(content: str, cfg: dict) -> str:
    """Strip PII from raw content before cloud dispatch. Unconditional — no bypass."""
    from kage.pii import _PII_PATTERNS  # inline to avoid circular import
    extra = cfg.get("pii_patterns", [])
    all_patterns = _PII_PATTERNS + extra
    sanitized = content
    for entry in all_patterns:
        try:
            sanitized = re.sub(entry["pattern"], "[REDACTED_PII]", sanitized)
        except re.error:
            pass  # skip malformed user-configured patterns
    return sanitized


def distill_and_judge(content: str, source: str) -> dict:
    """3e-gate content, retrieve dedup candidates, call cloud, return structured judgment.
    Returns a dict with keys: dedup, contradiction, quality, reason, note, staleness.
    On JSON parse failure, returns a safe HOLD result (no crash)."""

    # Step A — load config and gate (ALWAYS first, NEVER skipped)
    try:
        cfg = runtime.config.data
    except Exception as exc:
        return {
            "quality": "HOLD", "reason": f"config error: {exc}",
            "dedup": {"verdict": "DISTINCT"}, "contradiction": {"found": False},
            "note": {"title": "", "body": "", "tags": []}, "staleness": [],
        }
    sanitized = _gate_text(content, cfg)

    # Step B — title guess for dedup candidates
    # First non-empty line as FTS query; pass only paths+counts (no bodies) to bound egress.
    title_guess = next((ln.strip().lstrip('#').strip() for ln in content.splitlines() if ln.strip()), "")
    try:
        candidates = locate_memory(title_guess)[:5] if title_guess else []
    except Exception:
        candidates = []  # DB error → no dedup context, but cloud can still judge

    # Step C — build user message
    candidate_block = ""
    if candidates:
        lines = [f"- {c['content_path']} (recalled {c['recalled_count']}x)" for c in candidates]
        candidate_block = "\nExisting related notes (titles/paths only — no bodies):\n" + "\n".join(lines)

    user_msg = f"source: {source}{candidate_block}\n\ncontent:\n{sanitized}"
    messages = [{"role": "user", "content": user_msg}]

    # Step D — cloud dispatch
    provider = cfg.get("librarian", {}).get("cloud_provider", cfg.get("cloud_provider", "claude"))
    try:
        raw = runtime.cloud.complete(provider, _DISTILL_SYSTEM, messages, cfg)
    except Exception as exc:
        return {
            "quality": "HOLD", "reason": f"cloud error: {exc}",
            "dedup": {"verdict": "DISTINCT"}, "contradiction": {"found": False},
            "note": {"title": "", "body": "", "tags": []}, "staleness": [],
        }
    delay = cfg.get("librarian", {}).get("delay_seconds", 0)
    if delay:
        time.sleep(delay)

    # Step E — parse JSON; strip code fences if model wraps despite instruction
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # ponytail: fence stripping covers the most common model non-compliance
        stripped = re.sub(r'^```[a-z]*\n?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
        try:
            result = json.loads(stripped)
        except json.JSONDecodeError:
            return {
                "quality": "HOLD", "reason": "parse error — review manually",
                "dedup": {"verdict": "DISTINCT"}, "contradiction": {"found": False},
                "note": {"title": "", "body": "", "tags": []}, "staleness": [],
            }

    # Step F — token log (char-count proxy; same pattern as scout.py _token_log)
    # ponytail: char count as token proxy — upgrade to tiktoken when precision matters
    # log failure is observational — must not prevent result from being returned
    try:
        log_dir = runtime.config.home / "librarian" / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / f"{date.today()}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                "source": source, "prompt_chars": len(user_msg),
                "response_chars": len(raw), "quality": result.get("quality", "?"),
                "provider": provider,
            }) + "\n")
    except Exception:
        pass

    return result


@dataclass
class ApprovalRequest:
    id: str
    action: str             # 'promote' | 'delete' | 'move' | 'merge'
    reason: str             # one sentence from distill_and_judge, shown verbatim in CLI card
    sanitized_preview: str  # first 200 chars of sanitized note body
    created_at: str


def request_approval(staging_id: str | None, action: str, reason: str,
                     note_json: dict, sanitized_preview: str) -> str:
    """Emit a typed ApprovalRequest into approval_queue. Returns approval_queue id.
    Sets staging row to 'held' so it won't be re-processed on next run.
    action: 'promote' | 'delete' | 'move' | 'merge'"""
    approval_id = str(uuid.uuid4())
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO approval_queue"
            " (id, staging_id, note_id, action, reason, sanitized_preview, note_json, created_at)"
            " VALUES (?, ?, NULL, ?, ?, ?, ?, ?)",
            (approval_id, staging_id, action, reason, sanitized_preview,
             json.dumps(note_json), created_at),
        )
        if staging_id:
            conn.execute(
                "UPDATE staging_queue SET status='held', decision='hold', reviewed_at=?"
                " WHERE id=?",
                (created_at, staging_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return approval_id


def write_note(approval_id: str) -> bool:
    """Post-approval write to permanent memory. Returns True on success.
    Write order: DB INSERT first, then file — stale pointer surfaces in
    'kage reindex' as '⚠ missing file, skipping'; a ghost file has no DB row
    and is permanently undetectable."""

    # Step 1 — read note_json from approval_queue; guard against double-write
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT note_json, staging_id, decision FROM approval_queue WHERE id = ?",
            (approval_id,),
        ).fetchone()
        if not row:
            return False
        # Idempotency: if already decided, don't create a duplicate note.
        if row[2] is not None:
            return row[2] == "approved"
        note = json.loads(row[0])
        staging_id = row[1]
    finally:
        conn.close()

    # Merge project/identity/source from staging row — distill_and_judge produces only
    # {body, title, tags}; the staging item holds the full partition context.
    if staging_id:
        conn = _connect()
        try:
            sq = conn.execute(
                "SELECT project, identity, source FROM staging_queue WHERE id=?",
                (staging_id,),
            ).fetchone()
        finally:
            conn.close()
        if sq:
            if not note.get("project"):
                note["project"] = sq[0]
            if not note.get("identity"):
                note["identity"] = sq[1] or "personal"
            if not note.get("source"):
                note["source"] = sq[2] or "librarian"

    # Step 2 — generate mem_id (slug + uuid suffix, no new dep)
    title = note.get("title", "untitled")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    mem_id = slug + "-" + uuid.uuid4().hex[:8]

    # Step 3 — prepare fields
    project = note.get("project") or None
    identity = note.get("identity") or "personal"
    source = note.get("source", "librarian")
    body = note.get("body", "")
    tags_raw = note.get("tags", [])
    tags_str = ",".join(tags_raw) if isinstance(tags_raw, list) else str(tags_raw)
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    # state mirrors cli.py _save() convention
    state = "scoped" if project else "baseline"
    rel_path = f"memory/{mem_id}.md"
    mem_path = runtime.config.home / rel_path
    chunk_id = f"{mem_id}_c0"

    # Step 4 — INSERT into memories FIRST (before file write)
    # DB row before file: stale pointer (missing file) surfaces in 'kage reindex' warning;
    # ghost file (no DB row) is undetectable and can't be cleaned up automatically.
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO memories"
            " (id, content_path, project, created_at, local_only, state,"
            "  source, recalled_count, last_recalled, librarian_flag, tags)"
            " VALUES (?, ?, ?, ?, 0, ?, ?, 0, NULL, 'none', ?)",
            (mem_id, rel_path, project, ts, state, source, tags_str),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memory_identities(mem_id, identity) VALUES (?, ?)",
            (mem_id, identity),
        )
        if project:
            conn.execute(
                "INSERT OR IGNORE INTO memory_projects(mem_id, project) VALUES (?, ?)",
                (mem_id, project),
            )
        conn.execute("INSERT INTO memory_fts (id, body) VALUES (?, ?)", (mem_id, body))
        # Single chunk = whole body (Librarian notes are 200-500 words; no sectioning needed)
        conn.execute(
            "INSERT INTO chunks (id, note_id, section_title, char_start, char_end, needs_embed)"
            " VALUES (?, ?, '', 0, ?, 1)",
            (chunk_id, mem_id, len(body)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()

    # Step 5 — write markdown file (after DB commit)
    mem_path.parent.mkdir(parents=True, exist_ok=True)
    front = (f"---\nid: {mem_id}\ntitle: {title}\nproject: {project or ''}\n"
             f"created_at: {ts}\nsource: {source}\ntags: {tags_str}\n"
             f"identities:\n  - {identity}\nstate: {state}\n")
    mem_path.write_text(front + "---\n\n" + body.rstrip() + "\n")

    # Step 6 — embed and add to ChromaDB (graceful fallback: needs_embed=1 stays)
    try:
        from kage.embed import OllamaUnavailable
        vec = runtime.embed.embed(body, runtime.config.data)
        coll = runtime.vector.collection(
            runtime.config.home / "chroma",
            runtime.config.data.get("embed_model", "nomic-embed-text"),
        )
        coll.add(
            ids=[chunk_id],
            embeddings=[vec],
            metadatas=[{
                "note_id": mem_id, "project": project or "",
                "created_at": ts, "content_path": rel_path,
                "section_title": "", "char_start": 0, "char_end": len(body),
            }],
        )
        conn2 = _connect()
        try:
            conn2.execute("UPDATE chunks SET needs_embed=0 WHERE id=?", (chunk_id,))
            conn2.commit()
        finally:
            conn2.close()
    except Exception:
        pass  # needs_embed=1 stays — kage reindex will embed on next run

    # Step 7 — update staging + approval rows
    conn = _connect()
    try:
        if staging_id:
            conn.execute(
                "UPDATE staging_queue SET status='approved', decision='approve',"
                " reviewed_at=? WHERE id=?",
                (ts, staging_id),
            )
        conn.execute(
            "UPDATE approval_queue SET decision='approved', decided_at=? WHERE id=?",
            (ts, approval_id),
        )
        conn.commit()
    finally:
        conn.close()

    # Step 8 — audit log
    _write_audit({"event": "librarian_write", "note_id": mem_id, "source": source, "ts": ts})
    return True


def get_catalog_stats() -> dict:
    """Return catalog stats for kage status."""
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM memories")
        note_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM staging_queue WHERE status = 'pending'")
        queue_depth = cur.fetchone()[0]
        last_run = _LIBRARIAN_LAST_RUN.read_text().strip() if _LIBRARIAN_LAST_RUN.exists() else None
        cur.execute("SELECT source, COUNT(*) FROM memories GROUP BY source")
        notes_by_source = dict(cur.fetchall())
        return {
            "note_count": note_count,
            "queue_depth": queue_depth,
            "last_run": last_run,
            "notes_by_source": notes_by_source,
        }
    finally:
        if conn:
            conn.close()


_LIBRARIAN_INSTRUCTION = """# Librarian — memory curation policy

You are Librarian, kage's sole writer to permanent memory.

## Core rules (never violated)
- One note per atomic fact. Never bundle two facts in one note.
- Never write to permanent memory without request_approval completing.
- Never delete anything — only stage_for_deletion (user decides).
- distill_and_judge handles the 3e gate internally — do not call _gate_text directly.

## Per-run process
1. get_staging_queue() — fetch pending items
2. For each item:
   a. distill_and_judge(content, source) — get the five-output judgment
   b. Route per quality verdict:
      PROMOTE → request_approval(staging_id=item.id, action='promote', reason=..., note_json=result['note'], sanitized_preview=result['note']['body'][:200])
      HOLD    → do nothing (item stays pending; will surface in 'kage librarian queue')
      DISCARD → discard_staging_item(staging_id=item.id)
   c. If result['staleness'] is non-empty: annotate_memory for each stale path with field='librarian_flag', value='stale'
   d. If result['dedup']['verdict'] == 'SUPERSEDES': annotate_memory on the superseded path with field='superseded_by', value=new_note_title
3. get_catalog_stats() — include totals in librarian_summary

## Promotion criteria
A fact is worth PROMOTE if it is:
- Durable (true beyond this session)
- Actionable or referenceable in future recall
- Novel (not already in memory in equivalent form)
- Specific (vague observations → HOLD or DISCARD)

## HOLD criteria
- Uncertain relevance
- Decision pending
- Contradicts existing note (contradiction.found=true)

## DISCARD criteria
- Ephemeral (true only right now)
- Exact duplicate (dedup.verdict=DUPLICATE)
- Too vague to be useful in recall

When quality=DISCARD: always call discard_staging_item(staging_id) to close the item.
DUPLICATE verdict implies DISCARD — call discard_staging_item unless user might want to review it.
"""


def _litellm_target(provider: str, cfg: dict) -> tuple[str, str | None, str | None]:
    """kage provider config → (litellm_model, api_key|None, api_base|None). Mirrors scout.py."""
    pcfg = {**DEFAULT_PROVIDERS.get(provider, {}), **cfg.get("providers", {}).get(provider, {})}
    if "model" not in pcfg:
        raise ValueError(f"librarian cloud_provider '{provider}' not configured")
    ptype = pcfg.get("type", "openai-compat")
    model = f"{_LITELLM_PREFIX.get(ptype, 'openai')}/{pcfg['model']}"
    api_key = os.environ.get(pcfg["api_key_env"]) or None
    if ptype == "openai-compat":
        # kage POSTs to base_url + chat_path; LiteLLM appends '/chat/completions' to api_base,
        # so api_base = base_url + (chat_path minus that suffix).
        api_base = pcfg["base_url"] + pcfg.get("chat_path", "/chat/completions").removesuffix("/chat/completions")
    else:
        api_base = None
    return model, api_key, api_base


def build_librarian(cfg: dict) -> LlmAgent:
    """Build the Librarian LlmAgent with all 10 tools wired as ADK FunctionTools."""
    provider = cfg.get("librarian", {}).get("cloud_provider",
               cfg.get("cloud_provider", "claude"))
    model_str, api_key, api_base = _litellm_target(provider, cfg)
    # Pass api_key / api_base ONLY when non-None — empty string makes some LiteLLM providers
    # attempt a doomed auth handshake; None api_base lets native vendors use their own endpoint.
    kwargs = {"model": model_str}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    return LlmAgent(
        name="Librarian",
        model=LiteLlm(**kwargs),
        instruction=_LIBRARIAN_INSTRUCTION,
        tools=[
            get_staging_queue,
            locate_memory,
            distill_and_judge,
            deposit_to_queue,
            annotate_memory,
            stage_for_deletion,
            discard_staging_item,
            request_approval,
            write_note,
            get_catalog_stats,
        ],
        output_key="librarian_summary",
    )


def _run_once_impl(cfg: dict) -> str:
    """Synchronous entry point for 'kage librarian run'. Wraps asyncio.run()."""
    agent = build_librarian(cfg)
    # node= not agent= — LlmAgent is a BaseNode; InMemoryRunner takes node=
    runner = InMemoryRunner(node=agent, app_name="kage-librarian")
    # ponytail: asyncio.run() assumes no outer loop — upgrade path: nest_asyncio or make call-site async when kage chat needs it
    return asyncio.run(_run_once_async(runner))


async def _run_once_async(runner: InMemoryRunner) -> str:
    """Async core: create session, drain event stream, re-fetch state to read output_key.
    The original session object is NOT mutated after run_async — must re-fetch (Scout pattern)."""
    session = await runner.session_service.create_session(
        app_name="kage-librarian", user_id="kage", session_id=str(uuid.uuid4())
    )
    async for _ in runner.run_async(
        user_id="kage",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[
            types.Part(text=(
                "Process the staging queue. Review pending items, "
                "distill and judge each one, request approval for promotes, "
                "and update the catalog."
            ))
        ]),
    ):
        pass  # drain stream — output lands in session state via output_key, not events
    # Re-fetch: run_async mutates the session service's internal store, not the local session var.
    refreshed = await runner.session_service.get_session(
        app_name="kage-librarian", user_id="kage", session_id=session.id
    )
    return (refreshed.state.get("librarian_summary") if refreshed else None) or "done"


def _acquire_lockfile() -> bool:
    """Advisory lockfile — returns True if acquired, False if another process holds it.
    Handles stale locks: checks if the writing PID is still alive before blocking."""
    if _LOCKFILE.exists():
        try:
            pid = int(_LOCKFILE.read_text().strip())
            os.kill(pid, 0)  # POSIX: signal 0 raises OSError if process is dead
            return False      # process alive — lock is held
        except (ValueError, OSError):
            pass  # stale lock (process dead) — safe to overwrite
    _LOCKFILE.write_text(str(os.getpid()))
    return True


def _release_lockfile() -> None:
    try:
        _LOCKFILE.unlink(missing_ok=True)
    except OSError:
        pass


def run(cfg: dict) -> str:
    """Public entry point for 'kage librarian run'. Holds both the in-process lock
    and the cross-process lockfile for the duration of the run.
    ChromaDB PersistentClient is NOT multi-process safe — the lockfile is load-bearing."""
    with _LOCK:  # in-process: one coroutine at a time
        if not _acquire_lockfile():
            return "another Librarian process is running — skipping"
        try:
            result = _run_once_impl(cfg)
            _LIBRARIAN_LAST_RUN.write_text(
                datetime.now().astimezone().isoformat(timespec="seconds")
            )
            return result
        finally:
            _release_lockfile()


def reject_approval(approval_id: str, reason: str = "") -> bool:
    """Mark an approval request rejected. Returns True if the row was found."""
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT staging_id FROM approval_queue WHERE id = ?", (approval_id,)
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE approval_queue SET decision='rejected', decided_at=? WHERE id=?",
            (ts, approval_id),
        )
        if row[0]:  # staging_id may be None for manual approvals
            conn.execute(
                "UPDATE staging_queue SET status='rejected', decision=?, reviewed_at=? WHERE id=?",
                (reason or "rejected", ts, row[0]),
            )
        conn.commit()
        return True
    finally:
        conn.close()
