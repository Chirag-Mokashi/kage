from __future__ import annotations

import pathlib
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id           TEXT PRIMARY KEY,
    content_path TEXT NOT NULL,
    project      TEXT,
    created_at   TEXT NOT NULL,
    needs_embed  INTEGER NOT NULL DEFAULT 1,
    local_only   INTEGER NOT NULL DEFAULT 0,
    state        TEXT NOT NULL DEFAULT 'scoped' CHECK (state IN ('scoped','baseline','pending'))
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(id UNINDEXED, body);
CREATE TABLE IF NOT EXISTS chunks (
    id            TEXT PRIMARY KEY,
    note_id       TEXT NOT NULL,
    section_title TEXT NOT NULL DEFAULT '',
    char_start    INTEGER NOT NULL,
    char_end      INTEGER NOT NULL,
    needs_embed   INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS memory_projects (
    mem_id   TEXT NOT NULL,
    project  TEXT NOT NULL,
    PRIMARY KEY (mem_id, project)
);
CREATE TABLE IF NOT EXISTS memory_identities (
    mem_id   TEXT NOT NULL,
    identity TEXT NOT NULL,
    PRIMARY KEY (mem_id, identity)
);
CREATE INDEX IF NOT EXISTS idx_mem_projects_project    ON memory_projects(project);
CREATE INDEX IF NOT EXISTS idx_mem_identities_identity ON memory_identities(identity);
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    identity    TEXT NOT NULL,
    project     TEXT,
    destination TEXT NOT NULL,
    deleted     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS session_turns (
    session_id  TEXT NOT NULL,
    idx         INTEGER NOT NULL,
    parent_idx  INTEGER,
    role        TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    note_ids    TEXT NOT NULL DEFAULT '[]',
    destination TEXT NOT NULL,
    model       TEXT,
    reason      TEXT,
    tokens      INTEGER,
    ts          TEXT NOT NULL,
    deleted     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, idx),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);
"""


class Store:
    def __init__(self, db_path: pathlib.Path):
        self._db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_schema(self) -> None:
        conn = self.connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN needs_embed INTEGER NOT NULL DEFAULT 1")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists in an existing DB
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN local_only INTEGER NOT NULL DEFAULT 0")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN state TEXT NOT NULL DEFAULT 'scoped'")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists in an existing DB
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN source TEXT DEFAULT 'user'")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN recalled_count INTEGER DEFAULT 0")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN last_recalled TEXT DEFAULT NULL")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN librarian_flag TEXT DEFAULT 'none'")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN superseded_by TEXT DEFAULT NULL")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN tags TEXT DEFAULT NULL")
                conn.commit()
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
        finally:
            conn.close()

    def allowed_note_ids(self, identity: str, project: str | None) -> set[str]:
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT m.id
                FROM memories m
                JOIN memory_identities mi ON mi.mem_id = m.id
                WHERE mi.identity = :identity
                  AND m.state != 'pending'
                  AND (
                    :project IS NULL
                    OR EXISTS (
                        SELECT 1 FROM memory_projects mp
                        WHERE mp.mem_id = m.id AND mp.project = :project
                    )
                    OR (
                        m.state = 'baseline'
                        AND NOT EXISTS (
                            SELECT 1 FROM memory_projects mp2
                            WHERE mp2.mem_id = m.id
                        )
                    )
                  )
            """, {"identity": identity, "project": project})
            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()
