import pytest

from lab_devices.experiment.errors import EvaluationError
from lab_devices.experiment.inputs import (
    InputRequest,
    UnattendedInputProvider,
    validate_input_value,
)
from lab_devices.experiment.runlog import InMemoryRunLog, RunEvent


def _req(**kw):
    base = dict(name="x", type="float", prompt=None, min=None, max=None,
                choices=None, block_id="blocks[0]")
    base.update(kw)
    return InputRequest(**base)


def test_in_memory_log_appends_in_order():
    log = InMemoryRunLog()
    e1 = RunEvent(0.0, "run_started")
    e2 = RunEvent(1.0, "block_started", "blocks[0]", {"n": 1})
    log.emit(e1)
    log.emit(e2)
    assert log.events == [e1, e2]
    assert log.events[1].data == {"n": 1}


async def test_unattended_provider_is_fail_safe():
    with pytest.raises(EvaluationError, match="no input provider"):
        await UnattendedInputProvider().request(_req())


def test_validate_float_accepts_int_rejects_bool():
    assert validate_input_value(_req(type="float"), 3) == 3
    assert validate_input_value(_req(type="float"), 3.5) == 3.5
    with pytest.raises(EvaluationError):
        validate_input_value(_req(type="float"), True)
    with pytest.raises(EvaluationError):
        validate_input_value(_req(type="float"), "3.5")


def test_validate_int_strict():
    assert validate_input_value(_req(type="int"), 4) == 4
    with pytest.raises(EvaluationError):
        validate_input_value(_req(type="int"), 4.0)  # providers return typed values
    with pytest.raises(EvaluationError):
        validate_input_value(_req(type="int"), True)


def test_validate_bounds():
    req = _req(type="float", min=0.0, max=2.0)
    assert validate_input_value(req, 1.5) == 1.5
    with pytest.raises(EvaluationError, match="below min"):
        validate_input_value(req, -0.1)
    with pytest.raises(EvaluationError, match="above max"):
        validate_input_value(req, 2.1)


def test_validate_enum_and_bool():
    req = _req(type="enum", choices=["a", "b"])
    assert validate_input_value(req, "a") == "a"
    with pytest.raises(EvaluationError):
        validate_input_value(req, "c")
    with pytest.raises(EvaluationError):
        validate_input_value(_req(type="bool"), 1)
    assert validate_input_value(_req(type="bool"), True) is True


def test_validate_unknown_type_fails_safe():
    with pytest.raises(EvaluationError, match="unsupported type"):
        validate_input_value(_req(type="voltage"), 1.0)
