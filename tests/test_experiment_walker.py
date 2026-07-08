import pytest

from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.errors import BlockFailedError
from lab_devices.experiment.execute import execute_blocks
from lab_devices.experiment.state import RunState, Stream
from tests.experiment_run_helpers import (
    ScriptedInputProvider,
    add_standard_devices,
    make_workflow,
    verbs,
)
from tests.fakeclock import FakeClock, drive


def make_ctx(client, workflow, *, clock=None, inputs=None):
    options = RunOptions(clock=clock or FakeClock())
    if inputs is not None:
        options.input_provider = inputs
    state = RunState()
    for name in workflow.streams:
        state.streams[name] = Stream()
    return RunContext(client=client, workflow=workflow, state=state, options=options)


async def run_blocks(ctx):
    await drive(ctx.clock, execute_blocks(ctx.workflow.blocks, ctx))


def kinds(ctx):
    return [(e.kind, e.block_id) for e in ctx.options.log_sink.events]


async def test_serial_order_and_gap_after(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "valve_1", "verb": "home", "params": {"position": 1}},
         "gap_after": "30s"},
        {"command": {"device": "pump_1", "verb": "stop"}},
    ])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert verbs(fake) == [("valve_1", "home"), ("pump_1", "stop")]
    assert ctx.clock.now() == pytest.approx(30.0)  # the gap really slept


async def test_trailing_gap_is_honored(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "stop"}, "gap_after": "10s"},
    ])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert ctx.clock.now() == pytest.approx(10.0)  # spec §9: honored unconditionally


async def test_wait_block_sleeps(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"wait": {"duration": "5min"}}])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert ctx.clock.now() == pytest.approx(300.0)


async def test_block_events_wrap_execution(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"command": {"device": "pump_1", "verb": "stop"}}])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert kinds(ctx) == [
        ("block_started", "blocks[0]"), ("block_finished", "blocks[0]"),
    ]


async def test_failure_wrapped_once_with_origin_id(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"serial": {"children": [
            {"command": {"device": "pump_1", "verb": "dispense",
                         "params": {"volume_ml": "mean(OD)"}}},
        ]}}],
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    with pytest.raises(BlockFailedError) as info:
        await run_blocks(ctx)
    assert info.value.block_id == "blocks[0].children[0]"
    failed = [e for e in ctx.options.log_sink.events if e.kind == "block_failed"]
    assert len(failed) == 1 and failed[0].block_id == "blocks[0].children[0]"
    assert fake.calls == []  # fail-safe: nothing hit the wire


async def test_serial_stops_at_first_failure(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
        {"command": {"device": "pump_2", "verb": "stop"}},
    ])
    ctx = make_ctx(client, wf)
    with pytest.raises(BlockFailedError):
        await run_blocks(ctx)
    assert verbs(fake) == [("pump_1", "dispense")]  # second block never dispatched


async def test_measure_stamps_stream_with_clock_time(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"wait": {"duration": "10s"}},
         {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}],
        streams={"OD": {"units": "AU"}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    samples = ctx.state.streams["OD"].samples
    assert len(samples) == 1
    assert samples[0].value == pytest.approx(0.523)  # FakeLab canned absorbance
    assert samples[0].timestamp == pytest.approx(10.0)
    recorded = [e for e in ctx.options.log_sink.events if e.kind == "measure_recorded"]
    assert recorded[0].data["stream"] == "OD"


async def test_measure_blank_uses_slope_result_field(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure_blank", "into": "S"}}],
        streams={"S": {}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert ctx.state.streams["S"].samples[0].value == pytest.approx(123.45)


async def test_operator_input_binds_scripted_value(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"operator_input": {"name": "target", "type": "float", "min": 0.0, "max": 2.0}},
    ])
    provider = ScriptedInputProvider({"target": 1.5})
    ctx = make_ctx(client, wf, inputs=provider)
    await run_blocks(ctx)
    assert ctx.state.bindings == {"target": 1.5}
    assert provider.requests[0].block_id == "blocks[0]"
    assert [e.kind for e in ctx.options.log_sink.events if "input" in e.kind] == [
        "input_requested", "input_bound",
    ]


async def test_operator_input_constraint_violation_fails_block(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"operator_input": {"name": "target", "type": "float", "min": 0.0, "max": 2.0}},
    ])
    ctx = make_ctx(client, wf, inputs=ScriptedInputProvider({"target": 99.0}))
    with pytest.raises(BlockFailedError, match="above max"):
        await run_blocks(ctx)
    assert ctx.state.bindings == {}


async def test_unattended_input_fails_safe(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"operator_input": {"name": "target", "type": "float"}},
    ])
    ctx = make_ctx(client, wf)  # default UnattendedInputProvider
    with pytest.raises(BlockFailedError, match="no input provider"):
        await run_blocks(ctx)
