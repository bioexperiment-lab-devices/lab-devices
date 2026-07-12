"""Web operator-input provider: one pending request, resolved over HTTP. See design §7.4."""

from __future__ import annotations

import asyncio

from lab_devices.experiment import BindingValue, InputRequest
from lab_devices.experiment.inputs import validate_input_value


class NoPendingInputError(Exception):
    """POST /runs/{id}/input with no operator input awaiting a value (§6: 409)."""


class WebInputProvider:
    """Parks each engine InputRequest as an asyncio.Future until submit() resolves it.

    Abort cancels the run task and the awaited future with it; the finally block
    clears pending state so late submits get NoPendingInputError, never a leak.
    """

    def __init__(self) -> None:
        self._request: InputRequest | None = None
        self._future: asyncio.Future[BindingValue] | None = None

    @property
    def pending(self) -> InputRequest | None:
        if self._future is None or self._future.done():
            return None
        return self._request

    async def request(self, request: InputRequest) -> BindingValue:
        self._request = request
        self._future = asyncio.get_running_loop().create_future()
        try:
            return await self._future
        finally:
            self._request = None
            self._future = None

    def submit(self, value: BindingValue) -> BindingValue:
        """Validate with the engine's rules and resolve the pending request.

        Raises NoPendingInputError (409) or EvaluationError (422 — stays pending).
        """
        if self._request is None or self._future is None or self._future.done():
            raise NoPendingInputError("no operator input is pending")
        validated = validate_input_value(self._request, value)
        self._future.set_result(validated)
        return validated
