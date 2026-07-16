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
    validate_doc,
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


async def test_create_renaming_keeps_a_free_name(store: ExperimentsStore) -> None:
    created = await store.create_renaming(make_doc("Fresh"))
    assert created["name"] == "Fresh"
    assert created["doc"]["name"] == "Fresh"


async def test_create_renaming_walks_suffixes_when_taken(store: ExperimentsStore) -> None:
    await store.create(make_doc("X"))
    first = await store.create_renaming(make_doc("X"))
    second = await store.create_renaming(make_doc("X"))
    assert first["name"] == "X (copy)"
    assert second["name"] == "X (copy 2)"
    assert first["doc"]["name"] == "X (copy)"
    assert first["id"] != second["id"]


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


def test_a_diagnostic_inside_a_for_each_body_reports_the_authored_path() -> None:
    doc = ExperimentDoc.model_validate(
        {
            "doc_version": 1,
            "name": "macro",
            "description": None,
            "roles": {"od_meter": {"type": "densitometer"}},
            "workflow": {
                "schema_version": 1,
                "metadata": {"name": "macro"},
                "streams": {"od_1": {"units": None}, "od_2": {"units": None}},
                "blocks": [
                    {
                        "for_each": {
                            "var": "t",
                            "in": [1, 2],
                            "body": [
                                {"measure": {"device": "od_meter", "verb": "measure", "into": "od_{t}"}},
                                # `nope` is not a declared stream, binding, or function -> one
                                # diagnostic per COPY at expanded blocks[1] and blocks[3], both
                                # authored at blocks[0].body[1].
                                {"branch": {"if": "nope > 1", "then": []}},
                            ],
                        }
                    }
                ],
            },
        }
    )
    diags = validate_doc(doc)
    assert diags, "expected the bad expression to produce a diagnostic"
    paths = {d["path"] for d in diags}
    # Authored, not expanded: every copy points at the one block the author can edit.
    assert paths == {"blocks[0].body[1] branch if"}


def test_a_plain_group_ref_under_for_each_reports_a_compound_authored_path() -> None:
    """Critical fix: a validate-phase walk from a group_ref call site into a PLAIN
    group's body builds a compound "<call site>->name.body[i]" path (validate.py:894).
    The for_each duplicates the call site (blocks[0] and blocks[1]), but both copies are
    authored at the same place: blocks[0].body[0] (the group_ref itself, inside the
    for_each body) calling into groups['mygroup'].body[0] (the group definition, authored
    where it is written and never duplicated). _remap must split on the first "->",
    remap only the call-site segment, and carry the group-body tail through unchanged --
    then dedup collapses the two per-copy diagnostics into one."""
    doc = ExperimentDoc.model_validate(
        {
            "doc_version": 1,
            "name": "plain-group-under-for-each",
            "description": None,
            "roles": {},
            "workflow": {
                "schema_version": 1,
                "groups": {
                    "mygroup": {
                        "body": [
                            {"compute": {"into": "x", "value": "nope_undeclared_thing"}}
                        ]
                    }
                },
                "blocks": [
                    {
                        "for_each": {
                            "var": "t",
                            "in": [1, 2],
                            "body": [{"group_ref": {"name": "mygroup"}}],
                        }
                    }
                ],
            },
        }
    )
    diags = validate_doc(doc)
    assert len(diags) == 1, f"expected the two per-copy diagnostics to dedup to one, got {diags}"
    assert diags[0]["path"] == "blocks[0].body[0]->mygroup.body[0] compute value"


def test_a_compound_path_reached_through_a_parametrized_group_remaps_the_call_site() -> None:
    """Regression guard: a plain group_ref (to `plaingroup`) nested inside a
    PARAMETRIZED group's body (`paramgroup`, called with args) still produces a compound
    "<call site>->plaingroup.body[i]" path once validate.py walks into the surviving
    GroupRef node -- the parametrized call site is fully inlined at expand time, but the
    trace still knows it as groups['paramgroup'].body[0]. That call-site segment must
    remap; the plaingroup.body[0] tail is already authored and passes through untouched."""
    doc = ExperimentDoc.model_validate(
        {
            "doc_version": 1,
            "name": "plain-group-under-parametrized-group",
            "description": None,
            "roles": {},
            "workflow": {
                "schema_version": 1,
                "groups": {
                    "plaingroup": {
                        "body": [
                            {"compute": {"into": "x", "value": "nope_undeclared_thing"}}
                        ]
                    },
                    "paramgroup": {
                        "params": ["tube"],
                        "body": [{"group_ref": {"name": "plaingroup"}}],
                    },
                },
                "blocks": [{"group_ref": {"name": "paramgroup", "args": {"tube": 1}}}],
            },
        }
    )
    diags = validate_doc(doc)
    assert len(diags) == 1
    assert diags[0]["path"] == "groups['paramgroup'].body[0]->plaingroup.body[0] compute value"


def test_a_diagnostic_with_no_arrow_remaps_by_identity_when_unduplicated() -> None:
    """Regression guard: partition("->") on a path with no "->" leaves head == the whole
    prefix and arrow == tail == "", so behavior for the common (non-compound) case is
    byte-for-byte identical to before this fix."""
    doc = ExperimentDoc.model_validate(
        {
            "doc_version": 1,
            "name": "no-arrow",
            "description": None,
            "roles": {},
            "workflow": {
                "schema_version": 1,
                "blocks": [
                    {"compute": {"into": "x", "value": "nope_undeclared_thing"}}
                ],
            },
        }
    )
    diags = validate_doc(doc)
    assert len(diags) == 1
    assert diags[0]["path"] == "blocks[0] compute value"


def test_an_unmappable_diagnostic_path_passes_through_unchanged() -> None:
    """The passthrough branch (self-review flagged it untested): `_check_groups`'s
    recursive-group diagnostic is reported at the bare "groups['name']" container path --
    never a trace key, since the trace only ever records positions *inside* a body list.
    _remap must hand that raw path back unchanged rather than dropping the diagnostic."""
    doc = ExperimentDoc.model_validate(
        {
            "doc_version": 1,
            "name": "recursive-group",
            "description": None,
            "roles": {},
            "workflow": {
                "schema_version": 1,
                "groups": {"selfref": {"body": [{"group_ref": {"name": "selfref"}}]}},
                "blocks": [{"group_ref": {"name": "selfref"}}],
            },
        }
    )
    diags = validate_doc(doc)
    paths = {d["path"] for d in diags}
    assert "groups['selfref']" in paths
