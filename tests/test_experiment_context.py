# tests/test_experiment_context.py
from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.state import RunState
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.fakeclock import FakeClock


def _ctx(client, **opt):
    options = RunOptions(clock=FakeClock(start=100.0), **opt)
    return RunContext(
        client=client, workflow=make_workflow([]), state=RunState(), options=options
    )


def test_defaults():
    options = RunOptions()
    assert options.job_poll_interval == 0.25
    assert options.job_poll_max == 2.0
    assert options.job_timeout is None


async def test_device_handles_cached(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = _ctx(client)
    assert ctx.device("pump_1") is ctx.device("pump_1")
    assert ctx.device("pump_1").id == "pump_1"


async def test_locks_lazy_and_per_device(fake_client):
    _, client = fake_client
    ctx = _ctx(client)
    lock = ctx.lock("pump_1")
    assert ctx.lock("pump_1") is lock
    assert ctx.lock("pump_2") is not lock


async def test_gate_starts_set(fake_client):
    _, client = fake_client
    assert _ctx(client).gate.is_set()


async def test_emit_stamps_clock_time(fake_client):
    _, client = fake_client
    ctx = _ctx(client)
    ctx.emit("run_started")
    ctx.emit("block_started", "blocks[0]", n=1)
    events = ctx.options.log_sink.events
    assert [e.kind for e in events] == ["run_started", "block_started"]
    assert events[0].timestamp == 100.0
    assert events[1].block_id == "blocks[0]" and events[1].data == {"n": 1}
