import httpx

from lab_devices.devices.pump import Pump
from lab_devices.jobs import PumpJob
from lab_devices.models.pump import DispenseResult, PumpCapabilities
from lab_devices.transport import Transport
from tests.fakelab import FakeLab


def _pump():
    fake = FakeLab()
    fake.add_device(
        "pump_1",
        "pump",
        identify={
            "device_type": "pump",
            "model": "peristaltic-1ch",
            "capabilities": {"channels": 1, "speed_ml_min": {"min": 0.05, "max": 40.0}},
        },
        rotate={"state": "rotating", "direction": "forward", "speed_ml_min": 3.0},
        get_calibration={"ml_per_step": 0.000424, "set_at_uptime_ms": 120000},
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    return fake, Pump(Transport(client), "pump_1"), client


async def test_dispense_returns_pumpjob_and_result():
    fake, pump, client = _pump()
    try:
        job = await pump.dispense(volume_ml=10, speed_ml_min=3.0)
        assert isinstance(job, PumpJob)
        result = await job.result(poll_interval=0.0)
        assert isinstance(result, DispenseResult)
        assert result.dispensed_ml == 10.0
    finally:
        await client.aclose()


async def test_rotate_returns_state():
    fake, pump, client = _pump()
    try:
        state = await pump.rotate(direction="forward", speed_ml_min=3.0)
        assert state["direction"] == "forward"
    finally:
        await client.aclose()


async def test_identify_typed_capabilities():
    fake, pump, client = _pump()
    try:
        ident = await pump.identify()
        assert isinstance(ident.capabilities, PumpCapabilities)
        assert ident.capabilities.speed_ml_min.max == 40.0
    finally:
        await client.aclose()


async def test_get_calibration():
    fake, pump, client = _pump()
    try:
        cal = await pump.get_calibration()
        assert cal.ml_per_step == 0.000424
    finally:
        await client.aclose()
