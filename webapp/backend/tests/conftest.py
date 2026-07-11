"""Shared fixtures: app factory + ASGI-transport client (no lifespan needed)."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from experiment_studio.app import create_app
from experiment_studio.config import Settings


@pytest.fixture
def app() -> FastAPI:
    return create_app(Settings(static_dir=None))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://studio") as c:
        yield c
