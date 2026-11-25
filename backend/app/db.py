"""SQLite storage. Plain sqlite3 (stdlib): no ORM needed for 2 tables.
Functions are synchronous; call them via asyncio.to_thread from async routes."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    system_prompt TEXT,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,          -- 'user' or 'assistant'
    content    TEXT NOT NULL,
    metadata   TEXT,                   -- JSON string, assistant messages only
    created_at TEXT NOT NULL           -- server time, ISO-8601
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    def ping(self) -> bool:
        with self._conn() as c:
            c.execute("SELECT 1")
        return True

    def session_exists(self, session_id: str) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row is not None

    def get_system_prompt(self, session_id: str) -> Optional[str]:
        with self._conn() as c:
            row = c.execute(
                "SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row["system_prompt"] if row else None

    def get_history(self, session_id: str) -> list[dict]:
        """Oldest first, no system prompt. Returns role/content/metadata(dict|None)."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, content, metadata FROM messages "
                "WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        out = []
        for r in rows:
            item = {"role": r["role"], "content": r["content"]}
            if r["metadata"]:
                item["metadata"] = json.loads(r["metadata"])
            out.append(item)
        return out

    def save_exchange(
        self,
        session_id: str,
        user_content: str,
        assistant_content: str,
        metadata: dict,
        system_prompt: Optional[str] = None,
    ) -> None:
        """Atomically persist a successful turn (session + user msg + assistant msg).
        Called only after the LLM succeeded, so failed requests never touch history."""
        now = _now()
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO sessions(session_id, system_prompt, created_at) "
                "VALUES (?, ?, ?)",
                (session_id, system_prompt, now),
            )
            if system_prompt is not None:
                c.execute(
                    "UPDATE sessions SET system_prompt = ? WHERE session_id = ?",
                    (system_prompt, session_id),
                )
            c.execute(
                "INSERT INTO messages(session_id, role, content, metadata, created_at) "
                "VALUES (?, 'user', ?, NULL, ?)",
                (session_id, user_content, now),
            )
            c.execute(
                "INSERT INTO messages(session_id, role, content, metadata, created_at) "
                "VALUES (?, 'assistant', ?, ?, ?)",
                (session_id, assistant_content, json.dumps(metadata), now),
            )
