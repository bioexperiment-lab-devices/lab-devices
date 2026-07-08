import json
from pathlib import Path

import httpx
import pytest

from lab_devices.client import LabClient
from lab_devices.experiment import ExperimentRun, PersistenceError, RunOptions
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
