"""RunManager controls: pause/resume/abort/input/shutdown. See design §7.1, §7.4."""

import asyncio
import json
from types import SimpleNamespace

import pytest

import runsupport
from lab_devices.experiment import EvaluationError

from experiment_studio.docs_store import ExperimentDoc
from experiment_studio.inputs import NoPendingInputError
from experiment_studio.records import RecordsStore
from experiment_studio.runner import UnknownRunError


async def _start(env: SimpleNamespace, blocks: list, mapping: dict | None = None) -> str:
    doc = ExperimentDoc.model_validate(runsupport.make_doc(blocks))
    created = await env.docs.create(doc)
    return str(
        await env.manager.start(
            created["id"], runsupport.LAB, mapping or runsupport.MAPPING
        )
    )


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


async def _finish(env: SimpleNamespace, timeout: float = 10.0) -> None:
    task = env.manager.current_task()
    assert task is not None
    await asyncio.wait_for(task, timeout)


async def test_pause_resume_updates_status_and_tee(env: SimpleNamespace) -> None:
    env.fake.hold_job("dispense")
    run_id = await _start(env, runsupport.HAPPY_BLOCKS)
    await _wait_for(lambda: env.fake.jobs)  # run parked on the held job
    env.manager.pause(run_id)
    env.manager.pause(run_id)  # second pause is a no-op, not a second status message
    payload = env.manager.active_payload()
    assert payload is not None and payload["status"] == "paused"
    env.manager.resume(run_id)
    payload = env.manager.active_payload()
    assert payload is not None and payload["status"] == "running"
    active = env.manager.active()
    assert active is not None
    statuses = [m["status"] for m in active.tee.messages if m["type"] == "status"]
    assert statuses == ["running", "paused", "running"]
    kinds = [m["kind"] for m in active.tee.messages if m["type"] == "event"]
    assert "paused" in kinds and "resumed" in kinds
    env.fake.complete_job("j-1")
    await _finish(env)


async def test_abort_finalizes_aborted_record_with_artifacts(
    env: SimpleNamespace,
) -> None:
    env.fake.hold_job("dispense")
    run_id = await _start(env, runsupport.HAPPY_BLOCKS)
    await _wait_for(lambda: env.fake.jobs)
    env.manager.abort(run_id)
    env.manager.abort(run_id)  # idempotent while still active
    await _finish(env)
    record = await RecordsStore(env.db, env.data_dir).get(run_id)
    assert record["status"] == "aborted"
    art = env.data_dir / record["dir"]
    events = [json.loads(line) for line in (art / "run_log.jsonl").read_text().splitlines()]
    kinds = [e["kind"] for e in events]
    assert "abort_requested" in kinds
    assert kinds[-1] == "run_finished"
    report = json.loads((art / "report.json").read_text())
    assert report["status"] == "aborted"
    # after terminal, control endpoints 404 (§6)
    with pytest.raises(UnknownRunError):
        env.manager.abort(run_id)


async def test_controls_reject_wrong_run_id(env: SimpleNamespace) -> None:
    env.fake.hold_job("dispense")
    await _start(env, runsupport.HAPPY_BLOCKS)
    with pytest.raises(UnknownRunError):
        env.manager.pause("not-the-run")
    with pytest.raises(UnknownRunError):
        env.manager.submit_input("not-the-run", 1)
    await _wait_for(lambda: env.fake.jobs)
    env.fake.complete_job("j-1")
    await _finish(env)


async def test_operator_input_flow(env: SimpleNamespace) -> None:
    run_id = await _start(env, runsupport.INPUT_BLOCKS)
    await _wait_for(
        lambda: (env.manager.active_payload() or {}).get("pending_input") is not None
    )
    payload = env.manager.active_payload()
    assert payload is not None
    pending = payload["pending_input"]
    assert pending == {
        "name": "target",
        "type": "int",
        "prompt": "Target cycles?",
        "min": 1,
        "max": 10,
        "choices": None,
        "block_id": pending["block_id"],
    }
    with pytest.raises(EvaluationError):
        env.manager.submit_input(run_id, 99)  # above max — stays pending
    assert (env.manager.active_payload() or {})["pending_input"] is not None
    env.manager.submit_input(run_id, 7)
    await _finish(env)
    record = await RecordsStore(env.db, env.data_dir).get(run_id)
    assert record["status"] == "completed"
    art = env.data_dir / record["dir"]
    events = [json.loads(line) for line in (art / "run_log.jsonl").read_text().splitlines()]
    bound = next(e for e in events if e["kind"] == "input_bound")
    assert bound["data"] == {"name": "target", "value": 7}


async def test_submit_input_without_pending_raises(env: SimpleNamespace) -> None:
    env.fake.hold_job("dispense")
    run_id = await _start(env, runsupport.HAPPY_BLOCKS)
    with pytest.raises(NoPendingInputError):
        env.manager.submit_input(run_id, 1)
    await _wait_for(lambda: env.fake.jobs)
    env.fake.complete_job("j-1")
    await _finish(env)


async def test_abort_cancels_pending_input(env: SimpleNamespace) -> None:
    run_id = await _start(env, runsupport.INPUT_BLOCKS)
    await _wait_for(
        lambda: (env.manager.active_payload() or {}).get("pending_input") is not None
    )
    env.manager.abort(run_id)
    await _finish(env)
    record = await RecordsStore(env.db, env.data_dir).get(run_id)
    assert record["status"] == "aborted"


async def test_shutdown_aborts_and_finalizes(env: SimpleNamespace) -> None:
    env.fake.hold_job("dispense")
    run_id = await _start(env, runsupport.HAPPY_BLOCKS)
    await _wait_for(lambda: env.fake.jobs)
    await env.manager.shutdown()
    task = env.manager.current_task()
    assert task is not None and task.done()
    record = await RecordsStore(env.db, env.data_dir).get(run_id)
    assert record["status"] == "aborted"
    assert env.manager.active_payload() is None
    await env.manager.shutdown()  # idempotent


async def test_new_run_allowed_after_terminal(env: SimpleNamespace) -> None:
    run_id_1 = await _start(env, runsupport.HAPPY_BLOCKS)
    await _finish(env)
    doc = ExperimentDoc.model_validate(
        runsupport.make_doc(runsupport.HAPPY_BLOCKS, name="Second")
    )
    created = await env.docs.create(doc)
    run_id_2 = await env.manager.start(
        created["id"], runsupport.LAB, runsupport.MAPPING
    )
    assert run_id_2 != run_id_1
    await _finish(env)
