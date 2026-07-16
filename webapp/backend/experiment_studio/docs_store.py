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
from lab_devices.experiment.expand import expand_dict

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


def validate_doc(doc: ExperimentDoc) -> list[dict[str, str]]:
    """§4.3: doc-level role checks, placeholder substitution, engine parse + validate."""
    role_types = {name: role.type for name, role in doc.roles.items()}
    diags = roles_mod.role_diagnostics(role_types, set(verb_catalog()))
    try:
        expanded = expand_dict(doc.workflow)  # for_each/group(tube) -> concrete roles (§9)
    except WorkflowLoadError as exc:
        return diags + [{"category": "expansion", "path": "workflow", "message": str(exc)}]
    substituted, ref_diags = roles_mod.substitute(
        expanded, roles_mod.placeholder_ids(role_types)
    )
    diags += ref_diags
    if diags:
        return diags  # substitution unsound; engine output would duplicate (plan P3)
    try:
        workflow = workflow_from_dict(substituted)
    except WorkflowLoadError as exc:
        return [{"category": "schema", "path": "workflow", "message": str(exc)}]
    try:
        validate(workflow)
    except ValidationError as exc:
        return [
            {"category": d.category, "path": d.path, "message": d.message}
            for d in exc.diagnostics
        ]
    return []
