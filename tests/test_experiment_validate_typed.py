import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate
from lab_devices.experiment.workflow import ParamDecl, RoleDecl, Workflow

# Role names must survive the legacy_device_type id->type bridge (rsplit on the last "_",
# keep the prefix) until Task 8 threads roles all the way through -- see the brief's known
# limitation note. "od_meter_1"/"medium_pump" as used verbatim in the brief do NOT survive
# it ("od_meter_1" -> "od_meter", "medium_pump" -> "medium"), so every role name here is
# renamed to <device_type>_<n>, which the bridge decodes correctly.
DEFAULT_ROLES = {
    "densitometer_1": {"type": "densitometer"},
    "densitometer_2": {"type": "densitometer"},
    "pump_1": {"type": "pump"},
}


def wf2(blocks, *, streams=None, groups=None, roles=None):
    return workflow_from_dict({
        "schema_version": 2,
        "roles": DEFAULT_ROLES if roles is None else roles,
        "streams": {name: {} for name in (streams or [])},
        "groups": groups or {},
        "blocks": blocks,
    })


def diags(workflow):
    with pytest.raises(ValidationError) as exc:
        validate(workflow)
    return exc.value.diagnostics


def messages(workflow):
    return [d.message for d in diags(workflow)]


STOP_PUMP = {"command": {"device": "pump_1", "verb": "stop"}}


def _svc(params, body=None):
    return {"svc": {"params": params, "body": body or [STOP_PUMP]}}


def test_group_ref_missing_arg_is_reported_per_param():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": 1}}}],
        groups=_svc([{"name": "tube", "kind": "int"},
                     {"name": "dose", "kind": "number"}]),
    )
    msgs = messages(w)
    assert any("missing argument 'dose' (number)" in m for m in msgs)
    assert not any("must match params" in m for m in msgs)


def test_group_ref_extra_arg_is_reported_per_arg():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": 1, "ghost": 2}}}],
        groups=_svc([{"name": "tube", "kind": "int"}]),
    )
    assert any("group_ref 'svc' has no parameter 'ghost'" in m for m in messages(w))


def test_group_ref_with_exact_args_is_clean():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": 1}}}],
        groups=_svc([{"name": "tube", "kind": "int"}]),
    )
    assert validate(w) is None


def test_for_each_block_level_fields_still_rejected():
    w = wf2([{"for_each": {"vars": [{"name": "t", "kind": "int"}],
                           "in": [{"t": 1}], "body": [STOP_PUMP]},
              "gap_after": "1s"}])
    assert any("may not carry block-level 'gap_after'" in m for m in messages(w))


def _fe(vars_, rows, body=None):
    return {"for_each": {"vars": vars_, "in": rows, "body": body or [STOP_PUMP]}}


def test_for_each_row_missing_a_declared_var():
    w = wf2([_fe([{"name": "t", "kind": "int"}, {"name": "d", "kind": "number"}],
                 [{"t": 1, "d": 0.5}, {"t": 2}])])
    assert any("'in' row 1 is missing 't'" not in m and "row 1 is missing 'd'" in m
               for m in messages(w))


def test_for_each_row_with_an_extra_key():
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1, "ghost": 9}])])
    assert any("'in' row 0 has no variable 'ghost'" in m for m in messages(w))


def test_for_each_row_must_be_an_object():
    # Unreachable via wf2/workflow_from_dict: serialize._for_each's _obj() already
    # rejects a non-dict row at PARSE time, so a JSON-authored doc can never carry one
    # this far. This is defense-in-depth for a ForEach built directly through the
    # Python API (the pattern _check_groups's `isinstance(b.name, str)` also guards
    # against), so it is exercised by constructing the AST directly.
    fe = B.ForEach(
        vars=[ParamDecl(name="t", kind="int")],
        items=[{"t": 1}, 2],  # type: ignore[list-item]
        body=[B.Command(device="pump_1", verb="stop")],
    )
    w = Workflow(schema_version=2, roles={"pump_1": RoleDecl(type="pump")}, blocks=[fe])
    assert any("'in' row 1 must be an object" in m for m in messages(w))


def test_for_each_rows_matching_the_declaration_are_clean():
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1}, {"t": 2}])])
    assert validate(w) is None


def test_int_param_rejects_a_float_literal():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": 1.5}}}],
        groups=_svc([{"name": "tube", "kind": "int"}]),
    )
    assert any("expected int for parameter 'tube', got 1.5" in m for m in messages(w))


def test_int_param_rejects_a_bool_literal():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": True}}}],
        groups=_svc([{"name": "tube", "kind": "int"}]),
    )
    assert any("expected int for parameter 'tube', got True" in m for m in messages(w))


def test_bool_param_rejects_an_int_literal():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"flag": 1}}}],
        groups=_svc([{"name": "flag", "kind": "bool"}]),
    )
    assert any("expected bool for parameter 'flag', got 1" in m for m in messages(w))


def test_string_param_rejects_a_number():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"label": 3}}}],
        groups=_svc([{"name": "label", "kind": "string"}]),
    )
    assert any("expected string for parameter 'label', got 3" in m for m in messages(w))


def test_number_param_accepts_an_int_literal():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"dose": 2}}}],
        groups=_svc([{"name": "dose", "kind": "number"}]),
    )
    assert validate(w) is None


def test_for_each_cell_kind_is_checked_too():
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1}, {"t": "two"}])])
    assert any("expected int for parameter 't', got 'two'" in m for m in messages(w))
