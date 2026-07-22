from lab_devices.experiment.workflow import ConstantDecl, Workflow
from lab_devices.experiment.serialize import workflow_from_dict, workflow_to_dict


def test_workflow_defaults_constants_to_empty():
    w = Workflow(schema_version=3)
    assert w.constants == {}


def test_constant_decl_holds_value_and_unit():
    c = ConstantDecl(value=37.0, as_="celsius")
    assert c.value == 37.0
    assert c.as_ == "celsius"

    d = ConstantDecl(value="DOSE * COUNT")
    assert d.value == "DOSE * COUNT"
    assert d.as_ is None


def _doc(constants):
    return {"schema_version": 3, "persistence": {"default": "in_memory", "format": "jsonl"},
            "constants": constants, "blocks": []}


def test_constants_round_trip():
    doc = _doc({"MAX_TEMP": {"value": 37.0, "as": "celsius"},
               "DOSES": {"value": 3},
               "TOTAL_ML": {"value": "DOSES * 2"}})
    w = workflow_from_dict(doc)
    assert w.constants["MAX_TEMP"].value == 37.0
    assert w.constants["MAX_TEMP"].as_ == "celsius"
    assert w.constants["TOTAL_ML"].value == "DOSES * 2"
    out = workflow_to_dict(w)
    assert out["constants"] == doc["constants"]


def test_empty_constants_are_omitted():
    out = workflow_to_dict(workflow_from_dict(_doc({})))
    assert "constants" not in out


def test_constants_key_sits_between_streams_and_groups():
    doc = {"schema_version": 3, "persistence": {"default": "in_memory", "format": "jsonl"},
           "streams": {"od": {"units": "unitless"}},
           "constants": {"K": {"value": 1}},
           "groups": {},
           "blocks": []}
    out = workflow_to_dict(workflow_from_dict(doc))
    keys = [k for k in out if k in ("streams", "constants", "groups")]
    assert keys == ["streams", "constants"]  # groups empty -> omitted; constants after streams
