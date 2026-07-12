"""W6: active() hides the finalization window (status is only ever running|paused)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from experiment_studio.runner import ActiveRun, RunManager, UnknownRunError


def _stub_active(status: str, task: asyncio.Task[None]) -> ActiveRun:
    stub = cast(Any, object())
    return ActiveRun(
        run_id="r1",
        record_id="r1",
        experiment_id="e1",
        experiment_name="exp",
        lab="lab",
        role_mapping={},
        status=status,
        run=stub,
        tee=stub,
        inputs=stub,
        client=stub,
        artifact_dir=Path("."),
        task=task,
    )


@pytest.mark.parametrize("status", ["completed", "failed", "aborted", "cancelled", "interrupted"])
async def test_active_hides_terminal_finalization_window(status: str) -> None:
    manager = RunManager(cast(Any, None), Path("."), cast(Any, None))
    task = asyncio.create_task(asyncio.sleep(30))
    try:
        manager._current = _stub_active(status, task)
        assert manager.active() is None
        assert manager.active_payload() is None
        with pytest.raises(UnknownRunError):
            manager._require_active("r1")
    finally:
        task.cancel()


async def test_active_still_returns_running_and_paused() -> None:
    manager = RunManager(cast(Any, None), Path("."), cast(Any, None))
    task = asyncio.create_task(asyncio.sleep(30))
    try:
        for status in ("running", "paused"):
            manager._current = _stub_active(status, task)
            current = manager.active()
            assert current is not None and current.status == status
    finally:
        task.cancel()
