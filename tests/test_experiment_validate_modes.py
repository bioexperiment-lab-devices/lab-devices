# tests/test_experiment_validate_modes.py
from lab_devices.experiment.validate import validate
from tests.experiment_validate_helpers import MEASURE_OD, cmd, diags, wf

ROTATE = cmd("pump_1", "rotate", {"direction": "forward", "speed_ml_min": 2.0})
STOP = cmd("pump_1", "stop")
DISPENSE = cmd("pump_1", "dispense", {"volume_ml": 1.0})
DISPENSE_2 = cmd("pump_2", "dispense", {"volume_ml": 1.0})
THERMO_ON = cmd("densitometer_1", "set_thermostat", {"enabled": True, "target_c": 37.0})
THERMO_OFF = cmd("densitometer_1", "set_thermostat", {"enabled": False})
LED_ON = cmd("densitometer_1", "set_led", {"level": 5})
LED_OFF = cmd("densitometer_1", "set_led", {"level": 0})


def test_free_start_stop_mode_valid():
    # §15.2 pattern: rotate ... other-device work ... stop
    assert validate(wf([ROTATE, MEASURE_OD, STOP], streams=["OD"])) is None


def test_command_inside_open_mode():
    d = diags(wf([ROTATE, DISPENSE, STOP]))
    assert any(
        x.category == "mode" and "'rotate'" in x.message and x.path == "blocks[1]" for x in d
    )


def test_reopen_same_mode():
    d = diags(wf([ROTATE, ROTATE]))
    assert any(x.category == "mode" for x in d)


def test_adjust_open_led_mode_rejected():
    d = diags(wf([LED_ON, cmd("densitometer_1", "set_led", {"level": 3})]))
    assert any(x.category == "mode" for x in d)


def test_close_without_open_is_noop():
    assert validate(wf([LED_OFF, STOP, THERMO_OFF])) is None


def test_unclosed_mode_at_end_is_legal():
    # Least-strict lifetimes: the finalizer is the universal close (design §12-13).
    assert validate(wf([ROTATE])) is None


def test_maybe_open_then_matching_close_clean():
    blocks = [
        {"branch": {"if": "1 < 2", "then": [ROTATE]}},
        STOP,
        DISPENSE,
    ]
    assert validate(wf(blocks)) is None


def test_maybe_open_then_conflicting_command():
    blocks = [
        {"branch": {"if": "1 < 2", "then": [ROTATE]}},
        DISPENSE,
    ]
    d = diags(wf(blocks))
    assert any(x.category == "mode" and "possibly open" in x.message for x in d)


def test_open_on_both_arms_is_definitely_open():
    blocks = [
        {"branch": {"if": "1 < 2", "then": [ROTATE], "else": [ROTATE]}},
        DISPENSE,
    ]
    d = diags(wf(blocks))
    assert any(x.category == "mode" and "open interval" in x.message for x in d)


def test_thermostat_and_measure_disjoint_channels():
    assert validate(wf([THERMO_ON, MEASURE_OD, THERMO_OFF], streams=["OD"])) is None


def test_led_mode_blocks_measure():
    d = diags(wf([LED_ON, MEASURE_OD], streams=["OD"]))
    assert any(x.category == "mode" and "'set_led'" in x.message for x in d)


def test_densitometer_stop_conflicts_with_thermostat_mode():
    d = diags(wf([THERMO_ON, cmd("densitometer_1", "stop")]))
    assert any(x.category == "mode" for x in d)


def test_loop_body_open_without_close_back_edge():
    d = diags(wf([{"loop": {"count": 3, "body": [ROTATE]}}]))
    assert any(x.category == "mode" and "body[0]" in x.path for x in d)


def test_loop_body_balanced_clean():
    assert validate(wf([{"loop": {"count": 3, "body": [ROTATE, STOP]}}])) is None


def test_count_one_loop_open_no_back_edge():
    assert validate(wf([{"loop": {"count": 1, "body": [ROTATE]}}])) is None


def test_expression_param_mode_is_conservative_open():
    blocks = [
        {"operator_input": {"name": "lvl", "type": "int"}},
        cmd("densitometer_1", "set_led", {"level": "lvl"}),
        MEASURE_OD,
    ]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "mode" for x in d)


def test_parallel_same_device_channel_overlap():
    blocks = [{"parallel": {"children": [
        DISPENSE, cmd("pump_1", "dispense", {"volume_ml": 2.0}),
    ]}}]
    d = diags(wf(blocks))
    assert any(x.category == "affinity" and "'pump_1'" in x.message for x in d)


def test_parallel_disjoint_devices_clean():
    assert validate(wf([{"parallel": {"children": [DISPENSE, DISPENSE_2]}}])) is None


def test_parallel_same_device_disjoint_channels_clean():
    blocks = [{"parallel": {"children": [MEASURE_OD, THERMO_ON]}}]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_parallel_same_device_same_channel_conflict():
    blocks = [{"parallel": {"children": [MEASURE_OD, LED_ON]}}]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "affinity" and "optics" in x.message for x in d)


def test_footprint_reaches_nested_and_groups():
    groups = {"work": {"body": [DISPENSE]}}
    blocks = [{"parallel": {"children": [
        {"loop": {"count": 2, "body": [{"group_ref": {"name": "work"}}]}},
        {"branch": {"if": "1 < 2", "then": [ROTATE, STOP]}},
    ]}}]
    d = diags(wf(blocks, groups=groups))
    assert any(x.category == "affinity" and "motor" in x.message for x in d)


def test_mode_spanning_parallel_other_devices_clean():
    blocks = [
        ROTATE,
        {"parallel": {"children": [DISPENSE_2, MEASURE_OD]}},
        STOP,
    ]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_mode_spanning_parallel_conflicting_child():
    blocks = [ROTATE, {"parallel": {"children": [DISPENSE, MEASURE_OD]}}, STOP]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "mode" for x in d)


def test_close_inside_parallel_child():
    blocks = [ROTATE, {"parallel": {"children": [STOP, MEASURE_OD]}}, DISPENSE]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_mode_opened_in_child_closed_after_parallel():
    blocks = [{"parallel": {"children": [ROTATE, MEASURE_OD]}}, STOP, DISPENSE]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_loop_body_branch_reopen_on_back_edge():
    # P4: re-open through a nested branch inside a loop body. Iteration 1 leaves
    # rotate maybe-open; iteration 2's rotate re-opens inside that interval.
    blocks = [{"loop": {"count": 3, "body": [
        {"branch": {"if": "1 < 2", "then": [
            {"serial": {"children": [ROTATE]}},
        ]}},
    ]}}]
    d = diags(wf(blocks))
    assert any(x.category == "mode" for x in d)


def test_group_opening_mode_referenced_twice_serially():
    # P6: a group opens a mode and never closes it; referencing the group a
    # second time serially re-opens inside the still-open interval.
    groups = {"stir": {"body": [ROTATE]}}
    blocks = [{"group_ref": {"name": "stir"}}, {"group_ref": {"name": "stir"}}]
    d = diags(wf(blocks, groups=groups))
    mode_diags = [x for x in d if x.category == "mode"]
    assert mode_diags
    assert any("->" in x.path for x in mode_diags)
