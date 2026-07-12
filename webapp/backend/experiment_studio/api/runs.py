"""Run lifecycle endpoints. See webapp design §6, §7."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from experiment_studio.api.deps import get_run_manager
from experiment_studio.runner import RunManager

router = APIRouter()


class StartRunRequest(BaseModel):
    experiment_id: str
    lab: str
    role_mapping: dict[str, str]


class SubmitInputRequest(BaseModel):
    value: bool | int | float | str


@router.post("", status_code=201)
async def start_run(
    body: StartRunRequest, manager: RunManager = Depends(get_run_manager)
) -> dict[str, Any]:
    run_id = await manager.start(body.experiment_id, body.lab, body.role_mapping)
    return {"run_id": run_id}


@router.get("/active")
async def active_run(
    manager: RunManager = Depends(get_run_manager),
) -> dict[str, Any] | None:
    return manager.active_payload()


@router.post("/{run_id}/pause", status_code=204)
async def pause_run(run_id: str, manager: RunManager = Depends(get_run_manager)) -> None:
    manager.pause(run_id)


@router.post("/{run_id}/resume", status_code=204)
async def resume_run(run_id: str, manager: RunManager = Depends(get_run_manager)) -> None:
    manager.resume(run_id)


@router.post("/{run_id}/abort", status_code=204)
async def abort_run(run_id: str, manager: RunManager = Depends(get_run_manager)) -> None:
    manager.abort(run_id)


@router.post("/{run_id}/input", status_code=204)
async def submit_input(
    run_id: str,
    body: SubmitInputRequest,
    manager: RunManager = Depends(get_run_manager),
) -> None:
    manager.submit_input(run_id, body.value)
