# tests/test_experiment_context.py
from pathlib import Path

from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.runlog import InMemoryRunLog
from lab_devices.experiment.state import RunState
from lab_devices.experiment.workflow import Workflow
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
    # Tolerate a transient blip on ONE get_job without abandoning a live job, but never poll a
    # genuinely dead device forever: 5 consecutive failures, ~6s at the capped poll interval.
    assert options.job_poll_max_failures == 5


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
    events = ctx.log_sink.events
    assert [e.kind for e in events] == ["run_started", "block_started"]
    assert events[0].timestamp == 100.0
    assert events[1].block_id == "blocks[0]" and events[1].data == {"n": 1}


def test_run_options_new_persistence_fields_default():
    opts = RunOptions()
    assert opts.log_sink is None
    assert opts.output_dir is None
    assert opts.flush_interval == 30.0


def test_run_options_accepts_output_dir(tmp_path: Path):
    opts = RunOptions(output_dir=tmp_path, flush_interval=5.0)
    assert opts.output_dir == tmp_path
    assert opts.flush_interval == 5.0


async def test_context_default_log_sink_when_options_none(fake_client):
    _, client = fake_client
    ctx = RunContext(client=client, workflow=Workflow(schema_version=1),
                     state=RunState(), options=RunOptions())
    assert isinstance(ctx.log_sink, InMemoryRunLog)  # field default when options.log_sink is None
    ctx.emit("run_started")
    assert ctx.log_sink.events[0].kind == "run_started"


async def test_context_adopts_injected_log_sink(fake_client):
    # A directly-built context (as unit tests build) must honor an injected options sink.
    _, client = fake_client
    sink = InMemoryRunLog()
    ctx = RunContext(client=client, workflow=Workflow(schema_version=1),
                     state=RunState(), options=RunOptions(log_sink=sink))
    assert ctx.log_sink is sink
    ctx.emit("run_started")
    assert sink.events[0].kind == "run_started"
