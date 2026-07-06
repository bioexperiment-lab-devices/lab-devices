import httpx
import pytest

from lab_devices.client import LabClient
from lab_devices.devices.densitometer import Densitometer
from lab_devices.devices.pump import Pump
from lab_devices.devices.valve import Valve
from lab_devices.models import AgentInfo, DeviceInfo
from tests.fakelab import FakeLab


def _client(fake: FakeLab) -> LabClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    return LabClient("chisel", 8089, http=http)


async def test_handle_factories_typed():
    fake = FakeLab()
    async with _client(fake) as lab:
        assert isinstance(lab.pump(1), Pump)
        assert isinstance(lab.valve(2), Valve)
        assert isinstance(lab.densitometer(1), Densitometer)
        assert lab.pump(1).id == "pump_1"
        assert isinstance(lab.device("valve_3"), Valve)


async def test_device_unknown_prefix_raises():
    fake = FakeLab()
    async with _client(fake) as lab:
        with pytest.raises(ValueError):
            lab.device("thermometer_1")


async def test_list_devices_returns_models():
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    fake.add_device("valve_1", "valve")
    async with _client(fake) as lab:
        devices = await lab.list_devices()
        assert all(isinstance(d, DeviceInfo) for d in devices)
        assert {d.id for d in devices} == {"pump_1", "valve_1"}


async def test_agent_info_typed():
    fake = FakeLab()
    async with _client(fake) as lab:
        info = await lab.agent_info()
        assert isinstance(info, AgentInfo)
        assert info.hostname == "FAKE"


async def test_disconnect_returns_count():
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    async with _client(fake) as lab:
        assert await lab.disconnect() == 1


async def test_drive_pump_end_to_end():
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    async with _client(fake) as lab:
        job = await lab.pump(1).dispense(volume_ml=10, speed_ml_min=3.0)
        result = await job.result(poll_interval=0.0)
        assert result.dispensed_ml == 10.0


async def test_owned_http_closed_on_exit():
    """LabClient with owned http client must close it on context exit."""
    lab = LabClient("chisel", 8089)
    async with lab as _:
        assert lab._http.is_closed is False
    assert lab._http.is_closed is True


async def test_injected_http_not_closed_on_exit():
    """LabClient with injected http client must NOT close it on context exit."""
    injected = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={})),
        base_url="http://lab"
    )
    async with LabClient("chisel", 8089, http=injected) as lab:
        assert injected.is_closed is False
    assert injected.is_closed is False
    await injected.aclose()
