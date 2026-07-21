"""Operator-chosen device names, keyed per-lab by device_id. See design §7."""

from __future__ import annotations

from datetime import UTC, datetime

from experiment_studio.db import Database


class DeviceNamesStore:
    """DB-backed name lookup. One store per request over the shared connection."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_all(self, lab: str) -> dict[str, str]:
        cur = await self._db.conn.execute(
            "SELECT device_id, name FROM device_names WHERE lab = ?", (lab,)
        )
        rows = await cur.fetchall()
        return {row["device_id"]: row["name"] for row in rows}

    async def set(self, lab: str, device_id: str, name: str) -> None:
        await self._db.conn.execute(
            "INSERT INTO device_names (lab, device_id, name, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(lab, device_id) DO UPDATE SET "
            "name = excluded.name, updated_at = excluded.updated_at",
            (lab, device_id, name, datetime.now(UTC).isoformat()),
        )
        await self._db.conn.commit()

    async def clear(self, lab: str, device_id: str) -> None:
        await self._db.conn.execute(
            "DELETE FROM device_names WHERE lab = ? AND device_id = ?", (lab, device_id)
        )
        await self._db.conn.commit()
