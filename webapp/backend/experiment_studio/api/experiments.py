"""Experiment document CRUD endpoints. See webapp design §6."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from experiment_studio.api.deps import get_records_store
from experiment_studio.db import Database
from experiment_studio.docs_store import ExperimentDoc, ExperimentsStore
from experiment_studio.records import RecordsStore

router = APIRouter()


async def get_store(request: Request) -> ExperimentsStore:
    """Lazily open the database on first use; lifespan startup pre-populates app.state.db."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        settings = request.app.state.settings
        db = await Database.connect(settings.data_dir / "studio.db")
        request.app.state.db = db
    return ExperimentsStore(db)


@router.get("")
async def list_experiments(
    store: ExperimentsStore = Depends(get_store),
) -> list[dict[str, Any]]:
    return await store.list()


@router.post("", status_code=201)
async def create_experiment(
    doc: ExperimentDoc, store: ExperimentsStore = Depends(get_store)
) -> dict[str, Any]:
    return await store.create(doc)


@router.get("/{experiment_id}")
async def get_experiment(
    experiment_id: str, store: ExperimentsStore = Depends(get_store)
) -> dict[str, Any]:
    return await store.get(experiment_id)


@router.put("/{experiment_id}")
async def replace_experiment(
    experiment_id: str, doc: ExperimentDoc, store: ExperimentsStore = Depends(get_store)
) -> dict[str, Any]:
    return await store.replace(experiment_id, doc)


@router.delete("/{experiment_id}", status_code=204)
async def delete_experiment(
    experiment_id: str, store: ExperimentsStore = Depends(get_store)
) -> None:
    await store.delete(experiment_id)


@router.post("/{experiment_id}/duplicate", status_code=201)
async def duplicate_experiment(
    experiment_id: str, store: ExperimentsStore = Depends(get_store)
) -> dict[str, Any]:
    return await store.duplicate(experiment_id)


@router.get("/{experiment_id}/mappings/{lab}")
async def experiment_mappings(
    experiment_id: str,
    lab: str,
    store: ExperimentsStore = Depends(get_store),
    records: RecordsStore = Depends(get_records_store),
) -> dict[str, str]:
    """S2 mapping-memory read for preflight pre-fill (§9.4; §6 amended during W5)."""
    await store.get(experiment_id)  # 404 unknown_experiment when absent
    return await records.load_mapping(experiment_id, lab)
