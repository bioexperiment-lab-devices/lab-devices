import pytest

from lab_devices.experiment.errors import InvariantViolationError, OrphanedJobError
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


def test_close_one_of_two_co_resident_modes_is_identity_based():
    """Two modes co-reside on one device across disjoint channels; closing ONE frees
    only its channel. Identity-based close (Task 4a-6 review Q3): set_led stays open and
    its optics channel stays blocked while thermal is released."""
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
    closed = occ.register_close("densitometer_1", "set_thermostat")
    assert closed is not None and closed.mode_verb == "set_thermostat"
    assert [m.mode_verb for m in occ.open_modes()] == ["set_led"]  # set_led survives
    with pytest.raises(InvariantViolationError, match="mode 'set_led'"):
        occ.acquire("densitometer_1", OPTICS, "b3")  # optics still blocked by set_led
    occ.acquire("densitometer_1", THERMAL, "b4")  # thermal freed by the close


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


def test_a_stranded_job_keeps_its_channels_until_it_is_really_stopped():
    """A job the engine abandoned but could not stop is still running on the hardware, so its
    channels are still busy. `release` (the block's own `finally`) must NOT free them -- the
    block is over, but the JOB is not -- and the next dispatch on that channel must be refused
    with an OrphanedJobError naming the job, not with an InvariantViolationError: nothing
    proven-impossible happened, and a never-tolerated error would kill a run whose author asked
    to survive device faults. Only a stop that really killed the job frees them."""
    occ = Occupancy()
    occ.acquire("densitometer_1", OPTICS, "blocks[1]")
    occ.strand("densitometer_1", OPTICS, "blocks[1]", "j-1")

    occ.release("densitometer_1", OPTICS, "blocks[1]")  # the block's finally: must not free it
    with pytest.raises(OrphanedJobError, match="j-1"):
        occ.acquire("densitometer_1", OPTICS, "blocks[2]")
    assert occ.is_busy("densitometer_1") is True  # the idle oracle sees the live job
    occ.acquire("densitometer_1", THERMAL, "blocks[3]")  # a disjoint channel is unaffected

    occ.release_stranded("densitometer_1", "j-2")  # a DIFFERENT job's id frees nothing
    with pytest.raises(OrphanedJobError):
        occ.acquire("densitometer_1", OPTICS, "blocks[4]")

    occ.release_stranded("densitometer_1", "j-1")  # the orphan was stopped for real
    occ.acquire("densitometer_1", OPTICS, "blocks[5]")  # free again


def test_strand_only_converts_the_holds_of_the_block_that_placed_them():
    occ = Occupancy()
    occ.acquire("densitometer_1", OPTICS, "blocks[1]")
    occ.strand("densitometer_1", OPTICS | THERMAL, "blocks[9]", "j-1")  # not blocks[1]'s
    occ.release("densitometer_1", OPTICS, "blocks[1]")  # so this still frees its own hold
    assert occ.busy_devices() == set()


def test_is_busy_tracks_holds():
    from lab_devices.experiment.occupancy import Occupancy
    occ = Occupancy()
    assert occ.is_busy("pump_1") is False
    occ.acquire("pump_1", frozenset({"motor"}), "blocks[0]")
    assert occ.is_busy("pump_1") is True
    assert occ.busy_devices() == {"pump_1"}
    occ.release("pump_1", frozenset({"motor"}), "blocks[0]")
    assert occ.is_busy("pump_1") is False
    assert occ.busy_devices() == set()


def test_is_busy_tracks_open_mode():
    from lab_devices.experiment.occupancy import OpenMode, Occupancy
    occ = Occupancy()
    occ.acquire("pump_2", frozenset({"motor"}), "blocks[1]")
    occ.register_open(OpenMode("pump_2", "rotate", "stop", {}, frozenset({"motor"}), "blocks[1]"))
    assert occ.is_busy("pump_2") is True  # mode-held slot counts as busy
    occ.register_close("pump_2", "rotate")
    assert occ.is_busy("pump_2") is False
