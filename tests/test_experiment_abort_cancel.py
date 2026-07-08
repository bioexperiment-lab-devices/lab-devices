import asyncio

import pytest

from lab_devices.experiment import ExperimentRun, RunAbortedError, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.fakeclock import FakeClock

_DISPENSE = [{"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}}]


async def test_double_abort_balances_cancellation(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow(_DISPENSE)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock))
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # dispense in flight
    run.abort()
    run.abort()  # second abort must NOT issue a second cancel()
    with pytest.raises(RunAbortedError):
        await task
    assert run.report is not None and run.report.status == "aborted"
    assert task.cancelling() == 0  # one cancel, one uncancel -> balanced


async def test_external_cancel_reports_cancelled(fake_client):
    # A cancellation NOT via run.abort() (e.g. an enclosing TaskGroup) => status "cancelled",
    # and the CancelledError propagates (asyncio correctness). Distinct from operator abort.
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow(_DISPENSE)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock))
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # dispense in flight
    task.cancel()  # external cancellation, abort_requested stays False
    with pytest.raises(asyncio.CancelledError):
        await task
    assert run.report is not None
    assert run.report.status == "cancelled"
    assert isinstance(run.report.error, asyncio.CancelledError)
    # finalizer still ran: the in-flight dispense's device was stopped
    from tests.experiment_run_helpers import verbs

    assert ("pump_1", "stop") in verbs(fake)
