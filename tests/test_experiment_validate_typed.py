import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate
from lab_devices.experiment.workflow import Group, LocalDecl, ParamDecl, RoleDecl, Workflow

# A role name encodes nothing: its type comes from the declaration and only from there
# (design 2026-07-20 5.2). "od_meter_1" and "medium_pump" are deliberately NOT of the form
# <device_type>_<n>, so the deleted rsplit("_", 1) bridge would have decoded them to the
# non-types 'od_meter' and 'medium'. The role-argument tests below use them for exactly
# that reason -- they cannot pass unless the type is read from the declaration.
DEFAULT_ROLES = {
    "densitometer_1": {"type": "densitometer"},
    "densitometer_2": {"type": "densitometer"},
    "pump_1": {"type": "pump"},
    "od_meter_1": {"type": "densitometer"},
    "medium_pump": {"type": "pump"},
}


def wf2(blocks, *, streams=None, groups=None, roles=None):
    return workflow_from_dict({
        "schema_version": 2,
        "roles": DEFAULT_ROLES if roles is None else roles,
        "streams": {name: {} for name in (streams or [])},
        "groups": groups or {},
        "blocks": blocks,
    })


def diags(workflow):
    with pytest.raises(ValidationError) as exc:
        validate(workflow)
    return exc.value.diagnostics


def messages(workflow):
    return [d.message for d in diags(workflow)]


STOP_PUMP = {"command": {"device": "pump_1", "verb": "stop"}}


def _svc(params, body=None):
    return {"svc": {"params": params, "body": body or [STOP_PUMP]}}


def test_group_ref_missing_arg_is_reported_per_param():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": 1}}}],
        groups=_svc([{"name": "tube", "kind": "int"},
                     {"name": "dose", "kind": "number"}]),
    )
    msgs = messages(w)
    assert any("missing argument 'dose' (number)" in m for m in msgs)
    assert not any("must match params" in m for m in msgs)


def test_group_ref_extra_arg_is_reported_per_arg():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": 1, "ghost": 2}}}],
        groups=_svc([{"name": "tube", "kind": "int"}]),
    )
    assert any("group_ref 'svc' has no parameter 'ghost'" in m for m in messages(w))


def test_group_ref_with_exact_args_is_clean():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": 1}}}],
        groups=_svc([{"name": "tube", "kind": "int"}]),
    )
    assert validate(w) is None


def test_for_each_block_level_fields_still_rejected():
    w = wf2([{"for_each": {"vars": [{"name": "t", "kind": "int"}],
                           "in": [{"t": 1}], "body": [STOP_PUMP]},
              "gap_after": "1s"}])
    assert any("may not carry block-level 'gap_after'" in m for m in messages(w))


def _fe(vars_, rows, body=None):
    return {"for_each": {"vars": vars_, "in": rows, "body": body or [STOP_PUMP]}}


def test_for_each_row_missing_a_declared_var():
    w = wf2([_fe([{"name": "t", "kind": "int"}, {"name": "d", "kind": "number"}],
                 [{"t": 1, "d": 0.5}, {"t": 2}])])
    assert any("'in' row 1 is missing 't'" not in m and "row 1 is missing 'd'" in m
               for m in messages(w))


def test_for_each_row_with_an_extra_key():
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1, "ghost": 9}])])
    assert any("'in' row 0 has no variable 'ghost'" in m for m in messages(w))


def test_for_each_row_must_be_an_object():
    # Unreachable via wf2/workflow_from_dict: serialize._for_each's _obj() already
    # rejects a non-dict row at PARSE time, so a JSON-authored doc can never carry one
    # this far. This is defense-in-depth for a ForEach built directly through the
    # Python API (the pattern _check_groups's `isinstance(b.name, str)` also guards
    # against), so it is exercised by constructing the AST directly.
    fe = B.ForEach(
        vars=[ParamDecl(name="t", kind="int")],
        items=[{"t": 1}, 2],  # type: ignore[list-item]
        body=[B.Command(device="pump_1", verb="stop")],
    )
    w = Workflow(schema_version=2, roles={"pump_1": RoleDecl(type="pump")}, blocks=[fe])
    assert any("'in' row 1 must be an object" in m for m in messages(w))


def test_for_each_rows_matching_the_declaration_are_clean():
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1}, {"t": 2}])])
    assert validate(w) is None


def test_for_each_vars_must_be_non_empty():
    w = wf2([_fe([], [{}])])
    d = diags(w)
    assert any(
        x.category == "for_each" and "for_each 'vars' must be non-empty" in x.message
        for x in d
    )


def test_int_param_rejects_a_float_literal():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": 1.5}}}],
        groups=_svc([{"name": "tube", "kind": "int"}]),
    )
    assert any("expected int for parameter 'tube', got 1.5" in m for m in messages(w))


def test_int_param_rejects_a_bool_literal():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": True}}}],
        groups=_svc([{"name": "tube", "kind": "int"}]),
    )
    assert any("expected int for parameter 'tube', got True" in m for m in messages(w))


def test_bool_param_rejects_an_int_literal():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"flag": 1}}}],
        groups=_svc([{"name": "flag", "kind": "bool"}]),
    )
    assert any("expected bool for parameter 'flag', got 1" in m for m in messages(w))


def test_string_param_rejects_a_number():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"label": 3}}}],
        groups=_svc([{"name": "label", "kind": "string"}]),
    )
    assert any("expected string for parameter 'label', got 3" in m for m in messages(w))


def test_number_param_accepts_an_int_literal():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"dose": 2}}}],
        groups=_svc([{"name": "dose", "kind": "number"}]),
    )
    assert validate(w) is None


def test_for_each_cell_kind_is_checked_too():
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1}, {"t": "two"}])])
    assert any("expected int for parameter 't', got 'two'" in m for m in messages(w))


def test_role_arg_must_name_a_declared_role():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"meter": "densitometer_9"}}}],
        groups=_svc([{"name": "meter", "kind": "role",
                      "device_type": "densitometer"}]),
    )
    assert any("names undeclared role 'densitometer_9'" in m for m in messages(w))


def test_role_arg_device_type_must_match_the_declaration():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"meter": "medium_pump"}}}],
        groups=_svc([{"name": "meter", "kind": "role",
                      "device_type": "densitometer"}]),
    )
    assert any(
        "role 'medium_pump' has type 'pump', but parameter 'meter' requires "
        "'densitometer'" in m
        for m in messages(w)
    )


def test_role_arg_naming_a_matching_role_is_clean():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"meter": "od_meter_1"}}}],
        groups=_svc([{"name": "meter", "kind": "role",
                      "device_type": "densitometer"}]),
    )
    assert validate(w) is None


def test_stream_arg_must_name_a_declared_stream():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"od": "od_9"}}}],
        streams=["od_1"],
        groups=_svc([{"name": "od", "kind": "stream"}]),
    )
    assert any("names undeclared stream 'od_9'" in m for m in messages(w))


def test_stream_arg_naming_a_declared_stream_is_clean():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"od": "od_1"}}}],
        streams=["od_1"],
        groups=_svc([{"name": "od", "kind": "stream"}]),
    )
    assert validate(w) is None


def test_binding_arg_must_be_identifier_shaped():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"c": "9lives"}}}],
        groups=_svc([{"name": "c", "kind": "binding"}]),
    )
    assert any("binding argument '9lives' is not a usable binding name" in m
               for m in messages(w))


def test_binding_arg_may_not_be_a_reserved_name():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"c": "not"}}}],
        groups=_svc([{"name": "c", "kind": "binding"}]),
    )
    assert any("binding argument 'not' is not a usable binding name" in m
               for m in messages(w))


def test_binding_arg_may_not_collide_with_a_stream():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"c": "od_1"}}}],
        streams=["od_1"],
        groups=_svc([{"name": "c", "kind": "binding"}]),
    )
    assert any("binding argument 'od_1' is already declared as a stream" in m
               for m in messages(w))


def test_reference_arg_must_be_a_string():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"od": 3}}}],
        streams=["od_1"],
        groups=_svc([{"name": "od", "kind": "stream"}]),
    )
    assert any("stream argument must be a name string, got 3" in m for m in messages(w))


def test_stream_arg_may_not_name_another_groups_local_by_hand():
    """The scope boundary, pinned as intended behaviour: a group local's qualified name
    is manufactured by the expander and is not a declared stream at this point. Passing
    one by literal spelling is not expressible -- thread a hole instead."""
    groups = {
        "owner": {"locals": {"c_series": {"kind": "stream"}}, "body": [STOP_PUMP]},
        "svc": {"params": [{"name": "od", "kind": "stream"}], "body": [STOP_PUMP]},
    }
    w = wf2(
        [{"group_ref": {"name": "owner", "as": "tube_1"}},
         {"group_ref": {"name": "svc", "args": {"od": "tube_1_c_series"}}}],
        groups=groups,
    )
    assert any("names undeclared stream 'tube_1_c_series'" in m for m in messages(w))


def test_hole_arg_of_the_same_kind_is_clean():
    groups = _svc([{"name": "od", "kind": "stream"}])
    w = wf2(
        [_fe([{"name": "od", "kind": "stream"}],
             [{"od": "od_1"}],
             [{"group_ref": {"name": "svc", "args": {"od": "{od}"}}}])],
        streams=["od_1"],
        groups=groups,
    )
    assert validate(w) is None


def test_hole_arg_of_the_wrong_kind_is_diagnosed():
    groups = _svc([{"name": "od", "kind": "stream"}])
    w = wf2(
        [_fe([{"name": "t", "kind": "int"}],
             [{"t": 1}],
             [{"group_ref": {"name": "svc", "args": {"od": "{t}"}}}])],
        streams=["od_1"],
        groups=groups,
    )
    assert any("int variable 't' cannot bind a stream parameter" in m
               for m in messages(w))


def test_hole_arg_role_device_type_must_agree():
    groups = _svc([{"name": "meter", "kind": "role", "device_type": "densitometer"}])
    w = wf2(
        [_fe([{"name": "p", "kind": "role", "device_type": "pump"}],
             [{"p": "medium_pump"}],
             [{"group_ref": {"name": "svc", "args": {"meter": "{p}"}}}])],
        groups=groups,
    )
    assert any("role<pump> variable 'p' cannot bind a role<densitometer> parameter" in m
               for m in messages(w))


def test_int_var_binding_a_number_param_is_clean():
    # An int IS a number: _value_matches already accepts the literal `2` in a number slot
    # (see test_number_param_accepts_an_int_literal), so the hole form must widen the same
    # way -- design ruling 2026-07-20.
    groups = _svc([{"name": "dose", "kind": "number"}])
    w = wf2(
        [_fe([{"name": "t", "kind": "int"}],
             [{"t": 1}],
             [{"group_ref": {"name": "svc", "args": {"dose": "{t}"}}}])],
        groups=groups,
    )
    assert validate(w) is None


def test_int_var_binding_a_string_param_is_still_diagnosed():
    # The int -> number widening must not spill over into unrelated kinds.
    groups = _svc([{"name": "label", "kind": "string"}])
    w = wf2(
        [_fe([{"name": "t", "kind": "int"}],
             [{"t": 1}],
             [{"group_ref": {"name": "svc", "args": {"label": "{t}"}}}])],
        groups=groups,
    )
    d = diags(w)
    assert any(
        x.category == "params"
        and "int variable 't' cannot bind a string parameter" in x.message
        for x in d
    )


def test_embedded_hole_in_a_reference_arg_is_rejected():
    groups = _svc([{"name": "od", "kind": "stream"}])
    w = wf2(
        [_fe([{"name": "t", "kind": "int"}],
             [{"t": 1}],
             [{"group_ref": {"name": "svc", "args": {"od": "od_{t}"}}}])],
        streams=["od_1"],
        groups=groups,
    )
    assert any("must be a whole name or a whole hole" in m for m in messages(w))


def test_embedded_hole_in_a_value_arg_is_fine():
    groups = _svc([{"name": "label", "kind": "string"}])
    w = wf2(
        [_fe([{"name": "t", "kind": "int"}],
             [{"t": 1}],
             [{"group_ref": {"name": "svc", "args": {"label": "tube {t}: service"}}}])],
        streams=[],
        groups=groups,
    )
    assert validate(w) is None


def test_param_and_local_name_collision_is_rejected():
    groups = {"svc": {
        "params": [{"name": "c", "kind": "int"}],
        "locals": {"c": {"kind": "binding"}},
        "body": [STOP_PUMP],
    }}
    w = wf2([{"group_ref": {"name": "svc", "as": "t1", "args": {"c": 1}}}],
            groups=groups)
    assert any("'c' is declared as both a parameter and a local" in m
               for m in messages(w))


def test_duplicate_param_name_is_rejected():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"t": 1}}}],
        groups=_svc([{"name": "t", "kind": "int"}, {"name": "t", "kind": "number"}]),
    )
    assert any("duplicate parameter name 't'" in m for m in messages(w))


def test_reserved_param_name_is_rejected():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"not": 1}}}],
        groups=_svc([{"name": "not", "kind": "int"}]),
    )
    assert any("declared name 'not' is reserved" in m for m in messages(w))


def test_non_identifier_param_name_is_rejected():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"9lives": 1}}}],
        groups=_svc([{"name": "9lives", "kind": "int"}]),
    )
    d = diags(w)
    assert any(
        x.category == "declaration" and "declared name '9lives' is not an identifier" in x.message
        for x in d
    )


def test_non_identifier_local_name_is_rejected():
    groups = {"svc": {
        "locals": {"9lives": {"kind": "binding", "init": "0"}},
        "body": [STOP_PUMP],
    }}
    w = wf2([{"group_ref": {"name": "svc", "as": "t1"}}], groups=groups)
    d = diags(w)
    assert any(
        x.category == "declaration" and "declared name '9lives' is not an identifier" in x.message
        for x in d
    )


def test_duplicate_for_each_var_name_is_rejected():
    w = wf2([_fe([{"name": "t", "kind": "int"}, {"name": "t", "kind": "int"}],
                 [{"t": 1}])])
    assert any("duplicate parameter name 't'" in m for m in messages(w))


def test_distinct_param_and_local_names_are_clean():
    groups = {"svc": {
        "params": [{"name": "tube", "kind": "int"}],
        "locals": {"c": {"kind": "binding", "init": "0"}},
        "body": [{"compute": {"into": "{c}", "value": "{c} + {tube}"}}],
    }}
    w = wf2([{"group_ref": {"name": "svc", "as": "t1", "args": {"tube": 1}}}],
            groups=groups)
    assert validate(w) is None


def test_for_each_var_shadowing_a_group_param_is_diagnosed():
    groups = {"svc": {
        "params": [{"name": "t", "kind": "int"}],
        "body": [_fe([{"name": "t", "kind": "int"}], [{"t": 1}, {"t": 2}])],
    }}
    w = wf2([{"group_ref": {"name": "svc", "args": {"t": 1}}}], groups=groups)
    assert any("'t' shadows an enclosing group parameter or for_each variable" in m
               for m in messages(w))


def test_for_each_var_shadowing_a_group_local_is_diagnosed():
    groups = {"svc": {
        "locals": {"c": {"kind": "binding", "init": "0"}},
        "body": [_fe([{"name": "c", "kind": "int"}], [{"c": 1}])],
    }}
    w = wf2([{"group_ref": {"name": "svc", "as": "t1"}}], groups=groups)
    assert any("'c' shadows an enclosing group parameter or for_each variable" in m
               for m in messages(w))


def test_nested_for_each_var_shadowing_is_diagnosed():
    inner = _fe([{"name": "t", "kind": "int"}], [{"t": 9}])
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1}], [inner])])
    assert any("'t' shadows an enclosing group parameter or for_each variable" in m
               for m in messages(w))


def test_distinct_nested_var_names_are_clean():
    inner = _fe([{"name": "u", "kind": "int"}], [{"u": 9}])
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1}], [inner])])
    assert validate(w) is None


def _local_group(init):
    return {"svc": {
        "locals": {"c": {"kind": "binding", "init": init}},
        "body": [{"compute": {"into": "{c}", "value": "{c} + 1"}}],
    }}


def test_local_init_may_not_reference_a_binding():
    w = wf2([{"group_ref": {"name": "svc", "as": "t1"}}],
            groups=_local_group("seed + 1"))
    msgs = messages(w)
    assert any("init must be a constant expression, but reads 'seed'" in m for m in msgs)


def test_local_init_may_not_call_a_stat():
    w = wf2([{"group_ref": {"name": "svc", "as": "t1"}}],
            streams=["od_1"],
            groups=_local_group("mean(od_1, last=5min)"))
    assert any("init must be a constant expression, but reads 'od_1'" in m
               for m in messages(w))


def test_local_init_may_not_count_a_stream():
    w = wf2([{"group_ref": {"name": "svc", "as": "t1"}}],
            streams=["od_1"],
            groups=_local_group("count(od_1) > 0"))
    assert any("init must be a constant expression, but reads 'od_1'" in m
               for m in messages(w))


def test_local_init_with_a_bad_expression_is_diagnosed():
    # Unreachable via wf2/workflow_from_dict for a hole-free init: serialize._local_decls
    # already parses and rejects it at LOAD time (_checked_expr), so a JSON-authored doc
    # can never carry a syntactically-bad init this far. Same defense-in-depth pattern as
    # test_for_each_row_must_be_an_object -- exercised by constructing the AST directly.
    group = Group(
        name="svc", locals={"c": LocalDecl(kind="binding", init="0 +")},
        body=[B.Compute(into="{c}", value="{c} + 1")],
    )
    w = Workflow(
        schema_version=2, roles={"pump_1": RoleDecl(type="pump")}, groups={"svc": group},
        blocks=[B.GroupRef(name="svc", as_="t1")],
    )
    assert any("invalid init expression" in m for m in messages(w))


def test_constant_local_inits_are_clean():
    for init in ("0", "false", "2 * 3 + 1", "true and not false"):
        w = wf2([{"group_ref": {"name": "svc", "as": "t1"}}],
                groups=_local_group(init))
        assert validate(w) is None, init
