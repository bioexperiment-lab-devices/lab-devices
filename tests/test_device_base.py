import httpx

from lab_devices.devices.base import Device
from lab_devices.models import Identify, PingResult
from lab_devices.transport import Transport
from tests.fakelab import FakeLab


def _device(fake: FakeLab, device_id: str):
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    return Device(Transport(client), device_id), client


async def test_id_and_type():
    fake = FakeLab()
    fake.add_device("densitometer_1", "densitometer")
    device, client = _device(fake, "densitometer_1")
    try:
        assert device.id == "densitometer_1"
        assert device.type == "densitometer"
    finally:
        await client.aclose()


async def test_ping_returns_model():
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    device, client = _device(fake, "pump_1")
    try:
        ping = await device.ping()
        assert isinstance(ping, PingResult)
        assert ping.uptime_ms == 8123456
    finally:
        await client.aclose()


async def test_identify_memory_served():
    fake = FakeLab()
    fake.add_device("pump_1", "pump", identify={"device_type": "pump", "model": "peristaltic-1ch"})
    fake.unreachable.add("pump_1")  # still served from memory
    device, client = _device(fake, "pump_1")
    try:
        ident = await device.identify()
        assert isinstance(ident, Identify)
        assert ident.model == "peristaltic-1ch"
    finally:
        await client.aclose()


async def test_command_escape_hatch():
    fake = FakeLab()
    fake.add_device("pump_1", "pump", rotate_raw={"state": "rotating", "speed_pct": 25})
    device, client = _device(fake, "pump_1")
    try:
        result = await device.command("rotate_raw", {"direction": "forward", "speed_pct": 25})
        assert result["speed_pct"] == 25
    finally:
        await client.aclose()
