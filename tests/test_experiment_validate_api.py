import json

import pytest

import lab_devices.experiment as exp
from lab_devices.experiment import (
    ValidationError,
    load_and_validate,
    validate,
    workflow_from_dict,
)

# The design spec's flagship example (§15.2), verbatim. It must validate cleanly:
# free start/stop rotate..stop, close-with-no-open set_led(0), post-test feedback
# loop, group ref, operator-input binding.
_ROLES_DOC = {
    "pump_1": {"type": "pump"},
    "pump_2": {"type": "pump"},
    "densitometer_1": {"type": "densitometer"},
}

SPEC_EXAMPLE = {
    "schema_version": 2,
    "metadata": {
        "name": "od-feedback-feed",
        "author": "khamitov",
        "description": "Feed pump_1 by live OD until target, stirring throughout.",
    },
    "persistence": {"default": "disk", "format": "jsonl"},
    "roles": _ROLES_DOC,
    "streams": {
        "OD": {"units": "AU"},
        "temp": {"units": "C", "persistence": "in_memory"},
    },
    "groups": {
        "prime_line": {
            "body": [
                {"command": {"device": "pump_1", "verb": "dispense",
                             "params": {"volume_ml": 1.0, "speed_ml_min": 5.0}}}
            ]
        }
    },
    "blocks": [
        {"serial": {"children": [
            {"operator_input": {"name": "target_OD", "type": "float",
                                "prompt": "Enter target OD", "min": 0.0, "max": 2.0}},
            {"group_ref": {"name": "prime_line"}},
            {"command": {"device": "pump_2", "verb": "rotate",
                         "params": {"direction": "forward", "speed_ml_min": 2.0}}},
            {"loop": {
                "check": "after",
                "until": "mean(OD, last=5min) >= target_OD",
                "body": [
                    {"measure": {"device": "densitometer_1", "verb": "measure",
                                 "into": "OD"}},
                    {"command": {"device": "pump_1", "verb": "dispense",
                                 "params": {
                                     "volume_ml": "2.0 * (target_OD - mean(OD, last=100))",
                                     "speed_ml_min": 3.0}},
                     "gap_after": "30s"},
                ],
            }},
            {"command": {"device": "pump_2", "verb": "stop"}},
            {"branch": {
                "if": "last(OD) > target_OD",
                "then": [{"command": {"device": "densitometer_1", "verb": "set_led",
                                      "params": {"level": 0}}}],
            }},
        ]}}
    ],
}


def test_spec_flagship_example_validates():
    assert validate(workflow_from_dict(SPEC_EXAMPLE)) is None


def test_load_and_validate_returns_workflow(tmp_path):
    p = tmp_path / "wf.json"
    p.write_text(json.dumps(SPEC_EXAMPLE))
    w = load_and_validate(p)
    assert w.metadata.name == "od-feedback-feed"


def test_load_and_validate_rejects(tmp_path):
    doc = {
        "schema_version": 2,
        "roles": {"pump_1": {"type": "pump"}},
        "blocks": [
            {"command": {"device": "pump_1", "verb": "rotate",
                         "params": {"direction": "forward", "speed_ml_min": 2.0}}},
            {"command": {"device": "pump_1", "verb": "dispense",
                         "params": {"volume_ml": 1.0}}},
        ],
    }
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(doc))
    with pytest.raises(ValidationError) as exc:
        load_and_validate(p)
    assert any(x.category == "mode" for x in exc.value.diagnostics)


def test_collect_all_categories_in_one_raise():
    doc = {
        "schema_version": 2,
        "roles": {"pump_1": {"type": "pump"}, "densitometer_1": {"type": "densitometer"}},
        "streams": {},
        "blocks": [
            {"group_ref": {"name": "ghost"}},
            {"command": {"device": "pump_1", "verb": "rotate",
                         "params": {"direction": "forward"}}},
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
            {"branch": {"if": "1 + 1",
                        "then": [{"command": {"device": "pump_1", "verb": "stop"}}]}},
        ],
    }
    with pytest.raises(ValidationError) as exc:
        validate(workflow_from_dict(doc))
    cats = {d.category for d in exc.value.diagnostics}
    assert {"group", "params", "declaration", "type"} <= cats


def test_validation_error_message_lists_each_diagnostic():
    doc = {
        "schema_version": 2,
        "blocks": [{"group_ref": {"name": "ghost"}}],
    }
    with pytest.raises(ValidationError) as exc:
        validate(workflow_from_dict(doc))
    assert "unknown group 'ghost'" in str(exc.value)


def test_exports():
    for name in (
        "validate", "load_and_validate", "ValidationError", "Diagnostic",
        "references", "ExprRefs", "infer_type", "TypeReport", "BindingType", "ExprType",
    ):
        assert name in exp.__all__
        assert getattr(exp, name) is not None
