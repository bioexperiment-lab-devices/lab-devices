"""aiosqlite connection with hand-rolled PRAGMA user_version migrations. See design §8.1."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

# Append-only: user_version counts applied entries. W4 appends records/mappings tables.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE experiments (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        doc TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE records (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        experiment_id TEXT,
        experiment_name TEXT NOT NULL,
        lab TEXT NOT NULL,
        role_mapping TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        dir TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE mappings (
        experiment_id TEXT NOT NULL,
        lab TEXT NOT NULL,
        role TEXT NOT NULL,
        device_id TEXT NOT NULL,
        PRIMARY KEY (experiment_id, lab, role)
    )
    """,
    """
    CREATE TABLE device_names (
        lab TEXT NOT NULL,
        device_id TEXT NOT NULL,
        name TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (lab, device_id)
    )
    """,
]


class Database:
    """One aiosqlite connection; aiosqlite already serializes statements onto its thread."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    @property
    def conn(self) -> aiosqlite.Connection:
        return self._conn

    @classmethod
    async def connect(cls, path: Path) -> Database:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        db = cls(conn)
        try:
            await db._migrate()
        except BaseException:
            await conn.close()
            raise
        return db

    async def _migrate(self) -> None:
        cur = await self._conn.execute("PRAGMA user_version")
        row = await cur.fetchone()
        version = int(row[0]) if row is not None else 0
        for i, statement in enumerate(MIGRATIONS[version:], start=version + 1):
            # DDL + version bump commit together: a crash between them would re-run
            # the DDL on next boot and fail forever (W2 repro).
            await self._conn.execute("BEGIN")
            try:
                await self._conn.execute(statement)
                await self._conn.execute(f"PRAGMA user_version = {i}")
                await self._conn.commit()
            except BaseException:
                await self._conn.rollback()
                raise

    async def close(self) -> None:
        await self._conn.close()
