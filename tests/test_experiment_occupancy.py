import pytest

from lab_devices.experiment.errors import InvariantViolationError
from lab_devices.experiment.occupancy import Occupancy, OpenMode

MOTOR = frozenset({"motor"})
OPTICS = frozenset({"optics"})
THERMAL = frozenset({"thermal"})


def _rotate_mode(block_id="blocks[0]"):
    return OpenMode(
        device="pump_1", mode_verb="rotate", teardown_verb="stop",
        teardown_params={}, channels=MOTOR, block_id=block_id,
    )


def test_acquire_release_cycle():
    occ = Occupancy()
    occ.acquire("pump_1", MOTOR, "blocks[0]")
    with pytest.raises(InvariantViolationError, match="command in flight"):
        occ.acquire("pump_1", MOTOR, "blocks[1]")
    occ.release("pump_1", MOTOR, "blocks[0]")
    occ.acquire("pump_1", MOTOR, "blocks[1]")  # free again


def test_distinct_channels_do_not_conflict():
    occ = Occupancy()
    occ.acquire("densitometer_1", THERMAL, "blocks[0]")
    occ.acquire("densitometer_1", OPTICS, "blocks[1]")  # legal: disjoint channels
    occ.acquire("pump_1", MOTOR, "blocks[2]")  # different device entirely


def test_open_mode_blocks_same_channel_commands():
    occ = Occupancy()
    occ.acquire("pump_1", MOTOR, "blocks[0]")
    occ.register_open(_rotate_mode("blocks[0]"))
    occ.release("pump_1", MOTOR, "blocks[0]")  # opener's hold is gone; mode remains
    with pytest.raises(InvariantViolationError, match="mode 'rotate'"):
        occ.acquire("pump_1", MOTOR, "blocks[1]")  # dispense while rotating
    with pytest.raises(InvariantViolationError):
        occ.acquire("pump_1", MOTOR, "blocks[2]", closes="set_led")  # wrong close


def test_matching_close_passes_through_and_frees():
    occ = Occupancy()
    occ.acquire("pump_1", MOTOR, "blocks[0]")
    occ.register_open(_rotate_mode("blocks[0]"))
    occ.release("pump_1", MOTOR, "blocks[0]")
    occ.acquire("pump_1", MOTOR, "blocks[3]", closes="rotate")  # allowed through
    closed = occ.register_close("pump_1", "rotate")
    assert closed is not None and closed.block_id == "blocks[0]"
    occ.release("pump_1", MOTOR, "blocks[3]")
    occ.acquire("pump_1", MOTOR, "blocks[4]")  # fully free now
    assert occ.open_modes() == ()


def test_close_with_no_open_mode_is_noop():
    occ = Occupancy()
    assert occ.register_close("pump_1", "rotate") is None


def test_release_only_frees_own_holds():
    occ = Occupancy()
    occ.acquire("pump_1", MOTOR, "blocks[0]")
    occ.release("pump_1", MOTOR, "blocks[9]")  # someone else's release: no effect
    with pytest.raises(InvariantViolationError):
        occ.acquire("pump_1", MOTOR, "blocks[1]")


def test_open_modes_snapshot_in_open_order():
    occ = Occupancy()
    led = OpenMode("densitometer_1", "set_led", "set_led", {"level": 0}, OPTICS, "b1")
    thermo = OpenMode(
        "densitometer_1", "set_thermostat", "set_thermostat", {"enabled": False},
        THERMAL, "b2",
    )
    occ.acquire("densitometer_1", OPTICS, "b1")
    occ.register_open(led)
    occ.acquire("densitometer_1", THERMAL, "b2")
    occ.register_open(thermo)
    assert [m.mode_verb for m in occ.open_modes()] == ["set_led", "set_thermostat"]
