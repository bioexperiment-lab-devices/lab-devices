import asyncio

import pytest

from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.errors import BlockFailedError, InvariantViolationError
from lab_devices.experiment.execute import execute_blocks
from lab_devices.experiment.state import RunState, Stream
from tests.experiment_run_helpers import (
    add_standard_devices,
    make_workflow,
    role_devices,
    verbs,
)
from tests.fakeclock import FakeClock, drive


def make_ctx(client, workflow, *, clock=None):
    state = RunState()
    for name in workflow.streams:
        state.streams[name] = Stream()
    return RunContext(client=client, workflow=workflow, state=state,
                      options=RunOptions(clock=clock or FakeClock()),
                      role_devices=role_devices(workflow))


async def test_children_run_concurrently(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.polls_to_complete_by_cmd["dispense"] = 2  # each job needs one 0.25s poll sleep
    wf = make_workflow([
        {"parallel": {"children": [
            {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
            {"command": {"device": "pump_2", "verb": "dispense", "params": {"volume_ml": 2.0}}},
        ]}},
    ])
    ctx = make_ctx(client, wf)
    await drive(ctx.clock, execute_blocks(wf.blocks, ctx))
    assert sorted(verbs(fake)) == [("pump_1", "dispense"), ("pump_2", "dispense")]
    # concurrent poll sleeps overlap: total elapsed is ONE poll interval, not two
    assert ctx.clock.now() == pytest.approx(0.25)


async def test_start_offset_staggers_branch_start(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"parallel": {"children": [
            {"command": {"device": "pump_1", "verb": "stop"}},
            {"command": {"device": "pump_2", "verb": "stop"}, "start_offset": "60s"},
        ]}},
    ])
    ctx = make_ctx(client, wf)
    task = asyncio.ensure_future(execute_blocks(wf.blocks, ctx))
    await ctx.clock.settle()
    assert verbs(fake) == [("pump_1", "stop")]  # offset branch not started yet
    await ctx.clock.advance(59.9)
    assert verbs(fake) == [("pump_1", "stop")]
    await ctx.clock.advance(0.2)
    assert verbs(fake) == [("pump_1", "stop"), ("pump_2", "stop")]
    await drive(ctx.clock, task)


async def test_failing_child_cancels_siblings_exception_group(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    wf = make_workflow(
        [{"parallel": {"children": [
            {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
            {"loop": {"count": 999, "body": [
                {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
                {"wait": {"duration": "10s"}},
            ]}},
        ]}}],
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    with pytest.raises(BaseExceptionGroup) as info:
        await drive(ctx.clock, execute_blocks(wf.blocks, ctx))
    leaves = info.value.exceptions
    assert len(leaves) == 1 and isinstance(leaves[0], BlockFailedError)
    assert leaves[0].block_id == "blocks[0].children[0]"
    # sibling loop was cancelled long before 999 iterations
    assert len([v for v in verbs(fake) if v == ("densitometer_1", "measure")]) <= 2


async def test_exception_group_not_flattened_by_ancestors(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    wf = make_workflow([
        {"serial": {"children": [
            {"parallel": {"children": [
                {"command": {"device": "pump_1", "verb": "dispense",
                             "params": {"volume_ml": 1.0}}},
                {"command": {"device": "pump_2", "verb": "stop"}},
            ]}},
        ]}},
    ])
    ctx = make_ctx(client, wf)
    with pytest.raises(BaseExceptionGroup):  # NOT BlockFailedError: ancestors must not wrap
        await drive(ctx.clock, execute_blocks(wf.blocks, ctx))
    failed_events = [e for e in ctx.log_sink.events if e.kind == "block_failed"]
    assert len(failed_events) == 1  # origin leaf only


async def test_runtime_occupancy_net_under_real_concurrency(fake_client):
    """The validator would reject this tree; built unvalidated on purpose to prove the
    runtime safety net: sibling tasks cannot interleave through check-and-mark."""
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"parallel": {"children": [
            {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
            {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 2.0}}},
        ]}},
    ])
    ctx = make_ctx(client, wf)
    with pytest.raises(BaseExceptionGroup) as info:
        await drive(ctx.clock, execute_blocks(wf.blocks, ctx))
    assert any(isinstance(e, InvariantViolationError) for e in info.value.exceptions)
    dispenses = [v for v in verbs(fake) if v[1] == "dispense"]
    assert len(dispenses) == 1  # second dispatch never reached the wire
    assert len(ctx.in_flight) == 1  # cancelled wait leaves the job tracked (§7 step 6)
    events = [e.kind for e in ctx.log_sink.events]
    assert "invariant_violation" in events


async def test_wire_lock_not_held_across_job_poll_sleep(fake_client):
    """The per-device wire lock spans one HTTP call, never a job poll sleep (D2). Two
    children share densitometer_1 on DISJOINT channels: a measure job (optics) whose
    poll waits, and a set_thermostat (thermal) staggered to dispatch DURING that wait.
    If the lock were held across the poll sleep, set_thermostat could not reach the wire
    until after the final poll; instead it lands between the two get_job polls."""
    fake, client = fake_client
    add_standard_devices(fake)
    fake.record_polls = True  # get_job polls become visible in fake.calls
    fake.polls_to_complete_by_cmd["measure"] = 2  # poll 1 at t=0, sleep, poll 2 at t=0.25
    wf = make_workflow(
        [{"parallel": {"children": [
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
            {"command": {"device": "densitometer_1", "verb": "set_thermostat",
                         "params": {"enabled": True, "target_c": 37.0}},
             "start_offset": "0.1s"},  # dispatches inside the [0, 0.25) poll-sleep window
        ]}}],
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    await drive(ctx.clock, execute_blocks(wf.blocks, ctx))
    assert verbs(fake) == [
        ("densitometer_1", "measure"),
        ("densitometer_1", "get_job"),  # poll 1 at t=0 (still running)
        ("densitometer_1", "set_thermostat"),  # t=0.1, mid poll-sleep — lock was free
        ("densitometer_1", "get_job"),  # poll 2 at t=0.25 (succeeded)
    ]
    assert ctx.clock.now() == pytest.approx(0.25)  # both finish within one poll interval
