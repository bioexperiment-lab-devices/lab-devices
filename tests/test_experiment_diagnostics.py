import pytest

from lab_devices.experiment.errors import Diagnostic, ExperimentError, ValidationError


def test_validation_error_taxonomy():
    assert issubclass(ValidationError, ExperimentError)


def test_diagnostic_str():
    d = Diagnostic("mode", "blocks[0].children[2]", "command inside open interval")
    assert str(d) == "[mode] blocks[0].children[2]: command inside open interval"


def test_diagnostic_is_frozen():
    d = Diagnostic("block", "blocks[0]", "msg")
    with pytest.raises(Exception):
        d.category = "other"


def test_validation_error_carries_diagnostics():
    d1 = Diagnostic("group", "blocks[0]", "unknown group 'x'")
    d2 = Diagnostic("data-flow", "blocks[1]", "binding 'y' may be read before it is written")
    err = ValidationError([d1, d2])
    assert err.diagnostics == (d1, d2)
    text = str(err)
    assert text.startswith("2 validation error(s):")
    assert "  - [group] blocks[0]: unknown group 'x'" in text
    assert "  - [data-flow] blocks[1]:" in text


def test_validation_error_single():
    err = ValidationError([Diagnostic("affinity", "blocks[3]", "overlap")])
    assert "1 validation error(s):" in str(err)
    assert len(err.diagnostics) == 1
