import asyncio

import pytest

from lab_devices.experiment import Console, DeviceBusyError, ExperimentRun, RunOptions
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


async def test_rediscover_without_run_allowed(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    console = Console(client)
    devices = await console.rediscover()
    assert len(devices) == 4


async def test_disconnect_refuses_busy_then_succeeds(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow(_DISPENSE)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock))
    console = Console(client, run)
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # dispense in flight -> pump_1 busy
    assert run.is_device_busy("pump_1")
    with pytest.raises(DeviceBusyError, match="pump_1"):
        await console.disconnect("pump_1")
    with pytest.raises(DeviceBusyError):
        await console.rediscover()  # any busy device blocks a bus rescan
    # after the run finishes, pump_1 is idle -> recovery allowed
    fake.held_jobs.discard("dispense")
    await drive(clock, task)
    assert not run.is_device_busy("pump_1")
    released = await console.disconnect("pump_1")
    assert released >= 0


async def test_disconnect_null_port_refuses(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.devices["pump_1"]["port"] = None  # stuck/unbound device: no resolvable port
    console = Console(client)
    # a null port must refuse (ValueError) rather than fall through to a whole-agent disconnect
    with pytest.raises(ValueError):
        await console.disconnect("pump_1")


async def test_disconnect_unknown_device_raises(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    console = Console(client)
    with pytest.raises(ValueError):
        await console.disconnect("pump_99")


async def test_introspection_during_paused_run(fake_client):
    # Pause quiesces dispatch; introspection stays available and safe (parent §14).
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow(_DISPENSE)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock))
    console = Console(client, run)
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    run.pause()
    await clock.settle()
    # while paused: introspection works, list_devices reflects the bus
    devices = await console.list_devices()
    assert any(d.id == "densitometer_1" for d in devices)
    status = await console.device_status("densitometer_1")
    assert status.state == "idle"
    # a busy device still refuses disconnect even while paused
    with pytest.raises(DeviceBusyError):
        await console.disconnect("pump_1")
    # resume + finish
    run.resume()
    fake.held_jobs.discard("dispense")
    report = await drive(clock, task)
    assert report.status == "completed"
