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
