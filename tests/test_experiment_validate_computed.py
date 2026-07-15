from lab_devices.experiment.validate import validate
from tests.experiment_validate_helpers import MEASURE_OD, cmd, diags, wf

SEED_C = {"compute": {"into": "c", "value": "0"}}
STEP_C = {"compute": {"into": "c", "value": "c * 0.5 + 1"}}
INPUT_X = {"operator_input": {"name": "x", "type": "float"}}


def test_seeded_accumulator_is_clean():
    blocks = [SEED_C, {"loop": {"count": 3, "body": [STEP_C]}}]
    assert validate(wf(blocks)) is None


def test_unseeded_accumulator_is_read_before_write():
    blocks = [{"loop": {"count": 3, "body": [STEP_C]}}]
    d = diags(wf(blocks))
    assert any(x.category == "data-flow" and "'c'" in x.message and "before" in x.message
               for x in d)


def test_compute_then_read_binding_clean():
    blocks = [{"compute": {"into": "c", "value": "2 * 3"}},
              cmd("pump_1", "dispense", {"volume_ml": "c"})]
    assert validate(wf(blocks)) is None


def test_record_writes_undeclared_stream():
    d = diags(wf([{"record": {"into": "r", "value": "1"}}]))
    assert any(x.category == "declaration" and "'r'" in x.message for x in d)


def test_record_reading_own_stream_before_first_write():
    blocks = [{"record": {"into": "r", "value": "mean(r, last=5)"}}]
    d = diags(wf(blocks, streams=["r"]))
    assert any(x.category == "data-flow" and "'r'" in x.message for x in d)


def test_record_reading_measured_stream_clean():
    blocks = [MEASURE_OD, {"record": {"into": "r", "value": "last(OD)"}}]
    assert validate(wf(blocks, streams=["OD", "r"])) is None


def test_stream_written_by_both_measure_and_record():
    blocks = [MEASURE_OD, {"record": {"into": "OD", "value": "1"}}]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "declaration" and "OD" in x.message
               and "measure" in x.message and "record" in x.message for x in d)


def test_name_is_both_binding_and_stream():
    blocks = [{"compute": {"into": "OD", "value": "1"}}, MEASURE_OD]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "declaration" and "OD" in x.message for x in d)


def test_compute_and_operator_input_same_name():
    blocks = [INPUT_X, {"compute": {"into": "x", "value": "2"}}]
    d = diags(wf(blocks))
    assert any(x.category == "declaration" and "'x'" in x.message for x in d)


def test_retry_on_compute_rejected():
    blocks = [{"compute": {"into": "c", "value": "1"},
               "retry": {"attempts": 2, "backoff": "1s"}}]
    d = diags(wf(blocks))
    assert any("retry is only valid on command and measure" in x.message for x in d)


def test_record_value_must_be_number_not_boolean_literal():
    d = diags(wf([{"record": {"into": "r", "value": True}}], streams=["r"]))
    assert any(x.category == "type" and "number" in x.message for x in d)


def test_compute_reading_tolerated_duration_window_needs_guard():
    # a tolerated measure only maybe-writes OD; a duration read of it must be guarded
    blocks = [
        {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"},
         "on_error": "continue"},
        {"compute": {"into": "m", "value": "mean(OD, last=5min)"}},
    ]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "data-flow" and "OD" in x.message for x in d)
