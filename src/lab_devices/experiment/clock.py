"""Injectable clock: one time source for stamps, windows, and sleeps. See design 4-exec §6."""

from __future__ import annotations

import asyncio
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class MonotonicClock:
    """Production clock: event-loop time + asyncio.sleep."""

    def now(self) -> float:
        return asyncio.get_running_loop().time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
