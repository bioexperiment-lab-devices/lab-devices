import lab_devices


def test_top_level_exports():
    for name in [
        "LabClient",
        "Pump",
        "Valve",
        "Densitometer",
        "Device",
        "Job",
        "PumpJob",
        "LabError",
        "LabDevicesError",
        "DeviceUnreachableError",
        "BusyError",
        "NotCalibratedError",
        "DeviceInfo",
        "DispenseResult",
        "MeasureResult",
        "ValveMoveResult",
    ]:
        assert hasattr(lab_devices, name), f"missing export: {name}"


def test_registry_not_top_level_but_importable():
    assert not hasattr(lab_devices, "LabRegistry")
    from lab_devices.discovery import LabRegistry  # noqa: F401


def test_all_is_sorted_and_complete():
    assert lab_devices.__all__ == sorted(lab_devices.__all__)
