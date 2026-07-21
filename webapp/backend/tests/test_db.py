"""Database migration behavior (design §8.1)."""

import sqlite3
from pathlib import Path

import pytest

from experiment_studio import db as db_module
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


async def test_w4_tables_exist(tmp_path: Path) -> None:
    db = await Database.connect(tmp_path / "studio.db")
    cur = await db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row["name"] for row in await cur.fetchall()}
    assert {"experiments", "records", "mappings", "device_names"} <= names
    cur = await db.conn.execute("PRAGMA user_version")
    row = await cur.fetchone()
    assert row is not None and row[0] == len(db_module.MIGRATIONS) == 4
    await db.close()


async def test_failed_migration_is_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W2 carry-forward: DDL and the user_version bump commit together — a broken
    migration must leave neither the table nor the bump behind (no boot loop)."""
    good = db_module.MIGRATIONS[0]
    monkeypatch.setattr(db_module, "MIGRATIONS", [good, "CREATE TABLE broken ("])
    with pytest.raises(sqlite3.OperationalError):
        await Database.connect(tmp_path / "studio.db")
    raw = sqlite3.connect(tmp_path / "studio.db")
    try:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
        tables = {r[0] for r in raw.execute("SELECT name FROM sqlite_master")}
        assert "broken" not in tables
    finally:
        raw.close()
    # boot recovers once the migration list is fixed
    monkeypatch.setattr(
        db_module, "MIGRATIONS", [good, "CREATE TABLE fixed (id TEXT PRIMARY KEY)"]
    )
    db = await Database.connect(tmp_path / "studio.db")
    cur = await db.conn.execute("PRAGMA user_version")
    row = await cur.fetchone()
    assert row is not None and row[0] == 2
    await db.close()
