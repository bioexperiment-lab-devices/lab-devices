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
        await db._migrate()
        return db

    async def _migrate(self) -> None:
        cur = await self._conn.execute("PRAGMA user_version")
        row = await cur.fetchone()
        version = int(row[0]) if row is not None else 0
        for i, statement in enumerate(MIGRATIONS[version:], start=version + 1):
            await self._conn.execute(statement)
            await self._conn.execute(f"PRAGMA user_version = {i}")
            await self._conn.commit()

    async def close(self) -> None:
        await self._conn.close()
