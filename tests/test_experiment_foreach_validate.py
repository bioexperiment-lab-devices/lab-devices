import pytest

from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate


def _validate(doc):
    validate(workflow_from_dict(doc))


def _messages(exc):
    return [d.message for d in exc.value.diagnostics]


_GROUP_OD = {"svc": {"params": [{"name": "t", "kind": "int"}], "body": [
    {"measure": {"device": "densitometer_{t}", "verb": "measure", "into": "od_{t}"}}]}}


def test_for_each_of_reads_over_distinct_devices_is_clean():
    _validate({
        "schema_version": 3,
        "roles": {f"densitometer_{i}": {"type": "densitometer"} for i in (1, 2, 3)},
        "streams": {"od_1": {"units": "unitless"}, "od_2": {"units": "unitless"}, "od_3": {"units": "unitless"}},
        "blocks": [{"parallel": {"children": [
            {"for_each": {"vars": [{"name": "t", "kind": "int"}],
                          "in": [{"t": 1}, {"t": 2}, {"t": 3}],
                          "body": [{"measure": {"device": "densitometer_{t}",
                                                "verb": "measure", "into": "od_{t}"}}]}}]}}],
    })


def test_for_each_of_reads_over_one_shared_device_is_affinity_error():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 3,
            "roles": {"densitometer_1": {"type": "densitometer"}},
            "streams": {"od_1": {"units": "unitless"}},
            "blocks": [{"parallel": {"children": [
                {"for_each": {"vars": [{"name": "t", "kind": "int"}],
                              "in": [{"t": 1}, {"t": 2}],
                              "body": [{"measure": {"device": "densitometer_1",
                                                    "verb": "measure", "into": "od_1"}}]}}]}}],
        })
    assert any("both command device" in m for m in _messages(exc))


def test_for_each_seeded_accumulator_is_clean():
    _validate({
        "schema_version": 3,
        "streams": {},
        "blocks": [
            {"for_each": {"vars": [{"name": "t", "kind": "int"}],
                          "in": [{"t": 1}, {"t": 2}],
                          "body": [{"compute": {"into": "c_{t}", "value": "0"}}]}},
            {"loop": {"count": 2, "body": [
                {"for_each": {"vars": [{"name": "t", "kind": "int"}],
                              "in": [{"t": 1}, {"t": 2}],
                              "body": [{"compute": {"into": "c_{t}",
                                                    "value": "c_{t} * 0.9"}}]}}]}},
        ],
    })


def test_for_each_unseeded_accumulator_is_read_before_write():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 3,
            "blocks": [{"loop": {"count": 2, "body": [
                {"for_each": {"vars": [{"name": "t", "kind": "int"}],
                              "in": [{"t": 1}, {"t": 2}],
                              "body": [{"compute": {"into": "c_{t}",
                                                    "value": "c_{t} * 0.9"}}]}}]}}],
        })
    assert any("read before it is written" in m for m in _messages(exc))


def test_group_arity_mismatch_is_diagnosed():
    # Reported per-param, not as a set-difference message (design 2026-07-20 §2.4):
    # 'x' is missing 't' AND supplies an unrelated 'x'.
    with pytest.raises(ValidationError) as exc:
        _validate({"schema_version": 3, "streams": {"od_1": {"units": "unitless"}}, "groups": _GROUP_OD,
                   "blocks": [{"group_ref": {"name": "svc", "args": {"x": 1}}}]})
    msgs = _messages(exc)
    assert any("missing argument 't' (int)" in m for m in msgs)
    assert any("group_ref 'svc' has no parameter 'x'" in m for m in msgs)


def test_for_each_forbidden_block_key_is_diagnosed():
    with pytest.raises(ValidationError) as exc:
        _validate({"schema_version": 3,
                   "blocks": [{"for_each": {"vars": [{"name": "t", "kind": "int"}],
                                            "in": [{"t": 1}],
                                            "body": [{"wait": {"duration": "1s"}}]},
                               "on_error": "continue"}]})
    assert any("block-level" in m for m in _messages(exc))


def test_parametrized_group_expands_and_validates_streams():
    with pytest.raises(ValidationError) as exc:
        _validate({"schema_version": 3,
                   "roles": {f"densitometer_{i}": {"type": "densitometer"} for i in (1, 2)},
                   "groups": _GROUP_OD,  # od_{t} not declared
                   "blocks": [{"for_each": {"vars": [{"name": "t", "kind": "int"}],
                               "in": [{"t": 1}, {"t": 2}],
                               "body": [{"group_ref": {"name": "svc",
                                                       "args": {"t": "{t}"}}}]}}]})
    assert any("undeclared stream" in m for m in _messages(exc))


def test_recursive_parametrized_group_is_caught():
    with pytest.raises(ValidationError) as exc:
        _validate({"schema_version": 3,
                   "groups": {"a": {"params": [{"name": "t", "kind": "int"}],
                                    "body": [{"group_ref": {"name": "a", "args": {"t": "{t}"}}}]}},
                   "blocks": [{"group_ref": {"name": "a", "args": {"t": 1}}}]})
    assert any("recursive group" in m for m in _messages(exc))


def test_macro_doc_defaults_diagnostic_not_duplicated():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 3,
            "defaults": {"retry": {"attempts": 3, "allow_repeat": True}},
            "blocks": [{"for_each": {"vars": [{"name": "t", "kind": "int"}],
                        "in": [{"t": 1}],
                        "body": [{"wait": {"duration": "1s"}}]}}],
        })
    hits = [m for m in _messages(exc) if "allow_repeat" in m]
    assert len(hits) == 1, hits
