"""Typed for_each: `vars` declarations + typed `in` rows (design 2026-07-20 §4)."""

import pytest

from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.expand import expand_dict


def _wf(for_each_body):
    return {"schema_version": 3, "blocks": [{"for_each": for_each_body}]}


def test_typed_rows_bind_each_cell_by_declared_kind():
    out = expand_dict(_wf({
        "vars": [{"name": "tube", "kind": "int"},
                 {"name": "meter", "kind": "role", "device_type": "densitometer"},
                 {"name": "od", "kind": "stream"}],
        "in": [{"tube": 1, "meter": "od_meter_1", "od": "od_1"},
               {"tube": 2, "meter": "od_meter_2", "od": "od_2"}],
        "body": [{"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"}},
                 {"command": {"device": "valve_1", "verb": "set_position",
                              "params": {"position": "{tube}"}}}],
    }))
    ms = [b for b in out["blocks"] if "measure" in b]
    cs = [b for b in out["blocks"] if "command" in b]
    assert [m["measure"]["device"] for m in ms] == ["od_meter_1", "od_meter_2"]
    assert [m["measure"]["into"] for m in ms] == ["od_1", "od_2"]
    assert [c["command"]["params"]["position"] for c in cs] == [1, 2]  # typed, not "1"


def test_scalar_var_shorthand_is_rejected():
    with pytest.raises(WorkflowLoadError, match="shorthand was removed"):
        expand_dict(_wf({"var": "t", "in": [1, 2],
                         "body": [{"wait": {"duration": "{t}s"}}]}))


def test_scalar_in_items_are_rejected():
    with pytest.raises(WorkflowLoadError, match="row 0 must be an object"):
        expand_dict(_wf({"vars": [{"name": "t", "kind": "int"}], "in": [1, 2],
                         "body": [{"wait": {"duration": "{t}s"}}]}))


def test_row_missing_a_declared_var_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="row 1: missing 'od' \\(kind 'stream'\\)"):
        expand_dict(_wf({
            "vars": [{"name": "tube", "kind": "int"}, {"name": "od", "kind": "stream"}],
            "in": [{"tube": 1, "od": "od_1"}, {"tube": 2}],
            "body": [{"record": {"into": "{od}", "value": "{tube}"}}],
        }))


def test_row_with_an_extra_key_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="row 0: unknown name 'port'"):
        expand_dict(_wf({
            "vars": [{"name": "tube", "kind": "int"}],
            "in": [{"tube": 1, "port": 5}],
            "body": [{"wait": {"duration": "{tube}s"}}],
        }))


def test_cell_of_the_wrong_json_type_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="row 1: 'tube' expects kind 'int', got '2'"):
        expand_dict(_wf({
            "vars": [{"name": "tube", "kind": "int"}],
            "in": [{"tube": 1}, {"tube": "2"}],
            "body": [{"wait": {"duration": "{tube}s"}}],
        }))


def test_reference_cell_may_not_be_glued_to_identifier_text_in_the_body():
    with pytest.raises(WorkflowLoadError, match="whole identifier"):
        expand_dict(_wf({
            "vars": [{"name": "od", "kind": "stream"}],
            "in": [{"od": "od_1"}],
            "body": [{"record": {"into": "{od}_raw", "value": "1"}}],
        }))


def test_vars_must_be_a_list_of_declarations():
    with pytest.raises(WorkflowLoadError, match="for_each 'vars' must be a list"):
        expand_dict(_wf({"vars": {"tube": "int"}, "in": [{"tube": 1}],
                         "body": [{"wait": {"duration": "1s"}}]}))


def test_an_unknown_kind_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="needs a 'name' and a valid 'kind'"):
        expand_dict(_wf({"vars": [{"name": "t", "kind": "integer"}], "in": [{"t": 1}],
                         "body": [{"wait": {"duration": "{t}s"}}]}))


def test_empty_in_is_still_rejected():
    with pytest.raises(WorkflowLoadError, match="'in' must be a non-empty list"):
        expand_dict(_wf({"vars": [{"name": "t", "kind": "int"}], "in": [],
                         "body": [{"wait": {"duration": "{t}s"}}]}))


def test_a_role_var_without_device_type_is_a_load_error():
    # expand_dict runs on raw JSON before workflow_from_dict, and had its own tolerant
    # _decls reader that checked 'name'/'kind' but never 'device_type' -- so a role decl
    # missing it silently passed expand_dict while serialize._param_decls (used by
    # workflow_from_dict on the very same document) already rejects it. Closes that gap.
    with pytest.raises(WorkflowLoadError, match="kind 'role' requires 'device_type'"):
        expand_dict(_wf({"vars": [{"name": "meter", "kind": "role"}],
                         "in": [{"meter": "densitometer_1"}],
                         "body": [{"wait": {"duration": "1s"}}]}))


def test_a_non_role_var_with_device_type_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="'device_type' is only allowed on kind 'role'"):
        expand_dict(_wf({
            "vars": [{"name": "t", "kind": "int", "device_type": "pump"}],
            "in": [{"t": 1}],
            "body": [{"wait": {"duration": "{t}s"}}],
        }))
