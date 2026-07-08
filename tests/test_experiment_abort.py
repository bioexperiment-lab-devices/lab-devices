import asyncio

import pytest

from lab_devices.experiment import ExperimentRun, RunAbortedError, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock


def start_run(client, wf):
    run = ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))
    task = asyncio.ensure_future(run.execute())
    return run, run._options.clock, task


async def test_abort_midrun_cancels_and_finalizes(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    assert verbs(fake) == [("pump_2", "rotate"), ("pump_1", "dispense")]

    run.abort()
    with pytest.raises(RunAbortedError):
        await task
    assert run.report.status == "aborted"
    assert isinstance(run.report.error, asyncio.CancelledError)
    # finalizer: (1) stop the in-flight job's device, (2) teardown rotate, (3) sweep
    assert verbs(fake)[2:] == [
        ("pump_1", "stop"),   # step 1: cancelled wait left the job tracked
        ("pump_2", "stop"),   # step 2: rotate teardown
        ("pump_2", "stop"),   # step 3: sweep, touched order
        ("pump_1", "stop"),
    ]
    assert run._ctx.occupancy.open_modes() == ()
    kinds = [e.kind for e in run.report.log.events]
    assert "abort_requested" in kinds and "finalize_finished" in kinds


async def test_abort_before_execute(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"command": {"device": "pump_1", "verb": "stop"}}])
    run = ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))
    run.abort()
    with pytest.raises(RunAbortedError):
        await run.execute()
    assert fake.calls == []  # nothing dispatched, nothing touched, empty sweep
    assert run.report.status == "aborted"


async def test_abort_while_paused(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
        {"command": {"device": "pump_2", "verb": "stop"}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    run.pause()
    run.abort()  # abort must win over the closed gate
    with pytest.raises(RunAbortedError):
        await task
    assert run.report.status == "aborted"
    assert ("pump_1", "stop") in verbs(fake)  # in-flight dispense's device stopped
    assert ("pump_2", "stop") not in verbs(fake)[:2]  # second block never dispatched


async def test_abort_idempotent(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    run.abort()
    run.abort()
    with pytest.raises(RunAbortedError):
        await task
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("abort_requested") == 1
