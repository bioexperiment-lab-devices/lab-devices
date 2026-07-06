from lab_devices.models import DeviceInfo, Identify, PingResult, RawModel


def test_from_raw_keeps_unknown_fields():
    info = PingResult.from_raw({"uptime_ms": 42, "surprise_field": "kept"})
    assert info.uptime_ms == 42
    assert info.raw["surprise_field"] == "kept"


def test_missing_fields_default_to_none():
    info = PingResult.from_raw({})
    assert info.uptime_ms is None


def test_none_input_is_safe():
    info = PingResult.from_raw(None)
    assert info.uptime_ms is None
    assert info.raw == {}


def test_nested_identify_parsed():
    info = DeviceInfo.from_raw(
        {
            "id": "pump_1",
            "type": "pump",
            "port": "COM3",
            "connected": True,
            "identify": {"device_type": "pump", "model": "peristaltic-1ch"},
        }
    )
    assert info.id == "pump_1"
    assert isinstance(info.identify, Identify)
    assert info.identify.model == "peristaltic-1ch"


def test_nested_null_stays_none():
    info = DeviceInfo.from_raw(
        {"id": "valve_1", "type": "valve", "port": "COM7", "connected": False, "identify": None}
    )
    assert info.identify is None


def test_rawmodel_is_base():
    assert issubclass(DeviceInfo, RawModel)
