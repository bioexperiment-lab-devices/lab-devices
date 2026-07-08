import asyncio

import pytest

from lab_devices.experiment import (
    BlockFailedError,
    ExperimentRun,
    FinalizeError,
    InMemoryRunLog,  # noqa: F401  # imported to prove it's exported (test_public_exports)
    RunOptions,
    UnsupportedPersistenceError,
    ValidationError,
)
from lab_devices.experiment.errors import ExperimentRunError
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


def make_run(client, workflow, **opt):
    options = RunOptions(clock=opt.pop("clock", FakeClock()), **opt)
    return ExperimentRun(client, workflow, options=options)


async def test_happy_path_report(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}],
        streams={"OD": {"units": "AU"}},
    )
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed" and report.error is None
    assert report.finalize_errors == ()
    assert len(report.state.streams["OD"]) == 1
    assert run.report is report
    kinds = [e.kind for e in report.log.events]
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished"


async def test_validates_at_construction(fake_client):
    _, client = fake_client
    wf = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "ghost"}}]
    )  # undeclared stream -> validator rejects
    with pytest.raises(ValidationError):
        ExperimentRun(client, wf)


async def test_declared_streams_pre_created(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"branch": {"if": "count(S) == 0",
                     "then": [{"command": {"device": "pump_1", "verb": "stop"}}]}}],
        streams={"S": {}},
    )
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    assert verbs(fake)[0] == ("pump_1", "stop")  # count()==0 on a never-written stream


async def test_disk_persistence_rejected_before_hardware(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"command": {"device": "pump_1", "verb": "stop"}}],
        persistence={"default": "disk", "format": "jsonl"},
    )
    run = make_run(client, wf)
    with pytest.raises(UnsupportedPersistenceError, match="Increment 5"):
        await run.execute()
    assert fake.calls == []  # nothing touched the wire
    assert run.report is not None and run.report.status == "failed"


async def test_per_stream_disk_override_rejected(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}],
        streams={"OD": {"persistence": "disk"}},
    )
    run = make_run(client, wf)
    with pytest.raises(UnsupportedPersistenceError):
        await run.execute()


async def test_block_failure_finalizes_and_reraises_with_notes(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = make_run(client, wf)
    with pytest.raises(BlockFailedError):
        await drive(run._options.clock, run.execute())
    assert run.report.status == "failed"
    assert ("pump_2", "stop") in verbs(fake)  # rotate torn down by the finalizer


async def test_finalize_error_on_otherwise_successful_run(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
    ])  # rotate left open: finalizer will close it
    fake.inject_error("pump_2", "stop", "hardware_error", "stall", times=2)  # teardown+sweep
    run = make_run(client, wf)
    with pytest.raises(FinalizeError) as info:
        await drive(run._options.clock, run.execute())
    assert len(info.value.errors) == 2
    assert run.report.status == "completed"  # block plane succeeded (D8)
    assert run.report.finalize_errors == info.value.errors


async def test_execute_is_single_shot(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"command": {"device": "pump_1", "verb": "stop"}}])
    run = make_run(client, wf)
    await drive(run._options.clock, run.execute())
    with pytest.raises(ExperimentRunError, match="once"):
        await run.execute()


async def test_external_cancellation_finalizes_and_reraises(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = make_run(client, wf)
    clock = run._options.clock
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    task.cancel()  # external cancel, NOT operator abort
    with pytest.raises(asyncio.CancelledError):
        await task
    assert run.report.status == "aborted"
    seq = verbs(fake)
    assert ("pump_1", "stop") in seq  # in-flight job device stopped (step 1)
    assert seq.count(("pump_2", "stop")) >= 1  # rotate torn down


def test_public_exports():
    import lab_devices.experiment as exp

    for name in (
        "ExperimentRun", "RunOptions", "RunReport", "assign_block_ids",
        "Clock", "MonotonicClock", "OperatorInputProvider", "InputRequest",
        "UnattendedInputProvider", "RunEvent", "RunLogSink", "InMemoryRunLog",
        "ExperimentRunError", "BlockFailedError", "InvariantViolationError",
        "RunAbortedError", "FinalizeError", "UnsupportedPersistenceError",
    ):
        assert hasattr(exp, name) and name in exp.__all__, name
