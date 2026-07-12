"""ExperimentsStore CRUD semantics (design §6, §8.1)."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from experiment_studio.db import Database
from experiment_studio.docs_store import (
    ExperimentDoc,
    ExperimentsStore,
    NameConflictError,
    UnknownExperimentError,
)


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[ExperimentsStore]:
    db = await Database.connect(tmp_path / "studio.db")
    yield ExperimentsStore(db)
    await db.close()


def make_doc(name: str = "OD growth curve", **overrides: Any) -> ExperimentDoc:
    payload: dict[str, Any] = {
        "doc_version": 1,
        "name": name,
        "description": "demo",
        "roles": {"feed_pump": {"type": "pump"}},
        "workflow": {"schema_version": 1, "blocks": []},
    }
    payload.update(overrides)
    return ExperimentDoc.model_validate(payload)


async def test_create_get_roundtrip(store: ExperimentsStore) -> None:
    created = await store.create(make_doc())
    assert created["name"] == "OD growth curve"
    assert created["doc"]["roles"] == {"feed_pump": {"type": "pump"}}
    assert created["created_at"] == created["updated_at"]
    fetched = await store.get(created["id"])
    assert fetched == created


async def test_list_returns_summaries_newest_updated_first(store: ExperimentsStore) -> None:
    a = await store.create(make_doc("A"))
    await store.create(make_doc("B"))
    await store.replace(a["id"], make_doc("A", description="bumped"))
    listed = await store.list()
    assert [e["name"] for e in listed] == ["A", "B"]
    assert all("doc" not in e for e in listed)
    assert listed[0]["description"] == "bumped"


async def test_create_duplicate_name_conflicts(store: ExperimentsStore) -> None:
    await store.create(make_doc("X"))
    with pytest.raises(NameConflictError):
        await store.create(make_doc("X"))


async def test_replace_updates_doc_and_name(store: ExperimentsStore) -> None:
    created = await store.create(make_doc("old"))
    replaced = await store.replace(created["id"], make_doc("new"))
    assert replaced["name"] == "new"
    assert replaced["created_at"] == created["created_at"]
    assert replaced["updated_at"] >= created["updated_at"]
    assert replaced["doc"]["name"] == "new"


async def test_replace_rename_onto_existing_conflicts(store: ExperimentsStore) -> None:
    await store.create(make_doc("taken"))
    other = await store.create(make_doc("mine"))
    with pytest.raises(NameConflictError):
        await store.replace(other["id"], make_doc("taken"))


async def test_unknown_ids_raise(store: ExperimentsStore) -> None:
    with pytest.raises(UnknownExperimentError):
        await store.get("nope")
    with pytest.raises(UnknownExperimentError):
        await store.replace("nope", make_doc())
    with pytest.raises(UnknownExperimentError):
        await store.delete("nope")
    with pytest.raises(UnknownExperimentError):
        await store.duplicate("nope")


async def test_delete_removes_row(store: ExperimentsStore) -> None:
    created = await store.create(make_doc())
    await store.delete(created["id"])
    with pytest.raises(UnknownExperimentError):
        await store.get(created["id"])


async def test_duplicate_suffixes_name(store: ExperimentsStore) -> None:
    src = await store.create(make_doc("X"))
    first = await store.duplicate(src["id"])
    second = await store.duplicate(src["id"])
    assert first["name"] == "X (copy)"
    assert second["name"] == "X (copy 2)"
    assert first["doc"]["name"] == "X (copy)"
    assert first["doc"]["workflow"] == src["doc"]["workflow"]
    assert first["id"] != src["id"]


async def test_name_conflict_rolls_back_transaction(tmp_path: Path) -> None:
    """W2 carry-forward: a failed INSERT/UPDATE must not leave the connection in an
    open transaction."""
    db = await Database.connect(tmp_path / "studio.db")
    store = ExperimentsStore(db)
    doc = ExperimentDoc(doc_version=1, name="A", workflow={"schema_version": 1})
    created = await store.create(doc)
    with pytest.raises(NameConflictError):
        await store.create(doc)
    assert not db.conn.in_transaction
    other = await store.create(doc.model_copy(update={"name": "B"}))
    with pytest.raises(NameConflictError):
        await store.replace(other["id"], doc)  # rename B -> A collides
    assert not db.conn.in_transaction
    with pytest.raises(UnknownExperimentError):
        await store.delete("nope")
    assert not db.conn.in_transaction
    assert created["name"] == "A"
    await db.close()
