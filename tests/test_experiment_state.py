import pytest

from lab_devices.experiment.state import RunState, Sample, Stream


def test_stream_appends_in_order():
    s = Stream()
    s.append(1.0, 0.5)
    s.append(2.0, 0.6)
    assert len(s) == 2
    assert list(s.samples) == [Sample(1.0, 0.5), Sample(2.0, 0.6)]


def test_equal_timestamps_allowed():
    s = Stream()
    s.append(1.0, 0.5)
    s.append(1.0, 0.6)
    assert len(s) == 2


def test_decreasing_timestamp_rejected():
    s = Stream()
    s.append(2.0, 0.5)
    with pytest.raises(ValueError, match="non-decreasing"):
        s.append(1.0, 0.6)


def test_sample_is_frozen():
    sample = Sample(1.0, 0.5)
    with pytest.raises(AttributeError):
        sample.value = 0.7


def test_run_state_record_creates_stream():
    state = RunState()
    state.record("OD", 1.0, 0.5)
    state.record("OD", 2.0, 0.6)
    assert len(state.streams["OD"]) == 2
    assert state.streams["OD"].samples[-1] == Sample(2.0, 0.6)


def test_run_state_bind():
    state = RunState()
    state.bind("target_OD", 0.8)
    state.bind("mode", "fast")
    assert state.bindings == {"target_OD": 0.8, "mode": "fast"}
