"""In-memory tee run-log sink feeding the WS broadcast buffer. See design §7.3, §7.5."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from lab_devices.experiment import RunEvent
from lab_devices.experiment.persist import run_event_to_dict


class TeeRunLogSink:
    """Buffers run events in memory and wakes WebSocket readers.

    `seq` equals the message's index in `messages` (contiguous from 0); event and
    status messages share the counter so `?since=N` replay is a list slice. emit()
    must never raise and never block (§7.3): a raising sink can make a run
    un-abortable (engine Increment-5 lesson).
    """

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.closed = False
        self._wakeup = asyncio.Event()

    @property
    def last_seq(self) -> int:
        return len(self.messages) - 1

    def emit(self, event: RunEvent) -> None:
        try:
            self._append(
                {"type": "event", "seq": len(self.messages), **run_event_to_dict(event)}
            )
        except Exception:  # pragma: no cover — §7.3 hard rule
            pass

    def append_status(self, status: str) -> None:
        self._append({"type": "status", "seq": len(self.messages), "status": status})

    def close(self) -> None:
        """Terminal: streams drain any remaining messages, then finish."""
        self.closed = True
        self._wakeup.set()

    def events(self) -> list[dict[str, Any]]:
        """Engine events without the WS envelope — the run_log.jsonl payload (§7.1.5)."""
        return [
            {key: value for key, value in message.items() if key not in ("type", "seq")}
            for message in self.messages
            if message["type"] == "event"
        ]

    async def stream(self, since: int) -> AsyncIterator[dict[str, Any]]:
        """Yield messages with seq > since, then live messages until close()."""
        index = max(since + 1, 0)
        while True:
            while index < len(self.messages):
                yield self.messages[index]
                index += 1
            if self.closed:
                return
            self._wakeup.clear()
            if index < len(self.messages) or self.closed:
                continue  # appended/closed between drain and clear — re-check
            await self._wakeup.wait()

    def _append(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        self._wakeup.set()
