from lab_devices.experiment.validate import validate
from tests.experiment_validate_helpers import MEASURE_OD, cmd, diags, wf

INPUT_X = {"operator_input": {"name": "x", "type": "float"}}
DISPENSE_X = cmd("pump_1", "dispense", {"volume_ml": "x * 2"})


def test_read_before_write_binding():
    d = diags(wf([DISPENSE_X, INPUT_X]))
    assert any(
        x.category == "data-flow" and "'x'" in x.message and "before" in x.message for x in d
    )


def test_write_then_read_clean():
    assert validate(wf([INPUT_X, DISPENSE_X])) is None


def test_branch_one_arm_write_not_definite():
    blocks = [
        {"branch": {"if": "1 < 2", "then": [INPUT_X]}},
        DISPENSE_X,
    ]
    d = diags(wf(blocks))
    assert any(x.category == "data-flow" and "'x'" in x.message for x in d)


def test_branch_both_arms_write_definite():
    blocks = [
        {"branch": {"if": "1 < 2", "then": [INPUT_X], "else": [INPUT_X]}},
        DISPENSE_X,
    ]
    assert validate(wf(blocks)) is None


def test_read_inside_writing_arm_clean():
    blocks = [{"branch": {"if": "1 < 2", "then": [INPUT_X, DISPENSE_X]}}]
    assert validate(wf(blocks)) is None


def test_condition_read_before_write():
    blocks = [{"branch": {"if": "x > 1", "then": [INPUT_X]}}]
    d = diags(wf(blocks))
    assert any(
        x.category == "data-flow" and "'x'" in x.message and "branch if" in x.path for x in d
    )


def test_post_test_until_sees_body_writes():
    blocks = [{"loop": {"until": "mean(OD) > 1", "check": "after", "body": [MEASURE_OD]}}]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_pre_test_until_needs_preseed():
    blocks = [{"loop": {"until": "mean(OD) > 1", "check": "before", "body": [MEASURE_OD]}}]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "data-flow" and "'OD'" in x.message for x in d)


def test_pre_test_until_with_preseed_clean():
    blocks = [
        MEASURE_OD,
        {"loop": {"until": "mean(OD) > 1", "check": "before", "body": [MEASURE_OD]}},
    ]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_pre_test_count_exemption():
    blocks = [{"loop": {"until": "count(OD) >= 10", "check": "before", "body": [MEASURE_OD]}}]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_count_loop_writes_survive():
    blocks = [
        {"loop": {"count": 3, "body": [MEASURE_OD]}},
        cmd("pump_1", "dispense", {"volume_ml": "last(OD)"}),
    ]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_pre_test_loop_writes_do_not_survive():
    blocks = [
        {"loop": {"until": "count(OD) >= 1", "check": "before", "body": [MEASURE_OD]}},
        cmd("pump_1", "dispense", {"volume_ml": "last(OD)"}),
    ]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "data-flow" and "'OD'" in x.message for x in d)


def test_post_test_loop_writes_survive():
    blocks = [
        {"loop": {"until": "count(OD) >= 5", "check": "after", "body": [MEASURE_OD]}},
        cmd("pump_1", "dispense", {"volume_ml": "last(OD)"}),
    ]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_parallel_sibling_writes_not_visible():
    blocks = [{"parallel": {"children": [
        {"serial": {"children": [INPUT_X]}},
        {"serial": {"children": [DISPENSE_X]}},
    ]}}]
    d = diags(wf(blocks))
    assert any(x.category == "data-flow" and "'x'" in x.message for x in d)


def test_parallel_writes_visible_after_join():
    blocks = [
        {"parallel": {"children": [
            {"serial": {"children": [INPUT_X]}},
            {"serial": {"children": [MEASURE_OD]}},
        ]}},
        DISPENSE_X,
        cmd("pump_2", "dispense", {"volume_ml": "last(OD)"}),
    ]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_group_expansion_flows_state():
    groups = {"seed": {"body": [INPUT_X]}}
    blocks = [{"group_ref": {"name": "seed"}}, DISPENSE_X]
    assert validate(wf(blocks, groups=groups)) is None


def test_binding_written_in_loop_body_post_test_until():
    blocks = [{"loop": {"until": "x > 1", "check": "after", "body": [INPUT_X]}}]
    assert validate(wf(blocks)) is None


def test_binding_pre_test_until_unwritten():
    blocks = [{"loop": {"until": "x > 1", "check": "before", "body": [INPUT_X]}}]
    d = diags(wf(blocks))
    assert any(x.category == "data-flow" and "'x'" in x.message for x in d)
