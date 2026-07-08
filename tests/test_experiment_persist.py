import pytest

from lab_devices.experiment import PersistenceError
from lab_devices.experiment.persist import run_event_to_dict, safe_stream_filename
from lab_devices.experiment.runlog import RunEvent


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
