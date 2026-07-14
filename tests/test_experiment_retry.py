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
