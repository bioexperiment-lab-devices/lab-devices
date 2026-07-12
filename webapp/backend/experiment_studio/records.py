"""Run records: rows, artifact directory readers, zip download. See design §8."""

from __future__ import annotations

import csv
import io
import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from lab_devices.experiment import PersistenceError
from lab_devices.experiment.persist import safe_stream_filename

from experiment_studio.db import Database


class UnknownRecordError(Exception):
    """No record row with the requested id."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_json(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "experiment_id": row["experiment_id"],
        "experiment_name": row["experiment_name"],
        "lab": row["lab"],
        "role_mapping": json.loads(row["role_mapping"]),
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "dir": row["dir"],
    }


_COLUMNS = (
    "id, name, experiment_id, experiment_name, lab, role_mapping, status,"
    " started_at, ended_at, dir"
)


class RecordsStore:
    """CRUD over records rows and their artifact dirs under data_dir (§8.1–8.2)."""

    def __init__(self, db: Database, data_dir: Path) -> None:
        self._db = db
        self._data_dir = data_dir

    def artifact_dir(self, record: dict[str, Any]) -> Path:
        return self._data_dir / str(record["dir"])

    async def create(
        self,
        *,
        record_id: str,
        name: str,
        experiment_id: str | None,
        experiment_name: str,
        lab: str,
        role_mapping: dict[str, str],
        started_at: str,
        dir: str,
    ) -> dict[str, Any]:
        await self._db.conn.execute(
            f"INSERT INTO records ({_COLUMNS})"
            " VALUES (?, ?, ?, ?, ?, ?, 'running', ?, NULL, ?)",
            (
                record_id,
                name,
                experiment_id,
                experiment_name,
                lab,
                json.dumps(role_mapping),
                started_at,
                dir,
            ),
        )
        await self._db.conn.commit()
        return await self.get(record_id)

    async def list(self) -> list[dict[str, Any]]:
        cur = await self._db.conn.execute(
            f"SELECT {_COLUMNS} FROM records ORDER BY started_at DESC"
        )
        return [_row_json(row) for row in await cur.fetchall()]

    async def get(self, record_id: str) -> dict[str, Any]:
        cur = await self._db.conn.execute(
            f"SELECT {_COLUMNS} FROM records WHERE id = ?", (record_id,)
        )
        row = await cur.fetchone()
        if row is None:
            raise UnknownRecordError(f"no record {record_id!r}")
        return _row_json(row)

    async def rename(self, record_id: str, name: str) -> dict[str, Any]:
        cur = await self._db.conn.execute(
            "UPDATE records SET name = ? WHERE id = ?", (name, record_id)
        )
        if cur.rowcount == 0:
            await self._db.conn.rollback()
            raise UnknownRecordError(f"no record {record_id!r}")
        await self._db.conn.commit()
        return await self.get(record_id)

    async def finalize(
        self, record_id: str, *, status: str, ended_at: str
    ) -> None:
        await self._db.conn.execute(
            "UPDATE records SET status = ?, ended_at = ? WHERE id = ?",
            (status, ended_at, record_id),
        )
        await self._db.conn.commit()

    async def delete(self, record_id: str) -> None:
        record = await self.get(record_id)
        await self._db.conn.execute(
            "DELETE FROM records WHERE id = ?", (record_id,)
        )
        await self._db.conn.commit()
        target = (self._data_dir / record["dir"]).resolve()
        if target.is_relative_to(self._data_dir.resolve()) and target.is_dir():
            shutil.rmtree(target, ignore_errors=True)

    async def sweep_interrupted(self) -> int:
        """§7.6: any row still 'running' at boot was orphaned by a crash."""
        cur = await self._db.conn.execute(
            "UPDATE records SET status = 'interrupted', ended_at = ?"
            " WHERE status = 'running'",
            (_now(),),
        )
        await self._db.conn.commit()
        return cur.rowcount

    async def save_mapping(
        self,
        experiment_id: str | None,
        lab: str,
        role_mapping: dict[str, str],
    ) -> None:
        """S2 mapping memory: remember the last device per (experiment, lab, role)."""
        if experiment_id is None:
            return
        for role, device_id in role_mapping.items():
            await self._db.conn.execute(
                "INSERT OR REPLACE INTO mappings"
                " (experiment_id, lab, role, device_id)"
                " VALUES (?, ?, ?, ?)",
                (experiment_id, lab, role, device_id),
            )
        await self._db.conn.commit()

    async def load_mapping(self, experiment_id: str, lab: str) -> dict[str, str]:
        """S2 mapping memory read: last device per role for (experiment, lab); {} if none."""
        cur = await self._db.conn.execute(
            "SELECT role, device_id FROM mappings WHERE experiment_id = ? AND lab = ?",
            (experiment_id, lab),
        )
        return {row["role"]: row["device_id"] for row in await cur.fetchall()}


# ---- artifact readers (§6: /records/{id}/events, /records/{id}/streams, download) ----


def read_events(artifact_dir: Path) -> list[dict[str, Any]]:
    """Parsed run_log.jsonl; [] when absent (interrupted runs have no log — S7)."""
    path = artifact_dir / "run_log.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def read_streams(artifact_dir: Path) -> dict[str, dict[str, Any]]:
    """Stream series from the engine-written CSVs, keyed by declared stream name."""
    workflow_path = artifact_dir / "workflow.json"
    if not workflow_path.is_file():
        return {}
    declared = json.loads(workflow_path.read_text()).get("streams") or {}
    out: dict[str, dict[str, Any]] = {}
    for name, decl in declared.items():
        try:
            filename = safe_stream_filename(name)
        except PersistenceError:
            continue  # the engine refused this name at run time too
        path = artifact_dir / f"{filename}.csv"
        if not path.is_file():
            continue
        t: list[float] = []
        v: list[float] = []
        with path.open(newline="") as fh:
            reader = csv.reader(fh)
            next(reader, None)  # header
            for row in reader:
                if len(row) < 2:
                    continue
                t.append(float(row[0]))
                v.append(float(row[1]))
        units = decl.get("units") if isinstance(decl, dict) else None
        out[name] = {"t": t, "v": v, "units": units}
    return out


def build_zip(artifact_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(artifact_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(artifact_dir).as_posix())
    return buffer.getvalue()
