"""Experiment document CRUD endpoints. See webapp design §6."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from experiment_studio.db import Database
from experiment_studio.docs_store import ExperimentDoc, ExperimentsStore

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
