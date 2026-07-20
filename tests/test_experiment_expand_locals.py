"""Group locals: qualified naming, stream emission, init hoisting (design 2026-07-20 §2.2, §6)."""

import pytest

from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.expand import expand_dict


def _svc(locals_, body):
    return {"params": [{"name": "tube", "kind": "int"}], "locals": locals_, "body": body}


def test_locals_expand_to_qualified_names():
    out = expand_dict({
        "schema_version": 2,
        "groups": {"svc": _svc(
            {"c": {"kind": "binding"}, "c_series": {"kind": "stream", "units": "ug/mL"}},
            [{"compute": {"into": "{c}", "value": "1"}},
             {"record": {"into": "{c_series}", "value": "{c}"}}],
        )},
        "blocks": [{"group_ref": {"name": "svc", "as": "tube_1", "args": {"tube": 1}}}],
    })
    kids = out["blocks"][0]["serial"]["children"]
    assert kids[0]["compute"]["into"] == "tube_1_c"
    assert kids[1]["record"] == {"into": "tube_1_c_series", "value": "tube_1_c"}


def test_as_interpolates_from_the_call_site_env():
    out = expand_dict({
        "schema_version": 2,
        "groups": {"svc": _svc({"c": {"kind": "binding"}},
                               [{"compute": {"into": "{c}", "value": "{tube}"}}])},
        "blocks": [{"for_each": {"var": "t", "in": [1, 2], "body": [
            {"group_ref": {"name": "svc", "as": "tube_{t}", "args": {"tube": "{t}"}}}]}}],
    })
    intos = [b["serial"]["children"][0]["compute"]["into"] for b in out["blocks"]]
    assert intos == ["tube_1_c", "tube_2_c"]


def test_stream_locals_emit_stream_declarations():
    out = expand_dict({
        "schema_version": 2,
        "groups": {"svc": _svc(
            {"c_series": {"kind": "stream", "units": "ug/mL"},
             "r_series": {"kind": "stream", "units": "1/h", "persistence": "disk"}},
            [{"record": {"into": "{c_series}", "value": "1"}}],
        )},
        "blocks": [{"group_ref": {"name": "svc", "as": "t1", "args": {"tube": 1}}}],
    })
    assert out["streams"] == {"t1_c_series": {"units": "ug/mL"},
                              "t1_r_series": {"units": "1/h", "persistence": "disk"}}


def test_init_seeds_hoist_to_the_front_of_blocks_in_expansion_order():
    out = expand_dict({
        "schema_version": 2,
        "groups": {"svc": _svc(
            {"c": {"kind": "binding", "init": "0"},
             "contaminated": {"kind": "binding", "init": "false"},
             "r": {"kind": "binding"}},
            [{"compute": {"into": "{r}", "value": "{c} + {tube}"}}],
        )},
        "blocks": [{"for_each": {"var": "t", "in": [1, 2], "body": [
            {"group_ref": {"name": "svc", "as": "tube_{t}", "args": {"tube": "{t}"}}}]}}],
    })
    seeds = [b["compute"] for b in out["blocks"][:4]]
    assert seeds == [
        {"into": "tube_1_c", "value": "0"},
        {"into": "tube_1_contaminated", "value": "false"},
        {"into": "tube_2_c", "value": "0"},
        {"into": "tube_2_contaminated", "value": "false"},
    ]
    # `r` has no init, so it is declared-only -- no seed for it.
    assert len(out["blocks"]) == 6
    assert out["blocks"][4]["serial"]["children"][0]["compute"]["into"] == "tube_1_r"


def test_as_is_required_when_the_group_declares_locals():
    with pytest.raises(WorkflowLoadError, match="'as' is required"):
        expand_dict({
            "schema_version": 2,
            "groups": {"svc": _svc({"c": {"kind": "binding"}},
                                   [{"compute": {"into": "{c}", "value": "1"}}])},
            "blocks": [{"group_ref": {"name": "svc", "args": {"tube": 1}}}],
        })


def test_as_must_expand_to_an_identifier():
    with pytest.raises(WorkflowLoadError, match="must expand to an identifier"):
        expand_dict({
            "schema_version": 2,
            "groups": {"svc": _svc({"c": {"kind": "binding"}},
                                   [{"compute": {"into": "{c}", "value": "1"}}])},
            "blocks": [{"group_ref": {"name": "svc", "as": "tube 1", "args": {"tube": 1}}}],
        })


def test_a_bare_value_hole_as_is_not_an_identifier():
    # "{tube}" with tube: int substitutes to the JSON integer 1, which is not a name.
    with pytest.raises(WorkflowLoadError, match="must expand to an identifier"):
        expand_dict({
            "schema_version": 2,
            "groups": {"svc": _svc({"c": {"kind": "binding"}},
                                   [{"compute": {"into": "{c}", "value": "1"}}])},
            "blocks": [{"for_each": {"var": "t", "in": [1], "body": [
                {"group_ref": {"name": "svc", "as": "{t}", "args": {"tube": "{t}"}}}]}}],
        })


def test_duplicate_qualified_instance_name_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="duplicate instance name 'tube_1'"):
        expand_dict({
            "schema_version": 2,
            "groups": {"svc": _svc({"c": {"kind": "binding"}},
                                   [{"compute": {"into": "{c}", "value": "1"}}])},
            "blocks": [
                {"group_ref": {"name": "svc", "as": "tube_1", "args": {"tube": 1}}},
                {"group_ref": {"name": "svc", "as": "tube_1", "args": {"tube": 2}}},
            ],
        })


def test_a_local_kind_other_than_stream_or_binding_is_rejected():
    with pytest.raises(WorkflowLoadError, match="must be 'stream' or 'binding'"):
        expand_dict({
            "schema_version": 2,
            "groups": {"svc": _svc({"c": {"kind": "int"}},
                                   [{"compute": {"into": "{c}", "value": "1"}}])},
            "blocks": [{"group_ref": {"name": "svc", "as": "t1", "args": {"tube": 1}}}],
        })


def test_init_expression_is_substituted_against_the_call_site_args():
    # A value-kind param hole is still a constant after substitution (design §2.3), so
    # `init: "{tube}"` must seed the call-site value, not die on an unbound hole.
    out = expand_dict({
        "schema_version": 2,
        "groups": {"svc": _svc({"c": {"kind": "binding", "init": "{tube}"}},
                               [{"compute": {"into": "{c}", "value": "1"}}])},
        "blocks": [{"group_ref": {"name": "svc", "as": "t1", "args": {"tube": 7}}}],
    })
    assert out["blocks"][0]["compute"] == {"into": "t1_c", "value": "7"}


def test_binding_locals_across_instances_can_collide_on_qualified_name():
    # as="a" + local "b_c" and as="a_b" + local "c" both qualify to "a_b_c" -- exactly the
    # silent-merge outcome the duplicate-`as` rule exists to prevent (design 2026-07-20 §6).
    group = {
        "params": [],
        "locals": {"b_c": {"kind": "binding"}, "c": {"kind": "binding"}},
        "body": [{"compute": {"into": "{b_c}", "value": "1"}},
                 {"compute": {"into": "{c}", "value": "1"}}],
    }
    with pytest.raises(WorkflowLoadError, match="already emitted"):
        expand_dict({
            "schema_version": 2,
            "groups": {"svc": group},
            "blocks": [
                {"group_ref": {"name": "svc", "as": "a", "args": {}}},
                {"group_ref": {"name": "svc", "as": "a_b", "args": {}}},
            ],
        })


def test_an_escaping_local_is_readable_from_a_top_level_expression():
    # examples/morbidostat.json gates a top-level abort on per-tube latches (design §2.2).
    out = expand_dict({
        "schema_version": 2,
        "groups": {"svc": _svc({"contaminated": {"kind": "binding", "init": "false"}},
                               [{"compute": {"into": "{contaminated}", "value": "true"}}])},
        "blocks": [
            {"for_each": {"var": "t", "in": [1, 2], "body": [
                {"group_ref": {"name": "svc", "as": "tube_{t}", "args": {"tube": "{t}"}}}]}},
            {"abort": {"if": "tube_1_contaminated and tube_2_contaminated", "message": "x"}},
        ],
    })
    assert out["blocks"][-1]["abort"]["if"] == "tube_1_contaminated and tube_2_contaminated"
    assert [b["compute"]["into"] for b in out["blocks"][:2]] == [
        "tube_1_contaminated", "tube_2_contaminated"]
