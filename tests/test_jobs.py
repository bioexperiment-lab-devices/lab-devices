import httpx
import pytest

from lab_devices import errors
from lab_devices.jobs import Job
from lab_devices.models import RawModel
from lab_devices.transport import Transport
from tests.fakelab import FakeLab
from dataclasses import dataclass


@dataclass
class _DispenseResult(RawModel):
    dispensed_ml: float | None = None


class _StubDevice:
    def __init__(self, transport: Transport, device_id: str) -> None:
        self._transport = transport
        self.id = device_id

    async def stop(self):
        return await self._transport.command(self.id, "stop")


def _wire():
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    transport = Transport(client)
    return fake, transport, _StubDevice(transport, "pump_1"), client


async def test_result_polls_to_success_and_parses_model():
    fake, transport, device, client = _wire()
    try:
        started = await transport.command("pump_1", "dispense", {"volume_ml": 10})
        job = Job.from_start_result(device, started, result_model=_DispenseResult)
        assert job.state == "running"
        result = await job.result(poll_interval=0.0)
        assert isinstance(result, _DispenseResult)
        assert result.dispensed_ml == 10.0
        assert job.state == "succeeded"
    finally:
        await client.aclose()


async def test_failed_job_raises():
    fake, transport, device, client = _wire()
    fake.fail_job = True
    try:
        started = await transport.command("pump_1", "dispense", {"volume_ml": 10})
        job = Job.from_start_result(device, started)
        with pytest.raises(errors.JobFailedError):
            await job.result(poll_interval=0.0)
    finally:
        await client.aclose()


async def test_timeout_raises_without_cancelling():
    fake, transport, device, client = _wire()
    fake.polls_to_complete = 10_000  # never completes in time
    try:
        started = await transport.command("pump_1", "dispense", {"volume_ml": 10})
        job = Job.from_start_result(device, started)
        with pytest.raises(errors.JobTimeoutError):
            await job.result(poll_interval=0.01, timeout=0.05)
    finally:
        await client.aclose()


async def test_refresh_updates_progress():
    fake, transport, device, client = _wire()
    fake.polls_to_complete = 2
    try:
        started = await transport.command("pump_1", "dispense", {"volume_ml": 10})
        job = Job.from_start_result(device, started)
        await job.refresh()
        assert job.state == "running"
        await job.refresh()
        assert job.state == "succeeded"
    finally:
        await client.aclose()
