"""Shared builders for the validator test files."""
import pytest

from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate
from tests.experiment_role_helpers import auto_roles


def wf(blocks, streams=None, groups=None, roles=None):
    doc = {
        "schema_version": 2,
        "streams": {name: {} for name in (streams or [])},
        "groups": groups or {},
        "blocks": blocks,
    }
    doc["roles"] = auto_roles(doc) if roles is None else roles
    return workflow_from_dict(doc)


def diags(workflow):
    with pytest.raises(ValidationError) as exc:
        validate(workflow)
    return exc.value.diagnostics


def cmd(device, verb, params=None):
    return {"command": {"device": device, "verb": verb, "params": params or {}}}


MEASURE_OD = {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}
