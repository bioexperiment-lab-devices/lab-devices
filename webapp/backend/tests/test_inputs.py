"""WebInputProvider: pending lifecycle, validation, double-submit. See design §7.4."""

import asyncio

import pytest

from lab_devices.experiment import EvaluationError, InputRequest

from experiment_studio.inputs import NoPendingInputError, WebInputProvider


def _request(type_: str = "int", **kw: object) -> InputRequest:
    fields = {
        "name": "target",
        "type": type_,
        "prompt": "T?",
        "min": 1,
        "max": 10,
        "choices": None,
        "block_id": "blocks[0]",
    }
    fields.update(kw)
    return InputRequest(**fields)  # type: ignore[arg-type]


async def test_submit_resolves_pending_request() -> None:
    provider = WebInputProvider()
    assert provider.pending is None
    task = asyncio.create_task(provider.request(_request()))
    await asyncio.sleep(0)
    assert provider.pending is not None
    assert provider.pending.name == "target"
    assert provider.submit(7) == 7
    assert await asyncio.wait_for(task, 5) == 7
    assert provider.pending is None


async def test_submit_invalid_value_keeps_request_pending() -> None:
    provider = WebInputProvider()
    task = asyncio.create_task(provider.request(_request()))
    await asyncio.sleep(0)
    with pytest.raises(EvaluationError):
        provider.submit(0)  # below min
    with pytest.raises(EvaluationError):
        provider.submit("seven")  # wrong type
    assert provider.pending is not None
    provider.submit(3)
    assert await asyncio.wait_for(task, 5) == 3


async def test_submit_without_pending_raises() -> None:
    provider = WebInputProvider()
    with pytest.raises(NoPendingInputError):
        provider.submit(1)


async def test_double_submit_raises() -> None:
    provider = WebInputProvider()
    task = asyncio.create_task(provider.request(_request()))
    await asyncio.sleep(0)
    provider.submit(2)
    with pytest.raises(NoPendingInputError):
        provider.submit(3)
    assert await asyncio.wait_for(task, 5) == 2


async def test_cancelled_request_clears_pending() -> None:
    """Abort cancels the run task; the awaited future dies with it (§7.4)."""
    provider = WebInputProvider()
    task = asyncio.create_task(provider.request(_request()))
    await asyncio.sleep(0)
    assert provider.pending is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.pending is None
    with pytest.raises(NoPendingInputError):
        provider.submit(1)
