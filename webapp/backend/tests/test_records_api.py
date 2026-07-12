"""HTTP layer for records: list/get/rename/delete/download + guards. See design §6."""

import asyncio
import io
import json
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import runsupport
from experiment_studio.records import RecordsStore


async def _seed_record(api: SimpleNamespace, *, status: str = "completed") -> dict:
    record_id = str(uuid4())
    art = api.data_dir / f"runs/{record_id}"
    art.mkdir(parents=True)
    (art / "run_log.jsonl").write_text(
        '{"timestamp": 1.0, "kind": "run_started", "block_id": null, "data": {}}\n'
    )
    (art / "workflow.json").write_text(json.dumps({"streams": {"od": {"units": "AU"}}}))
    (art / "od.csv").write_text("timestamp,value\n1.5,0.5\n")
    (art / "report.json").write_text(json.dumps({"status": status}))
    (art / "doc.json").write_text(json.dumps({"doc_version": 1, "name": "Exp"}))
    store = RecordsStore(api.db, api.data_dir)
    await store.create(
        record_id=record_id,
        name="Exp — 2026-07-12 10:00",
        experiment_id="e1",
        experiment_name="Exp",
        lab=runsupport.LAB,
        role_mapping={"feed": "pump_1"},
        started_at="2026-07-12T10:00:00+00:00",
        dir=f"runs/{record_id}",
    )
    await store.finalize(record_id, status=status, ended_at="2026-07-12T10:05:00+00:00")
    return await store.get(record_id)


async def _wait_for_job(api: SimpleNamespace) -> None:
    """Poll until the background run task has actually issued a job (Task 4 finding:
    start() no longer awaits anything after create_task, so the task isn't guaranteed
    to have run at all by the time POST /api/runs returns)."""
    async with asyncio.timeout(5):
        while not api.fake.jobs:
            await asyncio.sleep(0.005)


async def test_list_and_get(api: SimpleNamespace) -> None:
    record = await _seed_record(api)
    listed = (await api.client.get("/api/records")).json()
    assert [r["id"] for r in listed] == [record["id"]]
    got = (await api.client.get(f"/api/records/{record['id']}")).json()
    assert got["report"] == {"status": "completed"}
    assert got["doc"]["name"] == "Exp"


async def test_get_unknown_404(api: SimpleNamespace) -> None:
    response = await api.client.get("/api/records/nope")
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_record"


async def test_rename(api: SimpleNamespace) -> None:
    record = await _seed_record(api)
    response = await api.client.patch(
        f"/api/records/{record['id']}", json={"name": "First run"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "First run"
    response = await api.client.patch(f"/api/records/{record['id']}", json={"name": ""})
    assert response.status_code == 422  # pydantic min_length


async def test_delete_removes_row_and_dir(api: SimpleNamespace) -> None:
    record = await _seed_record(api)
    response = await api.client.delete(f"/api/records/{record['id']}")
    assert response.status_code == 204
    assert not (api.data_dir / record["dir"]).exists()
    assert (await api.client.delete(f"/api/records/{record['id']}")).status_code == 404


async def test_delete_active_record_409(api: SimpleNamespace) -> None:
    api.fake.hold_job("dispense")
    response = await api.client.post(
        "/api/experiments", json=runsupport.make_doc(runsupport.HAPPY_BLOCKS)
    )
    experiment_id = response.json()["id"]
    response = await api.client.post(
        "/api/runs",
        json={
            "experiment_id": experiment_id,
            "lab": runsupport.LAB,
            "role_mapping": runsupport.MAPPING,
        },
    )
    run_id = response.json()["run_id"]
    response = await api.client.delete(f"/api/records/{run_id}")
    assert response.status_code == 409
    assert response.json()["code"] == "run_active"
    await _wait_for_job(api)
    api.fake.complete_job("j-1")
    task = api.manager.current_task()
    assert task is not None
    await task


async def test_download_zip(api: SimpleNamespace) -> None:
    record = await _seed_record(api)
    response = await api.client.get(f"/api/records/{record['id']}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert 'filename="Exp_2026-07-12_10_00.zip"' in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert set(zf.namelist()) == {
            "run_log.jsonl",
            "workflow.json",
            "od.csv",
            "report.json",
            "doc.json",
        }


async def test_events_and_streams_empty_for_interrupted(api: SimpleNamespace) -> None:
    record = await _seed_record(api, status="interrupted")
    (api.data_dir / record["dir"] / "run_log.jsonl").unlink()
    events = (await api.client.get(f"/api/records/{record['id']}/events")).json()
    assert events == []
