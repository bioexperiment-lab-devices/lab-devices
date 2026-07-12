"""Lab roster and device endpoints. See webapp design §6."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from lab_devices.discovery import LabRegistry

from experiment_studio.api.deps import get_run_manager
from experiment_studio.labs import LabsService
from experiment_studio.runner import RunActiveError, RunManager

router = APIRouter()


def get_labs_service(request: Request) -> LabsService:
    """Lazily construct the real service on first use (tests override this dependency)."""
    service = getattr(request.app.state, "labs", None)
    if service is None:
        service = LabsService(LabRegistry())
        request.app.state.labs = service
    return service


@router.get("")
async def list_labs(service: LabsService = Depends(get_labs_service)) -> list[dict[str, Any]]:
    return await service.list_labs()


@router.get("/{lab}/devices")
async def lab_devices(
    lab: str, service: LabsService = Depends(get_labs_service)
) -> list[dict[str, Any]]:
    return await service.devices(lab)


@router.post("/{lab}/discover")
async def lab_discover(
    lab: str,
    service: LabsService = Depends(get_labs_service),
    manager: RunManager = Depends(get_run_manager),
) -> list[dict[str, Any]]:
    active = manager.active()
    if active is not None and active.lab == lab:
        raise RunActiveError(active.run_id)  # §6: 409 while a run is active on that lab
    return await service.discover(lab)
