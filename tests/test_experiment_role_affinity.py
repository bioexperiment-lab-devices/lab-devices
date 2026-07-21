import json

import pytest

from lab_devices.experiment.context import RunOptions
from lab_devices.experiment.errors import ValidationError, WorkflowLoadError
from lab_devices.experiment.run import ExperimentRun
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate
from tests.experiment_run_helpers import add_standard_devices
from tests.fakeclock import FakeClock, drive


def _doc(roles, lanes):
    return {
        "schema_version": 2,
        "roles": roles,
        "streams": {},
        "blocks": [{"parallel": {"children": lanes}}],
    }


def _dispense(role):
    return {"command": {"device": role, "verb": "dispense",
                        "params": {"volume_ml": 1.0}}}


def _rebind(doc, mapping):
    """The same document with every ROLE NAME replaced by its mapped device id --
    i.e. the document Studio used to hand the engine before roles moved in (§5.4)."""
    text = json.dumps(doc)
    for role, device in mapping.items():
        text = text.replace(f'"{role}"', f'"{device}"')
    rebound = json.loads(text)
    rebound["roles"] = {
        device: {"type": doc["roles"][role]["type"], "device": device}
        for role, device in mapping.items()
    }
    return rebound


def _diag_keys(doc):
    """Category+path of every diagnostic. Messages are excluded on purpose: they embed
    the device string, which is the one thing that legitimately differs."""
    try:
        validate(workflow_from_dict(doc))
    except ValidationError as exc:
        return sorted((d.category, d.path) for d in exc.diagnostics)
    return []


TWO_ROLES = {"left_feed": {"type": "pump", "device": "pump_1"},
             "right_feed": {"type": "pump", "device": "pump_2"}}
INJECTIVE = {"left_feed": "pump_1", "right_feed": "pump_2"}


def test_disjoint_lanes_agree_under_both_analyses():
    doc = _doc(TWO_ROLES, [_dispense("left_feed"), _dispense("right_feed")])
    assert _diag_keys(doc) == []
    assert _diag_keys(_rebind(doc, INJECTIVE)) == []


def test_conflicting_lanes_agree_under_both_analyses():
    doc = _doc(TWO_ROLES, [_dispense("left_feed"), _dispense("left_feed")])
    by_role = _diag_keys(doc)
    by_device = _diag_keys(_rebind(doc, INJECTIVE))
    assert by_role == by_device
    assert ("affinity", "blocks[0]") in by_role  # not vacuously equal: both DIAGNOSE


def test_a_non_injective_mapping_is_exactly_where_the_two_analyses_diverge(fake_client):
    """Two distinct roles, two disjoint lanes -- clean by role name. Alias them onto one
    device and the device-id analysis reports an affinity conflict the role-name analysis
    cannot see. That divergence is the runtime collision §5.4 describes, and it is why
    the mapping must be injective: _resolve_roles refuses it before validate() runs."""
    fake, client = fake_client
    add_standard_devices(fake)
    doc = _doc(TWO_ROLES, [_dispense("left_feed"), _dispense("right_feed")])
    aliased = {"left_feed": "pump_1", "right_feed": "pump_1"}

    assert _diag_keys(doc) == []
    assert ("affinity", "blocks[0]") in _diag_keys(_rebind(doc, aliased))

    with pytest.raises(WorkflowLoadError, match="must be injective"):
        ExperimentRun(client, workflow_from_dict(doc),
                      options=RunOptions(clock=FakeClock(), role_mapping=aliased))
    assert fake.calls == []


async def test_the_injective_mapping_of_that_same_workflow_runs(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    doc = _doc(TWO_ROLES, [_dispense("left_feed"), _dispense("right_feed")])
    clock = FakeClock()
    run = ExperimentRun(client, workflow_from_dict(doc),
                        options=RunOptions(clock=clock, role_mapping=INJECTIVE))
    report = await drive(clock, run.execute())
    assert report.status == "completed"
    assert report.role_devices == INJECTIVE
    dispensed = {d for d, c, _ in fake.calls if c == "dispense"}
    assert dispensed == {"pump_1", "pump_2"}
