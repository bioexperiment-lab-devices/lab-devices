# tests/test_experiment_e2e_concurrent.py
"""Concurrent flagships (spec §16 #9-10): same-device channel overlap, input lanes."""
import asyncio

import pytest

from lab_devices.experiment import ExperimentRun, RunOptions
from lab_devices.experiment.inputs import InputRequest
from lab_devices.experiment.state import BindingValue
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


async def test_flagship_thermal_optics_overlap_one_densitometer(fake_client):
    """Validator-legal same-device parallelism: thermostat (thermal) alongside a measure
    loop (optics), serialized on the wire by the per-device lock (D2)."""
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"parallel": {"children": [
            {"command": {"device": "densitometer_1", "verb": "set_thermostat",
                         "params": {"enabled": True, "target_c": 37.0}}},
            {"loop": {"count": 2, "body": [
                {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
            ]}},
        ]}}],
        streams={"OD": {"units": "AU"}},
    )
    run = ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    assert len(report.state.streams["OD"]) == 2
    seq = verbs(fake)
    assert seq.count(("densitometer_1", "measure")) == 2
    # thermostat mode was torn down by the finalizer (never explicitly closed)
    teardowns = [e for e in report.log.events if e.kind == "teardown_issued"]
    assert len(teardowns) == 1 and teardowns[0].data["verb"] == "set_thermostat"
    thermostat_calls = [c[2] for c in fake.calls if c[1] == "set_thermostat"]
    assert thermostat_calls[0] == {"enabled": True, "target_c": 37.0}  # the open
    assert {"enabled": False} in thermostat_calls  # teardown (and sweep) closed it
    assert run._ctx.occupancy.open_modes() == ()


class GatedInputProvider:
    """Blocks its lane until the test releases it — proves siblings keep running."""

    def __init__(self, value: BindingValue) -> None:
        self.value = value
        self.release = asyncio.Event()
        self.requests: list[InputRequest] = []

    async def request(self, request: InputRequest) -> BindingValue:
        self.requests.append(request)
        await self.release.wait()
        return self.value


async def test_flagship_operator_input_blocks_only_its_lane(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"parallel": {"children": [
            {"operator_input": {"name": "target", "type": "float"}},
            {"command": {"device": "pump_1", "verb": "stop"}},
        ]}},
    ])
    provider = GatedInputProvider(1.5)
    run = ExperimentRun(
        client, wf, options=RunOptions(clock=FakeClock(), input_provider=provider)
    )
    clock = run._options.clock
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    assert ("pump_1", "stop") in verbs(fake)  # sibling lane ran while input pending
    assert len(provider.requests) == 1        # ...and the request is outstanding
    assert "target" not in run._ctx.state.bindings

    provider.release.set()
    report = await drive(clock, task)
    assert report.status == "completed"
    assert report.state.bindings == {"target": 1.5}


async def test_flagship_concurrent_failure_single_finalize_pass(fake_client):
    """Flagship 9b: a failing parallel child cancels its sibling and the run finalizes
    exactly once through the facade (single safe-state pass, §9/§11)."""
    fake, client = fake_client
    add_standard_devices(fake)
    fake.inject_error("pump_1", "dispense", "hardware_error", "stall")
    wf = make_workflow([
        {"parallel": {"children": [
            {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
            {"command": {"device": "pump_2", "verb": "dispense", "params": {"volume_ml": 1.0}}},
        ]}},
    ])
    run = ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))
    with pytest.raises(BaseExceptionGroup):
        await drive(run._options.clock, run.execute())
    report = run.report
    assert report.status == "failed"
    starts = [e for e in report.log.events if e.kind == "finalize_started"]
    assert len(starts) == 1  # exactly one safe-state pass despite concurrent lanes
