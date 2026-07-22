import httpx

from lab_devices.devices.densitometer import Densitometer
from lab_devices.jobs import Job
from lab_devices.models.densitometer import DensitometerStatus, MeasureResult, ReadingsResult
from lab_devices.transport import Transport
from tests.fakelab import FakeLab


def _dens():
    fake = FakeLab()
    fake.add_device(
        "densitometer_1",
        "densitometer",
        identify={
            "device_type": "densitometer",
            "model": "TDS909A-wide",
            "capabilities": {"wavelength_nm": 600, "thermostat": {"min_c": 20.0, "max_c": 45.0}},
        },
        set_thermostat={"enabled": True, "target_c": 37.0},
        get_readings={"readings": [{"seq": 1, "absorbance": 0.5, "temperature_c": 37.0}], "dropped": 0},
        status={"state": "idle", "temperature_c": 36.98},
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    return fake, Densitometer(Transport(client), "densitometer_1"), client


async def test_measure_job_result():
    fake, dens, client = _dens()
    try:
        job = await dens.measure()
        assert isinstance(job, Job)
        result = await job.result(poll_interval=0.0)
        assert isinstance(result, MeasureResult)
        assert result.absorbance == 0.523
    finally:
        await client.aclose()


async def test_set_thermostat():
    fake, dens, client = _dens()
    try:
        res = await dens.set_thermostat(enabled=True, target_c=37.0)
        assert res["target_c"] == 37.0
    finally:
        await client.aclose()


async def test_read_temperature_reads_status_without_optics():
    fake, dens, client = _dens()
    try:
        status = await dens.read_temperature()
        assert isinstance(status, DensitometerStatus)
        assert status.temperature_c == 36.98
    finally:
        await client.aclose()


async def test_get_readings_typed():
    fake, dens, client = _dens()
    try:
        readings = await dens.get_readings()
        assert isinstance(readings, ReadingsResult)
        assert readings.readings[0].absorbance == 0.5
        assert readings.dropped == 0
    finally:
        await client.aclose()
