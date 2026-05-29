from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


class VerificationStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            with conn:
                self._ensure_verified_users_schema(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pending_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        discord_id TEXT NOT NULL,
                        discord_name TEXT NOT NULL,
                        minecraft_name TEXT NOT NULL COLLATE NOCASE,
                        requested_at TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        decided_by TEXT,
                        decided_at TEXT
                    )
                    """
                )

    def _ensure_verified_users_schema(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(verified_users)").fetchall()
        if not columns:
            conn.execute(
                """
                CREATE TABLE verified_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    discord_id TEXT NOT NULL,
                    discord_name TEXT NOT NULL,
                    minecraft_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    verified_at TEXT NOT NULL,
                    approved_by TEXT,
                    rcon_response TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_verified_users_discord_id ON verified_users(discord_id)")
            return

        column_names = {column[1] for column in columns}
        if "id" in column_names and any(column[1] == "discord_id" and column[5] == 0 for column in columns):
            conn.execute("CREATE INDEX IF NOT EXISTS idx_verified_users_discord_id ON verified_users(discord_id)")
            return

        conn.execute("ALTER TABLE verified_users RENAME TO verified_users_legacy")
        conn.execute(
            """
            CREATE TABLE verified_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT NOT NULL,
                discord_name TEXT NOT NULL,
                minecraft_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                verified_at TEXT NOT NULL,
                approved_by TEXT,
                rcon_response TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO verified_users (discord_id, discord_name, minecraft_name, verified_at, approved_by, rcon_response)
            SELECT discord_id, discord_name, minecraft_name, verified_at, approved_by, rcon_response
            FROM verified_users_legacy
            ORDER BY verified_at
            """
        )
        conn.execute("DROP TABLE verified_users_legacy")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_verified_users_discord_id ON verified_users(discord_id)")

    def add_verified_user(
        self,
        *,
        discord_id: str,
        discord_name: str,
        minecraft_name: str,
        verified_at: str,
        approved_by: str | None,
        rcon_response: str | None,
    ) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO verified_users (
                        discord_id, discord_name, minecraft_name, verified_at, approved_by, rcon_response
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (discord_id, discord_name, minecraft_name, verified_at, approved_by, rcon_response),
                )

    def get_by_discord_id(self, discord_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM verified_users WHERE discord_id = ? ORDER BY verified_at DESC LIMIT 1",
                (discord_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_by_discord_id(self, discord_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM verified_users WHERE discord_id = ? ORDER BY verified_at DESC",
                (discord_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_by_discord_id(self, discord_id: str) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM verified_users WHERE discord_id = ?",
                (discord_id,),
            ).fetchone()
        return int(row["count"]) if row else 0

    def get_by_minecraft_name(self, minecraft_name: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM verified_users WHERE minecraft_name = ? COLLATE NOCASE",
                (minecraft_name,),
            ).fetchone()
        return dict(row) if row else None

    def remove_by_minecraft_name(self, minecraft_name: str) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute("DELETE FROM verified_users WHERE minecraft_name = ? COLLATE NOCASE", (minecraft_name,))

    def list_verified_users(self, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM verified_users ORDER BY verified_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_pending_request(
        self,
        *,
        discord_id: str,
        discord_name: str,
        minecraft_name: str,
        requested_at: str,
    ) -> int:
        with closing(self._connect()) as conn:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO pending_requests (discord_id, discord_name, minecraft_name, requested_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (discord_id, discord_name, minecraft_name, requested_at),
                )
                return int(cursor.lastrowid)

    def get_pending_request(self, request_id: int) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM pending_requests WHERE id = ? AND status = 'pending'",
                (request_id,),
            ).fetchone()
        return dict(row) if row else None

    def mark_request_decided(self, request_id: int, status: str, decided_by: str) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE pending_requests
                    SET status = ?, decided_by = ?, decided_at = datetime('now')
                    WHERE id = ?
                    """,
                    (status, decided_by, request_id),
                )