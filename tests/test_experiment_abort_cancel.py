import asyncio

import pytest

from lab_devices.experiment import ExperimentRun, RunAbortedError, RunOptions
from lab_devices.experiment.runlog import InMemoryRunLog
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
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
    assert ("pump_1", "stop") in verbs(fake)


class _AbortEventRaisingSink:
    """Passes every event through to an inner log EXCEPT abort_requested, which raises."""

    def __init__(self) -> None:
        self.inner = InMemoryRunLog()

    def emit(self, event) -> None:
        if event.kind == "abort_requested":
            raise RuntimeError("sink boom on abort_requested")
        self.inner.emit(event)


async def test_abort_survives_raising_sink_on_abort_event(fake_client):
    # NEW-2: a log sink that raises on the abort_requested emit must NOT block the abort
    # path (design 5 §8). The cancel must already be issued, and the run still finalizes.
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow(_DISPENSE)
    clock = FakeClock()
    sink = _AbortEventRaisingSink()
    run = ExperimentRun(client, wf, RunOptions(clock=clock, log_sink=sink))
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # dispense in flight
    run.abort()  # must NOT raise out of the call despite the sink raising
    with pytest.raises(RunAbortedError):
        await task
    assert run.report is not None and run.report.status == "aborted"
    assert ("pump_1", "stop") in verbs(fake)  # finalizer reached safe state
