"""Experiment doc model, CRUD store, and validation orchestration. See design §4, §6, §8.1."""

from __future__ import annotations

import itertools
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import aiosqlite
from pydantic import BaseModel, Field

from lab_devices.experiment import (
    ValidationError,
    WorkflowLoadError,
    validate,
    verb_catalog,
    workflow_from_dict,
)
from lab_devices.experiment.expand import expand_dict_traced

from experiment_studio import roles as roles_mod
from experiment_studio.db import Database


class RoleDef(BaseModel):
    type: str


class ExperimentDoc(BaseModel):
    """Saved unit (§4.1): wraps the engine workflow JSON; `device` fields hold role names."""

    doc_version: Literal[1]
    name: str = Field(min_length=1)
    description: str | None = None
    roles: dict[str, RoleDef] = Field(default_factory=dict)
    workflow: dict[str, Any]


class UnknownExperimentError(Exception):
    """No experiment row with the requested id."""


class NameConflictError(Exception):
    """Experiment names are unique (§8.1); the requested name is taken."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _summary(row: aiosqlite.Row) -> dict[str, Any]:
    doc = json.loads(row["doc"])
    return {
        "id": row["id"],
        "name": row["name"],
        "description": doc.get("description"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _full(row: aiosqlite.Row) -> dict[str, Any]:
    out = _summary(row)
    out["doc"] = json.loads(row["doc"])
    return out


class ExperimentsStore:
    """CRUD over the experiments table; raises domain errors mapped to HTTP in app.py."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list(self) -> list[dict[str, Any]]:
        cur = await self._db.conn.execute(
            "SELECT id, name, doc, created_at, updated_at FROM experiments"
            " ORDER BY updated_at DESC"
        )
        return [_summary(row) for row in await cur.fetchall()]

    async def create(self, doc: ExperimentDoc) -> dict[str, Any]:
        row_id = str(uuid.uuid4())
        now = _now()
        try:
            await self._db.conn.execute(
                "INSERT INTO experiments (id, name, doc, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (row_id, doc.name, doc.model_dump_json(), now, now),
            )
        except sqlite3.IntegrityError:
            await self._db.conn.rollback()
            raise NameConflictError(f"experiment name {doc.name!r} already exists") from None
        await self._db.conn.commit()
        return await self.get(row_id)

    async def get(self, experiment_id: str) -> dict[str, Any]:
        cur = await self._db.conn.execute(
            "SELECT id, name, doc, created_at, updated_at FROM experiments WHERE id = ?",
            (experiment_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise UnknownExperimentError(f"no experiment {experiment_id!r}")
        return _full(row)

    async def replace(self, experiment_id: str, doc: ExperimentDoc) -> dict[str, Any]:
        try:
            cur = await self._db.conn.execute(
                "UPDATE experiments SET name = ?, doc = ?, updated_at = ? WHERE id = ?",
                (doc.name, doc.model_dump_json(), _now(), experiment_id),
            )
        except sqlite3.IntegrityError:
            await self._db.conn.rollback()
            raise NameConflictError(f"experiment name {doc.name!r} already exists") from None
        if cur.rowcount == 0:
            await self._db.conn.rollback()
            raise UnknownExperimentError(f"no experiment {experiment_id!r}")
        await self._db.conn.commit()
        return await self.get(experiment_id)

    async def delete(self, experiment_id: str) -> None:
        cur = await self._db.conn.execute(
            "DELETE FROM experiments WHERE id = ?", (experiment_id,)
        )
        if cur.rowcount == 0:
            await self._db.conn.rollback()
            raise UnknownExperimentError(f"no experiment {experiment_id!r}")
        await self._db.conn.commit()

    async def create_renaming(self, doc: ExperimentDoc) -> dict[str, Any]:
        """create(), but walk '(copy)', '(copy 2)'… until a free name lands
        (design §5.1)."""
        try:
            return await self.create(doc)
        except NameConflictError:
            pass
        for n in itertools.count(1):
            candidate = (
                f"{doc.name} (copy)" if n == 1 else f"{doc.name} (copy {n})"
            )
            try:
                return await self.create(
                    doc.model_copy(update={"name": candidate})
                )
            except NameConflictError:
                continue
        raise AssertionError("unreachable")

    async def duplicate(self, experiment_id: str) -> dict[str, Any]:
        source = await self.get(experiment_id)
        return await self.create_renaming(
            ExperimentDoc.model_validate(source["doc"])
        )


def _remap_group_segment(seg: str, trace: dict[str, str]) -> str:
    """Remap one `<group>.body[i]...` segment of a compound path.

    validate.py names the group BARE (`g1.body[0]`, :894/:940) while the trace keys group
    bodies the way validate.py's own _iter_all_blocks does (`groups['g1'].body[0]`, :63-64).
    The indices genuinely need mapping: expand.py expands a plain group's body IN PLACE
    (:270-274), so a for_each inside it shifts them.
    """
    name, dot, rest = seg.partition(".")
    if not dot:
        return seg
    prefix = f"groups[{name!r}]."
    mapped = trace.get(prefix + rest)
    if mapped is None or not mapped.startswith(prefix):
        return seg
    return name + "." + mapped[len(prefix):]


def _remap(path: str, trace: dict[str, str]) -> str:
    """Rewrite a diagnostic's structural path from expanded indices to authored ones.

    A path is a structural prefix plus an optional context suffix the validator appends
    (" branch if", " param 'x'"); only the prefix is a path, and no structural token contains
    a space. The prefix may itself be compound — "<call site>-><group>.body[i]" — when an
    analysis walks into a plain group's body; every segment is mapped with its own key form.
    An unmappable segment is carried through: a raw path beats no path (design §5.3).
    """
    prefix, sep, suffix = path.partition(" ")
    head, *segments = prefix.split("->")
    out = trace.get(head, head)
    for seg in segments:
        out += "->" + _remap_group_segment(seg, trace)
    return out + sep + suffix


def _remap_diagnostics(
    diags: list[dict[str, str]], trace: dict[str, str]
) -> list[dict[str, str]]:
    """Remap every diagnostic's path from expanded to authored, then dedup: a for_each
    body diagnosed once per copy collapses to a single authored diagnostic. Order-preserving
    (first occurrence wins) — some tests assert on diagnostic order."""
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for d in diags:
        remapped = {**d, "path": _remap(d["path"], trace)}
        key = (remapped["category"], remapped["path"], remapped["message"])
        if key in seen:
            continue
        seen.add(key)
        out.append(remapped)
    return out


def validate_doc(doc: ExperimentDoc) -> list[dict[str, str]]:
    """§4.3: doc-level role checks, placeholder substitution, engine parse + validate."""
    role_types = {name: role.type for name, role in doc.roles.items()}
    diags = roles_mod.role_diagnostics(role_types, set(verb_catalog()))
    try:
        # for_each/group(tube) -> concrete roles (§9); trace maps expanded -> authored paths
        # so every diagnostic downstream of the expand can be reported where the author edits.
        expanded, trace = expand_dict_traced(doc.workflow)
    except WorkflowLoadError as exc:
        return diags + [{"category": "expansion", "path": "workflow", "message": str(exc)}]
    substituted, ref_diags = roles_mod.substitute(
        expanded, roles_mod.placeholder_ids(role_types)
    )
    diags += _remap_diagnostics(ref_diags, trace)
    if diags:
        return diags  # substitution unsound; engine output would duplicate (plan P3)
    try:
        workflow = workflow_from_dict(substituted)
    except WorkflowLoadError as exc:
        return [{"category": "schema", "path": "workflow", "message": str(exc)}]
    try:
        validate(workflow)
    except ValidationError as exc:
        return _remap_diagnostics(
            [
                {"category": d.category, "path": d.path, "message": d.message}
                for d in exc.diagnostics
            ],
            trace,
        )
    return []
