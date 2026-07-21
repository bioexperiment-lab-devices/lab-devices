import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import UnknownRoleError, WorkflowLoadError
from lab_devices.experiment.serialize import (
    SCHEMA_VERSION,
    block_from_dict,
    workflow_from_dict,
    workflow_to_dict,
)
from lab_devices.experiment.workflow import LocalDecl, ParamDecl, RoleDecl

ROLES = {
    "od_meter_1": RoleDecl(type="densitometer"),
    "medium_pump": RoleDecl(type="pump", device="pump_2"),
}


def test_schema_version_is_three():
    assert SCHEMA_VERSION == 3


def test_older_document_is_rejected_with_a_message_naming_the_remedy():
    """A v2 doc has no stream units and no `as` casts, so it cannot be lifted mechanically.
    The message has to say so, or the author retries the same load."""
    with pytest.raises(WorkflowLoadError) as exc:
        workflow_from_dict({"schema_version": 2, "blocks": []})
    text = str(exc.value)
    assert "unsupported schema_version 2; expected 3" in text
    assert "cannot be migrated automatically" in text
    assert "design 2026-07-21 §8" in text


def test_roles_parse_before_blocks_so_a_role_resolves_to_a_device_type():
    """The ordering test: `device` holds a ROLE name, and the parse-time registry lookup
    needs its type. If blocks were still parsed inside the Workflow(...) call, this raises."""
    w = workflow_from_dict({
        "schema_version": 3,
        "roles": {"od_meter_1": {"type": "densitometer"}},
        "streams": {"od_1": {"units": "unitless"}},
        "blocks": [{"measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"}}],
    })
    assert w.roles == {"od_meter_1": RoleDecl(type="densitometer")}
    assert w.role_type("od_meter_1") == "densitometer"
    assert isinstance(w.blocks[0], B.Measure)
    assert w.blocks[0].device == "od_meter_1"


def test_a_role_declaration_may_bind_a_device_directly():
    w = workflow_from_dict({
        "schema_version": 3,
        "roles": {"medium_pump": {"type": "pump", "device": "pump_2"}},
        "blocks": [{"command": {"device": "medium_pump", "verb": "stop"}}],
    })
    assert w.roles["medium_pump"] == RoleDecl(type="pump", device="pump_2")


def test_undeclared_role_in_a_device_field_is_a_load_error():
    with pytest.raises(UnknownRoleError, match="ghost_pump"):
        workflow_from_dict({
            "schema_version": 3,
            "roles": {"medium_pump": {"type": "pump"}},
            "blocks": [{"command": {"device": "ghost_pump", "verb": "stop"}}],
        })


def test_a_role_body_verb_is_still_checked_against_the_declared_type():
    """The type comes from the declaration now, not from the id's suffix: a densitometer
    role cannot dispense."""
    with pytest.raises(WorkflowLoadError, match="densitometer"):
        workflow_from_dict({
            "schema_version": 3,
            "roles": {"od_meter_1": {"type": "densitometer"}},
            "blocks": [{"command": {"device": "od_meter_1", "verb": "dispense",
                                    "params": {"volume_ml": 1.0}}}],
        })


def test_unexpanded_hole_in_a_device_field_still_defers_the_lookup():
    """The `if "{" not in device` escape stays: a group body names a role via a hole."""
    b = block_from_dict({"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"}},
                        ROLES)
    assert isinstance(b, B.Measure) and b.device == "{meter}"


def test_unknown_role_device_type_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="toaster"):
        workflow_from_dict({
            "schema_version": 3,
            "roles": {"breakfast": {"type": "toaster"}},
            "blocks": [],
        })


def test_role_declaration_with_an_unknown_key_is_a_load_error():
    """A typo'd plural like 'devices' must not silently drop the device binding -- the
    same trap _param_decls and _local_decls already guard against."""
    with pytest.raises(WorkflowLoadError, match="unknown key"):
        workflow_from_dict({
            "schema_version": 3,
            "roles": {"medium_pump": {"type": "pump", "devices": "pump_2"}},
            "blocks": [],
        })


def test_typed_group_params_parse_in_authoring_order():
    w = workflow_from_dict({
        "schema_version": 3,
        "roles": {"od_meter_1": {"type": "densitometer"}},
        "groups": {"service": {
            "params": [
                {"name": "tube", "kind": "int"},
                {"name": "od", "kind": "stream"},
                {"name": "meter", "kind": "role", "device_type": "densitometer"},
            ],
            "body": [{"wait": {"duration": "1s"}}],
        }},
        "blocks": [],
    })
    params = w.groups["service"].params
    assert params == [
        ParamDecl(name="tube", kind="int"),
        ParamDecl(name="od", kind="stream"),
        ParamDecl(name="meter", kind="role", device_type="densitometer"),
    ]
    assert [p.name for p in params] == ["tube", "od", "meter"]


@pytest.mark.parametrize("params, match", [
    ([{"name": "tube", "kind": "integer"}], "unknown kind"),
    ([{"name": "meter", "kind": "role"}], "requires 'device_type'"),
    ([{"name": "meter", "kind": "role", "device_type": "toaster"}], "unknown device type"),
    ([{"name": "tube", "kind": "int", "device_type": "pump"}], "only allowed on kind 'role'"),
    ([{"kind": "int"}], "requires 'name'"),
    ([{"name": "tube"}], "requires 'kind'"),
    ([{"name": "tube", "kind": "int", "typo": 1}], "unknown key"),
    (["tube"], "must be an object"),
    ({"tube": "int"}, "must be a list"),
])
def test_malformed_param_declarations_rejected(params, match):
    with pytest.raises(WorkflowLoadError, match=match):
        workflow_from_dict({
            "schema_version": 3,
            "groups": {"service": {"params": params, "body": []}},
            "blocks": [],
        })


def test_group_locals_parse():
    w = workflow_from_dict({
        "schema_version": 3,
        "groups": {"service": {
            "params": [{"name": "tube", "kind": "int"}],
            "locals": {
                "c": {"kind": "binding", "init": "0"},
                "r": {"kind": "binding"},
                "c_series": {"kind": "stream", "units": "ug/mL", "persistence": "disk"},
            },
            "body": [{"wait": {"duration": "1s"}}],
        }},
        "blocks": [],
    })
    locals_ = w.groups["service"].locals
    assert locals_["c"] == LocalDecl(kind="binding", init="0")
    assert locals_["r"] == LocalDecl(kind="binding")
    assert locals_["c_series"] == LocalDecl(
        kind="stream", units="ug/mL", persistence="disk"
    )


@pytest.mark.parametrize("locals_, match", [
    ({"c": {"kind": "int"}}, "must be 'stream' or 'binding'"),
    ({"c": {"kind": "stream", "init": "0"}}, "'init' is only allowed on kind 'binding'"),
    ({"c": {"kind": "binding", "units": "AU"}}, "only allowed on kind 'stream'"),
    ({"c": {"kind": "binding", "init": "1 +"}}, "init"),
    ({"c": {}}, "requires 'kind'"),
    ({"c": {"kind": "binding", "typo": 1}}, "unknown key"),
    (["c"], "must be an object"),
])
def test_malformed_local_declarations_rejected(locals_, match):
    with pytest.raises(WorkflowLoadError, match=match):
        workflow_from_dict({
            "schema_version": 3,
            "groups": {"service": {"locals": locals_, "body": []}},
            "blocks": [],
        })


V3_DOC = {
    "schema_version": 3,
    "metadata": {"name": "typed", "author": "khamitov"},
    "persistence": {"default": "in_memory", "format": "jsonl"},
    "defaults": {"retry": {"attempts": 2, "backoff": "5s"}},
    "roles": {
        "od_meter_1": {"type": "densitometer"},
        "medium_pump": {"type": "pump", "device": "pump_2"},
    },
    "streams": {"od_1": {"units": "AU"}},
    "groups": {"service": {
        "params": [
            {"name": "tube", "kind": "int"},
            {"name": "meter", "kind": "role", "device_type": "densitometer"},
        ],
        "locals": {
            "c": {"kind": "binding", "init": "0"},
            "c_series": {"kind": "stream", "units": "ug/mL"},
        },
        "body": [{"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"}}],
    }},
    "blocks": [
        {"measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"}},
        {"command": {"device": "medium_pump", "verb": "dispense",
                     "params": {"volume_ml": 0.5}}},
    ],
}


def test_v3_document_round_trips_byte_for_byte():
    assert workflow_to_dict(workflow_from_dict(V3_DOC)) == V3_DOC


def test_emitted_key_order_puts_roles_immediately_before_streams():
    """Dict equality does not check order, so the round-trip test above cannot see this."""
    out = workflow_to_dict(workflow_from_dict(V3_DOC))
    assert list(out) == ["schema_version", "metadata", "persistence", "defaults",
                         "roles", "streams", "groups", "blocks"]
    assert list(out["groups"]["service"]) == ["params", "locals", "body"]


def test_empty_roles_and_locals_are_omitted_from_the_emitted_document():
    doc = {
        "schema_version": 3,
        "persistence": {"default": "in_memory", "format": "jsonl"},
        "groups": {"noop": {"body": [{"wait": {"duration": "1s"}}]}},
        "blocks": [{"wait": {"duration": "1s"}}],
    }
    out = workflow_to_dict(workflow_from_dict(doc))
    assert "roles" not in out
    assert list(out["groups"]["noop"]) == ["body"]
    assert out == doc
