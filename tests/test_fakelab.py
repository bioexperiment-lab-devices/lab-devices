async def test_ping_and_devices_list(lab_transport):
    fake, transport = lab_transport
    fake.add_device("pump_1", "pump")
    assert (await transport.command("pump_1", "ping"))["uptime_ms"] == 8123456
    body = await transport.get_devices()
    assert body["devices"][0]["id"] == "pump_1"


async def test_job_completes_after_polls(lab_transport):
    fake, transport = lab_transport
    fake.add_device("pump_1", "pump")
    fake.polls_to_complete = 2
    started = await transport.command("pump_1", "dispense", {"volume_ml": 10, "speed_ml_min": 3})
    job_id = started["job"]["job_id"]
    first = await transport.command("pump_1", "get_job", {"job_id": job_id})
    assert first["state"] == "running"
    second = await transport.command("pump_1", "get_job", {"job_id": job_id})
    assert second["state"] == "succeeded"
    assert second["result"]["dispensed_ml"] == 10.0


async def test_unreachable_device(lab_transport):
    from lab_devices import errors

    fake, transport = lab_transport
    fake.add_device("pump_1", "pump")
    fake.unreachable.add("pump_1")
    import pytest

    with pytest.raises(errors.DeviceUnreachableError):
        await transport.command("pump_1", "status")
