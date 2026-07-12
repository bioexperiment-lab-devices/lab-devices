"""Shared fixtures: app factory + ASGI-transport client (no lifespan needed)."""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from experiment_studio.app import create_app
from experiment_studio.config import Settings


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
