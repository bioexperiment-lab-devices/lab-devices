import dataclasses
from typing import get_args

import pytest

from lab_devices.experiment.errors import UnknownRoleError, WorkflowLoadError
from lab_devices.experiment.workflow import (
    REFERENCE_KINDS,
    VALUE_KINDS,
    Group,
    LocalDecl,
    ParamDecl,
    ParamKind,
    RoleDecl,
    Workflow,
)


def test_kind_sets_partition_the_param_kind_union():
    """VALUE_KINDS and REFERENCE_KINDS must cover ParamKind exactly and not overlap:
    every substitution rule in design 2026-07-20 §3 branches on which set a kind is in,
    so a kind in neither set (or both) has undefined substitution behaviour."""
    assert VALUE_KINDS == {"int", "number", "bool", "string"}
    assert REFERENCE_KINDS == {"role", "stream", "binding"}
    assert not (VALUE_KINDS & REFERENCE_KINDS)
    assert VALUE_KINDS | REFERENCE_KINDS == set(get_args(ParamKind))


def test_param_decl_defaults_and_role_carries_device_type():
    p = ParamDecl("tube", "int")
    assert p.name == "tube" and p.kind == "int" and p.device_type is None
    meter = ParamDecl(name="meter", kind="role", device_type="densitometer")
    assert meter.device_type == "densitometer"
    with pytest.raises(dataclasses.FrozenInstanceError):
        meter.kind = "int"


def test_local_decl_defaults():
    binding = LocalDecl(kind="binding", init="0")
    assert binding.kind == "binding" and binding.init == "0"
    assert binding.units is None and binding.persistence is None
    stream = LocalDecl(kind="stream", units="ug/mL", persistence="disk")
    assert stream.init is None and stream.units == "ug/mL"
    assert stream.persistence == "disk"


def test_role_decl_device_is_optional():
    assert RoleDecl(type="densitometer").device is None
    assert RoleDecl(type="pump", device="pump_2").device == "pump_2"


def test_group_declares_typed_params_and_locals():
    g = Group(name="service")
    assert g.params == [] and g.locals == {} and g.body == []
    typed = Group(
        name="service",
        params=[ParamDecl("tube", "int"), ParamDecl("od", "stream")],
        locals={"c": LocalDecl(kind="binding", init="0")},
    )
    assert [p.name for p in typed.params] == ["tube", "od"]
    assert typed.params[1].kind == "stream"
    assert typed.locals["c"].init == "0"


def test_workflow_roles_default_empty():
    w = Workflow(schema_version=2)
    assert w.roles == {}


def test_role_type_reads_the_declaration():
    w = Workflow(
        schema_version=2,
        roles={"od_meter_1": RoleDecl(type="densitometer"),
               "medium_pump": RoleDecl(type="pump", device="pump_2")},
    )
    assert w.role_type("od_meter_1") == "densitometer"
    assert w.role_type("medium_pump") == "pump"


def test_role_type_raises_unknown_role_error_naming_the_declared_roles():
    w = Workflow(schema_version=2, roles={"od_meter_1": RoleDecl(type="densitometer")})
    with pytest.raises(UnknownRoleError, match="od_meter_2"):
        w.role_type("od_meter_2")
    with pytest.raises(UnknownRoleError, match=r"od_meter_1"):
        w.role_type("od_meter_2")


def test_unknown_role_error_is_a_workflow_load_error():
    """Existing callers catch WorkflowLoadError; an undeclared role must not escape them."""
    assert issubclass(UnknownRoleError, WorkflowLoadError)


def test_value_kind_samples_stay_total_over_value_kinds():
    """_hole_kind_binds derives hole-kind agreement from _value_matches by probing this
    sample table, so consistency with the literal rule is only as good as the table's
    coverage. A missing kind raises KeyError mid-validation instead of emitting a
    diagnostic; an empty sample tuple makes `all(...)` vacuously true, silently widening
    the check to accept everything (design 2026-07-20 §2.1)."""
    from lab_devices.experiment.validate import _VALUE_KIND_SAMPLES

    assert set(_VALUE_KIND_SAMPLES) == VALUE_KINDS
    assert all(_VALUE_KIND_SAMPLES.values())
