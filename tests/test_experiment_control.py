import asyncio

from lab_devices.experiment import Console, ExperimentRun, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.fakeclock import FakeClock, drive

_DISPENSE = [{"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}}]


async def test_console_without_run_introspects(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    console = Console(client)
    devices = await console.list_devices()
    assert {d.id for d in devices} == {"pump_1", "pump_2", "valve_1", "densitometer_1"}
    info = await console.agent_info()
    assert info.version == "2.0.0+test"
    ping = await console.device_ping("densitometer_1")
    assert ping.uptime_ms == 8123456
    status = await console.device_status("densitometer_1")
    assert status.state == "idle"


async def test_introspection_during_live_run_routes_through_wire_lock(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow(_DISPENSE)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock))
    console = Console(client, run)
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # dispense in flight; pump_1 busy but wire lock free between polls
    ping = await console.device_ping("pump_1")  # coexists via the shared wire lock (D2)
    assert ping.uptime_ms == 8123456
    fake.held_jobs.discard("dispense")
    await drive(clock, task)
