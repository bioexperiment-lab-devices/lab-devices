"""Shared fixtures: app factory + ASGI-transport client (no lifespan needed)."""

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

import runsupport
from experiment_studio.app import create_app
from experiment_studio.config import Settings
from experiment_studio.db import Database
from experiment_studio.docs_store import ExperimentsStore
from experiment_studio.runner import RunManager


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return create_app(Settings(static_dir=None, data_dir=tmp_path))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://studio") as c:
        yield c
    db = getattr(app.state, "db", None)
    if db is not None:
        await db.close()


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[SimpleNamespace]:
    """Manager-level harness: real Database + RunManager over a FakeLab."""
    fake = runsupport.default_fake()
    db = await Database.connect(tmp_path / "studio.db")
    registry = runsupport.fake_registry()
    manager = RunManager(
        db,
        tmp_path,
        registry,
        client_factory=runsupport.fake_client_factory(fake),
        run_options=dict(runsupport.FAST_RUN_OPTIONS),
    )
    yield SimpleNamespace(
        fake=fake, db=db, manager=manager, docs=ExperimentsStore(db), data_dir=tmp_path
    )
    await manager.shutdown()
    await registry.aclose()
    await db.close()
