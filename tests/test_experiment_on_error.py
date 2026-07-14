"""`on_error: continue` — block-level fault tolerance (design 2026-07-14 §2.2, §3.3-3.4)."""
import asyncio

import pytest

from lab_devices import errors as core_errors
from lab_devices.experiment import (
    ExperimentRun,
    InvariantViolationError,
    RunAbortedError,
    RunOptions,
)
from lab_devices.experiment.execute import _tolerable
from tests.experiment_run_helpers import make_workflow, verbs
from tests.fakeclock import FakeClock, drive

FLAKY = ("hardware_error", "flaky")


def _measure(i: int = 1, **extra):
    block = {"measure": {"device": f"densitometer_{i}", "verb": "measure", "into": f"od_{i}"}}
    block.update(extra)
    return block


def _home(device: str = "valve_1"):
    return {"command": {"device": device, "verb": "home", "params": {"position": 1}}}


def _wait(duration: str):
    return {"wait": {"duration": duration}}


def _serial(*children):
    return {"serial": {"children": list(children)}}


def _isolation_workflow(*, tolerate_lane_2: bool):
    """Three lanes: 1 and 3 wait 30s before their own measure -- deliberately OUTLIVING
    lane 2's near-instant dispatch failure, so this fixture actually discriminates fault
    isolation from a mere status/count coincidence (a bare `measure` in every lane can
    finish before lane 2's failure even propagates, and would carry zero information about
    isolation either way)."""
    lane2 = _measure(2)
    if tolerate_lane_2:
        lane2["on_error"] = "continue"
    return make_workflow(
        [{"parallel": {"children": [
            _serial(_wait("30s"), _measure(1)),
            lane2,
            _serial(_wait("30s"), _measure(3)),
        ]}}],
        streams={"od_1": {}, "od_2": {}, "od_3": {}},
    )


def _kinds(report):
    return [e.kind for e in report.log.events]


async def test_tolerated_failure_continues_to_the_next_sibling(fake_client):
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.add_device("valve_1", "valve")
    fake.inject_error("densitometer_1", "measure", *FLAKY, times=10)
    clock = FakeClock()
    workflow = make_workflow(
        [
            _measure(on_error="continue"),
            _home("valve_1"),
        ],
        streams={"od_1": {}},
    )
    report = await drive(
        clock, ExperimentRun(client, workflow, options=RunOptions(clock=clock)).execute()
    )
    assert report.status == "completed"
    assert ("valve_1", "home") in verbs(fake)  # the sibling still ran
    assert len(report.tolerated_errors) == 1
    assert report.tolerated_errors[0].block_id == "blocks[0]"
    assert "flaky" in report.tolerated_errors[0].error
    assert "block_error_tolerated" in _kinds(report)
    assert report.state.streams["od_1"].samples == []  # the sample really was dropped


async def test_a_tolerated_block_is_failed_not_finished(fake_client):
    """Exactly-once event semantics (§10): the block failed and was absorbed. It did not
    finish, and the run log must not claim it did."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", *FLAKY, times=10)
    clock = FakeClock()
    workflow = make_workflow([_measure(on_error="continue")], streams={"od_1": {}})
    report = await drive(
        clock, ExperimentRun(client, workflow, options=RunOptions(clock=clock)).execute()
    )
    kinds = _kinds(report)
    assert kinds.count("block_failed") == 1
    assert kinds.count("block_error_tolerated") == 1
    assert kinds.count("block_finished") == 0
    tolerated = next(e for e in report.log.events if e.kind == "block_error_tolerated")
    assert tolerated.block_id == "blocks[0]"
    assert "flaky" in tolerated.data["error"]


async def test_a_tolerated_parallel_lane_leaves_its_siblings_running(fake_client):
    """Feature #3: one bad vial must not kill the other fourteen.

    Lanes 1 and 3 wait 30s before their own measure -- outliving lane 2's near-instant
    dispatch failure -- so this fixture actually discriminates isolation from a status/count
    coincidence: a bare `measure` in every lane can finish before lane 2's failure even
    propagates, in which case these same three assertions would hold with NO isolation
    mechanism at all. `_run_parallel` is an asyncio.TaskGroup, which cancels siblings only
    when a lane *raises*. A tolerated lane absorbs its failure inside its own task and
    returns normally, so the TaskGroup never sees an exception and the siblings survive to
    reach their own measure blocks 30s later.

    Mutation-verified: a mutant that keeps the tolerance decision (the ToleratedError is
    still recorded) but re-raises a sentinel that the parallel then swallows -- so the
    TaskGroup still cancels lanes 1 and 3 -- makes this test FAIL (od_1/od_3 drop to 0
    samples) while every other test in this file stays green.
    """
    fake, client = fake_client
    for i in (1, 2, 3):
        fake.add_device(f"densitometer_{i}", "densitometer")
    fake.inject_error("densitometer_2", "measure", *FLAKY, times=10)
    clock = FakeClock()
    workflow = _isolation_workflow(tolerate_lane_2=True)
    report = await drive(
        clock, ExperimentRun(client, workflow, options=RunOptions(clock=clock)).execute()
    )
    assert report.status == "completed"
    assert len(report.state.streams["od_1"].samples) == 1  # outlived lane 2's failure
    assert len(report.state.streams["od_2"].samples) == 0  # the bad vial dropped its sample
    assert len(report.state.streams["od_3"].samples) == 1
    assert len(report.tolerated_errors) == 1
    assert report.tolerated_errors[0].block_id == "blocks[0].children[1]"


async def test_an_untolerated_parallel_lane_still_kills_its_siblings(fake_client):
    """The contrast that gives the test above its meaning: without `on_error: continue` on
    lane 2, its dispatch failure raises, the TaskGroup cancels lanes 1 and 3 while they are
    still asleep in their 30s wait -- BEFORE either reaches its own measure -- and the run
    fails. The siblings are genuinely killed here (never dispatched), not merely "the run
    raised"; that is the status quo this feature exists to change, and it must stay the
    default."""
    fake, client = fake_client
    for i in (1, 2, 3):
        fake.add_device(f"densitometer_{i}", "densitometer")
    fake.inject_error("densitometer_2", "measure", *FLAKY, times=10)
    clock = FakeClock()
    workflow = _isolation_workflow(tolerate_lane_2=False)
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    with pytest.raises(BaseExceptionGroup):
        await drive(clock, run.execute())
    assert run.report.status == "failed"
    assert run.report.tolerated_errors == ()
    assert run.report.state.streams["od_1"].samples == []  # killed mid-wait: never measured
    assert run.report.state.streams["od_3"].samples == []
    assert ("densitometer_1", "measure") not in verbs(fake)
    assert ("densitometer_3", "measure") not in verbs(fake)


async def test_tolerance_on_the_parallel_itself_abandons_the_container(fake_client):
    """`on_error` on the `parallel` block: the TaskGroup's ExceptionGroup is caught at the
    parallel's own frame, the container is abandoned, and the PARENT carries on.

    The lane itself has no `on_error`, so it fails with an ordinary `BlockFailedError`; the
    parallel's tolerance must flatten the TaskGroup's ExceptionGroup down to that error's own
    message, not report the group's boilerplate `str()` (design 2026-07-14 §3.4) -- the one
    shape that would otherwise reach report.json and Studio with no indication of what
    actually failed."""
    fake, client = fake_client
    for i in (1, 2):
        fake.add_device(f"densitometer_{i}", "densitometer")
    fake.add_device("valve_1", "valve")
    fake.inject_error("densitometer_2", "measure", *FLAKY, times=10)
    clock = FakeClock()
    workflow = make_workflow(
        [
            {"parallel": {"children": [_measure(1), _measure(2)]}, "on_error": "continue"},
            _home("valve_1"),
        ],
        streams={"od_1": {}, "od_2": {}},
    )
    report = await drive(
        clock, ExperimentRun(client, workflow, options=RunOptions(clock=clock)).execute()
    )
    assert report.status == "completed"
    assert ("valve_1", "home") in verbs(fake)
    assert len(report.tolerated_errors) == 1
    assert report.tolerated_errors[0].block_id == "blocks[0]"  # the parallel, not a lane
    error = report.tolerated_errors[0].error
    assert "flaky" in error  # names the actual failure...
    assert "blocks[0].children[1]" in error  # ...and which lane it came from
    assert "TaskGroup" not in error  # ...not the group's own boilerplate str()


async def test_tolerance_on_a_serial_abandons_the_rest_of_its_body(fake_client):
    """A tolerated container abandons the blocks it had not reached yet -- the tolerance is
    `continue past this block`, never `skip this block and finish the rest of it`."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.add_device("valve_1", "valve")
    fake.add_device("valve_2", "valve")
    fake.inject_error("densitometer_1", "measure", *FLAKY, times=10)
    clock = FakeClock()
    workflow = make_workflow(
        [
            {
                "serial": {"children": [
                    _measure(),
                    _home("valve_2"),  # never reached
                ]},
                "on_error": "continue",
            },
            _home("valve_1"),
        ],
        streams={"od_1": {}},
    )
    report = await drive(
        clock, ExperimentRun(client, workflow, options=RunOptions(clock=clock)).execute()
    )
    assert report.status == "completed"
    assert ("valve_2", "home") not in verbs(fake)  # abandoned with the container
    assert ("valve_1", "home") in verbs(fake)  # the parent carried on
    assert [t.block_id for t in report.tolerated_errors] == ["blocks[0]"]


async def test_gap_after_is_still_honored_after_a_tolerated_block(fake_client):
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", *FLAKY, times=10)
    clock = FakeClock()
    workflow = make_workflow(
        [_measure(on_error="continue", gap_after="45s")], streams={"od_1": {}}
    )
    await drive(clock, ExperimentRun(client, workflow, options=RunOptions(clock=clock)).execute())
    assert clock.now() >= 45.0


async def test_retry_then_tolerate_composes(fake_client):
    """Retry first; only a persistent fault reaches the tolerance."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", *FLAKY, times=10)
    clock = FakeClock()
    workflow = make_workflow(
        [_measure(retry={"attempts": 3, "backoff": "2s"}, on_error="continue")],
        streams={"od_1": {}},
    )
    report = await drive(
        clock, ExperimentRun(client, workflow, options=RunOptions(clock=clock)).execute()
    )
    assert report.status == "completed"
    kinds = _kinds(report)
    assert kinds.count("block_retried") == 2  # exhausted the policy...
    assert kinds.count("block_error_tolerated") == 1  # ...then tolerated the failure
    assert len([c for c in fake.calls if c[1] == "measure"]) == 3


async def test_a_tolerated_loop_body_keeps_the_loop_running(fake_client):
    """The morbidostat shape: a sensor outage drops samples, and the run keeps cycling."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", *FLAKY, times=2)  # 2 of 4 reads fail
    clock = FakeClock()
    workflow = make_workflow(
        [{"loop": {"count": 4, "body": [_measure(on_error="continue")]}}],
        streams={"od_1": {}},
    )
    report = await drive(
        clock, ExperimentRun(client, workflow, options=RunOptions(clock=clock)).execute()
    )
    assert report.status == "completed"
    assert len(report.tolerated_errors) == 2
    assert len(report.state.streams["od_1"].samples) == 2  # ...and the run kept its 2 good reads


# --------------------------------------------------------------------------- #
# What a tolerance must NEVER swallow (design 2026-07-14 §3.3)                  #
# --------------------------------------------------------------------------- #
async def test_an_invariant_violation_is_never_tolerated(fake_client):
    """A proven-impossible state means the safety model is broken. Fail the run."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "busy", "device busy", times=10)
    clock = FakeClock()
    workflow = make_workflow([_measure(on_error="continue")], streams={"od_1": {}})
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    with pytest.raises(InvariantViolationError):
        await drive(clock, run.execute())
    assert run.report.status == "failed"
    assert run.report.tolerated_errors == ()
    assert _kinds(run.report).count("block_error_tolerated") == 0


async def test_an_invariant_violation_inside_a_parallel_is_never_tolerated(fake_client):
    """...and it is not laundered by an ExceptionGroup either: a tolerance on the `parallel`
    must look INSIDE the group the TaskGroup raises, at every depth."""
    fake, client = fake_client
    for i in (1, 2):
        fake.add_device(f"densitometer_{i}", "densitometer")
    fake.add_device("valve_1", "valve")
    fake.inject_error("densitometer_2", "measure", "busy", "device busy", times=10)
    clock = FakeClock()
    workflow = make_workflow(
        [
            {"parallel": {"children": [_measure(1), _measure(2)]}, "on_error": "continue"},
            _home("valve_1"),
        ],
        streams={"od_1": {}, "od_2": {}},
    )
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    with pytest.raises(BaseExceptionGroup) as exc:
        await drive(clock, run.execute())
    flat = exc.value.subgroup(InvariantViolationError)
    assert flat is not None  # the violation surfaced; it was not absorbed by the parallel
    assert run.report.status == "failed"
    assert run.report.tolerated_errors == ()
    assert ("valve_1", "home") not in verbs(fake)  # the run stopped; it did not carry on


async def test_a_tolerated_lane_does_not_launder_a_sibling_invariant_violation(fake_client):
    """The lane-level tolerance is per-lane. A tolerated lane absorbs ITS OWN failure -- it
    must not absorb an invariant violation raised by a DIFFERENT lane, which still tears the
    TaskGroup down and fails the run."""
    fake, client = fake_client
    for i in (1, 2):
        fake.add_device(f"densitometer_{i}", "densitometer")
    fake.inject_error("densitometer_1", "measure", *FLAKY, times=10)  # tolerated
    fake.inject_error("densitometer_2", "measure", "busy", "device busy", times=10)  # fatal
    clock = FakeClock()
    workflow = make_workflow(
        [{"parallel": {"children": [
            _measure(1, on_error="continue"),
            _measure(2, on_error="continue"),
        ]}}],
        streams={"od_1": {}, "od_2": {}},
    )
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    with pytest.raises(BaseExceptionGroup) as exc:
        await drive(clock, run.execute())
    assert exc.value.subgroup(InvariantViolationError) is not None
    assert run.report.status == "failed"


async def test_an_abort_inside_a_tolerated_block_is_never_swallowed(fake_client):
    """An operator abort must never be absorbed by a tolerance.

    The abort lands genuinely INSIDE `execute_block`'s try: `hold_job` parks the run in
    `_await_job`'s poll loop, which is reached through `_execute_inner`. (The one await
    `execute_block` has OUTSIDE its try is `ctx.gate.wait()`, so an abort delivered while
    paused would prove nothing -- this test must not be written that way.)

    Mutation-verified: widening `except Exception` to `except BaseException` in
    `execute_block` (with or without deleting the CancelledError arm, and with or without
    deleting the CancelledError branch of `_tolerable`) makes this test FAIL -- the abort is
    either absorbed outright (the run reports `completed`, and valve_1 is homed AFTER the
    operator hit abort) or masked as a BlockFailedError. `wait_for` turns a swallowed abort
    into a failure rather than a hang.
    """
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.add_device("valve_1", "valve")
    fake.hold_job("measure")  # parks the run inside the poll loop, inside execute_block's try
    clock = FakeClock()
    workflow = make_workflow(
        [
            _measure(on_error="continue"),
            _home("valve_1"),
        ],
        streams={"od_1": {}},
    )
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    await clock.advance(1.0)  # inside the job poll loop, i.e. inside the block's try

    run.abort()

    with pytest.raises(RunAbortedError):
        await asyncio.wait_for(task, timeout=5.0)
    assert run.report.status == "aborted"  # not "completed" with a tolerated abort
    assert run.report.tolerated_errors == ()
    assert _kinds(run.report).count("block_error_tolerated") == 0
    assert ("valve_1", "home") not in verbs(fake)  # no hardware moved after the abort


async def test_an_abort_inside_a_tolerated_parallel_lane_is_never_swallowed(fake_client):
    """The same guarantee one frame deeper. A TaskGroup cancels its lanes by cancelling their
    tasks, so the CancelledError arrives INSIDE the lane's own `execute_block` -- exactly
    where the tolerance sits. If the lane absorbed it, the lane would carry on running
    hardware commands after the operator hit abort (here: homing valve_1), while the
    TaskGroup's own re-raise would still make the run *look* aborted. So the discriminating
    assertion is the wire, not the status.

    Mutation-verified alongside the test above.
    """
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.add_device("valve_1", "valve")
    fake.hold_job("measure")
    clock = FakeClock()
    workflow = make_workflow(
        [{"parallel": {"children": [
            {"serial": {"children": [
                _measure(on_error="continue"),
                _home("valve_1"),  # must never reach the wire
            ]}},
            {"wait": {"duration": "600s"}},  # a genuine second lane for the TaskGroup
        ]}}],
        streams={"od_1": {}},
    )
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    await clock.advance(1.0)  # lane 1 is parked in the poll loop, inside its block's try

    run.abort()

    with pytest.raises(RunAbortedError):
        await asyncio.wait_for(task, timeout=5.0)
    assert run.report.status == "aborted"
    assert run.report.tolerated_errors == ()
    assert _kinds(run.report).count("block_error_tolerated") == 0
    assert ("valve_1", "home") not in verbs(fake)  # the lane stopped at the abort


async def test_a_tolerated_timeout_still_leaves_its_orphan_to_the_finalizer(fake_client):
    """A tolerance must not weaken the Task-5 invariant: `_await_job` raises JobTimeoutError
    WITHOUT cancelling the job -- it is still physically running -- so the job stays in
    `ctx.in_flight` and the finalizer must still stop that device. Absorbing the block's
    failure must not absorb that obligation."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    fake.add_device("valve_1", "valve")
    fake.hold_job("measure")  # the job never completes -> the block times out
    clock = FakeClock()
    workflow = make_workflow(
        [
            _measure(on_error="continue"),
            _home("valve_1"),
        ],
        streams={"od_1": {}},
    )
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock, job_timeout=5.0))
    report = await drive(clock, run.execute())

    assert report.status == "completed"
    assert "did not finish within" in report.tolerated_errors[0].error
    assert ("valve_1", "home") in verbs(fake)  # the run carried on...
    # ...and the abandoned job was never untracked while it may still have been running.
    # It stayed in ctx.in_flight (the tolerance did not pop it), so the finalizer stopped the
    # device it was left on -- block_id is None, i.e. issued by the finalizer, not the block.
    assert "j-1" in run._ctx.in_flight
    assert any(e.kind == "job_cancelled" and e.block_id is None for e in report.log.events)
    assert [j.state for j in fake.jobs.values()] == ["cancelled"]
    wire = verbs(fake)
    assert wire.index(("valve_1", "home")) < wire.index(("densitometer_1", "stop"))


async def test_a_tolerated_mode_open_failure_leaves_no_phantom_mode_or_busy_slot(fake_client):
    """A tolerated failure on a MODE-OPENING command (`set_thermostat`) must not leave a
    phantom `OpenMode` in occupancy or a leaked busy slot, and the finalizer must still sweep
    the device.

    `_dispatch_action`'s own acquire/finally already rolls the occupancy slot back on ANY
    dispatch failure -- `register_open` only runs after a successful call, and `holding`
    stays True (so the `finally` releases) whenever it does not (see
    `test_failed_call_rolls_back_mode_open`, tests/test_experiment_dispatch.py). The
    tolerance mechanism sits one frame above that and must not disturb it: this pins that it
    doesn't."""
    fake, client = fake_client
    fake.add_device("densitometer_1", "densitometer")
    # times=1: only the block's own attempt should fail. A larger count would also fail the
    # finalizer's own later set_thermostat(enabled=False) sweep call, turning this into a
    # FinalizeError instead of the clean "completed" this test means to pin.
    fake.inject_error("densitometer_1", "set_thermostat", *FLAKY, times=1)
    clock = FakeClock()
    workflow = make_workflow(
        [
            {
                "command": {
                    "device": "densitometer_1", "verb": "set_thermostat",
                    "params": {"enabled": True, "target_c": 37.0},
                },
                "on_error": "continue",
            },
        ]
    )
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())

    assert report.status == "completed"
    assert len(report.tolerated_errors) == 1
    assert "flaky" in report.tolerated_errors[0].error
    assert run._ctx.occupancy.open_modes() == ()  # no phantom OpenMode
    assert run._ctx.occupancy.busy_devices() == set()  # no leaked busy slot
    # the finalizer's unconditional sweep still ran for the (touched) device
    assert ("densitometer_1", "stop") in verbs(fake)
    assert ("densitometer_1", "set_thermostat") in verbs(fake)  # sweep's teardown call


def test_tolerable_denies_run_aborted_and_busy_error_defense_in_depth():
    """Defence in depth (Fix 3): neither of these can reach `_tolerable` through the normal
    walk today -- `RunAbortedError`'s only raise site is `run.py`, AFTER the block walk
    returns; `core_errors.BusyError` is converted to `InvariantViolationError` at its one
    call site in `_dispatch_action`. The deny-list denies them anyway, for the same reason
    it already denies `CancelledError`/`InvariantViolationError`: the guarantee must not rest
    on every call site converting first."""
    assert _tolerable(RunAbortedError("run aborted by operator")) is False
    assert _tolerable(core_errors.BusyError("device busy")) is False
