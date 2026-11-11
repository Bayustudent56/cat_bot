"""Modul SQLite untuk menyimpan log percakapan dan statistik CatBot."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    user_message    TEXT    NOT NULL,
    intent          TEXT    NOT NULL,
    score           REAL    NOT NULL DEFAULT 0,
    matched_pattern TEXT,
    response        TEXT    NOT NULL,
    is_fallback     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_conversations_intent   ON conversations (intent);
CREATE INDEX IF NOT EXISTS idx_conversations_fallback ON conversations (is_fallback);
CREATE INDEX IF NOT EXISTS idx_conversations_session  ON conversations (session_id);
"""


@contextmanager
def get_connection(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """Buka koneksi SQLite, commit otomatis, dan selalu ditutup."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path) -> None:
    """Buat folder dan tabel database jika belum ada."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)


def log_conversation(
    db_path: str | Path,
    session_id: str,
    user_message: str,
    intent: str,
    score: float,
    response: str,
    is_fallback: bool,
    matched_pattern: str | None = None,
) -> int:
    """Simpan satu percakapan dan kembalikan id barisnya."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO conversations
                (session_id, user_message, intent, score, matched_pattern, response, is_fallback)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user_message,
                intent,
                float(score),
                matched_pattern,
                response,
                1 if is_fallback else 0,
            ),
        )
        return int(cursor.lastrowid)


def get_recent_conversations(db_path: str | Path, limit: int = 50) -> list[dict[str, Any]]:
    """Ambil riwayat percakapan terbaru (paling baru di atas)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [dict(row) for row in rows]


def get_stats(db_path: str | Path) -> dict[str, Any]:
    """Statistik ringkas: total, fallback, tingkat dikenali, distribusi intent."""
    with get_connection(db_path) as conn:
        totals = conn.execute(
            """
            SELECT COUNT(*)                         AS total,
                   COALESCE(SUM(is_fallback), 0)    AS fallback_count,
                   COUNT(DISTINCT session_id)       AS sessions,
                   COALESCE(AVG(CASE WHEN is_fallback = 0 THEN score END), 0) AS avg_score
            FROM conversations
            """
        ).fetchone()
        intent_rows = conn.execute(
            """
            SELECT intent, COUNT(*) AS total
            FROM conversations
            GROUP BY intent
            ORDER BY total DESC, intent ASC
            """
        ).fetchall()

    total = int(totals["total"])
    fallback_count = int(totals["fallback_count"])
    recognized = total - fallback_count
    return {
        "total": total,
        "fallback_count": fallback_count,
        "recognized_count": recognized,
        "recognition_rate": round(recognized / total * 100, 1) if total else 0.0,
        "fallback_rate": round(fallback_count / total * 100, 1) if total else 0.0,
        "sessions": int(totals["sessions"]),
        "avg_score": round(float(totals["avg_score"]), 3),
        "intents": [{"intent": r["intent"], "total": int(r["total"])} for r in intent_rows],
    }


def get_fallback_questions(db_path: str | Path, limit: int = 50) -> list[dict[str, Any]]:
    """Daftar pertanyaan yang tidak dikenali, dikelompokkan dan diurutkan by frekuensi."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT MIN(user_message)      AS question,
                   COUNT(*)               AS total,
                   MAX(created_at)        AS last_seen
            FROM conversations
            WHERE is_fallback = 1
            GROUP BY LOWER(TRIM(user_message))
            ORDER BY total DESC, last_seen DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def clear_conversations(db_path: str | Path) -> None:
    """Hapus seluruh log percakapan (dipakai untuk reset/pengujian)."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM conversations")
