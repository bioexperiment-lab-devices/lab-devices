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
        "workflow": {"schema_version": 3, "roles": {"feed_pump": {"type": "pump"}}, "blocks": []},
    }
    payload.update(overrides)
    return ExperimentDoc.model_validate(payload)


async def test_create_get_roundtrip(store: ExperimentsStore) -> None:
    created = await store.create(make_doc())
    assert created["name"] == "OD growth curve"
    assert created["doc"]["workflow"]["roles"] == {"feed_pump": {"type": "pump"}}
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
            "workflow": {
                "schema_version": 3,
                "metadata": {"name": "macro"},
                "roles": {"od_meter": {"type": "densitometer"}},
                "streams": {"od_1": {"units": "unitless"}, "od_2": {"units": "unitless"}},
                "blocks": [
                    {
                        "for_each": {
                            "vars": [{"name": "t", "kind": "int"}],
                            "in": [{"t": 1}, {"t": 2}],
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
    group's body builds a compound "<call site>->name.body[i]" path (validate.py's
    mode/data-flow walkers). The for_each duplicates the call site (blocks[0] and
    blocks[1]), but both copies are authored at the same place: blocks[0].body[0] (the
    group_ref itself, inside the for_each body) calling into groups['mygroup'].body[0]
    (the group definition, authored where it is written and never duplicated). _remap
    must split on the first "->", remap only the call-site segment, and carry the
    group-body tail through unchanged -- then dedup collapses the two per-copy
    diagnostics into one."""
    doc = ExperimentDoc.model_validate(
        {
            "doc_version": 1,
            "name": "plain-group-under-for-each",
            "description": None,
            "workflow": {
                "schema_version": 3,
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
                            "vars": [{"name": "t", "kind": "int"}],
                            "in": [{"t": 1}, {"t": 2}],
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
    PARAMETRIZED group's body (`paramgroup`, called with a typed `tube: int` arg) still
    produces a compound "<call site>->plaingroup.body[i]" path once validate.py walks into
    the surviving GroupRef node -- the parametrized call site is fully inlined at expand
    time, but the trace still knows it as groups['paramgroup'].body[0]. That call-site
    segment must remap; the plaingroup.body[0] tail is already authored and passes through
    untouched."""
    doc = ExperimentDoc.model_validate(
        {
            "doc_version": 1,
            "name": "plain-group-under-parametrized-group",
            "description": None,
            "workflow": {
                "schema_version": 3,
                "groups": {
                    "plaingroup": {
                        "body": [
                            {"compute": {"into": "x", "value": "nope_undeclared_thing"}}
                        ]
                    },
                    "paramgroup": {
                        "params": [{"name": "tube", "kind": "int"}],
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
            "workflow": {
                "schema_version": 3,
                "blocks": [
                    {"compute": {"into": "x", "value": "nope_undeclared_thing"}}
                ],
            },
        }
    )
    diags = validate_doc(doc)
    assert len(diags) == 1
    assert diags[0]["path"] == "blocks[0] compute value"


def test_a_for_each_inside_a_plain_groups_own_body_remaps_the_tail_index() -> None:
    """Second Critical fix: expand.py expands a PLAIN group's body IN PLACE, so
    "g1.body[1]" in a compound path is an EXPANDED index into g1's own body, not an
    authored one -- unlike the call-site head, the tail segment genuinely needs remapping
    too. Reproduced with NO outer duplication at all: the for_each lives directly inside
    g1's own body. validate.py walks blocks[0] (group_ref g1) into g1's two expanded
    for_each copies, reporting one diagnostic per copy at "blocks[0]->g1.body[0]" and
    "blocks[0]->g1.body[1]" -- both trace back to the one authored for_each body block,
    groups['g1'].body[0].body[0]. Both must collapse to a single diagnostic at
    "blocks[0]->g1.body[0].body[0]"."""
    doc = ExperimentDoc.model_validate(
        {
            "doc_version": 1,
            "name": "for-each-inside-plain-group-body",
            "description": None,
            "workflow": {
                "schema_version": 3,
                "groups": {
                    "g1": {
                        "body": [
                            {
                                "for_each": {
                                    "vars": [{"name": "t", "kind": "int"}],
                                    "in": [{"t": 1}, {"t": 2}],
                                    "body": [
                                        {
                                            "compute": {
                                                "into": "x",
                                                "value": "nope_undeclared_thing",
                                            }
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                },
                "blocks": [{"group_ref": {"name": "g1"}}],
            },
        }
    )
    diags = validate_doc(doc)
    assert len(diags) == 1, f"expected the two per-copy diagnostics to dedup to one, got {diags}"
    assert diags[0]["path"] == "blocks[0]->g1.body[0].body[0] compute value"


def test_a_doubly_nested_plain_group_remaps_every_segment() -> None:
    """Regression guard for the general N-segment case: validate.py recurses when a
    plain group_ref's body itself contains another plain group_ref, building a
    three-segment compound path "blocks[0]->g1.body[0]->g2.body[i]". Every "->" segment
    must be remapped with its own trace-key spelling, not just the head -- here it is the
    innermost segment that actually shifts (g2's own body holds the for_each), proving
    the fix reaches every level, not just the first "->"."""
    doc = ExperimentDoc.model_validate(
        {
            "doc_version": 1,
            "name": "doubly-nested-plain-groups",
            "description": None,
            "workflow": {
                "schema_version": 3,
                "groups": {
                    "g1": {"body": [{"group_ref": {"name": "g2"}}]},
                    "g2": {
                        "body": [
                            {
                                "for_each": {
                                    "vars": [{"name": "t", "kind": "int"}],
                                    "in": [{"t": 1}, {"t": 2}],
                                    "body": [
                                        {
                                            "compute": {
                                                "into": "x",
                                                "value": "nope_undeclared_thing",
                                            }
                                        }
                                    ],
                                }
                            }
                        ]
                    },
                },
                "blocks": [{"group_ref": {"name": "g1"}}],
            },
        }
    )
    diags = validate_doc(doc)
    assert len(diags) == 1, f"expected the two per-copy diagnostics to dedup to one, got {diags}"
    assert diags[0]["path"] == "blocks[0]->g1.body[0]->g2.body[0].body[0] compute value"


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
            "workflow": {
                "schema_version": 3,
                "groups": {"selfref": {"body": [{"group_ref": {"name": "selfref"}}]}},
                "blocks": [{"group_ref": {"name": "selfref"}}],
            },
        }
    )
    diags = validate_doc(doc)
    paths = {d["path"] for d in diags}
    assert "groups['selfref']" in paths


def test_a_spaced_group_name_still_dedups_to_the_authored_path() -> None:
    """Critical fix (final W9 review, Finding 1): `_remap` partitioned on the FIRST space
    ANYWHERE in the path, but `groups[{name!r}]` places no restriction on `name` -- a group
    named 'wash cycle' puts a space INSIDE the quoted head. Pre-fix, that corrupted the
    head into 'groups['wash' (an unmappable string), so `_remap` fell back to identity and
    handed the diagnostic back with its EXPANDED index intact -- and since the for_each
    inside the group's body produces one diagnostic per copy at two different expanded
    indices, dedup (keyed on the post-remap path) never collapsed them: 2 diagnostics
    instead of 1, at 'body[0]' and 'body[1]' rather than the single authored 'body[0].body[0]'.
    A non-identifier group name is real, reachable state: GROUP_NAME_RE (docStore.ts)
    guards only addGroup/renameGroup, never import (convert.ts loads keys verbatim), and
    this is the increment's headline use case (hand-authored/imported JSON).

    `wash cycle` is a PLAIN group (no params/locals) so it survives expansion as a
    `w.groups` entry and the SIMPLE `record`-writes-undeclared-stream check (which walks
    `_iter_all_blocks` directly, not the path-sensitive "->" walker) reports its raw,
    un-remapped path as the literal quoted head "groups['wash cycle'].body[i]" -- no
    "->" and no trailing " <context>" suffix, so the only thing standing between a correct
    remap and a corrupted one is `_quoted_group_head_end`'s scan-from-past-the-quote.
    Verified this is load-bearing, not incidental: stubbing `_quoted_group_head_end` to
    always return 0 (the pre-fix behavior) turns this into 2 diagnostics with the raw,
    unmapped `groups['wash cycle'].body[0]`/`.body[1]` paths instead of 1 authored one."""
    doc = ExperimentDoc.model_validate(
        {
            "doc_version": 1,
            "name": "spaced-group-name",
            "description": None,
            "workflow": {
                "schema_version": 3,
                "streams": {"ok_stream": {"units": "unitless"}},
                "groups": {
                    "wash cycle": {
                        "body": [
                            {
                                "for_each": {
                                    "vars": [{"name": "t", "kind": "int"}],
                                    "in": [{"t": 1}, {"t": 2}],
                                    "body": [
                                        {"record": {"into": "nope_stream", "value": 1}}
                                    ],
                                }
                            },
                            {"wait": {"duration": "1s"}},
                        ]
                    }
                },
                "blocks": [{"group_ref": {"name": "wash cycle"}}],
            },
        }
    )
    diags = validate_doc(doc)
    assert len(diags) == 1, f"expected the two per-copy diagnostics to dedup to one, got {diags}"
    assert diags[0]["path"] == "groups['wash cycle'].body[0].body[0]"


def test_dedup_key_includes_the_message_not_just_category_and_path() -> None:
    """Minor 1 (final W9 review): two per-copy diagnostics that remap to the SAME authored
    path but carry DIFFERENT messages must both survive -- only exact duplicates collapse.
    Here a for_each's `t: string` var is substituted whole into a compute `into` hole, so
    each copy names a different (equally unusable) binding: 'compute into '1'/'2' is not a
    usable binding name'. Dropping `message` from the dedup key would wrongly collapse
    these two distinct diagnostics into one, silently hiding one copy's report."""
    doc = ExperimentDoc.model_validate(
        {
            "doc_version": 1,
            "name": "distinct-messages-one-path",
            "description": None,
            "workflow": {
                "schema_version": 3,
                "blocks": [
                    {
                        "for_each": {
                            "vars": [{"name": "t", "kind": "string"}],
                            "in": [{"t": "1"}, {"t": "2"}],
                            "body": [{"compute": {"into": "{t}", "value": 1}}],
                        }
                    }
                ],
            },
        }
    )
    diags = validate_doc(doc)
    assert len(diags) == 2, f"expected both distinct-message copies to survive, got {diags}"
    assert {d["path"] for d in diags} == {"blocks[0].body[0]"}
    messages = {d["message"] for d in diags}
    assert messages == {
        "compute into '1' is not a usable binding name",
        "compute into '2' is not a usable binding name",
    }


def test_a_plain_group_calling_a_parametrized_group_does_not_corrupt_the_path() -> None:
    """Minor 2 (final W9 review): `_remap_group_segment`'s `not mapped.startswith(prefix)`
    containment guard is load-bearing. Plain group G's body calls parametrized group P
    (with a matching typed `x: int` arg), so expand.py's group-body pre-pass inlines P's
    body INTO G's body before G is ever referenced; the trace key for G's slot then points
    into P's authored body, a DIFFERENT group entirely. Without the guard, the buggy slice
    produces 'G.body[0]' -- a plausible-looking but WRONG path (that slot in G is the
    group_ref to P, not the compute block actually flagged). With the guard, the raw
    compound path is carried through unchanged: unclickable, but honest (design §5.3's
    documented passthrough) -- never guess at the wrong block."""
    doc = ExperimentDoc.model_validate(
        {
            "doc_version": 1,
            "name": "plain-group-calling-parametrized-group",
            "description": None,
            "workflow": {
                "schema_version": 3,
                "groups": {
                    "P": {
                        "params": [{"name": "x", "kind": "int"}],
                        "body": [
                            {"compute": {"into": "y", "value": "nope_undeclared_thing"}}
                        ],
                    },
                    "G": {"body": [{"group_ref": {"name": "P", "args": {"x": 1}}}]},
                },
                "blocks": [{"group_ref": {"name": "G"}}],
            },
        }
    )
    diags = validate_doc(doc)
    assert len(diags) == 1
    assert diags[0]["path"] == "blocks[0]->G.body[0].children[0] compute value"
