import asyncio

import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.errors import EvaluationError
from lab_devices.experiment.execute import _run_compute, _run_record
from lab_devices.experiment.state import RunState, Sample, Stream
from lab_devices.experiment.workflow import Workflow
from tests.fakeclock import FakeClock, drive


class _RecordingStreamSink:
    def __init__(self) -> None:
        self.samples: list[Sample] = []

    def write(self, sample: Sample) -> None:
        self.samples.append(sample)

    def flush(self) -> None: ...
    def close(self) -> None: ...


def _ctx(client, clock, state):
    return RunContext(client=client, workflow=Workflow(schema_version=1), state=state,
                      options=RunOptions(clock=clock))


def _block(kind, **kw):
    b = kind(**kw)
    b.id = "blocks[0]"
    return b


async def test_compute_binds_number(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    ctx = _ctx(client, clock, state)
    await drive(clock, _run_compute(_block(B.Compute, into="c", value="2 * 3"), ctx))
    assert state.bindings["c"] == 6


async def test_compute_binds_boolean(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    state.bindings["od"] = 0.9
    ctx = _ctx(client, clock, state)
    await drive(clock, _run_compute(_block(B.Compute, into="hot", value="od > 0.5"), ctx))
    assert state.bindings["hot"] is True


async def test_compute_accumulator_overwrites_reading_own_prior_value(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    state.bindings["c"] = 0.0
    ctx = _ctx(client, clock, state)
    block = _block(B.Compute, into="c", value="c * 0.5 + 1")
    await drive(clock, _run_compute(block, ctx))
    assert state.bindings["c"] == 1.0
    await drive(clock, _run_compute(block, ctx))
    assert state.bindings["c"] == 1.5


async def test_compute_emits_event(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    ctx = _ctx(client, clock, state)
    await drive(clock, _run_compute(_block(B.Compute, into="c", value="7"), ctx))
    kinds = [(e.kind, e.data) for e in ctx.log_sink.events]
    assert ("binding_computed", {"name": "c", "value": 7}) in kinds


async def test_compute_division_by_zero_raises(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    ctx = _ctx(client, clock, state)
    with pytest.raises(EvaluationError):
        await drive(clock, _run_compute(_block(B.Compute, into="c", value="1 / 0"), ctx))
    assert "c" not in state.bindings


async def test_record_appends_to_stream_and_sink(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    state.streams["r"] = Stream()
    state.bindings["x"] = 0.8
    ctx = _ctx(client, clock, state)
    sink = _RecordingStreamSink()
    ctx.stream_sinks = {"r": sink}
    await drive(clock, _run_record(_block(B.Record, into="r", value="x"), ctx))
    assert [s.value for s in state.streams["r"].samples] == [0.8]
    assert [s.value for s in sink.samples] == [0.8]
    assert sink.samples[0].timestamp == state.streams["r"].samples[0].timestamp


async def test_record_emits_sample_recorded_not_measure_recorded(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    state.streams["r"] = Stream()
    ctx = _ctx(client, clock, state)
    await drive(clock, _run_record(_block(B.Record, into="r", value="1.5"), ctx))
    kinds = [e.kind for e in ctx.log_sink.events]
    assert "sample_recorded" in kinds and "measure_recorded" not in kinds


async def test_record_rejects_boolean(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    state.streams["r"] = Stream()
    ctx = _ctx(client, clock, state)
    with pytest.raises(EvaluationError):
        await drive(clock, _run_record(_block(B.Record, into="r", value="true"), ctx))
    assert len(state.streams["r"].samples) == 0


async def test_compute_rejects_non_finite(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    ctx = _ctx(client, clock, state)
    with pytest.raises(EvaluationError):
        await drive(clock, _run_compute(_block(B.Compute, into="c", value=float("inf")), ctx))
    assert "c" not in state.bindings


async def test_record_rejects_non_finite_float(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    state.streams["r"] = Stream()
    ctx = _ctx(client, clock, state)
    with pytest.raises(EvaluationError):
        await drive(clock, _run_record(_block(B.Record, into="r", value=float("inf")), ctx))
    assert len(state.streams["r"].samples) == 0


async def test_record_rejects_oversized_int(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    state.streams["r"] = Stream()
    ctx = _ctx(client, clock, state)
    with pytest.raises(EvaluationError):
        await drive(clock, _run_record(_block(B.Record, into="r", value=10**400), ctx))
    assert len(state.streams["r"].samples) == 0


class _TickingClock:
    """now() advances 1.0 on every read, so a *second* clock read is observable — a
    two-call `now()` would stamp the sample one tick after the value was evaluated."""

    def __init__(self, start: float = 100.0) -> None:
        self._t = start
        self.reads = 0

    def now(self) -> float:
        self.reads += 1
        t = self._t
        self._t += 1.0
        return t

    async def sleep(self, seconds: float) -> None:  # pragma: no cover - record never sleeps
        await asyncio.sleep(0)


async def test_record_timestamp_is_the_single_evaluation_instant(fake_client):
    _, client = fake_client
    clock = _TickingClock(start=100.0)
    state = RunState()
    state.streams["src"] = Stream()
    state.streams["src"].append(50.0, 2.0)
    state.streams["r"] = Stream()
    ctx = RunContext(client=client, workflow=Workflow(schema_version=1), state=state,
                     options=RunOptions(clock=clock))
    # A duration-window expr is evaluated at exactly one `now`; the sample it produces
    # must be stamped with that SAME instant (the block's first clock read, 100.0). A
    # two-call form — one now() for the value, a later now() for the timestamp — would stamp
    # the sample at 101.0 instead. The ticking clock makes that regression observable (the
    # trailing `emit` reads the clock once more for the event timestamp, which is unrelated).
    await _run_record(_block(B.Record, into="r", value="last(src)"), ctx)
    assert state.streams["r"].samples[0].timestamp == 100.0
