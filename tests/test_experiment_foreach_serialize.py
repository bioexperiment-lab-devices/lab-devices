import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.serialize import (
    block_from_dict, block_to_dict, workflow_from_dict, workflow_to_dict,
)


def _roundtrip_block(d):
    assert block_to_dict(block_from_dict(d)) == d


def test_for_each_scalar_shorthand_is_rejected():
    # The `var` + scalar `in` shorthand cannot carry a kind, so schema_version 2 removes it
    # rather than leave an untyped path alive next to the typed one (design 2026-07-20 §4).
    with pytest.raises(WorkflowLoadError, match="shorthand was removed"):
        block_from_dict({"for_each": {"var": "tube", "in": [1, 2, 3],
                                      "body": [{"wait": {"duration": "1s"}}]}})


def test_for_each_object_items_roundtrip():
    d = {"for_each": {"vars": [{"name": "tube", "kind": "int"}, {"name": "port", "kind": "int"}],
                      "in": [{"tube": 1, "port": 5}, {"tube": 2, "port": 6}],
                      "body": [{"wait": {"duration": "1s"}}]}}
    _roundtrip_block(d)
    block = block_from_dict(d)
    assert isinstance(block, B.ForEach)
    assert [p.name for p in block.vars] == ["tube", "port"]
    assert block.items == [{"tube": 1, "port": 5}, {"tube": 2, "port": 6}]


def test_for_each_label_roundtrips():
    d = {"for_each": {"vars": [{"name": "t", "kind": "int"}], "in": [{"t": 1}],
                      "body": [{"wait": {"duration": "1s"}}]},
         "label": "per tube"}
    _roundtrip_block(d)


def test_group_ref_args_roundtrips():
    d = {"group_ref": {"name": "service", "args": {"tube": "{t}"}}}
    _roundtrip_block(d)
    assert block_from_dict(d).args == {"tube": "{t}"}


def test_plain_group_ref_has_empty_args():
    d = {"group_ref": {"name": "setup"}}
    _roundtrip_block(d)
    assert block_from_dict(d).args == {}


def test_non_object_group_ref_body_raises_workflow_load_error():
    with pytest.raises(WorkflowLoadError, match="group_ref requires an object body"):
        block_from_dict({"group_ref": 42})


def test_group_params_roundtrip_in_workflow():
    doc = {"schema_version": 3,
           "groups": {"service": {"params": [{"name": "tube", "kind": "int"}],
                                  "body": [{"wait": {"duration": "1s"}}]}},
           "blocks": [{"group_ref": {"name": "service", "args": {"tube": 1}}}]}
    assert workflow_to_dict(workflow_from_dict(doc)) == {
        "schema_version": 3,
        "persistence": {"default": "in_memory", "format": "jsonl"},
        "groups": {"service": {"params": [{"name": "tube", "kind": "int"}],
                               "body": [{"wait": {"duration": "1s"}}]}},
        "blocks": [{"group_ref": {"name": "service", "args": {"tube": 1}}}],
    }
