"""Lab roster and device endpoints. See webapp design §6."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from lab_devices.discovery import LabRegistry

from experiment_studio.api.deps import get_db, get_run_manager
from experiment_studio.db import Database
from experiment_studio.device_names import DeviceNamesStore
from experiment_studio.labs import LabsService
from experiment_studio.runner import RunActiveError, RunManager

router = APIRouter()


class NameBody(BaseModel):
    name: str


def _merge_names(
    devices: list[dict[str, Any]], names: dict[str, str]
) -> list[dict[str, Any]]:
    """Attach the operator-chosen name (or None) to each device payload (design §7.3)."""
    for device in devices:
        device["name"] = names.get(device["id"])
    return devices


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
    lab: str,
    service: LabsService = Depends(get_labs_service),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    devices = await service.devices(lab)
    names = await DeviceNamesStore(db).get_all(lab)
    return _merge_names(devices, names)


@router.post("/{lab}/discover")
async def lab_discover(
    lab: str,
    service: LabsService = Depends(get_labs_service),
    manager: RunManager = Depends(get_run_manager),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    active = manager.active()
    if active is not None and active.lab == lab:
        raise RunActiveError(active.run_id)  # §6: 409 while a run is active on that lab
    devices = await service.discover(lab)
    names = await DeviceNamesStore(db).get_all(lab)
    return _merge_names(devices, names)


@router.put("/{lab}/devices/{device_id}/name")
async def set_device_name(
    lab: str,
    device_id: str,
    body: NameBody,
    db: Database = Depends(get_db),
) -> dict[str, str | None]:
    store = DeviceNamesStore(db)
    name = body.name.strip()
    if name:
        await store.set(lab, device_id, name)
        return {"name": name}
    await store.clear(lab, device_id)
    return {"name": None}
