from lab_devices.experiment.workflow import ConstantDecl, Workflow


def test_workflow_defaults_constants_to_empty():
    w = Workflow(schema_version=3)
    assert w.constants == {}


def test_constant_decl_holds_value_and_unit():
    c = ConstantDecl(value=37.0, as_="celsius")
    assert c.value == 37.0
    assert c.as_ == "celsius"

    d = ConstantDecl(value="DOSE * COUNT")
    assert d.value == "DOSE * COUNT"
    assert d.as_ is None
