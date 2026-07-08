import json
from pathlib import Path

import pytest

from lab_devices.experiment import PersistenceError
from lab_devices.experiment.persist import (
    JsonlRunLogSink,
    JsonlStreamSink,
    run_event_to_dict,
    safe_stream_filename,
)
from lab_devices.experiment.runlog import RunEvent
from lab_devices.experiment.state import Sample


def test_run_event_to_dict_shape():
    ev = RunEvent(12.5, "measure_recorded", "blocks[0]", {"stream": "OD", "value": 0.5})
    assert run_event_to_dict(ev) == {
        "timestamp": 12.5,
        "kind": "measure_recorded",
        "block_id": "blocks[0]",
        "data": {"stream": "OD", "value": 0.5},
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
    assert parsed[0] == {"timestamp": 0.0, "kind": "run_started", "block_id": None, "data": {}}
    assert parsed[1]["kind"] == "measure_recorded"
    assert parsed[1]["data"] == {"stream": "OD", "value": 0.5}


def test_jsonl_sink_remembers_write_error_never_raises(tmp_path: Path):
    sink = JsonlStreamSink(tmp_path / "OD.jsonl")
    sink.close()  # force subsequent writes onto a closed file
    sink.write(Sample(1.0, 0.5))  # must NOT raise
    assert sink.errors  # remembered instead
