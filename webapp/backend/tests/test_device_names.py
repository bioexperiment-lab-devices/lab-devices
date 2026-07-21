"""DeviceNamesStore CRUD over a real migrated Database."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from experiment_studio.db import Database
from experiment_studio.device_names import DeviceNamesStore


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[DeviceNamesStore]:
    db = await Database.connect(tmp_path / "studio.db")
    yield DeviceNamesStore(db)
    await db.close()


async def test_set_then_get_all(store: DeviceNamesStore) -> None:
    await store.set("chisel", "pump_1", "Culture pump")
    await store.set("chisel", "pump_2", "Waste pump")
    assert await store.get_all("chisel") == {"pump_1": "Culture pump", "pump_2": "Waste pump"}


async def test_get_all_is_scoped_by_lab(store: DeviceNamesStore) -> None:
    await store.set("chisel", "pump_1", "A")
    await store.set("other", "pump_1", "B")
    assert await store.get_all("chisel") == {"pump_1": "A"}


async def test_set_is_upsert(store: DeviceNamesStore) -> None:
    await store.set("chisel", "pump_1", "First")
    await store.set("chisel", "pump_1", "Second")
    assert await store.get_all("chisel") == {"pump_1": "Second"}


async def test_clear_removes_row(store: DeviceNamesStore) -> None:
    await store.set("chisel", "pump_1", "A")
    await store.clear("chisel", "pump_1")
    assert await store.get_all("chisel") == {}


async def test_get_all_empty_lab_is_empty_dict(store: DeviceNamesStore) -> None:
    assert await store.get_all("nobody") == {}
