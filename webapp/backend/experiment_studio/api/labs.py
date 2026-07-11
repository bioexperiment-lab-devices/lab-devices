"""Lab roster and device endpoints. See webapp design §6."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from lab_devices.discovery import LabRegistry

from experiment_studio.labs import LabsService

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
    lab: str, service: LabsService = Depends(get_labs_service)
) -> list[dict[str, Any]]:
    return await service.discover(lab)
