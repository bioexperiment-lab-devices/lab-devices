"""Shared builders for executor tests: workflows, devices, scripted inputs."""

from typing import Any

from lab_devices.experiment.inputs import InputRequest
from lab_devices.experiment.run import _resolve_roles, assign_block_ids
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.state import BindingValue
from lab_devices.experiment.workflow import Workflow
from tests.experiment_role_helpers import auto_roles
from tests.fakelab import FakeLab


# The roster that matches `add_standard_devices` one-to-one, each role bound to the
# identically-named device. For tests that build blocks in Python rather than in the
# document, so `auto_roles` has no `device:` field to find.
STANDARD_ROLES: dict[str, Any] = {
    "pump_1": {"type": "pump", "device": "pump_1"},
    "pump_2": {"type": "pump", "device": "pump_2"},
    "valve_1": {"type": "valve", "device": "valve_1"},
    "densitometer_1": {"type": "densitometer", "device": "densitometer_1"},
}


def make_workflow(
    blocks: list[dict[str, Any]],
    *,
    streams: dict[str, Any] | None = None,
    groups: dict[str, Any] | None = None,
    persistence: dict[str, Any] | None = None,
    roles: dict[str, Any] | None = None,
) -> Workflow:
    doc: dict[str, Any] = {"schema_version": 2, "blocks": blocks}
    if streams is not None:
        doc["streams"] = streams
    if groups is not None:
        doc["groups"] = groups
    if persistence is not None:
        doc["persistence"] = persistence
    doc["roles"] = auto_roles(doc) if roles is None else roles
    workflow = workflow_from_dict(doc)
    assign_block_ids(workflow)
    return workflow


def role_devices(workflow: Workflow) -> dict[str, str]:
    """The run's role -> physical device map, resolved exactly as ExperimentRun resolves it.
    Tests that build a RunContext directly (bypassing the run facade) still need one, and
    borrowing the production resolver keeps the injectivity rule in a single place."""
    return _resolve_roles(workflow, {})


def add_standard_devices(fake: FakeLab) -> None:
    fake.add_device("pump_1", "pump")
    fake.add_device("pump_2", "pump")
    fake.add_device("valve_1", "valve")
    fake.add_device("densitometer_1", "densitometer")


def verbs(fake: FakeLab) -> list[tuple[str, str]]:
    """(device, cmd) projection of the chronological call log."""
    return [(device, cmd) for device, cmd, _ in fake.calls]


class ScriptedInputProvider:
    """Test provider: returns scripted values by input name; records every request."""

    def __init__(self, values: dict[str, BindingValue]) -> None:
        self.values = dict(values)
        self.requests: list[InputRequest] = []

    async def request(self, request: InputRequest) -> BindingValue:
        self.requests.append(request)
        return self.values[request.name]
