"""Run event WebSocket with replay-on-reconnect. See design §7.5."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from experiment_studio.api.deps import get_run_manager
from experiment_studio.runner import RunManager, UnknownRunError

router = APIRouter()


@router.websocket("/runs/{run_id}/events")
async def run_events(
    websocket: WebSocket,
    run_id: str,
    since: int = Query(default=-1),
    manager: RunManager = Depends(get_run_manager),
) -> None:
    await websocket.accept()
    try:
        stream = manager.stream(run_id, since)
    except UnknownRunError:
        await websocket.close(code=4404)
        return
    try:
        async for message in stream:
            await websocket.send_json(message)
        await websocket.close(code=1000)
    except (WebSocketDisconnect, RuntimeError):
        # client went away mid-send; a reconnect resumes via ?since=<last seq>
        pass
