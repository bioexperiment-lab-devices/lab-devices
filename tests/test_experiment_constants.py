from lab_devices.experiment import ExperimentRun, RunOptions
from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.run import assign_block_ids
from lab_devices.experiment.workflow import ConstantDecl, Workflow
from lab_devices.experiment.serialize import workflow_from_dict, workflow_to_dict
from lab_devices.experiment.validate import binding_types, validate
from tests.fakeclock import FakeClock, drive


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


def test_constants_appear_in_binding_types_with_units():
    w = workflow_from_dict(_doc({"MAX_TEMP": {"value": 37.0, "as": "celsius"},
                                 "DOSES": {"value": 3}}))
    types = binding_types(w)
    assert types["DOSES"].base == "int"
    assert types["MAX_TEMP"].base == "number"
    from lab_devices.experiment.units import unit_str
    assert unit_str(types["MAX_TEMP"].unit) == "celsius"


def test_derived_constant_infers_from_earlier_constant():
    w = workflow_from_dict(_doc({"DOSES": {"value": 3}, "TOTAL": {"value": "DOSES * 2"}}))
    assert binding_types(w)["TOTAL"].base == "int"


def _messages(doc):
    try:
        validate(workflow_from_dict(doc))
    except ValidationError as exc:
        return [d.message for d in exc.diagnostics]
    return []


def test_constant_bad_identifier_rejected():
    msgs = _messages(_doc({"1bad": {"value": 1}}))
    assert any("identifier" in m for m in msgs)


def test_constant_forward_reference_rejected():
    # TOTAL declared before DOSES -> forward ref
    msgs = _messages(_doc({"TOTAL": {"value": "DOSES * 2"}, "DOSES": {"value": 3}}))
    assert any("DOSES" in m and "earlier" in m for m in msgs)


def test_constant_self_reference_rejected():
    msgs = _messages(_doc({"X": {"value": "X + 1"}}))
    assert any("'X'" in m and "earlier" in m for m in msgs)


def test_constant_reading_stream_rejected():
    doc = {"schema_version": 3, "persistence": {"default": "in_memory", "format": "jsonl"},
           "streams": {"od": {"units": "unitless"}},
           "constants": {"K": {"value": "mean(od, last=5min)"}}, "blocks": []}
    msgs = _messages(doc)
    assert any("static" in m or "stream" in m for m in msgs)


def test_compute_writing_constant_name_rejected():
    doc = {"schema_version": 3, "persistence": {"default": "in_memory", "format": "jsonl"},
           "constants": {"K": {"value": 1}},
           "blocks": [{"compute": {"into": "K", "value": 2}}]}
    msgs = _messages(doc)
    assert any("'K'" in m and "constant" in m for m in msgs)


def test_constant_name_colliding_with_stream_rejected():
    doc = {"schema_version": 3, "persistence": {"default": "in_memory", "format": "jsonl"},
           "streams": {"od": {"units": "unitless"}},
           "constants": {"od": {"value": 1}}, "blocks": []}
    msgs = _messages(doc)
    assert any("'od'" in m for m in msgs)


def test_valid_derived_constants_pass():
    doc = _doc({"DOSES": {"value": 3}, "ML_PER_DOSE": {"value": 2.5},
                "TOTAL_ML": {"value": "DOSES * ML_PER_DOSE"}})
    assert _messages(doc) == []


def test_block_reading_constant_passes_dataflow_validation():
    # The path-sensitive "may be read before it is written" analysis must know constants are
    # bound before any block runs, or every block reading one is (wrongly) flagged.
    doc = _doc({"THRESHOLD": {"value": 10}, "LIMIT": {"value": "THRESHOLD * 2"}})
    doc["blocks"] = [{"compute": {"into": "seen_limit", "value": "LIMIT"}}]
    assert _messages(doc) == []


async def test_constant_is_bound_before_blocks_and_derives(fake_client):
    # THRESHOLD=10, LIMIT=THRESHOLD*2=20 ; a compute copies LIMIT into a binding we can read back.
    _, client = fake_client
    doc = _doc({"THRESHOLD": {"value": 10}, "LIMIT": {"value": "THRESHOLD * 2"}})
    doc["blocks"] = [{"compute": {"into": "seen_limit", "value": "LIMIT"}}]
    workflow = workflow_from_dict(doc)
    assign_block_ids(workflow)
    run = ExperimentRun(client, workflow, options=RunOptions(clock=FakeClock()))
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    assert report.state.bindings["THRESHOLD"] == 10
    assert report.state.bindings["LIMIT"] == 20
    assert report.state.bindings["seen_limit"] == 20
