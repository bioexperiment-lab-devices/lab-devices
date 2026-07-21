"""The opaque unit type, parser, renderer, and algebra. See design 2026-07-21 §5,
Engine B plan Task 1."""

from __future__ import annotations

import pytest

from lab_devices.experiment.errors import UnitError
from lab_devices.experiment.units import (
    UNITLESS,
    parse_unit,
    unit_div,
    unit_mul,
    unit_str,
)


def test_parse_simple_and_empty() -> None:
    assert parse_unit("AU") == (("AU", 1),)
    assert parse_unit("per_hour") == (("per_hour", 1),)
    assert parse_unit("x_MIC") == (("x_MIC", 1),)
    assert parse_unit("") == UNITLESS
    assert parse_unit(None) == UNITLESS
    assert parse_unit("unitless") == UNITLESS


def test_parse_quotient_and_product() -> None:
    assert parse_unit("AU/s") == (("AU", 1), ("s", -1))
    assert parse_unit("ml/min") == (("min", -1), ("ml", 1))  # canonical: sorted by symbol
    assert parse_unit("a*b") == (("a", 1), ("b", 1))
    assert parse_unit("a/b/c") == (("a", 1), ("b", -1), ("c", -1))  # a/(b*c)


def test_parse_exponents_and_cancellation() -> None:
    assert parse_unit("m^2") == (("m", 2),)
    assert parse_unit("m^2/m") == (("m", 1),)  # cancels to m^1


def test_parse_rejects_garbage() -> None:
    for bad in ("2AU", "AU//s", "AU^", "AU^x", "/s"):
        with pytest.raises(UnitError):
            parse_unit(bad)


def test_algebra() -> None:
    au, s = parse_unit("AU"), parse_unit("s")
    assert unit_mul(au, s) == parse_unit("AU*s")
    assert unit_div(au, s) == parse_unit("AU/s")
    assert unit_div(au, au) == UNITLESS
    assert unit_mul(au, UNITLESS) == au


def test_render_round_trips() -> None:
    for text in ("AU", "AU/s", "per_hour", "x_MIC", "ml/min"):
        assert parse_unit(unit_str(parse_unit(text))) == parse_unit(text)
    assert unit_str(UNITLESS) == "unitless"
    assert unit_str(parse_unit("AU/s")) == "AU/s"
    assert unit_str(parse_unit("1/s")) == "1/s"
