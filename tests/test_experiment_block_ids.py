# tests/test_experiment_block_ids.py
from lab_devices.experiment.blocks import Command
from lab_devices.experiment.run import assign_block_ids
from lab_devices.experiment.serialize import block_to_dict, workflow_from_dict


def _wf(doc_blocks, groups=None):
    doc = {"schema_version": 3, "roles": {"pump_1": {"type": "pump"}}, "blocks": doc_blocks}
    if groups:
        doc["groups"] = groups
    return workflow_from_dict(doc)


def test_id_defaults_to_none_and_never_serializes():
    b = Command(device="pump_1", verb="stop")
    assert b.id is None
    b.id = "blocks[0]"
    assert "id" not in block_to_dict(b)


def test_loader_rejects_authored_id_key():
    import pytest

    from lab_devices.experiment.errors import WorkflowLoadError

    with pytest.raises(WorkflowLoadError, match="exactly one type key"):
        workflow_from_dict(
            {"schema_version": 3, "roles": {"pump_1": {"type": "pump"}},
             "blocks": [{"command": {"device": "pump_1", "verb": "stop"}, "id": "x"}]}
        )


def test_assign_ids_structural_paths():
    w = _wf(
        [
            {"serial": {"children": [
                {"command": {"device": "pump_1", "verb": "stop"}},
                {"branch": {"if": "true", "then": [
                    {"command": {"device": "pump_1", "verb": "stop"}}],
                    "else": [{"command": {"device": "pump_1", "verb": "stop"}}]}},
                {"loop": {"count": 2, "body": [
                    {"command": {"device": "pump_1", "verb": "stop"}}]}},
            ]}}
        ],
        groups={"g": {"body": [{"command": {"device": "pump_1", "verb": "stop"}}]}},
    )
    assign_block_ids(w)
    serial = w.blocks[0]
    assert serial.id == "blocks[0]"
    assert serial.children[0].id == "blocks[0].children[0]"
    branch = serial.children[1]
    assert branch.then[0].id == "blocks[0].children[1].then[0]"
    assert branch.else_[0].id == "blocks[0].children[1].else[0]"
    assert serial.children[2].body[0].id == "blocks[0].children[2].body[0]"
    assert w.groups["g"].body[0].id == "groups['g'].body[0]"
