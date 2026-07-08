import asyncio

import pytest

from lab_devices.experiment.clock import Clock, MonotonicClock
from tests.fakeclock import FakeClock, drive


async def test_monotonic_clock_satisfies_protocol():
    clock: Clock = MonotonicClock()
    before = clock.now()
    await clock.sleep(0)
    assert clock.now() >= before


async def test_fake_clock_no_premature_fire():
    clock = FakeClock()
    fired: list[str] = []

    async def sleeper(name: str, seconds: float) -> None:
        await clock.sleep(seconds)
        fired.append(name)

    t1 = asyncio.ensure_future(sleeper("a", 10.0))
    t2 = asyncio.ensure_future(sleeper("b", 5.0))
    await clock.advance(4.9)
    assert fired == []
    await clock.advance(0.2)
    assert fired == ["b"]
    await clock.advance(5.0)
    assert fired == ["b", "a"]
    assert clock.now() == pytest.approx(10.1)
    await asyncio.gather(t1, t2)


async def test_fake_clock_chained_sleeps_fire_in_order():
    clock = FakeClock()
    fired: list[float] = []

    async def chain() -> None:
        for _ in range(3):
            await clock.sleep(1.0)
            fired.append(clock.now())

    task = asyncio.ensure_future(chain())
    await clock.advance(3.0)  # sleeps registered one at a time; settling must chain them
    assert fired == [pytest.approx(1.0), pytest.approx(2.0), pytest.approx(3.0)]
    await task


async def test_drive_runs_to_completion():
    clock = FakeClock()

    async def work() -> str:
        await clock.sleep(30.0)
        await clock.sleep(30.0)
        return "done"

    assert await drive(clock, work()) == "done"
    assert clock.now() == pytest.approx(60.0)


async def test_drive_detects_deadlock():
    clock = FakeClock()
    gate = asyncio.Event()  # never set: no sleeper, task never done

    async def stuck() -> None:
        await gate.wait()

    with pytest.raises(AssertionError, match="deadlock"):
        await drive(clock, stuck())
