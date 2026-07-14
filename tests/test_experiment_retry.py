"""Retry envelope around the dispatch pipeline (design 2026-07-14 §2.1, §3.1-3.2)."""
import asyncio

import pytest

from lab_devices import errors as core_errors
from lab_devices.experiment import BlockFailedError, ExperimentRun, RunAbortedError, RunOptions
from lab_devices.experiment.blocks import Retry
from lab_devices.experiment.execute import (
    _await_job,
    _clear_orphaned_job,
    _refuse_retry,
    _run_action,
)
from lab_devices.experiment.occupancy import OpenMode
from lab_devices.experiment.runlog import InMemoryRunLog
from lab_devices.jobs import Job
from tests.experiment_run_helpers import make_workflow, verbs
from tests.fakeclock import FakeClock, drive


def _od_workflow(retry=None, **block_extra):
    block = {"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"}}
    if retry is not None:
        block["retry"] = retry
    block.update(block_extra)
    return make_workflow([block], streams={"od_1": {"units": "AU"}})


async def test_retry_recovers_from_a_transient_fault(fake_client):
    """The fault that killed the real morbidostat run: one flaky read, next one succeeds."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error(
        "densitometer_1", "measure", "hardware_error",
        "intensity array: record header/index mismatch", times=1,
    )
    clock = FakeClock()
    run = ExperimentRun(
        client,
        _od_workflow(retry={"attempts": 3, "backoff": "2s"}),
        options=RunOptions(clock=clock),
    )
    report = await drive(clock, run.execute())
    assert report.status == "completed"
    assert len(report.state.streams["od_1"].samples) == 1
    kinds = [e.kind for e in report.log.events]
    assert kinds.count("block_retried") == 1
    assert kinds.count("block_failed") == 0


async def test_retry_exhausts_and_fails_the_run(fake_client):
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "hardware_error", "flaky", times=10)
    clock = FakeClock()
    run = ExperimentRun(
        client,
        _od_workflow(retry={"attempts": 3, "backoff": "2s"}),
        options=RunOptions(clock=clock),
    )
    with pytest.raises(BlockFailedError):
        await drive(clock, run.execute())
    assert run.report.status == "failed"
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("block_retried") == 2  # attempts=3 -> 2 retries, then failure
    assert kinds.count("block_failed") == 1


async def test_a_deny_listed_error_is_never_retried(fake_client):
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "not_calibrated", "calibrate me", times=10)
    clock = FakeClock()
    run = ExperimentRun(
        client,
        _od_workflow(retry={"attempts": 5, "backoff": "2s"}),
        options=RunOptions(clock=clock),
    )
    with pytest.raises(BlockFailedError):
        await drive(clock, run.execute())
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("block_retried") == 0  # fails fast; the error will never change


async def test_backoff_sleeps_on_the_clock(fake_client):
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "hardware_error", "flaky", times=1)
    clock = FakeClock()
    run = ExperimentRun(
        client,
        _od_workflow(retry={"attempts": 3, "backoff": "30s"}),
        options=RunOptions(clock=clock),
    )
    await drive(clock, run.execute())
    assert clock.now() >= 30.0  # the back-off was actually waited, on the fake clock


async def test_abort_during_backoff_is_not_retried(fake_client):
    """An operator abort must never be delayed or swallowed by a retry storm."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "hardware_error", "flaky", times=10)
    clock = FakeClock()
    run = ExperimentRun(
        client,
        _od_workflow(retry={"attempts": 5, "backoff": "60s"}),
        options=RunOptions(clock=clock),
    )
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    await clock.advance(1.0)  # first attempt has failed; we are inside the back-off sleep
    run.abort()
    with pytest.raises(RunAbortedError):
        await task
    assert run.report.status == "aborted"
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("block_retried") == 1  # the abort cut the storm short; no further attempt
    assert [c for c in fake.calls if c[1] == "measure"] == [("densitometer_1", "measure", {})]


async def test_abort_during_the_dispatch_is_not_retried(fake_client):
    """The other abort test lands in the back-off, which sits OUTSIDE _run_action's try. This
    one lands inside _dispatch_action -- the only await the except clause ever sees, and so the
    only place _is_retryable's CancelledError branch can fire. hold_job parks the run in
    _await_job's poll loop, inside the try. wait_for turns a swallowed abort (which would park
    forever in the 60s back-off) into a failure rather than a hang."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.hold_job("measure")
    clock = FakeClock()
    run = ExperimentRun(
        client,
        _od_workflow(retry={"attempts": 5, "backoff": "60s"}),
        options=RunOptions(clock=clock),
    )
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    await clock.advance(1.0)  # inside the job poll loop, i.e. inside the dispatch
    run.abort()
    with pytest.raises(RunAbortedError):
        await asyncio.wait_for(task, timeout=5.0)
    assert run.report.status == "aborted"
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("block_retried") == 0  # the abort was not absorbed by the retry
    assert len([c for c in fake.calls if c[1] == "measure"]) == 1  # nor re-dispatched


async def test_a_cancelled_job_is_never_retried(fake_client):
    """A job reports `cancelled` only because someone deliberately stopped the device
    (Job.cancel() -> device.stop(), the Console/Studio recovery seam). Re-dispatching would
    silently undo an operator's stop -- and here, re-dose the culture."""
    fake, client = fake_client
    fake.add_device("pump_1", "pump")
    fake.cancel_jobs.add("dispense")
    clock = FakeClock()
    workflow = make_workflow([{
        "command": {"device": "pump_1", "verb": "dispense",
                    "params": {"volume_ml": 0.5, "speed_ml_min": 3.0}},
        "retry": {"attempts": 3, "backoff": "1s", "allow_repeat": True},
    }])
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    with pytest.raises(BlockFailedError):
        await drive(clock, run.execute())
    assert run.report.status == "failed"
    assert [e.kind for e in run.report.log.events].count("block_retried") == 0
    assert len([c for c in fake.calls if c[1] == "dispense"]) == 1  # the stop stayed stopped


async def test_a_cancelled_job_is_not_retried_under_a_workflow_default(fake_client):
    """The zero-opt-in route: a retry_safe verb under defaults.retry needs no author action,
    so the deny-list -- not allow_repeat -- is what protects the operator's stop here."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.cancel_jobs.add("measure")
    clock = FakeClock()
    workflow = _od_workflow()
    workflow.defaults.retry = Retry(attempts=3, backoff="1s")
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    with pytest.raises(BlockFailedError):
        await drive(clock, run.execute())
    assert [e.kind for e in run.report.log.events].count("block_retried") == 0
    assert len([c for c in fake.calls if c[1] == "measure"]) == 1


def _held_dispense_workflow():
    return make_workflow([{
        "command": {"device": "pump_1", "verb": "dispense",
                    "params": {"volume_ml": 0.5, "speed_ml_min": 3.0}},
        "retry": {"attempts": 3, "backoff": "1s", "allow_repeat": True},
    }])


async def test_a_job_timeout_retry_cancels_the_job_it_abandoned(fake_client):
    """_await_job raises JobTimeoutError WITHOUT cancelling the job -- it is still physically
    running. Re-dispatching on top of it would stack a second concurrent job on the device
    (the agent would reject it as `busy`, surfacing as a FALSE invariant_violation). Every
    re-dispatch must be preceded by a stop that kills the orphan."""
    fake, client = fake_client
    fake.add_device("pump_1", "pump")
    fake.hold_job("dispense")  # no job ever completes -> every attempt times out
    clock = FakeClock()
    run = ExperimentRun(
        client, _held_dispense_workflow(),
        options=RunOptions(clock=clock, job_timeout=5.0),
    )
    with pytest.raises(BlockFailedError):
        await drive(clock, run.execute())
    wire = [cmd for _, cmd, _ in fake.calls]
    assert wire[:5] == ["dispense", "stop", "dispense", "stop", "dispense"]
    assert [e.kind for e in run.report.log.events].count("block_retried") == 2
    cancels = [e for e in run.report.log.events
               if e.kind == "job_cancelled" and e.block_id == "blocks[0]"]
    assert len(cancels) == 2  # one per retry; the last attempt leaves it to the finalizer
    # no job was ever left running alongside its successor
    assert [j.state for j in fake.jobs.values()] == ["cancelled"] * 3


async def test_a_job_timeout_whose_orphan_cannot_be_cancelled_is_not_retried(fake_client):
    """The device is unreachable -- often the very reason the job timed out. We cannot stop the
    orphan, so we must not stack a second job on it: the original JobTimeoutError surfaces
    unmasked and the job stays tracked, so the finalizer still stops that device."""
    fake, client = fake_client
    fake.add_device("pump_1", "pump")
    fake.hold_job("dispense")
    fake.inject_error("pump_1", "stop", "device_unreachable", "device is not responding")
    clock = FakeClock()
    run = ExperimentRun(
        client, _held_dispense_workflow(),
        options=RunOptions(clock=clock, job_timeout=5.0),
    )
    with pytest.raises(BlockFailedError) as exc:
        await drive(clock, run.execute())
    assert "did not finish within" in str(exc.value)  # the original error, not the stop failure
    assert len([c for c in fake.calls if c[1] == "dispense"]) == 1  # no second, racing job
    assert [e.kind for e in run.report.log.events].count("block_retried") == 0
    assert len(run._ctx.in_flight) == 1  # still tracked: the finalizer must stop this device
    # ...and WHY we refused reaches the run log: block_failed carries str(exc), which drops
    # __notes__, so the reason has to live in the message itself.
    failed = next(e for e in run.report.log.events if e.kind == "block_failed")
    assert "could not be cancelled" in failed.data["error"]
    assert "device is not responding" in failed.data["error"]


def _thermostat_then_measure_workflow(measures=2):
    """The examples/morbidostat.json shape: a thermostat mode held open across repeated
    measures on the SAME densitometer -- the only device whose channel groups (optics vs
    thermal) are disjoint, so occupancy permits a live mode and a live job at once."""
    blocks = [{
        "command": {"device": "densitometer_1", "verb": "set_thermostat",
                    "params": {"enabled": True, "target_c": 37.0}},
    }]
    blocks += [
        {"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"}}
        for _ in range(measures)
    ]
    return make_workflow(blocks, streams={"od_1": {"units": "AU"}})


async def test_a_job_timeout_retry_is_refused_when_the_stop_would_kill_an_open_mode(fake_client):
    """The orphan-cancel is a device.stop(), and densitometer.stop is DEVICE-WIDE (optics |
    thermal): it kills the thermostat too. Clearing the orphan would have closed the thermostat
    on the hardware while ctx.occupancy still held the OpenMode -- so the run would have carried
    on, recorded its samples, reported `completed`, and left the culture thermally uncontrolled
    for the rest of a three-week experiment, with nothing in the log to say so.

    Zero author opt-in reaches this: densitometer.measure is retry_safe, so a plain workflow
    defaults.retry is enough. Fail closed: refuse the retry and fail the run.
    """
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.hold_next_job("measure")  # only the FIRST measure hangs; a retry would have succeeded
    clock = FakeClock()
    workflow = _thermostat_then_measure_workflow()
    workflow.defaults.retry = Retry(attempts=3, backoff="1s")  # no allow_repeat, no block policy
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock, job_timeout=5.0))

    with pytest.raises(BlockFailedError) as exc:
        await drive(clock, run.execute())

    assert run.report.status == "failed"  # NOT "completed" with a silently-dead thermostat
    assert "did not finish within" in str(exc.value)  # the original error, unmasked
    assert "set_thermostat" in str(exc.value)  # ...naming the mode the stop would have killed
    events = run.report.log.events
    kinds = [e.kind for e in events]
    assert kinds.count("block_retried") == 0  # the retry was refused, not taken
    # the thermostat was never stopped mid-run: no orphan-cancel fired, and the only measure
    # that reached the wire is the one that hung (no second, racing job).
    assert [e for e in events if e.kind == "job_cancelled" and e.block_id is not None] == []
    assert len([c for c in fake.calls if c[1] == "measure"]) == 1
    assert run.report.state.streams["od_1"].samples == []  # no reading under a dead thermostat
    assert len(run._ctx.in_flight) == 1  # orphan still tracked: the finalizer stops the device
    # the mode was still held when the block failed, and only the finalizer closed it
    assert kinds.index("block_failed") < kinds.index("finalize_started")
    assert any(e.kind == "teardown_issued" and e.data["verb"] == "set_thermostat" for e in events)
    assert run._ctx.occupancy.open_modes() == ()  # torn down for real, not silently


async def test_a_job_timeout_retry_cancels_the_orphan_when_no_mode_is_open(fake_client):
    """The guard is narrow: with no open mode on the device, the stop closes nothing but the
    orphan, so the retry proceeds exactly as before -- stop, then re-dispatch."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.hold_next_job("measure")
    clock = FakeClock()
    workflow = _od_workflow()
    workflow.defaults.retry = Retry(attempts=3, backoff="1s")
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock, job_timeout=5.0))

    report = await drive(clock, run.execute())

    assert report.status == "completed"
    wire = [(device, cmd) for device, cmd, _ in fake.calls]
    assert wire[:3] == [
        ("densitometer_1", "measure"), ("densitometer_1", "stop"), ("densitometer_1", "measure"),
    ]
    kinds = [e.kind for e in report.log.events]
    assert kinds.count("block_retried") == 1
    assert [e for e in report.log.events
            if e.kind == "job_cancelled" and e.block_id is not None] != []
    assert len(report.state.streams["od_1"].samples) == 1
    assert run._ctx.in_flight == {}  # the orphan was stopped; nothing left for the finalizer


async def test_an_open_mode_on_another_device_does_not_refuse_the_retry(fake_client):
    """The guard is scoped to the device being STOPPED, not to the run. Two densitometers --
    same device type, so the same `stop` channels: a thermostat open on densitometer_1 says
    nothing about whether densitometer_2 may be stopped to clear its own orphan. (Checking the
    channels alone would be too coarse here and would strand every retry in the run.)"""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.add_device("densitometer_2", "densitometer")
    fake.hold_next_job("measure")  # densitometer_2's, the only measure in the workflow
    clock = FakeClock()
    workflow = make_workflow(
        [
            {"command": {"device": "densitometer_1", "verb": "set_thermostat",
                         "params": {"enabled": True, "target_c": 37.0}}},
            {"measure": {"device": "densitometer_2", "verb": "measure", "into": "od_2"}},
        ],
        streams={"od_2": {"units": "AU"}},
    )
    workflow.defaults.retry = Retry(attempts=3, backoff="1s")
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock, job_timeout=5.0))

    report = await drive(clock, run.execute())

    assert report.status == "completed"
    assert [e.kind for e in report.log.events].count("block_retried") == 1
    two_wire = [cmd for device, cmd, _ in fake.calls if device == "densitometer_2"]
    assert two_wire[:3] == ["measure", "stop", "measure"]  # its own orphan was cleared
    cancels = [e for e in report.log.events
               if e.kind == "job_cancelled" and e.block_id is not None]
    assert [e.data["device"] for e in cancels] == ["densitometer_2"]  # d_1 was never stopped
    assert len(report.state.streams["od_2"].samples) == 1


# --------------------------------------------------------------------------- #
# A failed POLL is not a failed job (design 2026-07-14 §3.2)                    #
# --------------------------------------------------------------------------- #
UNREACHABLE = ("device_unreachable", "device is not responding")


async def test_a_transient_poll_failure_is_polled_again_not_re_dispatched(fake_client):
    """_await_job's job.refresh() is a `get_job` over the wire. A fault on ONE poll says
    nothing about the job -- it is still RUNNING on the hardware. Letting it out of _await_job
    abandons a live job and lets _run_action re-dispatch on top of it: two concurrent measures
    on one densitometer, from a single dropped packet.

    The morbidostat shape, and it needs ZERO author opt-in to reach: job_timeout is None (the
    default), densitometer.measure is retry_safe, so a plain defaults.retry is enough. Under the
    old code this produced two jobs (j-1 'cancelled' only at finalize, j-2 'succeeded') and
    still reported `completed`. The right answer to a failed poll is to poll again."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "get_job", *UNREACHABLE, times=1)
    clock = FakeClock()
    workflow = _thermostat_then_measure_workflow(measures=1)
    workflow.defaults.retry = Retry(attempts=3, backoff="1s")  # no allow_repeat, no block policy
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))  # job_timeout=None

    report = await drive(clock, run.execute())

    assert report.status == "completed"
    # ONE job was ever started, and it succeeded -- not [j-1 cancelled, j-2 succeeded].
    assert [(j.cmd, j.state) for j in fake.jobs.values()] == [("measure", "succeeded")]
    assert len([c for c in fake.calls if c[1] == "measure"]) == 1  # never re-dispatched
    kinds = [e.kind for e in report.log.events]
    assert kinds.count("job_poll_retried") == 1  # ...and the operator can see the blip
    assert kinds.count("block_retried") == 0  # the block was never re-dispatched
    assert len(report.state.streams["od_1"].samples) == 1  # the reading was not lost
    assert run._ctx.in_flight == {}
    # No device-wide stop was needed, so the thermostat was never at risk: nothing but the
    # thermostat and the measure reached the wire before the finalizer opened its sweep.
    wire = [c[1] for c in fake.calls]
    teardown_at = wire.index("set_thermostat", 1)  # the finalizer's teardown of the mode
    assert wire[:teardown_at] == ["set_thermostat", "measure"]  # no device-wide stop in between
    assert kinds.index("finalize_started") < kinds.index("teardown_issued")
    assert [e for e in report.log.events
            if e.kind == "job_cancelled" and e.block_id is not None] == []


async def test_a_poll_retry_event_carries_the_job_and_the_fault(fake_client):
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "get_job", "internal_error", "transport blip", times=2)
    clock = FakeClock()
    run = ExperimentRun(client, _od_workflow(), options=RunOptions(clock=clock))

    report = await drive(clock, run.execute())

    assert report.status == "completed"  # no retry policy at all: the poll loop stands alone
    events = [e for e in report.log.events if e.kind == "job_poll_retried"]
    assert [e.data["failure"] for e in events] == [1, 2]
    assert events[0].block_id == "blocks[0]"
    assert events[0].data["device"] == "densitometer_1"
    assert events[0].data["job_id"] == "j-1"
    assert events[0].data["of"] == 5  # RunOptions.job_poll_max_failures
    assert "transport blip" in events[0].data["error"]


async def test_a_poll_failure_budget_is_bounded_and_leaves_the_job_tracked(fake_client):
    """The bound is not optional: a device that is really gone must not be polled forever.
    On exhaustion the fault propagates as before -- and the job stays in ctx.in_flight,
    because it may still be running: the finalizer must stop that device."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "get_job", *UNREACHABLE, times=50)
    clock = FakeClock()
    run = ExperimentRun(
        client, _od_workflow(),
        options=RunOptions(clock=clock, job_poll_max_failures=3),
    )

    with pytest.raises(BlockFailedError) as exc:
        await drive(clock, run.execute())

    assert "device is not responding" in str(exc.value)  # the poll fault, unmasked
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("job_poll_retried") == 3  # 3 tolerated; the 4th propagates
    assert len([c for c in fake.calls if c[1] == "measure"]) == 1  # never re-dispatched
    assert len(run._ctx.in_flight) == 1  # still live on the hardware -> finalizer stops it
    assert any(
        e.kind == "job_cancelled" and e.block_id is None for e in run.report.log.events
    )  # ...and it did


async def test_job_timeout_bounds_the_poll_failure_path(fake_client):
    """job_poll_max_failures is not the only bound on a failing poll -- job_timeout must cut
    it off too. Moving the deadline check into the loop's success-only branch (so a failing
    poll never sees it) survives the rest of the suite: with a large job_poll_max_failures,
    the deadline would be the ONLY thing standing between a truly dead device and polling out
    a run's entire wall-clock budget."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "get_job", *UNREACHABLE, times=20)
    clock = FakeClock()
    run = ExperimentRun(
        client, _od_workflow(),
        options=RunOptions(clock=clock, job_timeout=5.0, job_poll_max_failures=10_000),
    )

    with pytest.raises(BlockFailedError) as exc:
        await drive(clock, run.execute())

    assert "did not finish within 5.0s" in str(exc.value)  # the deadline, not the poll budget
    assert len(run._ctx.in_flight) == 1  # still tracked: the finalizer must stop this device


async def test_the_poll_failure_budget_is_consecutive_not_cumulative(fake_client):
    """A flaky link must not accumulate its way to a false failure over a long measure:
    any successful poll proves the link is alive, so the count resets. Six failures, budget
    of three, never more than three in a row -- the job still runs to completion."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    clock = FakeClock()
    run = ExperimentRun(
        client, _od_workflow(),
        options=RunOptions(clock=clock, job_poll_max_failures=3),
    )
    ctx = run._ctx
    block = ctx.workflow.blocks[0]
    job = Job(ctx.device("densitometer_1"), "j-1")
    ctx.in_flight[job.job_id] = ("densitometer_1", job)
    script = ["fail", "fail", "fail", "ok", "fail", "fail", "fail", "done"]

    async def scripted_refresh():
        step = script.pop(0)
        if step == "fail":
            raise core_errors.DeviceUnreachableError("device is not responding")
        if step == "done":
            job.state = "succeeded"
        return job

    job.refresh = scripted_refresh

    await drive(clock, _await_job(job, block, ctx))

    assert script == []  # every scripted poll was made: no failure escaped the loop
    assert [e.kind for e in ctx.log_sink.events].count("job_poll_retried") == 6
    assert ctx.in_flight == {}  # terminal: untracked


async def test_a_deny_listed_poll_failure_is_not_polled_again(fake_client):
    """The poll loop reuses the dispatch deny-list. An unknown job_id will read the same
    forever -- polling it again is a waste and the fault must surface at once."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "get_job", "invalid_params", "unknown job_id", times=50)
    clock = FakeClock()
    run = ExperimentRun(client, _od_workflow(), options=RunOptions(clock=clock))

    with pytest.raises(BlockFailedError):
        await drive(clock, run.execute())

    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("job_poll_retried") == 0  # fails on the FIRST failed poll
    assert kinds.count("block_retried") == 0


async def test_an_abort_during_a_poll_retry_is_immediate(fake_client):
    """A poll retry must never swallow or delay an abort: CancelledError is a BaseException,
    so it passes straight through the poll loop's `except Exception`. wait_for turns a
    swallowed abort into a failure rather than a hang."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "get_job", *UNREACHABLE, times=50)
    clock = FakeClock()
    run = ExperimentRun(
        client, _od_workflow(),
        options=RunOptions(clock=clock, job_poll_max_failures=1000),  # would poll ~forever
    )
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    await clock.advance(1.0)  # inside the poll-retry loop, backing off on the clock
    run.abort()

    with pytest.raises(RunAbortedError):
        await asyncio.wait_for(task, timeout=5.0)

    assert run.report.status == "aborted"
    before = [e.kind for e in run.report.log.events]
    assert before.count("job_poll_retried") < 1000  # the loop was torn down, not run out
    assert len([c for c in fake.calls if c[1] == "measure"]) == 1  # nor re-dispatched


async def test_abort_during_the_poll_wire_call_is_not_retried(fake_client):
    """The test above lands its abort at `await ctx.clock.sleep(interval)` in _await_job --
    OUTSIDE that function's try, so the except clause never sees the cancellation at all.
    Identical vacuity to the one a previous round found in test_abort_during_backoff_is_not_
    retried, fixed there by adding test_abort_during_the_dispatch_is_not_retried -- but that
    fix was never carried across to the poll loop added afterward.

    This test parks the run genuinely INSIDE job.refresh() -- the handler's only await, and
    the only place the except clause (and _is_retryable's CancelledError branch) can ever
    observe a cancellation -- via an Event-gated fake response (pause_next_get_job), with no
    wall-clock sleep. wait_for turns a swallowed abort (which would otherwise hang forever,
    since nothing ever advances the clock again) into a failure rather than a hang.

    Mutation-verified: widening `except Exception` to `except BaseException` in _await_job AND
    deleting the isinstance(exc, asyncio.CancelledError) branch from _is_retryable makes this
    test FAIL -- the abort is absorbed by the poll loop (a job_poll_retried event fires, the
    run task stays alive past the abort) -- while all other tests in this file still pass."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.pause_next_get_job()  # the abort itself cancels this parked wire call; no release needed
    clock = FakeClock()
    run = ExperimentRun(client, _od_workflow(), options=RunOptions(clock=clock))
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # measure dispatched; its first get_job is now parked on `gate`

    run.abort()

    with pytest.raises(RunAbortedError):
        await asyncio.wait_for(task, timeout=5.0)

    assert run.report.status == "aborted"
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("job_poll_retried") == 0  # the poll fault never happened; abort won
    assert kinds.count("block_retried") == 0  # not absorbed by the retry loop either
    assert len(run._ctx.in_flight) == 1  # the job is still live: the finalizer must stop it


async def test_an_orphan_is_cleared_whenever_a_job_is_still_tracked(fake_client):
    """The orphan-clear keys on the GENERAL predicate -- "did this attempt leave a job in
    ctx.in_flight?" -- not on isinstance(exc, JobTimeoutError). An exhausted poll budget is a
    second way to abandon a live job, and it is not a JobTimeoutError: keying on the exception
    type would quietly reopen the job-stacking bug for it (wire: measure, measure; j-1 left
    running under j-2). Keying on the fact that matters closes it for every future error class
    too."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "get_job", *UNREACHABLE, times=6)  # budget 5 -> exhausted
    clock = FakeClock()
    workflow = _od_workflow()
    workflow.defaults.retry = Retry(attempts=2, backoff="1s")
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))

    report = await drive(clock, run.execute())

    assert report.status == "completed"
    wire = [(device, cmd) for device, cmd, _ in fake.calls]
    assert wire[:3] == [
        ("densitometer_1", "measure"), ("densitometer_1", "stop"), ("densitometer_1", "measure"),
    ]  # the re-dispatch was preceded by a stop that killed the orphan
    assert [(j.cmd, j.state) for j in fake.jobs.values()] == [
        ("measure", "cancelled"), ("measure", "succeeded"),
    ]  # j-1 was never left running alongside j-2
    kinds = [e.kind for e in report.log.events]
    assert kinds.count("job_poll_retried") == 5
    assert kinds.count("block_retried") == 1
    assert run._ctx.in_flight == {}


# --------------------------------------------------------------------------- #
# The open-mode guard is a check-and-act under a contended lock                 #
# --------------------------------------------------------------------------- #
def _same_device_parallel_workflow():
    """Two children on the SAME densitometer, on disjoint channels (thermal vs optics). The
    affinity check is per-(device, channel), so this validates clean -- which is what makes the
    guard's TOCTOU window reachable from a workflow, not just from a unit test."""
    return make_workflow(
        [{"parallel": {"children": [
            {"command": {"device": "densitometer_1", "verb": "set_thermostat",
                         "params": {"enabled": True, "target_c": 37.0}}},
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"}},
        ]}}],
        streams={"od_1": {"units": "AU"}},
    )


async def test_the_open_mode_guard_is_re_checked_under_the_wire_lock(fake_client):
    """TOCTOU under a contended lock. The open-mode check must be read no earlier than the
    moment the guard actually HOLDS ctx.lock(device): asyncio.Lock.acquire() only yields when
    the lock is CONTENDED, and it is exactly then that a read taken before queuing would go
    stale before the guard is ever granted the lock.

    The lane ahead of it in the lock queue is a sibling whose set_thermostat is in flight:
    _dispatch_action awaits its wire call UNDER the lock and calls register_open only after
    releasing it. So the heater can be physically ON and absent from ctx.occupancy at the moment
    the guard queues for the lock. A check read at that moment (instead of once inside the lock)
    would see zero open modes and issue the stop once the mode has been registered --
    thermostat dead, run `completed`, nothing in the log.

    ExperimentRun(...) construction is itself the reachability proof: it validates the workflow.
    """
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    clock = FakeClock()
    run = ExperimentRun(
        client, _same_device_parallel_workflow(),
        options=RunOptions(clock=clock, job_timeout=5.0),
    )
    ctx = run._ctx
    measure_block = ctx.workflow.blocks[0].children[1]
    job = Job(ctx.device("densitometer_1"), "j-1")  # the abandoned measure, still running
    ctx.in_flight[job.job_id] = ("densitometer_1", job)
    exc = core_errors.JobTimeoutError("job j-1 did not finish within 5.0s")
    thermostat_acked = asyncio.Event()

    async def thermostat_lane():
        # Exactly _dispatch_action's shape: the wire call under the lock, register_open only
        # after releasing it.
        async with ctx.lock("densitometer_1"):
            await thermostat_acked.wait()
        ctx.occupancy.register_open(OpenMode(
            device="densitometer_1", mode_verb="set_thermostat",
            teardown_verb="set_thermostat", teardown_params={"enabled": False},
            channels=frozenset({"thermal"}), block_id="blocks[0].children[0]",
        ))

    lane = asyncio.ensure_future(thermostat_lane())
    await clock.settle()
    assert ctx.lock("densitometer_1").locked()  # the heater is switching on...
    assert ctx.occupancy.open_modes("densitometer_1") == ()  # ...and is not yet in occupancy

    guard = asyncio.ensure_future(_clear_orphaned_job(exc, [job], measure_block, ctx))
    await clock.settle()  # the guard queues on the contended lock; nothing read yet

    thermostat_acked.set()  # the ack lands: lock released, THEN register_open
    may_retry = await guard
    await lane

    assert may_retry is False  # refused, on the mode it could only see from inside the lock
    assert [c[1] for c in fake.calls] == []  # no stop ever reached the wire
    assert len(ctx.occupancy.open_modes("densitometer_1")) == 1  # thermostat still held
    assert job.job_id in ctx.in_flight  # still live on the hardware: the finalizer must stop it
    assert "set_thermostat" in str(exc)  # ...and the reason reaches the run log
    assert [e.kind for e in ctx.log_sink.events].count("job_cancelled") == 0


async def test_the_orphan_check_confirms_job_identity_not_just_the_job_id(fake_client):
    """ctx.in_flight is keyed by job_id alone, and membership in it is now a safety decision
    (not just finalizer bookkeeping). If a DIFFERENT Job object were ever tracked under the
    same id -- two devices returning the same job_id would overwrite each other's entry -- a
    bare `job.job_id in ctx.in_flight` membership test would treat a foreign job as this
    attempt's own orphan: it would issue a stop attributed to the wrong job and pop the OTHER
    job's tracking entry, silently making the run believe a still-running job is untracked."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    clock = FakeClock()
    run = ExperimentRun(client, _od_workflow(), options=RunOptions(clock=clock))
    ctx = run._ctx
    block = ctx.workflow.blocks[0]
    job = Job(ctx.device("densitometer_1"), "j-1")  # this attempt's own (unabandoned) job
    other = Job(ctx.device("densitometer_1"), "j-1")  # a DIFFERENT Job tracked under the same id
    ctx.in_flight[other.job_id] = ("densitometer_1", other)
    exc = core_errors.JobTimeoutError("job j-1 did not finish within 5.0s")

    may_retry = await _clear_orphaned_job(exc, [job], block, ctx)

    assert may_retry is True  # not OUR job in in_flight -> nothing of ours to abandon
    assert [c[1] for c in fake.calls] == []  # no stop was issued over the identity mismatch
    assert ctx.in_flight[other.job_id][1] is other  # the OTHER job's tracking is untouched


def test_refuse_retry_keeps_str_and_message_in_agreement():
    """LabError.__init__ stores the message twice (args + .message). Folding the reason into
    only one of them leaves str(exc) and exc.message disagreeing -- a latent trap."""
    exc = core_errors.JobTimeoutError("job j-1 did not finish within 5.0s")

    assert _refuse_retry(exc, "retry refused: it would have killed set_thermostat") is False

    assert str(exc) == exc.message
    assert "did not finish within" in exc.message  # the original error, preserved as a prefix
    assert "retry refused" in exc.message


async def test_workflow_defaults_apply_to_a_block_without_retry(fake_client):
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "hardware_error", "flaky", times=1)
    clock = FakeClock()
    workflow = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"}}],
        streams={"od_1": {}},
    )
    workflow.defaults.retry = Retry(attempts=3, backoff="1s")
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())
    assert report.status == "completed"
    assert [e.kind for e in report.log.events].count("block_retried") == 1


async def test_workflow_defaults_never_retry_a_non_idempotent_verb(fake_client):
    """A blanket default must not silently double-dose a culture.

    This is the ONLY guard in the codebase for that property: the validator neither
    enforces nor can enforce it. It lives entirely in _effective_retry consulting
    Trait.retry_safe (design 2026-07-14 §2.4, §4).
    """
    fake, client = fake_client
    fake.add_device("pump_1", "pump")
    fake.inject_error("pump_1", "dispense", "hardware_error", "flaky", times=1)
    clock = FakeClock()
    workflow = make_workflow([{
        "command": {"device": "pump_1", "verb": "dispense",
                    "params": {"volume_ml": 0.5, "speed_ml_min": 3.0}}
    }])
    workflow.defaults.retry = Retry(attempts=3, backoff="1s")
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    with pytest.raises(BlockFailedError):
        await drive(clock, run.execute())
    assert [e.kind for e in run.report.log.events].count("block_retried") == 0
    # the cytotoxic drug reached the culture exactly once, not twice
    assert len([c for c in fake.calls if c[1] == "dispense"]) == 1


async def test_an_explicit_block_policy_overrides_the_workflow_default(fake_client):
    """Block policy wins as-is: an explicit allow_repeat opt-in retries a non-idempotent
    verb (the author accepted the repeat in-document), and it is not gated by the default."""
    fake, client = fake_client
    fake.add_device("pump_1", "pump")
    fake.inject_error("pump_1", "dispense", "hardware_error", "flaky", times=1)
    clock = FakeClock()
    workflow = make_workflow([{
        "command": {"device": "pump_1", "verb": "dispense",
                    "params": {"volume_ml": 0.5, "speed_ml_min": 3.0}},
        "retry": {"attempts": 2, "backoff": "1s", "allow_repeat": True},
    }])
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())
    assert report.status == "completed"
    assert [e.kind for e in report.log.events].count("block_retried") == 1


async def test_block_retried_event_carries_attempt_of_and_error(fake_client):
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "hardware_error", "flaky read", times=1)
    clock = FakeClock()
    run = ExperimentRun(
        client,
        _od_workflow(retry={"attempts": 3, "backoff": "1s"}),
        options=RunOptions(clock=clock),
    )
    report = await drive(clock, run.execute())
    event = next(e for e in report.log.events if e.kind == "block_retried")
    assert event.block_id == "blocks[0]"
    assert event.data["attempt"] == 1
    assert event.data["of"] == 3
    assert "flaky read" in event.data["error"]


async def test_no_retry_policy_dispatches_exactly_once(fake_client):
    """The default is unchanged behavior: one attempt, no back-off, no retry events."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "hardware_error", "flaky", times=1)
    clock = FakeClock()
    run = ExperimentRun(client, _od_workflow(), options=RunOptions(clock=clock))
    with pytest.raises(BlockFailedError):
        await drive(clock, run.execute())
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("block_retried") == 0
    assert len([c for c in fake.calls if c[1] == "measure"]) == 1


class _StrandEventRaisingSink:
    """Passes every event through to an inner log, then raises on `job_stranded` — the one emit
    that runs inside a `finally`, i.e. with the abort's CancelledError already in flight. A sink
    that raises breaks the protocol (emit() must never raise, design 5 §8), but the engine must
    survive one: no shipped sink raises, and a run must not become un-abortable because a custom
    one does."""

    def __init__(self) -> None:
        self.inner = InMemoryRunLog()
        self.raised = 0

    def emit(self, event) -> None:
        self.inner.emit(event)
        if event.kind == "job_stranded":
            self.raised += 1
            raise RuntimeError("sink boom on job_stranded")

    @property
    def events(self):
        return self.inner.events


_FINALIZER_SWEEP = {
    ("densitometer_1", verb)
    for verb in ("stop", "stop_monitoring", "set_led", "set_thermostat")
}


async def test_a_raising_sink_on_the_abort_path_never_resurrects_the_retry(fake_client):
    """A raising log sink in `_dispatch_action`'s `finally` must not displace the operator's
    abort. If it does, the CancelledError is REPLACED by the sink's error, `_run_action`'s
    `except Exception` catches it, `_is_retryable` says yes, `_clear_orphaned_job` stops the
    device and the retry loop RE-DISPATCHES — hardware moving after `abort()` has returned, the
    run hanging, no report. hold_job parks the run in the poll loop, inside the dispatch, so the
    abort lands where the `finally` (and the `job_stranded` emit) will run on the way out; the
    clock is then advanced well past the back-off so a surviving retry would have every chance to
    re-dispatch.

    The termination guard is `asyncio.wait`, deliberately NOT `wait_for`: an engine that lets a
    sink displace a cancellation displaces the one `wait_for` itself issues on timeout, and
    `wait_for` then waits for that cancellation to land — forever. Against this bug the usual
    guard IS the hang (measured: the pre-fix code hung pytest indefinitely under `wait_for`).
    `asyncio.wait` never cancels, so a run that will not stop is an assertion failure."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.hold_job("measure")
    clock = FakeClock()
    sink = _StrandEventRaisingSink()
    run = ExperimentRun(
        client,
        _od_workflow(retry={"attempts": 5, "backoff": "60s"}),
        options=RunOptions(clock=clock, log_sink=sink),
    )
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    await clock.advance(1.0)  # inside the job poll loop, i.e. inside the dispatch
    before = len(fake.calls)
    run.abort()
    await clock.advance(300.0)  # five back-offs' worth: a live retry would have fired by now
    done, _pending = await asyncio.wait({task}, timeout=5.0)
    if not done:
        task.cancel()  # never awaited: a run that swallows cancellations would hang the test
        raise AssertionError("the run never terminated after abort(): the abort was swallowed")
    with pytest.raises(RunAbortedError):
        await task
    assert sink.raised == 1  # the sink DID raise on the abort path (else the test proves nothing)
    assert run.report.status == "aborted"  # not "failed": the sink's error never became the run's
    assert isinstance(run.report.error, asyncio.CancelledError)
    after = verbs(fake)[before:]
    assert ("densitometer_1", "measure") not in after  # no re-dispatch after abort() returned
    assert set(after) <= _FINALIZER_SWEEP  # and nothing else reached the wire but safe state
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("block_retried") == 0  # nor was the abort delayed by a back-off


async def test_a_retry_never_dispatches_after_an_abort_however_the_error_arrived(fake_client):
    """The second half of that fix, on its own. With the `finally` emit wrapped, nothing can
    displace the CancelledError through the executor's own paths any more — so the retry loop's
    `abort_requested` guard is defence in depth, and this is the only way to see it work. Drive
    `_run_action` directly in the exact state a displaced cancellation leaves behind: the abort is
    a FACT (`ctx.abort_requested`), but no CancelledError is in flight. Nothing may reach the
    wire: `abort()` has returned."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    clock = FakeClock()
    run = ExperimentRun(
        client,
        _od_workflow(retry={"attempts": 3, "backoff": "1s"}),
        options=RunOptions(clock=clock),
    )
    ctx = run._ctx
    ctx.abort_requested = True  # the cancellation was consumed; only the fact survives
    with pytest.raises(asyncio.CancelledError):
        await _run_action(run._workflow.blocks[0], ctx)
    assert fake.calls == []  # the retry loop refused to dispatch at all
