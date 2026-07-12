"""Run-record endpoints: list, viewer payload, rename, delete, download. See §6, §9.5."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from experiment_studio.api.deps import get_records_store, get_run_manager
from experiment_studio.records import RecordsStore, build_zip, read_events, read_streams
from experiment_studio.runner import RunActiveError, RunManager

router = APIRouter()


class RenameRequest(BaseModel):
    name: str = Field(min_length=1)


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


@router.get("")
async def list_records(
    store: RecordsStore = Depends(get_records_store),
) -> list[dict[str, Any]]:
    return await store.list()


@router.get("/{record_id}")
async def get_record(
    record_id: str, store: RecordsStore = Depends(get_records_store)
) -> dict[str, Any]:
    """Row + report + source doc for the record viewer (§9.5; §6 amended during W4)."""
    record = await store.get(record_id)
    artifact_dir = store.artifact_dir(record)
    record["report"] = _read_json(artifact_dir / "report.json")
    record["doc"] = _read_json(artifact_dir / "doc.json")
    return record


@router.patch("/{record_id}")
async def rename_record(
    record_id: str,
    body: RenameRequest,
    store: RecordsStore = Depends(get_records_store),
) -> dict[str, Any]:
    return await store.rename(record_id, body.name)


@router.delete("/{record_id}", status_code=204)
async def delete_record(
    record_id: str,
    store: RecordsStore = Depends(get_records_store),
    manager: RunManager = Depends(get_run_manager),
) -> None:
    active = manager.active()
    if active is not None and active.record_id == record_id:
        raise RunActiveError(active.run_id)
    await store.delete(record_id)


@router.get("/{record_id}/download")
async def download_record(
    record_id: str, store: RecordsStore = Depends(get_records_store)
) -> Response:
    record = await store.get(record_id)
    payload = build_zip(store.artifact_dir(record))
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", record["name"]).strip("._") or record["id"]
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{stem}.zip"'},
    )


@router.get("/{record_id}/events")
async def record_events(
    record_id: str, store: RecordsStore = Depends(get_records_store)
) -> list[dict[str, Any]]:
    record = await store.get(record_id)
    return read_events(store.artifact_dir(record))


@router.get("/{record_id}/streams")
async def record_streams(
    record_id: str, store: RecordsStore = Depends(get_records_store)
) -> dict[str, Any]:
    record = await store.get(record_id)
    return read_streams(store.artifact_dir(record))
