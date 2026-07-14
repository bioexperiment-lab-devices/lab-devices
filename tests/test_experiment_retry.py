"""Retry envelope around the dispatch pipeline (design 2026-07-14 §2.1, §3.1-3.2)."""
import asyncio

import pytest

from lab_devices.experiment import BlockFailedError, ExperimentRun, RunAbortedError, RunOptions
from lab_devices.experiment.blocks import Retry
from tests.experiment_run_helpers import make_workflow
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
