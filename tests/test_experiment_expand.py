import pytest

from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.expand import _substitute, expand_dict


def _wf(blocks, groups=None):
    d = {"schema_version": 2, "blocks": blocks}
    if groups is not None:
        d["groups"] = groups
    return d


def test_whole_string_value_hole_substitutes_a_typed_json_value():
    env = {"tube": ("int", 1), "gain": ("number", 2.5), "on": ("bool", True),
           "tag": ("string", "a")}
    node = {"position": "{tube}", "gain": "{gain}", "on": "{on}", "tag": "{tag}"}
    assert _substitute(node, env) == {"position": 1, "gain": 2.5, "on": True, "tag": "a"}


def test_whole_string_reference_hole_substitutes_the_name_string():
    env = {"od": ("stream", "od_1"), "meter": ("role", "od_meter_1"),
           "c": ("binding", "tube_1_c")}
    node = {"into": "{od}", "device": "{meter}", "value": "{c}"}
    assert _substitute(node, env) == {"into": "od_1", "device": "od_meter_1",
                                      "value": "tube_1_c"}


def test_embedded_value_hole_stringifies_via_fmt():
    env = {"tube": ("int", 2), "gain": ("number", 3.0), "on": ("bool", False)}
    node = ["tube {tube}: service", "g={gain}", "flag={on}", "{tube}{tube}"]
    assert _substitute(node, env) == ["tube 2: service", "g=3", "flag=false", "22"]


def test_reference_hole_glued_to_identifier_text_is_a_load_error():
    env = {"od": ("stream", "od_1")}
    for glued in ("od_{od}", "{od}_raw"):
        with pytest.raises(WorkflowLoadError, match="whole identifier"):
            _substitute({"into": glued}, env)


def test_reference_hole_inside_an_expression_is_legal():
    # The rule forbids CONCATENATION, not embedding: a stream reference legitimately sits
    # inside a larger expression string, which is where most of them live (design §3).
    env = {"od": ("stream", "od_1")}
    node = {"value": "count({od}, last=11min) > 0 and mean({od}, last=11min) > 2.0"}
    assert _substitute(node, env) == {
        "value": "count(od_1, last=11min) > 0 and mean(od_1, last=11min) > 2.0"
    }


def test_hole_absent_from_the_env_passes_through_untouched():
    # Increment 7 order-independence: an outer for_each/args pass, or the residual-hole
    # scan, owns this hole -- substitution must not consume or reject it.
    env = {"tube": ("int", 1)}
    assert _substitute({"into": "{od}", "d": "x_{tube}_{other}"}, env) == {
        "into": "{od}", "d": "x_1_{other}"}


def test_group_args_are_bound_by_declared_kind():
    out = expand_dict(_wf(
        [{"group_ref": {"name": "svc",
                        "args": {"tube": 3, "od": "od_3", "label": "left"}}}],
        groups={"svc": {"params": [{"name": "tube", "kind": "int"},
                                   {"name": "od", "kind": "stream"},
                                   {"name": "label", "kind": "string"}],
                        "body": [{"command": {"device": "valve_1", "verb": "set_position",
                                              "params": {"position": "{tube}"},
                                              }, "label": "{label} {tube}"},
                                 {"record": {"into": "{od}", "value": "1"}}]}},
    ))
    kids = out["blocks"][0]["serial"]["children"]
    assert kids[0]["command"]["params"]["position"] == 3   # int, not "3"
    assert kids[0]["label"] == "left 3"
    assert kids[1]["record"]["into"] == "od_3"


def test_group_arg_of_the_wrong_json_type_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="expects kind 'int'"):
        expand_dict(_wf([{"group_ref": {"name": "svc", "args": {"tube": "two"}}}],
                        groups={"svc": {"params": [{"name": "tube", "kind": "int"}],
                                        "body": []}}))


def test_group_arg_bool_is_not_an_int():
    with pytest.raises(WorkflowLoadError, match="expects kind 'int'"):
        expand_dict(_wf([{"group_ref": {"name": "svc", "args": {"tube": True}}}],
                        groups={"svc": {"params": [{"name": "tube", "kind": "int"}],
                                        "body": []}}))


def test_missing_group_arg_is_reported_per_param():
    with pytest.raises(WorkflowLoadError, match="missing 'od' \\(kind 'stream'\\)"):
        expand_dict(_wf([{"group_ref": {"name": "svc", "args": {"tube": 1}}}],
                        groups={"svc": {"params": [{"name": "tube", "kind": "int"},
                                                   {"name": "od", "kind": "stream"}],
                                        "body": []}}))


def test_extra_group_arg_is_reported_per_param():
    with pytest.raises(WorkflowLoadError, match="unknown name 'nope'"):
        expand_dict(_wf([{"group_ref": {"name": "svc", "args": {"tube": 1, "nope": 2}}}],
                        groups={"svc": {"params": [{"name": "tube", "kind": "int"}],
                                        "body": []}}))


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
    assert cmds[0]["command"]["params"]["position"] == 7  # typed value hole (design §3.1)
    assert cmds[1]["command"]["device"] == "valve_2"


def test_parametrized_group_ref_inlines_as_serial_carrying_on_error():
    out = expand_dict(_wf(
        [{"group_ref": {"name": "svc", "args": {"t": 2}}, "on_error": "continue"}],
        groups={"svc": {"params": [{"name": "t", "kind": "int"}],
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
        groups={"svc": {"params": [{"name": "t", "kind": "int"}],
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
    with pytest.raises(WorkflowLoadError, match="missing 't'"):
        expand_dict(_wf([{"group_ref": {"name": "svc", "args": {"x": 1}}}],
                        groups={"svc": {"params": [{"name": "t", "kind": "int"}],
                                        "body": []}}))


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
        groups={"dose": {"params": [{"name": "volume", "kind": "int"}],
                         "body": [{"for_each": {"var": "valve", "in": [1, 2],
                                                "body": [inner_cmd]}}]}},
    ))
    cmds = out["blocks"][0]["serial"]["children"]
    assert [c["command"]["device"] for c in cmds] == ["valve_1", "valve_2"]
    assert [c["command"]["params"]["position"] for c in cmds] == [1, 2]
    assert [c["command"]["params"]["ml"] for c in cmds] == [5, 5]


def test_residual_hole_after_expansion_raises():
    with pytest.raises(WorkflowLoadError, match="unbound hole"):
        expand_dict(_wf([{"for_each": {"var": "t", "in": [1],
                          "body": [{"wait": {"duration": "{nope}s"}}]}}]))
