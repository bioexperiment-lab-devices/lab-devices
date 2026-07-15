import pytest

from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.expand import expand_dict


def _wf(blocks, groups=None):
    d = {"schema_version": 1, "blocks": blocks}
    if groups is not None:
        d["groups"] = groups
    return d


def test_for_each_scalar_splices_into_serial():
    out = expand_dict(_wf([
        {"serial": {"children": [
            {"for_each": {"var": "t", "in": [1, 2, 3],
                          "body": [{"wait": {"duration": "{t}s"}}]}}
        ]}}
    ]))
    kids = out["blocks"][0]["serial"]["children"]
    assert [k["wait"]["duration"] for k in kids] == ["1s", "2s", "3s"]


def test_for_each_in_parallel_yields_lanes():
    out = expand_dict(_wf([
        {"parallel": {"children": [
            {"for_each": {"var": "t", "in": [1, 2],
                          "body": [{"measure": {"device": "densitometer_{t}",
                                                "verb": "measure", "into": "od_{t}"}}]}}
        ]}}
    ]))
    lanes = out["blocks"][0]["parallel"]["children"]
    assert [lane["measure"]["device"] for lane in lanes] == ["densitometer_1", "densitometer_2"]
    assert [lane["measure"]["into"] for lane in lanes] == ["od_1", "od_2"]


def test_object_items_multi_field():
    out = expand_dict(_wf([
        {"for_each": {"in": [{"t": 1, "p": 7}, {"t": 2, "p": 8}],
                      "body": [{"command": {"device": "valve_{t}", "verb": "set_position",
                                            "params": {"position": "{p}"}}}]}}
    ]))
    cmds = out["blocks"]
    assert cmds[0]["command"]["device"] == "valve_1"
    assert cmds[0]["command"]["params"]["position"] == "7"
    assert cmds[1]["command"]["device"] == "valve_2"


def test_parametrized_group_ref_inlines_as_serial_carrying_on_error():
    out = expand_dict(_wf(
        [{"group_ref": {"name": "svc", "args": {"t": 2}}, "on_error": "continue"}],
        groups={"svc": {"params": ["t"],
                        "body": [{"measure": {"device": "densitometer_{t}",
                                              "verb": "measure", "into": "od_{t}"}}]}},
    ))
    wrap = out["blocks"][0]
    assert wrap["on_error"] == "continue"
    assert wrap["serial"]["children"][0]["measure"]["device"] == "densitometer_2"
    assert "groups" not in out  # parametrized group dropped after inlining


def test_plain_group_ref_left_as_node_and_group_kept():
    out = expand_dict(_wf(
        [{"group_ref": {"name": "setup"}}],
        groups={"setup": {"body": [{"wait": {"duration": "1s"}}]}},
    ))
    assert out["blocks"][0] == {"group_ref": {"name": "setup"}}
    assert out["groups"] == {"setup": {"body": [{"wait": {"duration": "1s"}}]}}


def test_for_each_over_group_ref_composition():
    out = expand_dict(_wf(
        [{"for_each": {"var": "t", "in": [1, 2, 3],
                       "body": [{"group_ref": {"name": "svc", "args": {"t": "{t}"}}}]}}],
        groups={"svc": {"params": ["t"],
                        "body": [{"measure": {"device": "densitometer_{t}",
                                              "verb": "measure", "into": "od_{t}"}}]}},
    ))
    devs = [b["serial"]["children"][0]["measure"]["device"] for b in out["blocks"]]
    assert devs == ["densitometer_1", "densitometer_2", "densitometer_3"]


def test_unbound_hole_raises():
    with pytest.raises(WorkflowLoadError, match="hole"):
        expand_dict(_wf([{"for_each": {"var": "t", "in": [1],
                                       "body": [{"wait": {"duration": "{nope}s"}}]}}]))


def test_arity_mismatch_raises():
    with pytest.raises(WorkflowLoadError, match="must match params"):
        expand_dict(_wf([{"group_ref": {"name": "svc", "args": {"x": 1}}}],
                        groups={"svc": {"params": ["t"], "body": []}}))


def test_var_with_object_items_raises():
    with pytest.raises(WorkflowLoadError, match="scalar items"):
        expand_dict(_wf([{"for_each": {"var": "t", "in": [{"t": 1}],
                                       "body": [{"wait": {"duration": "1s"}}]}}]))


def test_forbidden_block_key_on_for_each_raises():
    with pytest.raises(WorkflowLoadError, match="block-level"):
        expand_dict(_wf([{"for_each": {"var": "t", "in": [1],
                                       "body": [{"wait": {"duration": "1s"}}]},
                          "on_error": "continue"}]))


def test_expansion_cap_trips():
    with pytest.raises(WorkflowLoadError, match="exceeds"):
        expand_dict(_wf([{"for_each": {
            "var": "a", "in": list(range(200)),
            "body": [{"for_each": {"var": "b", "in": list(range(200)),
                                   "body": [{"wait": {"duration": "1s"}}]}}]}}]))


def test_parametrized_group_body_may_contain_for_each():
    inner_cmd = {"command": {"device": "valve_{valve}", "verb": "set_position",
                              "params": {"position": "{valve}", "ml": "{volume}"}}}
    out = expand_dict(_wf(
        [{"group_ref": {"name": "dose", "args": {"volume": 5}}}],
        groups={"dose": {"params": ["volume"],
                         "body": [{"for_each": {"var": "valve", "in": [1, 2],
                                                 "body": [inner_cmd]}}]}},
    ))
    cmds = out["blocks"][0]["serial"]["children"]
    assert [c["command"]["device"] for c in cmds] == ["valve_1", "valve_2"]
    assert [c["command"]["params"]["position"] for c in cmds] == ["1", "2"]
    assert [c["command"]["params"]["ml"] for c in cmds] == ["5", "5"]


def test_residual_hole_after_expansion_raises():
    with pytest.raises(WorkflowLoadError, match="unbound hole"):
        expand_dict(_wf([{"for_each": {"var": "t", "in": [1],
                          "body": [{"wait": {"duration": "{nope}s"}}]}}]))
