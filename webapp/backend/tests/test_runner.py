"""RunManager lifecycle at the manager level (no HTTP). See design §7.1–7.2, §8.2."""

import asyncio
import json
from types import SimpleNamespace

import pytest

import runsupport
from fakelab import FakeLab
from experiment_studio.docs_store import ExperimentDoc
from experiment_studio.records import RecordsStore
from experiment_studio.runner import PreflightError, RunActiveError, StartValidationError


async def _create_doc(env: SimpleNamespace, blocks: list, **kw: object) -> str:
    doc = ExperimentDoc.model_validate(runsupport.make_doc(blocks, **kw))
    created = await env.docs.create(doc)
    return str(created["id"])


async def _finish(env: SimpleNamespace, timeout: float = 10.0) -> None:
    task = env.manager.current_task()
    assert task is not None
    await asyncio.wait_for(task, timeout)


async def _wait_for_job(fake: FakeLab, job_id: str, timeout: float = 5.0) -> None:
    """Poll until the background run task has actually issued `job_id` (Finding 3:
    start() no longer awaits anything after create_task, so the task isn't
    guaranteed to have run at all by the time start() returns)."""

    async def _poll() -> None:
        while job_id not in fake.jobs:
            await asyncio.sleep(0.001)

    await asyncio.wait_for(_poll(), timeout)


async def test_happy_path_completes_with_full_artifacts(env: SimpleNamespace) -> None:
    experiment_id = await _create_doc(env, runsupport.HAPPY_BLOCKS)
    run_id = await env.manager.start(experiment_id, runsupport.LAB, runsupport.MAPPING)
    payload = env.manager.active_payload()
    assert payload is not None
    assert payload["run_id"] == run_id
    assert payload["record_id"] == run_id
    assert payload["experiment"] == {"id": experiment_id, "name": "Growth run"}
    assert payload["lab"] == runsupport.LAB
    await _finish(env)
    assert env.manager.active_payload() is None

    record = await RecordsStore(env.db, env.data_dir).get(run_id)
    assert record["status"] == "completed"
    assert record["ended_at"] is not None
    assert record["name"].startswith("Growth run — ")

    art = env.data_dir / f"runs/{run_id}"
    assert (art / "doc.json").is_file()
    assert (art / "od.csv").is_file()
    events = [json.loads(line) for line in (art / "run_log.jsonl").read_text().splitlines()]
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "run_started"
    assert "measure_recorded" in kinds
    assert kinds[-1] == "run_finished"

    report = json.loads((art / "report.json").read_text())
    assert report["status"] == "completed"
    assert report["error"] is None
    assert report["finalize_errors"] == []
    assert report["persistence_errors"] == []
    assert isinstance(report["clock_origin"], float)
    assert report["started_at"] < report["ended_at"]
    assert report["role_mapping"] == runsupport.MAPPING
    # engine event timestamps are monotonic-clock values comparable to clock_origin
    measure = next(e for e in events if e["kind"] == "measure_recorded")
    assert measure["timestamp"] >= report["clock_origin"]


async def test_persistence_forced_to_disk_csv(env: SimpleNamespace) -> None:
    """§7.2: whatever the doc says, the run copy persists every stream to disk as CSV."""
    doc = runsupport.make_doc(
        runsupport.HAPPY_BLOCKS,
        streams={"od": {"units": "AU", "persistence": "in_memory"}},
    )
    created = await env.docs.create(ExperimentDoc.model_validate(doc))
    run_id = await env.manager.start(created["id"], runsupport.LAB, runsupport.MAPPING)
    await _finish(env)
    art = env.data_dir / f"runs/{run_id}"
    workflow = json.loads((art / "workflow.json").read_text())
    assert workflow["persistence"] == {"default": "disk", "format": "csv"}
    assert "persistence" not in workflow["streams"]["od"]
    assert workflow["blocks"][0]["serial"]["children"][0]["command"]["device"] == "pump_1"
    lines = (art / "od.csv").read_text().splitlines()
    assert lines[0] == "timestamp,value"
    assert len(lines) == 2


async def test_mapping_saved_on_start(env: SimpleNamespace) -> None:
    experiment_id = await _create_doc(env, runsupport.HAPPY_BLOCKS)
    await env.manager.start(experiment_id, runsupport.LAB, runsupport.MAPPING)
    await _finish(env)
    cur = await env.db.conn.execute(
        "SELECT role, device_id FROM mappings WHERE experiment_id = ? ORDER BY role",
        (experiment_id,),
    )
    rows = [(r["role"], r["device_id"]) for r in await cur.fetchall()]
    assert rows == [("feed", "pump_1"), ("meter", "densitometer_1")]


async def test_second_start_rejected_while_active(env: SimpleNamespace) -> None:
    env.fake.hold_job("dispense")
    experiment_id = await _create_doc(env, runsupport.HAPPY_BLOCKS)
    run_id = await env.manager.start(experiment_id, runsupport.LAB, runsupport.MAPPING)
    with pytest.raises(RunActiveError) as info:
        await env.manager.start(experiment_id, runsupport.LAB, runsupport.MAPPING)
    assert info.value.active_run_id == run_id
    await _wait_for_job(env.fake, "j-1")
    env.fake.complete_job("j-1")
    await _finish(env)


@pytest.mark.parametrize(
    ("mapping", "fragment"),
    [
        ({"feed": "pump_1"}, "not mapped"),
        ({"feed": "densitometer_1", "meter": "densitometer_1"}, "not a 'pump'"),
        ({**{"feed": "pump_1", "meter": "densitometer_1"}, "ghost": "pump_1"}, "unknown role"),
        ({"feed": "pump_9", "meter": "densitometer_1"}, "not found in lab"),
    ],
)
async def test_preflight_failures(
    env: SimpleNamespace, mapping: dict[str, str], fragment: str
) -> None:
    experiment_id = await _create_doc(env, runsupport.HAPPY_BLOCKS)
    with pytest.raises(PreflightError) as info:
        await env.manager.start(experiment_id, runsupport.LAB, mapping)
    assert any(fragment in d["message"] for d in info.value.diagnostics)
    assert all(d["category"] == "mapping" for d in info.value.diagnostics)
    # preflight failures precede record creation (§7.1: record exists only from step 3)
    assert await RecordsStore(env.db, env.data_dir).list() == []
    assert env.manager.active_payload() is None


async def test_construction_validation_failure_finalizes_failed_record(
    env: SimpleNamespace,
) -> None:
    """§7.1: ExperimentRun construction ValidationError -> 422 + failed record with
    diagnostics in report.json."""
    experiment_id = await _create_doc(env, runsupport.INVALID_BLOCKS)
    with pytest.raises(StartValidationError) as info:
        await env.manager.start(experiment_id, runsupport.LAB, runsupport.MAPPING)
    assert info.value.diagnostics
    record = await RecordsStore(env.db, env.data_dir).get(info.value.record_id)
    assert record["status"] == "failed"
    art = env.data_dir / record["dir"]
    report = json.loads((art / "report.json").read_text())
    assert report["status"] == "failed"
    assert report["diagnostics"] == info.value.diagnostics
    assert (art / "doc.json").is_file()
    assert (art / "workflow.json").is_file()
    assert not (art / "run_log.jsonl").exists()
    assert env.manager.active_payload() is None


async def test_unexpected_start_failure_finalizes_failed_record(
    env: SimpleNamespace,
) -> None:
    """§10: no phantom 'running' record when start fails after record creation."""
    env.manager._run_options["bogus_option"] = 1  # RunOptions(**...) will TypeError
    experiment_id = await _create_doc(env, runsupport.HAPPY_BLOCKS)
    with pytest.raises(TypeError):
        await env.manager.start(experiment_id, runsupport.LAB, runsupport.MAPPING)
    records = await RecordsStore(env.db, env.data_dir).list()
    assert len(records) == 1
    assert records[0]["status"] == "failed"
    assert records[0]["ended_at"] is not None
    assert env.manager.active_payload() is None
    # a subsequent start succeeds
    del env.manager._run_options["bogus_option"]
    await env.manager.start(experiment_id, runsupport.LAB, runsupport.MAPPING)
    task = env.manager.current_task()
    assert task is not None
    await asyncio.wait_for(task, 10)
