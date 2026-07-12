"""RecordsStore CRUD + sweep + mappings + artifact readers + zip. See design §8."""

import io
import json
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from experiment_studio.db import Database
from experiment_studio.records import (
    RecordsStore,
    UnknownRecordError,
    build_zip,
    read_events,
    read_streams,
)


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = await Database.connect(tmp_path / "studio.db")
    yield database
    await database.close()


@pytest.fixture
def store(db: Database, tmp_path: Path) -> RecordsStore:
    return RecordsStore(db, tmp_path)


async def _create(store: RecordsStore, record_id: str, *, started_at: str) -> dict:
    return await store.create(
        record_id=record_id,
        name=f"Rec {record_id}",
        experiment_id="e1",
        experiment_name="Exp",
        lab="lab_a",
        role_mapping={"feed": "pump_1"},
        started_at=started_at,
        dir=f"runs/{record_id}",
    )


async def test_create_get_roundtrip(store: RecordsStore) -> None:
    created = await _create(store, "r1", started_at="2026-07-12T10:00:00+00:00")
    assert created["status"] == "running"
    assert created["ended_at"] is None
    assert created["role_mapping"] == {"feed": "pump_1"}
    assert created["dir"] == "runs/r1"
    assert (await store.get("r1")) == created


async def test_get_unknown_raises(store: RecordsStore) -> None:
    with pytest.raises(UnknownRecordError):
        await store.get("nope")


async def test_list_orders_by_started_at_desc(store: RecordsStore) -> None:
    await _create(store, "old", started_at="2026-07-12T09:00:00+00:00")
    await _create(store, "new", started_at="2026-07-12T11:00:00+00:00")
    assert [r["id"] for r in await store.list()] == ["new", "old"]


async def test_rename(store: RecordsStore) -> None:
    await _create(store, "r1", started_at="2026-07-12T10:00:00+00:00")
    renamed = await store.rename("r1", "First growth run")
    assert renamed["name"] == "First growth run"
    with pytest.raises(UnknownRecordError):
        await store.rename("nope", "x")


async def test_finalize(store: RecordsStore) -> None:
    await _create(store, "r1", started_at="2026-07-12T10:00:00+00:00")
    await store.finalize("r1", status="completed", ended_at="2026-07-12T10:05:00+00:00")
    record = await store.get("r1")
    assert record["status"] == "completed"
    assert record["ended_at"] == "2026-07-12T10:05:00+00:00"


async def test_delete_removes_row_and_dir(store: RecordsStore, tmp_path: Path) -> None:
    await _create(store, "r1", started_at="2026-07-12T10:00:00+00:00")
    art = tmp_path / "runs/r1"
    art.mkdir(parents=True)
    (art / "report.json").write_text("{}")
    await store.delete("r1")
    assert not art.exists()
    with pytest.raises(UnknownRecordError):
        await store.get("r1")


async def test_delete_survives_missing_dir(store: RecordsStore) -> None:
    await _create(store, "r1", started_at="2026-07-12T10:00:00+00:00")
    await store.delete("r1")  # dir never created — must not raise
    with pytest.raises(UnknownRecordError):
        await store.delete("r1")


async def test_sweep_interrupted(store: RecordsStore) -> None:
    await _create(store, "r1", started_at="2026-07-12T10:00:00+00:00")
    await _create(store, "r2", started_at="2026-07-12T10:01:00+00:00")
    await store.finalize("r2", status="completed", ended_at="2026-07-12T10:02:00+00:00")
    assert await store.sweep_interrupted() == 1
    assert (await store.get("r1"))["status"] == "interrupted"
    assert (await store.get("r1"))["ended_at"] is not None
    assert (await store.get("r2"))["status"] == "completed"
    assert await store.sweep_interrupted() == 0


async def test_save_mapping_upserts(store: RecordsStore, db: Database) -> None:
    await store.save_mapping("e1", "lab_a", {"feed": "pump_1", "meter": "densitometer_1"})
    await store.save_mapping("e1", "lab_a", {"feed": "pump_2"})
    cur = await db.conn.execute(
        "SELECT role, device_id FROM mappings WHERE experiment_id='e1' AND lab='lab_a'"
        " ORDER BY role"
    )
    rows = [(r["role"], r["device_id"]) for r in await cur.fetchall()]
    assert rows == [("feed", "pump_2"), ("meter", "densitometer_1")]


async def test_load_mapping_roundtrip(tmp_path: Path) -> None:
    db = await Database.connect(tmp_path / "studio.db")
    try:
        store = RecordsStore(db, tmp_path)
        assert await store.load_mapping("exp-1", "lab_a") == {}
        await store.save_mapping("exp-1", "lab_a", {"feed": "pump_1", "meter": "densitometer_1"})
        await store.save_mapping("exp-1", "lab_b", {"feed": "pump_9"})
        assert await store.load_mapping("exp-1", "lab_a") == {
            "feed": "pump_1",
            "meter": "densitometer_1",
        }
        assert await store.load_mapping("exp-1", "lab_b") == {"feed": "pump_9"}
        assert await store.load_mapping("other", "lab_a") == {}
    finally:
        await db.close()


# ---- artifact readers ----


def _make_artifacts(root: Path) -> Path:
    art = root / "runs/rX"
    art.mkdir(parents=True)
    (art / "run_log.jsonl").write_text(
        '{"timestamp": 1.0, "kind": "run_started", "block_id": null, "data": {}}\n'
        '{"timestamp": 2.0, "kind": "run_finished", "block_id": null,'
        ' "data": {"status": "completed"}}\n'
    )
    (art / "workflow.json").write_text(
        json.dumps({"streams": {"od": {"units": "AU"}, "ghost": {"units": "x"}}})
    )
    (art / "od.csv").write_text("timestamp,value\n1.5,0.5\n2.5,0.75\n")
    (art / "report.json").write_text(json.dumps({"status": "completed"}))
    return art


def test_read_events(tmp_path: Path) -> None:
    art = _make_artifacts(tmp_path)
    events = read_events(art)
    assert [e["kind"] for e in events] == ["run_started", "run_finished"]
    assert events[1]["data"] == {"status": "completed"}


def test_read_events_missing_file(tmp_path: Path) -> None:
    assert read_events(tmp_path) == []


def test_read_streams(tmp_path: Path) -> None:
    art = _make_artifacts(tmp_path)
    streams = read_streams(art)
    assert set(streams) == {"od"}  # 'ghost' declared but no CSV -> skipped
    assert streams["od"] == {"t": [1.5, 2.5], "v": [0.5, 0.75], "units": "AU"}


def test_read_streams_no_workflow(tmp_path: Path) -> None:
    assert read_streams(tmp_path) == {}


def test_build_zip(tmp_path: Path) -> None:
    art = _make_artifacts(tmp_path)
    payload = build_zip(art)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())
        assert names == {"run_log.jsonl", "workflow.json", "od.csv", "report.json"}
        assert b"timestamp,value" in zf.read("od.csv")
