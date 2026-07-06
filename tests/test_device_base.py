from dataclasses import dataclass

import httpx

from lab_devices.devices.base import Device
from lab_devices.jobs import Job
from lab_devices.models import Identify, PingResult, RawModel
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


async def test_status_raw_when_no_model():
    fake = FakeLab()
    fake.add_device("pump_1", "pump", status={"state": "dispensing", "speed_ml_min": 3.0})
    device, client = _device(fake, "pump_1")
    try:
        result = await device.status()
        assert isinstance(result, dict)
        assert result["state"] == "dispensing"
    finally:
        await client.aclose()


async def test_status_parsed_with_model():
    @dataclass
    class _Status(RawModel):
        state: str | None = None

    class _StatusDevice(Device):
        STATUS_MODEL = _Status

    fake = FakeLab()
    fake.add_device("pump_1", "pump", status={"state": "dispensing"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    device = _StatusDevice(Transport(client), "pump_1")
    try:
        result = await device.status()
        assert isinstance(result, _Status)
        assert result.state == "dispensing"
    finally:
        await client.aclose()


async def test_stop_returns_result():
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    device, client = _device(fake, "pump_1")
    try:
        result = await device.stop()
        assert isinstance(result, dict)
        assert result["state"] == "idle"
    finally:
        await client.aclose()


async def test_get_job_returns_job():
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    device, client = _device(fake, "pump_1")
    try:
        started = await device.command("dispense", {"volume_ml": 10})
        job_id = started["job"]["job_id"]
        job = await device.get_job(job_id)
        assert isinstance(job, Job)
        assert job.job_id == job_id
    finally:
        await client.aclose()
