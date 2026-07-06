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


# ---- Regression tests for Fix 1 & 2 ---- #
async def test_identify_unknown_device(lab_transport):
    """Identify on an unknown device (never registered) raises UnknownDeviceError at 404."""
    import pytest
    from lab_devices import errors

    fake, transport = lab_transport
    # Never register this device
    with pytest.raises(errors.UnknownDeviceError):
        await transport.command("unknown_pump", "identify")


async def test_identify_registered_unreachable_device(lab_transport):
    """Identify on a registered device with identify block in unreachable still returns 200."""
    fake, transport = lab_transport
    # Register with identify block
    fake.add_device(
        "pump_1",
        "pump",
        identify={"device_type": "pump", "model": "test-model", "serial": "12345"},
    )
    # Place in unreachable
    fake.unreachable.add("pump_1")
    # Identify should still work (memory-served)
    result = await transport.command("pump_1", "identify")
    assert result["serial"] == "12345"
    assert result["model"] == "test-model"


async def test_get_devices_shows_unreachable_as_disconnected(lab_transport):
    """get_devices() reports connected: false for unreachable devices, true otherwise."""
    fake, transport = lab_transport
    fake.add_device("pump_1", "pump")
    fake.add_device("pump_2", "pump")
    fake.unreachable.add("pump_2")

    body = await transport.get_devices()
    devices = {d["id"]: d for d in body["devices"]}

    assert devices["pump_1"]["connected"] is True
    assert devices["pump_2"]["connected"] is False
