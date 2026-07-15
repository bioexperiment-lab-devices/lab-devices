import pytest

from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate


def _validate(doc):
    validate(workflow_from_dict(doc))


def _messages(exc):
    return [d.message for d in exc.value.diagnostics]


_GROUP_OD = {"svc": {"params": ["t"], "body": [
    {"measure": {"device": "densitometer_{t}", "verb": "measure", "into": "od_{t}"}}]}}


def test_for_each_of_reads_over_distinct_devices_is_clean():
    _validate({
        "schema_version": 1,
        "streams": {"od_1": {}, "od_2": {}, "od_3": {}},
        "blocks": [{"parallel": {"children": [
            {"for_each": {"var": "t", "in": [1, 2, 3],
                          "body": [{"measure": {"device": "densitometer_{t}",
                                                "verb": "measure", "into": "od_{t}"}}]}}]}}],
    })


def test_for_each_of_reads_over_one_shared_device_is_affinity_error():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 1,
            "streams": {"od_1": {}},
            "blocks": [{"parallel": {"children": [
                {"for_each": {"var": "t", "in": [1, 2],
                              "body": [{"measure": {"device": "densitometer_1",
                                                    "verb": "measure", "into": "od_1"}}]}}]}}],
        })
    assert any("both command device" in m for m in _messages(exc))


def test_for_each_seeded_accumulator_is_clean():
    _validate({
        "schema_version": 1,
        "streams": {},
        "blocks": [
            {"for_each": {"var": "t", "in": [1, 2],
                          "body": [{"compute": {"into": "c_{t}", "value": "0"}}]}},
            {"loop": {"count": 2, "body": [
                {"for_each": {"var": "t", "in": [1, 2],
                              "body": [{"compute": {"into": "c_{t}",
                                                    "value": "c_{t} * 0.9"}}]}}]}},
        ],
    })


def test_for_each_unseeded_accumulator_is_read_before_write():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 1,
            "blocks": [{"loop": {"count": 2, "body": [
                {"for_each": {"var": "t", "in": [1, 2],
                              "body": [{"compute": {"into": "c_{t}",
                                                    "value": "c_{t} * 0.9"}}]}}]}}],
        })
    assert any("read before it is written" in m for m in _messages(exc))


def test_group_arity_mismatch_is_diagnosed():
    with pytest.raises(ValidationError) as exc:
        _validate({"schema_version": 1, "streams": {"od_1": {}}, "groups": _GROUP_OD,
                   "blocks": [{"group_ref": {"name": "svc", "args": {"x": 1}}}]})
    assert any("must match params" in m for m in _messages(exc))


def test_for_each_forbidden_block_key_is_diagnosed():
    with pytest.raises(ValidationError) as exc:
        _validate({"schema_version": 1,
                   "blocks": [{"for_each": {"var": "t", "in": [1],
                                            "body": [{"wait": {"duration": "1s"}}]},
                               "on_error": "continue"}]})
    assert any("block-level" in m for m in _messages(exc))


def test_parametrized_group_expands_and_validates_streams():
    with pytest.raises(ValidationError) as exc:
        _validate({"schema_version": 1, "groups": _GROUP_OD,  # od_{t} not declared
                   "blocks": [{"for_each": {"var": "t", "in": [1, 2],
                               "body": [{"group_ref": {"name": "svc",
                                                       "args": {"t": "{t}"}}}]}}]})
    assert any("undeclared stream" in m for m in _messages(exc))


def test_recursive_parametrized_group_is_caught():
    with pytest.raises(ValidationError) as exc:
        _validate({"schema_version": 1,
                   "groups": {"a": {"params": ["t"],
                                    "body": [{"group_ref": {"name": "a", "args": {"t": "{t}"}}}]}},
                   "blocks": [{"group_ref": {"name": "a", "args": {"t": 1}}}]})
    assert any("recursive group" in m for m in _messages(exc))
