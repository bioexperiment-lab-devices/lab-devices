from lab_devices.experiment.blocks import (
    Branch,
    Command,
    Loop,
    Measure,
    Serial,
)


def test_leaf_defaults_and_timing():
    cmd = Command(device="pump_1", verb="dispense", params={"volume_ml": 10})
    assert cmd.gap_after is None and cmd.start_offset is None and cmd.label is None
    assert cmd.params == {"volume_ml": 10}


def test_nested_tree_construction():
    tree = Serial(
        children=[
            Loop(
                until="mean(OD, last=5min) >= target",
                check="after",
                body=[
                    Measure(device="densitometer_1", verb="measure", into="OD"),
                    Command(
                        device="pump_1",
                        verb="dispense",
                        params={"volume_ml": "2.0 * mean(OD, last=100)"},
                        gap_after="30s",
                    ),
                ],
            ),
            Branch(if_="last(OD) > target", then=[Command(device="pump_2", verb="stop")]),
        ]
    )
    assert isinstance(tree.children[0], Loop)
    assert tree.children[0].check == "after"
    assert tree.children[0].body[1].gap_after == "30s"
    assert tree.children[1].else_ is None
