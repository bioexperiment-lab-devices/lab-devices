"""Database migration behavior (design §8.1)."""

from pathlib import Path

from experiment_studio.db import MIGRATIONS, Database


async def test_connect_applies_migrations_and_sets_user_version(tmp_path: Path) -> None:
    db = await Database.connect(tmp_path / "studio.db")
    try:
        cur = await db.conn.execute("PRAGMA user_version")
        row = await cur.fetchone()
        assert row is not None and row[0] == len(MIGRATIONS)
        cur = await db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='experiments'"
        )
        assert await cur.fetchone() is not None
    finally:
        await db.close()


async def test_reconnect_is_idempotent(tmp_path: Path) -> None:
    first = await Database.connect(tmp_path / "studio.db")
    await first.close()
    second = await Database.connect(tmp_path / "studio.db")  # would raise if CREATE re-ran
    try:
        cur = await second.conn.execute("PRAGMA user_version")
        row = await cur.fetchone()
        assert row is not None and row[0] == len(MIGRATIONS)
    finally:
        await second.close()


async def test_connect_creates_parent_directory(tmp_path: Path) -> None:
    db = await Database.connect(tmp_path / "nested" / "dir" / "studio.db")
    try:
        assert (tmp_path / "nested" / "dir" / "studio.db").exists()
    finally:
        await db.close()
