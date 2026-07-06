from lab_devices import errors


def test_hierarchy_roots():
    assert issubclass(errors.LabError, errors.LabDevicesError)
    assert issubclass(errors.DiscoveryError, errors.LabDevicesError)
    assert issubclass(errors.BusyError, errors.LabError)


def test_map_known_code_to_subclass():
    err = errors.map_command_error(
        {"code": "busy", "message": "device busy", "details": {"job_id": "j-1"}},
        request_id="req-1",
    )
    assert isinstance(err, errors.BusyError)
    assert err.code == "busy"
    assert err.message == "device busy"
    assert err.request_id == "req-1"
    assert err.job_id == "j-1"


def test_map_unknown_code_degrades_to_base():
    err = errors.map_command_error(
        {"code": "some_future_code", "message": "hmm"}, request_id="req-2"
    )
    assert type(err) is errors.LabError
    assert err.code == "some_future_code"


def test_hardware_error_component():
    err = errors.map_command_error(
        {"code": "hardware_error", "message": "fault", "details": {"component": "motor"}},
        request_id="r",
    )
    assert isinstance(err, errors.HardwareError)
    assert err.component == "motor"


def test_unknown_lab_client_carries_names():
    err = errors.UnknownLabClient("nope", available=["a", "b"])
    assert err.name == "nope"
    assert err.available == ["a", "b"]
    assert "a" in str(err)
