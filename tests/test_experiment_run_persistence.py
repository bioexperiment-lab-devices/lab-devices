import asyncio
import csv
import json
from pathlib import Path

import httpx
import pytest

from lab_devices.client import LabClient
from lab_devices.experiment import (
    ExperimentRun,
    InMemoryRunLog,
    PersistenceError,
    RunAbortedError,
    RunOptions,
)
from lab_devices.experiment.persist import run_event_to_dict
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.fakeclock import FakeClock, drive
from tests.fakelab import FakeLab

_MEASURE = [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}]
_STREAMS = {"OD": {"units": "AU"}}
_DISK_JSONL = {"default": "disk", "format": "jsonl"}


def _fresh_client() -> tuple[FakeLab, LabClient]:
    fake = FakeLab()
    add_standard_devices(fake)
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    return fake, LabClient("lab", 80, http=http)


async def test_disk_run_writes_runlog_and_stream(fake_client, tmp_path: Path):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(_MEASURE, streams=_STREAMS, persistence=_DISK_JSONL)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock, output_dir=tmp_path))
    await drive(clock, run.execute())
    assert run.report is not None and run.report.status == "completed"
    # stream file mirrors RunState exactly (same run)
    od_lines = [json.loads(x) for x in (tmp_path / "OD.jsonl").read_text().splitlines()]
    od_state = run.report.state.streams["OD"].samples
    assert len(od_lines) == len(od_state) == 1
    assert od_lines[0] == {"timestamp": od_state[0].timestamp, "value": od_state[0].value}
    # run log file exists and is parseable, ends with run_finished
    log_lines = [json.loads(x) for x in (tmp_path / "run_log.jsonl").read_text().splitlines()]
    assert log_lines[0]["kind"] == "run_started"
    assert log_lines[-1]["kind"] == "run_finished"
    assert run.report.persistence_errors == ()


async def test_disk_run_with_str_output_dir(fake_client, tmp_path: Path):
    # NEW-4: output_dir as a plain str (spec §5 allows Path | str | None) must be coerced,
    # not hit an uncaught TypeError that leaves the report unset.
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(_MEASURE, streams=_STREAMS, persistence=_DISK_JSONL)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock, output_dir=str(tmp_path)))
    await drive(clock, run.execute())
    assert run.report is not None and run.report.status == "completed"
    assert (tmp_path / "run_log.jsonl").exists()
    assert (tmp_path / "OD.jsonl").exists()


async def test_missing_output_dir_fails_before_hardware(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(_MEASURE, streams=_STREAMS, persistence=_DISK_JSONL)
    run = ExperimentRun(client, wf, RunOptions(clock=FakeClock()))  # no output_dir
    with pytest.raises(PersistenceError, match="output_dir"):
        await run.execute()
    assert run.report is not None and run.report.status == "failed"
    assert fake.calls == []  # no hardware touched


async def test_clobber_refused_before_hardware(fake_client, tmp_path: Path):
    fake, client = fake_client
    add_standard_devices(fake)
    (tmp_path / "run_log.jsonl").write_text("stale\n")
    wf = make_workflow(_MEASURE, streams=_STREAMS, persistence=_DISK_JSONL)
    run = ExperimentRun(client, wf, RunOptions(clock=FakeClock(), output_dir=tmp_path))
    with pytest.raises(PersistenceError, match="exists"):
        await run.execute()
    assert fake.calls == []
    assert (tmp_path / "run_log.jsonl").read_text() == "stale\n"  # untouched


_FEEDBACK = [
    {"serial": {"children": [
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"loop": {"check": "after", "count": 2, "body": [
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
        ]}},
        {"command": {"device": "pump_2", "verb": "stop"}},
    ]}}
]


async def test_disk_jsonl_run_log_mirrors_in_memory(fake_client, tmp_path: Path):
    # Baseline: identical workflow, in-memory persistence, an isolated second lab.
    _, base_client = _fresh_client()
    base_wf = make_workflow(_FEEDBACK, streams=_STREAMS,
                            persistence={"default": "in_memory", "format": "jsonl"})
    base_clock = FakeClock()
    base_run = ExperimentRun(base_client, base_wf, RunOptions(clock=base_clock))
    await drive(base_clock, base_run.execute())
    assert base_run.report is not None
    expected = [run_event_to_dict(e) for e in base_run.report.log.events]
    # Disk run of the identical workflow — deterministic clock => identical event sequence.
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(_FEEDBACK, streams=_STREAMS, persistence=_DISK_JSONL)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock, output_dir=tmp_path))
    await drive(clock, run.execute())
    disk = [json.loads(x) for x in (tmp_path / "run_log.jsonl").read_text().splitlines()]
    assert disk == expected  # byte-for-byte mirror of the in-memory log


async def test_disk_jsonl_stream_mirrors_runstate(fake_client, tmp_path: Path):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(_FEEDBACK, streams=_STREAMS, persistence=_DISK_JSONL)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock, output_dir=tmp_path))
    await drive(clock, run.execute())
    assert run.report is not None
    disk = [json.loads(x) for x in (tmp_path / "OD.jsonl").read_text().splitlines()]
    state = run.report.state.streams["OD"].samples
    assert len(disk) == len(state) == 2
    assert disk == [{"timestamp": s.timestamp, "value": s.value} for s in state]


async def test_disk_csv_stream_mirrors_runstate(fake_client, tmp_path: Path):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(_FEEDBACK, streams=_STREAMS,
                       persistence={"default": "disk", "format": "csv"})
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock, output_dir=tmp_path))
    await drive(clock, run.execute())
    assert run.report is not None
    rows = list(csv.reader((tmp_path / "OD.csv").read_text().splitlines()))
    assert rows[0] == ["timestamp", "value"]
    state = run.report.state.streams["OD"].samples
    assert [[repr(s.timestamp), repr(s.value)] for s in state] == rows[1:]


class _RaisingLogSink:
    def __init__(self) -> None:
        self.calls = 0

    def emit(self, event) -> None:
        self.calls += 1
        raise RuntimeError("sink boom")


class _RaisingFlushSink(InMemoryRunLog):
    """A non-conformant injected sink whose flush raises (goes beyond the emit-only protocol)."""

    def flush(self) -> None:
        raise RuntimeError("flush boom")


async def test_report_set_when_injected_sink_flush_raises(fake_client):
    # A foreign sink's flush/close must never unset the report (report-always-set invariant).
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"command": {"device": "pump_1", "verb": "stop"}}])
    run = ExperimentRun(client, wf, RunOptions(clock=FakeClock(), log_sink=_RaisingFlushSink()))
    clock = run._options.clock
    report = await drive(clock, run.execute())  # must NOT raise the sink's flush RuntimeError
    assert report.status == "completed"
    assert run.report is not None


async def test_disk_files_complete_and_parseable_after_abort(fake_client, tmp_path: Path):
    # Held measure job; abort mid-run; the finalizer's final flush must leave whole files.
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("measure")
    wf = make_workflow(_FEEDBACK, streams=_STREAMS, persistence=_DISK_JSONL)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock, output_dir=tmp_path))
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # dispatch reaches the held measure job (mirrors the abort test)
    run.abort()
    with pytest.raises(RunAbortedError):
        await task  # finalizer runs with no clock advance (only HTTP hops)
    assert run.report is not None and run.report.status == "aborted"
    # Every line parses (no torn final line); the log ends at run_finished(aborted).
    parsed = [json.loads(x) for x in (tmp_path / "run_log.jsonl").read_text().splitlines()]
    assert parsed[-1]["kind"] == "run_finished"
    assert parsed[-1]["data"]["status"] == "aborted"
    # Stream file parses; its samples match RunState up to the abort (empty: measure held).
    od = [json.loads(x) for x in (tmp_path / "OD.jsonl").read_text().splitlines()]
    assert od == [
        {"timestamp": s.timestamp, "value": s.value}
        for s in run.report.state.streams["OD"].samples
    ]


async def test_bounded_staleness_periodic_flush(fake_client, tmp_path: Path):
    # With a held job (no finalize yet), advancing past flush_interval flushes buffered lines.
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("measure")
    wf = make_workflow(_FEEDBACK, streams=_STREAMS, persistence=_DISK_JSONL)
    clock = FakeClock()
    run = ExperimentRun(
        client, wf, RunOptions(clock=clock, output_dir=tmp_path, flush_interval=10.0)
    )
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # events buffered in userspace, not yet flushed to disk
    assert "run_started" not in (tmp_path / "run_log.jsonl").read_text()
    await clock.advance(10.0)  # fire the periodic flush sleeper (advance() is a coroutine)
    assert "run_started" in (tmp_path / "run_log.jsonl").read_text()  # staleness bounded
    # Clean up: stop holding measures and let the run finish.
    fake.held_jobs.discard("measure")
    report = await drive(clock, task)
    assert report.status == "completed"


async def test_raising_log_sink_still_finalizes_and_sets_report(fake_client):
    # Closes the Increment-4 latent ticket: a custom sink raising on emit must not leave the
    # report unset or skip the finalizer (design 5 §8). The run still fails, but safely.
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"command": {"device": "pump_1", "verb": "stop"}}])
    sink = _RaisingLogSink()
    run = ExperimentRun(client, wf, RunOptions(clock=FakeClock(), log_sink=sink))
    clock = run._options.clock
    with pytest.raises(RuntimeError):
        await drive(clock, run.execute())
    assert run.report is not None  # finalizer ran and set the report despite the raising sink
    assert sink.calls > 0
