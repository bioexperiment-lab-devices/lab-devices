"""Unit checking at the validator: opaque-symbolic units, unitless adaptation in operators,
exact-on-assignment records, and the `as` cast. See design 2026-07-21 §3.1, §3.2, §5;
Engine B plan Task 3."""

from __future__ import annotations

import pytest

from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate

_METER = {"densitometer_1": {"type": "densitometer"}}
_MEASURE = {"measure": {"device": "densitometer_1", "verb": "measure", "into": "od"}}
_BLANK = {"measure": {"device": "densitometer_1", "verb": "measure_blank", "into": "bl"}}


def _doc(blocks, streams):
    return {"schema_version": 3, "roles": _METER, "streams": streams, "blocks": blocks}


def _validate(doc):
    validate(workflow_from_dict(doc))


def _diagnostics(doc):
    with pytest.raises(ValidationError) as exc:
        _validate(doc)
    return exc.value.diagnostics


def test_record_into_wrong_unit_stream_is_rejected():
    doc = _doc(
        [_MEASURE, {"record": {"into": "slope", "value": "mean(od)"}}],  # AU into AU/s
        {"od": {"units": "AU"}, "slope": {"units": "AU/s"}},
    )
    assert any(d.category == "units" for d in _diagnostics(doc))


def test_record_into_matching_unit_stream_is_clean():
    _validate(_doc(
        [_MEASURE, {"record": {"into": "od2", "value": "mean(od)"}}],  # AU into AU
        {"od": {"units": "AU"}, "od2": {"units": "AU"}},
    ))


def test_adding_two_different_units_is_rejected():
    doc = _doc(
        [_MEASURE, _BLANK, {"branch": {"if": "mean(od) + mean(bl) > 1", "then": []}}],
        {"od": {"units": "AU"}, "bl": {"units": "AU/s"}},
    )
    assert any(d.category == "units" for d in _diagnostics(doc))


def test_bare_literal_threshold_adapts_and_is_clean():
    # `last(od) > 0.15`: the bare 0.15 adapts to AU (design §3.2) — no unit error.
    _validate(_doc(
        [_MEASURE, {"branch": {"if": "last(od) > 0.15", "then": []}}],
        {"od": {"units": "AU"}},
    ))


def test_as_cast_bridges_a_derived_unitless_into_a_dimensioned_stream():
    # `24 * mean(od) / last(od)` derives unitless; `as: per_hour` asserts it for the stream.
    _validate(_doc(
        [_MEASURE, {"record": {"into": "rate", "value": "24 * mean(od) / last(od)",
                               "as": "per_hour"}}],
        {"od": {"units": "AU"}, "rate": {"units": "per_hour"}},
    ))


def test_as_cast_that_disagrees_with_the_stream_is_rejected():
    doc = _doc(
        [_MEASURE, {"record": {"into": "rate", "value": "mean(od)", "as": "AU"}}],  # AU != per_hour
        {"od": {"units": "AU"}, "rate": {"units": "per_hour"}},
    )
    assert any(d.category == "units" for d in _diagnostics(doc))
