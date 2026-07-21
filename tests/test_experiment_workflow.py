import json

import pytest

from lab_devices.experiment import Workflow, load_workflow, save_workflow
from lab_devices.experiment.errors import WorkflowLoadError

_ROLES_DOC = {
    "pump_1": {"type": "pump"},
    "pump_2": {"type": "pump"},
    "densitometer_1": {"type": "densitometer"},
}

EXAMPLE = {
    "schema_version": 3,
    "metadata": {"name": "od-feedback-feed", "author": "khamitov",
                 "description": "Feed pump_1 by live OD until target, stirring throughout."},
    "persistence": {"default": "disk", "format": "jsonl"},
    "roles": _ROLES_DOC,
    "streams": {"OD": {"units": "AU"}, "temp": {"units": "C", "persistence": "in_memory"}},
    "groups": {"prime_line": {"body": [
        {"command": {"device": "pump_1", "verb": "dispense",
                     "params": {"volume_ml": 1.0, "speed_ml_min": 5.0}}}]}},
    "blocks": [{"serial": {"children": [
        {"operator_input": {"name": "target_OD", "type": "float",
                            "prompt": "Enter target OD", "min": 0.0, "max": 2.0}},
        {"group_ref": {"name": "prime_line"}},
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"loop": {"check": "after", "until": "mean(OD, last=5min) >= target_OD", "body": [
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
            {"command": {"device": "pump_1", "verb": "dispense",
                         "params": {"volume_ml": "2.0 * (target_OD - mean(OD, last=100))",
                                    "speed_ml_min": 3.0}}, "gap_after": "30s"}]}},
        {"command": {"device": "pump_2", "verb": "stop"}},
        {"branch": {"if": "last(OD) > target_OD",
                    "then": [{"command": {"device": "densitometer_1", "verb": "set_led",
                                          "params": {"level": 0}}}]}}]}}],
}


def test_full_example_round_trips_through_file(tmp_path):
    path = tmp_path / "wf.json"
    path.write_text(json.dumps(EXAMPLE))
    wf = load_workflow(path)
    assert isinstance(wf, Workflow)
    assert wf.metadata.name == "od-feedback-feed"
    assert wf.persistence.default == "disk"
    assert wf.streams["temp"].persistence == "in_memory"
    assert "prime_line" in wf.groups

    out = tmp_path / "out.json"
    save_workflow(wf, out)
    assert json.loads(out.read_text()) == EXAMPLE


def test_bad_schema_version_rejected(tmp_path):
    path = tmp_path / "wf.json"
    path.write_text(json.dumps({"schema_version": 99, "blocks": []}))
    with pytest.raises(WorkflowLoadError):
        load_workflow(path)


def test_invalid_json_rejected(tmp_path):
    path = tmp_path / "wf.json"
    path.write_text("{not json")
    with pytest.raises(WorkflowLoadError):
        load_workflow(path)


@pytest.mark.parametrize("doc", [
    {"schema_version": 3, "metadata": None, "blocks": []},
    {"schema_version": 3, "persistence": "disk", "blocks": []},
    {"schema_version": 3, "streams": ["OD"], "blocks": []},
    {"schema_version": 3, "streams": {"OD": "AU"}, "blocks": []},
    {"schema_version": 3, "groups": None, "blocks": []},
    {"schema_version": True, "blocks": []},
    {"schema_version": 3, "roles": ["pump_1"], "blocks": []},
    {"schema_version": 3, "roles": {"pump_1": "pump"}, "blocks": []},
])
def test_malformed_workflow_sections_rejected(doc, tmp_path):
    path = tmp_path / "wf.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(WorkflowLoadError):
        load_workflow(path)


def test_non_dict_top_level_rejected(tmp_path):
    path = tmp_path / "wf.json"
    path.write_text(json.dumps("not a workflow"))
    with pytest.raises(WorkflowLoadError):
        load_workflow(path)
