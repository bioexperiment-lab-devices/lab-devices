"""Shared builders for the validator test files."""
import pytest

from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate


def wf(blocks, streams=None, groups=None):
    return workflow_from_dict({
        "schema_version": 1,
        "streams": {name: {} for name in (streams or [])},
        "groups": groups or {},
        "blocks": blocks,
    })


def diags(workflow):
    with pytest.raises(ValidationError) as exc:
        validate(workflow)
    return exc.value.diagnostics


def cmd(device, verb, params=None):
    return {"command": {"device": device, "verb": verb, "params": params or {}}}


MEASURE_OD = {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}
