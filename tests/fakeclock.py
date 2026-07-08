"""Deterministic manual-advance clock for executor tests (design 4-exec §6, D3)."""

import asyncio
import heapq
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")

_SETTLE_ROUNDS = 50  # bounded yields; covers httpx.MockTransport's event-loop hops


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start
        self._heap: list[tuple[float, int, asyncio.Future[None]]] = []
        self._seq = 0

    def now(self) -> float:
        return self._now

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._seq += 1
        heapq.heappush(self._heap, (self._now + seconds, self._seq, future))
        await future

    async def settle(self) -> None:
        """Let ready tasks run (bounded, deterministic)."""
        for _ in range(_SETTLE_ROUNDS):
            await asyncio.sleep(0)

    async def advance(self, seconds: float) -> None:
        """Advance time, firing due sleepers in deadline order; settle between firings
        so a woken task can register its next sleep before later deadlines fire."""
        target = self._now + seconds
        await self.settle()
        while self._heap and self._heap[0][0] <= target:
            deadline, _, future = heapq.heappop(self._heap)
            self._now = max(self._now, deadline)
            if not future.cancelled():
                future.set_result(None)
            await self.settle()
        self._now = target
        await self.settle()

    def next_deadline(self) -> "float | None":
        while self._heap and self._heap[0][2].cancelled():
            heapq.heappop(self._heap)
        return self._heap[0][0] if self._heap else None


async def drive(
    clock: FakeClock, coro: Coroutine[Any, Any, T], *, max_steps: int = 10_000
) -> T:
    """Run coro to completion, advancing the clock to each next deadline.

    Raises AssertionError on deadlock (task pending, no sleepers) instead of hanging.
    Not suitable for paused-run phases (a paused gate has no sleeper): use
    settle()/advance() manually there.
    """
    task: "asyncio.Task[T]" = asyncio.ensure_future(coro)
    try:
        for _ in range(max_steps):
            await clock.settle()
            if task.done():
                return task.result()
            deadline = clock.next_deadline()
            if deadline is None:
                raise AssertionError("deadlock: task pending but no sleepers scheduled")
            await clock.advance(deadline - clock.now())
        raise AssertionError(f"drive() did not finish within {max_steps} steps")
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except BaseException:
                pass
