"""Shared builders for executor tests: workflows, devices, scripted inputs."""

from typing import Any

from lab_devices.experiment.inputs import InputRequest
from lab_devices.experiment.run import assign_block_ids
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.state import BindingValue
from lab_devices.experiment.workflow import Workflow
from tests.experiment_role_helpers import auto_roles
from tests.fakelab import FakeLab


def make_workflow(
    blocks: list[dict[str, Any]],
    *,
    streams: dict[str, Any] | None = None,
    groups: dict[str, Any] | None = None,
    persistence: dict[str, Any] | None = None,
) -> Workflow:
    doc: dict[str, Any] = {"schema_version": 2, "blocks": blocks}
    if streams is not None:
        doc["streams"] = streams
    if groups is not None:
        doc["groups"] = groups
    if persistence is not None:
        doc["persistence"] = persistence
    doc["roles"] = auto_roles(doc)
    workflow = workflow_from_dict(doc)
    assign_block_ids(workflow)
    return workflow


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
