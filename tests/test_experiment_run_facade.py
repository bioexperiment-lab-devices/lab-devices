import asyncio

import pytest

from lab_devices.experiment import (
    BlockFailedError,
    ExperimentRun,
    FinalizeError,
    InMemoryRunLog,  # noqa: F401  # imported to prove it's exported (test_public_exports)
    PersistenceError,
    RunOptions,
    ValidationError,
)
from lab_devices.experiment.errors import ExperimentRunError
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


def make_run(client, workflow, **opt):
    options = RunOptions(clock=opt.pop("clock", FakeClock()), **opt)
    return ExperimentRun(client, workflow, options=options)


async def test_happy_path_report(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}],
        streams={"OD": {"units": "AU"}},
    )
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed" and report.error is None
    assert report.finalize_errors == ()
    assert len(report.state.streams["OD"]) == 1
    assert run.report is report
    kinds = [e.kind for e in report.log.events]
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished"


async def test_validates_at_construction(fake_client):
    _, client = fake_client
    wf = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "ghost"}}]
    )  # undeclared stream -> validator rejects
    with pytest.raises(ValidationError):
        ExperimentRun(client, wf)


async def test_declared_streams_pre_created(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"branch": {"if": "count(S) == 0",
                     "then": [{"command": {"device": "pump_1", "verb": "stop"}}]}}],
        streams={"S": {}},
    )
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    assert verbs(fake)[0] == ("pump_1", "stop")  # count()==0 on a never-written stream


async def test_disk_default_without_output_dir_fails_before_hardware(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"command": {"device": "pump_1", "verb": "stop"}}],
        persistence={"default": "disk", "format": "jsonl"},
    )
    run = make_run(client, wf)
    with pytest.raises(PersistenceError, match="output_dir"):
        await run.execute()
    assert fake.calls == []  # nothing touched the wire
    assert run.report is not None and run.report.status == "failed"


async def test_per_stream_disk_override_without_output_dir_fails(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}],
        streams={"OD": {"persistence": "disk"}},
    )
    run = make_run(client, wf)
    with pytest.raises(PersistenceError, match="output_dir"):
        await run.execute()
    assert fake.calls == []  # failed at sink-build, before hardware


async def test_block_failure_finalizes_and_reraises_with_notes(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = make_run(client, wf)
    with pytest.raises(BlockFailedError):
        await drive(run._options.clock, run.execute())
    assert run.report.status == "failed"
    assert ("pump_2", "stop") in verbs(fake)  # rotate torn down by the finalizer


async def test_finalize_error_on_otherwise_successful_run(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
    ])  # rotate left open: finalizer will close it
    fake.inject_error("pump_2", "stop", "hardware_error", "stall", times=2)  # teardown+sweep
    run = make_run(client, wf)
    with pytest.raises(FinalizeError) as info:
        await drive(run._options.clock, run.execute())
    assert len(info.value.errors) == 2
    assert run.report.status == "completed"  # block plane succeeded (D8)
    assert run.report.finalize_errors == info.value.errors


async def test_execute_is_single_shot(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"command": {"device": "pump_1", "verb": "stop"}}])
    run = make_run(client, wf)
    await drive(run._options.clock, run.execute())
    with pytest.raises(ExperimentRunError, match="once"):
        await run.execute()


async def test_external_cancellation_finalizes_and_reraises(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = make_run(client, wf)
    clock = run._options.clock
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    task.cancel()  # external cancel, NOT operator abort
    with pytest.raises(asyncio.CancelledError):
        await task
    assert run.report.status == "cancelled"  # external cancel, not operator abort (5a)
    seq = verbs(fake)
    assert ("pump_1", "stop") in seq  # in-flight job device stopped (step 1)
    assert seq.count(("pump_2", "stop")) >= 1  # rotate torn down


class FinalizeRaisingSink:
    """Public-API log sink that raises on every finalize-phase / reporting emit; earlier
    phases delegate to an inner InMemoryRunLog so the run reaches the finalizer (§11)."""

    _RAISING = frozenset({"teardown_issued", "sweep_command", "job_cancelled", "run_finished"})

    def __init__(self):
        self.inner = InMemoryRunLog()

    def emit(self, event):
        if event.kind.startswith("finalize") or event.kind in self._RAISING:
            raise OSError("log sink boom")
        self.inner.emit(event)

    @property
    def events(self):
        return self.inner.events


async def test_raising_log_sink_never_skips_safe_state_sweep(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
    ])  # rotate left open: the finalizer must tear it down and sweep despite the sink
    run = make_run(client, wf, log_sink=FinalizeRaisingSink())
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"       # reporting survived the raising sink
    assert run.report is report               # report set despite finalize-phase raises
    assert verbs(fake).count(("pump_2", "stop")) == 2  # teardown + sweep both hit the wire
    assert run._ctx.occupancy.open_modes() == ()       # mode closed after teardown


async def test_finalizer_teardown_failure_notes_the_block_error(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    fake.inject_error("pump_2", "stop", "hardware_error", "stall", times=1)  # teardown fails
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = make_run(client, wf)
    with pytest.raises(BlockFailedError) as info:
        await drive(run._options.clock, run.execute())
    assert run.report.status == "failed"
    assert run.report.finalize_errors  # teardown of the open rotate mode failed
    assert any(n.startswith("finalizer:") for n in getattr(info.value, "__notes__", []))


def test_public_exports():
    import lab_devices.experiment as exp

    for name in (
        "ExperimentRun", "RunOptions", "RunReport", "assign_block_ids",
        "Clock", "MonotonicClock", "OperatorInputProvider", "InputRequest",
        "UnattendedInputProvider", "RunEvent", "RunLogSink", "InMemoryRunLog",
        "ExperimentRunError", "BlockFailedError", "InvariantViolationError",
        "RunAbortedError", "FinalizeError", "PersistenceError",
        "CsvRunLogSink", "CsvStreamSink", "JsonlRunLogSink", "JsonlStreamSink",
        "SinkSet", "StreamSink",
    ):
        assert hasattr(exp, name) and name in exp.__all__, name
