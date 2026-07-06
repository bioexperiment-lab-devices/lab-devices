import httpx

from lab_devices.devices.valve import Valve
from lab_devices.jobs import Job
from lab_devices.models.valve import ValveMoveResult
from lab_devices.transport import Transport
from tests.fakelab import FakeLab


def _valve():
    fake = FakeLab()
    fake.add_device(
        "valve_1",
        "valve",
        identify={
            "device_type": "distribution_valve",
            "model": "radial-6",
            "capabilities": {"positions": 6, "seconds_per_position": 0.9},
        },
        home={"homed": True, "position": 0},
        configure={"default_rotation": "shortest", "hold_torque": False},
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    return fake, Valve(Transport(client), "valve_1"), client


async def test_home_then_set_position_job():
    fake, valve, client = _valve()
    try:
        homed = await valve.home(position=0)
        assert homed["homed"] is True
        job = await valve.set_position(position=4)
        assert isinstance(job, Job)
        result = await job.result(poll_interval=0.0)
        assert isinstance(result, ValveMoveResult)
        assert result.position == 4
    finally:
        await client.aclose()


async def test_configure_echo():
    fake, valve, client = _valve()
    try:
        cfg = await valve.configure(default_rotation="shortest")
        assert cfg["default_rotation"] == "shortest"
    finally:
        await client.aclose()
