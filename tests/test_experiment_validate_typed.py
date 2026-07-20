import pytest

from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate

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
