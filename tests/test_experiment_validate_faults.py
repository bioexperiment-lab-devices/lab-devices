import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate
from lab_devices.experiment.workflow import Workflow


def _validate(doc):
    validate(workflow_from_dict(doc))


def _messages(exc):
    return [d.message for d in exc.value.diagnostics]


def test_retry_on_a_wait_block_is_rejected():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 1,
            "blocks": [{"wait": {"duration": "1s"}, "retry": {"attempts": 3}}],
        })
    assert any("only valid on command and measure" in m for m in _messages(exc))


def test_retry_on_dispense_without_allow_repeat_is_rejected():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 1,
            "blocks": [{
                "command": {"device": "pump_1", "verb": "dispense",
                            "params": {"volume_ml": 0.5}},
                "retry": {"attempts": 3},
            }],
        })
    assert any("not idempotent" in m for m in _messages(exc))


def test_retry_on_dispense_with_allow_repeat_is_accepted():
    _validate({
        "schema_version": 1,
        "blocks": [{
            "command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 0.5}},
            "retry": {"attempts": 3, "allow_repeat": True},
        }],
    })


def test_retry_on_a_measure_needs_no_opt_in():
    _validate({
        "schema_version": 1,
        "streams": {"od_1": {}},
        "blocks": [{
            "measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
            "retry": {"attempts": 3, "backoff": "2s"},
        }],
    })


def test_defaults_retry_may_not_set_allow_repeat():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 1,
            "defaults": {"retry": {"attempts": 2, "allow_repeat": True}},
            "blocks": [{"wait": {"duration": "1s"}}],
        })
    assert any("blanket policy" in m for m in _messages(exc))


def test_defaults_retry_does_not_make_dispense_retryable():
    """A workflow-wide default must never silently start retrying a relative action."""
    _validate({
        "schema_version": 1,
        "defaults": {"retry": {"attempts": 3}},
        "blocks": [{
            "command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 0.5}}
        }],
    })


def test_on_error_continue_is_accepted_on_every_container():
    _validate({
        "schema_version": 1,
        "groups": {"g": {"body": [{"wait": {"duration": "1s"}}]}},
        "blocks": [
            {"serial": {"children": [{"wait": {"duration": "1s"}}]}, "on_error": "continue"},
            {"parallel": {"children": [{"wait": {"duration": "1s"}}]}, "on_error": "continue"},
            {"wait": {"duration": "1s"}, "on_error": "continue"},
            {
                "loop": {"count": 1, "body": [{"wait": {"duration": "1s"}}]},
                "on_error": "continue",
            },
            {
                "branch": {"if": "true", "then": [{"wait": {"duration": "1s"}}]},
                "on_error": "continue",
            },
            {"group_ref": {"name": "g"}, "on_error": "continue"},
        ],
    })


def test_bad_on_error_on_a_programmatic_ast_is_rejected():
    w = Workflow(schema_version=1, blocks=[B.Wait(duration="1s", on_error="retry")])
    with pytest.raises(ValidationError) as exc:
        validate(w)
    assert any("on_error must be one of" in m for m in _messages(exc))


_TOLERANT_MEASURE = {
    "measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
    "retry": {"attempts": 3, "backoff": "2s"},
    "on_error": "continue",
}


def test_tolerated_measure_then_unguarded_windowed_read_is_rejected():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 1,
            "streams": {"od_1": {}},
            "blocks": [
                _TOLERANT_MEASURE,
                {"branch": {"if": "mean(od_1, last=3) > 0.4",
                            "then": [{"wait": {"duration": "1s"}}]}},
            ],
        })
    assert any("no preceding measure" in d.message for d in exc.value.diagnostics)


def test_tolerated_measure_guarded_by_a_count_branch_validates():
    _validate({
        "schema_version": 1,
        "streams": {"od_1": {}},
        "blocks": [
            _TOLERANT_MEASURE,
            {"branch": {
                "if": "count(od_1) > 0",
                "then": [{"branch": {"if": "mean(od_1, last=3) > 0.4",
                                     "then": [{"wait": {"duration": "1s"}}]}}],
            }},
        ],
    })


def test_tolerated_measure_guarded_by_a_short_circuit_and_validates():
    """evaluate.py:85 documents this idiom; the analyzer now recognises it."""
    _validate({
        "schema_version": 1,
        "streams": {"od_1": {}},
        "blocks": [
            _TOLERANT_MEASURE,
            {"branch": {"if": "count(od_1) > 0 and mean(od_1, last=3) > 0.4",
                        "then": [{"wait": {"duration": "1s"}}]}},
        ],
    })


def test_an_untolerated_measure_still_needs_no_guard():
    """Regression: the existing definitely-written proof must not weaken."""
    _validate({
        "schema_version": 1,
        "streams": {"od_1": {}},
        "blocks": [
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"}},
            {"branch": {"if": "mean(od_1, last=3) > 0.4",
                        "then": [{"wait": {"duration": "1s"}}]}},
        ],
    })
