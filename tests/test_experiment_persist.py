import csv
import json
from pathlib import Path

import pytest

from lab_devices.experiment import PersistenceError
from lab_devices.experiment.persist import (
    CsvRunLogSink,
    CsvStreamSink,
    JsonlRunLogSink,
    JsonlStreamSink,
    SinkSet,
    run_event_to_dict,
    safe_stream_filename,
)
from lab_devices.experiment.runlog import InMemoryRunLog, RunEvent
from lab_devices.experiment.state import Sample
from lab_devices.experiment.workflow import Persistence, StreamDecl, Workflow


def test_run_event_to_dict_shape():
    ev = RunEvent(12.5, "measure_recorded", "blocks[0]", {"stream": "OD", "value": 0.5})
    assert run_event_to_dict(ev) == {
        "timestamp": 12.5,
        "kind": "measure_recorded",
        "block_id": "blocks[0]",
        "source_path": None,
        "data": {"stream": "OD", "value": 0.5},
    }


def test_run_event_to_dict_includes_source_path():
    ev = RunEvent(12.5, "block_started", "blocks[3]", source_path="blocks[2].body[0]")
    assert run_event_to_dict(ev) == {
        "timestamp": 12.5,
        "kind": "block_started",
        "block_id": "blocks[3]",
        "source_path": "blocks[2].body[0]",
        "data": {},
    }


def test_run_event_to_dict_none_block_id():
    ev = RunEvent(0.0, "run_started")
    assert run_event_to_dict(ev)["block_id"] is None


def test_safe_stream_filename_passthrough():
    assert safe_stream_filename("OD") == "OD"
    assert safe_stream_filename("temp_C.raw-1") == "temp_C.raw-1"


def test_safe_stream_filename_replaces_unsafe():
    assert safe_stream_filename("O D/2") == "O_D_2"


def test_safe_stream_filename_rejects_empty_and_traversal():
    with pytest.raises(PersistenceError):
        safe_stream_filename("")
    with pytest.raises(PersistenceError):
        safe_stream_filename("..")
    with pytest.raises(PersistenceError):
        safe_stream_filename("///")


def test_jsonl_stream_sink_writes_lines(tmp_path: Path):
    sink = JsonlStreamSink(tmp_path / "OD.jsonl")
    sink.write(Sample(1.0, 0.5))
    sink.write(Sample(2.0, 0.6))
    sink.flush()
    sink.close()
    lines = (tmp_path / "OD.jsonl").read_text().splitlines()
    assert [json.loads(x) for x in lines] == [
        {"timestamp": 1.0, "value": 0.5},
        {"timestamp": 2.0, "value": 0.6},
    ]


def test_jsonl_runlog_sink_writes_events(tmp_path: Path):
    sink = JsonlRunLogSink(tmp_path / "run_log.jsonl")
    sink.emit(RunEvent(0.0, "run_started"))
    sink.emit(RunEvent(1.0, "measure_recorded", "blocks[0]", {"stream": "OD", "value": 0.5}))
    sink.flush()
    sink.close()
    lines = (tmp_path / "run_log.jsonl").read_text().splitlines()
    parsed = [json.loads(x) for x in lines]
    assert parsed[0] == {
        "timestamp": 0.0,
        "kind": "run_started",
        "block_id": None,
        "source_path": None,
        "data": {},
    }
    assert parsed[1]["kind"] == "measure_recorded"
    assert parsed[1]["data"] == {"stream": "OD", "value": 0.5}


def test_jsonl_sink_remembers_write_error_never_raises(tmp_path: Path):
    sink = JsonlStreamSink(tmp_path / "OD.jsonl")
    sink.close()  # force subsequent writes onto a closed file
    sink.write(Sample(1.0, 0.5))  # must NOT raise
    assert sink.errors  # remembered instead


def test_csv_stream_sink_header_and_rows(tmp_path: Path):
    sink = CsvStreamSink(tmp_path / "OD.csv")
    sink.write(Sample(1.0, 0.5))
    sink.write(Sample(2.0, 0.6))
    sink.flush()
    sink.close()
    rows = list(csv.reader((tmp_path / "OD.csv").read_text().splitlines()))
    assert rows[0] == ["timestamp", "value"]
    assert rows[1] == ["1.0", "0.5"]
    assert rows[2] == ["2.0", "0.6"]


def test_csv_runlog_sink_json_data_column(tmp_path: Path):
    sink = CsvRunLogSink(tmp_path / "run_log.csv")
    sink.emit(RunEvent(1.0, "measure_recorded", "blocks[0]", {"stream": "OD", "value": 0.5}))
    sink.emit(RunEvent(0.0, "run_started"))
    sink.flush()
    sink.close()
    rows = list(csv.reader((tmp_path / "run_log.csv").read_text().splitlines()))
    assert rows[0] == ["timestamp", "kind", "block_id", "source_path", "data"]
    assert rows[1][0:3] == ["1.0", "measure_recorded", "blocks[0]"]
    assert json.loads(rows[1][4]) == {"stream": "OD", "value": 0.5}
    assert rows[2] == ["0.0", "run_started", "", "", "{}"]  # None block_id/source_path -> empty


def _wf(persistence: Persistence, streams: dict[str, StreamDecl]) -> Workflow:
    return Workflow(schema_version=1, streams=streams, persistence=persistence)


def test_sinkset_all_in_memory_no_files(tmp_path: Path):
    wf = _wf(Persistence(default="in_memory"), {"OD": StreamDecl()})
    ss = SinkSet.build(wf, output_dir=None, log_sink_override=None)
    assert isinstance(ss.log_sink, InMemoryRunLog)
    assert ss.stream_sinks == {"OD": None}
    assert ss.has_disk is False
    assert list(tmp_path.iterdir()) == []


def test_sinkset_disk_default_builds_all(tmp_path: Path):
    wf = _wf(Persistence(default="disk", format="jsonl"),
             {"OD": StreamDecl(), "temp": StreamDecl(persistence="in_memory")})
    ss = SinkSet.build(wf, output_dir=tmp_path, log_sink_override=None)
    assert isinstance(ss.log_sink, JsonlRunLogSink)
    assert isinstance(ss.stream_sinks["OD"], JsonlStreamSink)
    assert ss.stream_sinks["temp"] is None  # per-stream override wins
    assert ss.has_disk is True
    assert (tmp_path / "run_log.jsonl").exists()
    assert (tmp_path / "OD.jsonl").exists()
    assert not (tmp_path / "temp.jsonl").exists()
    ss.close_all()


def test_sinkset_injected_log_sink_overrides_config(tmp_path: Path):
    wf = _wf(Persistence(default="disk", format="jsonl"), {})
    inj = InMemoryRunLog()
    ss = SinkSet.build(wf, output_dir=tmp_path, log_sink_override=inj)
    assert ss.log_sink is inj
    assert not (tmp_path / "run_log.jsonl").exists()
    ss.close_all()


def test_sinkset_disk_without_output_dir_raises(tmp_path: Path):
    wf = _wf(Persistence(default="disk"), {"OD": StreamDecl()})
    with pytest.raises(PersistenceError, match="output_dir"):
        SinkSet.build(wf, output_dir=None, log_sink_override=None)


def test_sinkset_refuses_to_clobber(tmp_path: Path):
    (tmp_path / "run_log.jsonl").write_text("stale\n")
    wf = _wf(Persistence(default="disk"), {})
    with pytest.raises(PersistenceError, match="exists"):
        SinkSet.build(wf, output_dir=tmp_path, log_sink_override=None)
    assert (tmp_path / "run_log.jsonl").read_text() == "stale\n"  # untouched


def test_sinkset_name_collision_raises(tmp_path: Path):
    wf = _wf(Persistence(default="disk"), {"O D": StreamDecl(), "O/D": StreamDecl()})
    with pytest.raises(PersistenceError, match="collision"):
        SinkSet.build(wf, output_dir=tmp_path, log_sink_override=None)


def test_sinkset_bad_format_raises(tmp_path: Path):
    wf = _wf(Persistence(default="disk", format="xml"), {})
    with pytest.raises(PersistenceError, match="format"):
        SinkSet.build(wf, output_dir=tmp_path, log_sink_override=None)


def test_sinkset_bad_default_persistence_raises(tmp_path: Path):
    # NEW-1: an unknown persistence default must raise, never silently degrade to in-memory.
    wf = _wf(Persistence(default="dsik"), {})
    with pytest.raises(PersistenceError):
        SinkSet.build(wf, output_dir=tmp_path, log_sink_override=None)


def test_sinkset_bad_stream_persistence_raises(tmp_path: Path):
    # NEW-1: an unknown per-stream override must raise (case-sensitive: "Disk" != "disk").
    wf = _wf(Persistence(default="in_memory"), {"OD": StreamDecl(persistence="Disk")})
    with pytest.raises(PersistenceError):
        SinkSet.build(wf, output_dir=tmp_path, log_sink_override=None)


def test_sinkset_csv_format(tmp_path: Path):
    wf = _wf(Persistence(default="disk", format="csv"), {"OD": StreamDecl()})
    ss = SinkSet.build(wf, output_dir=tmp_path, log_sink_override=None)
    assert isinstance(ss.log_sink, CsvRunLogSink)
    assert isinstance(ss.stream_sinks["OD"], CsvStreamSink)
    ss.close_all()


def test_sinkset_open_failure_raises_persistence_error(tmp_path: Path):
    f = tmp_path / "afile"
    f.write_text("x")
    wf = _wf(Persistence(default="disk"), {"OD": StreamDecl()})
    with pytest.raises(PersistenceError):
        SinkSet.build(wf, output_dir=f, log_sink_override=None)
