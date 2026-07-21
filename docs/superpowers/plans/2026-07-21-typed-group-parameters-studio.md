# Typed Group Parameters — Studio Implementation Plan (PR 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Experiment Studio webapp speak engine schema 2 — typed group params, group locals, typed `for_each` rows, and roles that live inside the workflow — restoring the webapp CI to green so PR 1 (engine) and PR 2 (Studio) land together.

**Architecture:** The engine half (branch `feat/group-param-types`, PR #50) already speaks schema 2. This branch (`feat/studio-typed-params`) is stacked on it. The backend's redundant role machinery is deleted because the engine now owns role resolution, validation, and expansion via `RunOptions.role_mapping`; the frontend's self-contained TS mirror is upgraded to the schema-2 shapes and typed editors. Roles move from the doc envelope into `workflow.roles` on both sides.

**Tech Stack:** Python 3.14 (webapp/backend, FastAPI + Pydantic), TypeScript + React + Zustand + Vite + Vitest (webapp/frontend). No new dependencies.

## Global Constraints

- **Design spec:** `docs/superpowers/specs/2026-07-20-typed-group-parameters-design.md` §5, §9.2.
- **Branch:** `feat/studio-typed-params`, stacked on `feat/group-param-types` (frozen at 7bfc585 = PR #50). PR 2's base is `feat/group-param-types`, so its CI runs engine+Studio and is fully green.
- **This worktree's `.venv`** (at the worktree root) has BOTH the engine and `webapp/backend` installed editable. Backend commands run from `webapp/backend` using `../../.venv/bin/python`. The frontend has `node_modules` from `npm ci`.
- **Backend gate:** from `webapp/backend`: `../../.venv/bin/python -m pytest -q`, `../../.venv/bin/python -m mypy`, `../../.venv/bin/python -m ruff check .`. All clean.
- **Frontend gate:** from `webapp/frontend`: `npm run lint` (oxlint, zero errors — warnings OK), `npm test` (vitest run), `npm run build` (`tsc -b && vite build` — tsc must be clean).
- **Baselines:** `.superpowers/sdd/webapp-backend-red.txt` (48 failing) and `webapp-frontend-red.txt` (2 failing). The failing set may only SHRINK; the increment ends with BOTH gates fully green.
- **Shared fixtures:** `webapp/fixtures/*.json` and `gen_run.py`/`gen_torture.py` are touched by BOTH S1 and S2. S1 runs first and migrates them; S2 treats them as verify-only. Do not double-migrate.
- **Test discipline:** every negative/assertion test pins a specific shape or message, never merely "it loaded" — this codebase has a documented history of vacuous tests. Backend tests flat `tests/test_*.py`; frontend `*.test.ts` alongside source.
- **Roles-in-workflow key order** (must match engine `workflow_to_dict`): `[schema_version, metadata, persistence, defaults, roles, streams, groups, blocks]`, optional sections omitted when empty. Envelope key order: `[doc_version, name, description, workflow]`.

All task code below was verified against the landed schema-2 engine in this worktree during planning: diagnostic messages, remapped paths, the byte-exact morbidostat round-trip, and the tsc ripple set.

---

### Task S1: Backend speaks schema 2

Make the webapp-backend gate green under engine schema 2. The engine now owns role resolution, validation, and expansion via `ExperimentRun` + `RunOptions.role_mapping`; roles live inside the workflow (`workflow.roles`), group `params`/`for_each` `vars` are typed objects, and `SCHEMA_VERSION == 2`. This task deletes the webapp's redundant role machinery (`roles.py`'s `substitute`/`placeholder_ids`/`role_diagnostics`), simplifies `validate_doc` to *expand → engine parse → engine validate → path-remap* (the `_remap*` machinery is kept), rebuilds the runner around handing the engine `workflow + role_mapping` (keeping a lab-only roster/type preflight), migrates every fixture to schema 2, and rewrites the failing tests. The force-multiplier is `tests/runsupport.py::make_doc`.

**Baseline:** `.superpowers/sdd/webapp-backend-red.txt` lists 48 failing tests; this task empties it. Several currently-green tests (`test_doc_level_diagnostics`, `test_docs_store` CRUD roles assertion, `test_persistence_forced_to_disk_csv` device assertion) break under the source changes and are rewritten here so the gate ends fully green.

**Files:**
- **Delete** `webapp/backend/experiment_studio/roles.py` (nothing survives; the kept `_remap*` machinery in `docs_store.py` imports nothing from it).
- **Delete** `webapp/backend/tests/test_roles.py` (every test targets deleted machinery).
- **Modify** `webapp/backend/experiment_studio/docs_store.py` — imports (16–25), drop `RoleDef` (29–30) and `ExperimentDoc.roles` (39), rewrite `validate_doc` (251–281). Keep `_quoted_group_head_end`/`_remap_group_segment`/`_remap`/`_remap_diagnostics` (160–248) and the `ExperimentsStore` CRUD (72–157) verbatim.
- **Modify** `webapp/backend/experiment_studio/runner.py` — imports (28, 34), replace `_mapping_diagnostics` (101–116) with a lab-independent shape check, rewrite the preflight/build section of `_start_checked` (287–304, 322–339). Keep `_force_disk_persistence`, `_engine_diagnostics`, and the failed-record finalization paths.
- **Modify** `webapp/backend/tests/runsupport.py` — `make_doc` (55–77).
- **Modify** `webapp/backend/tests/test_docs_store.py` — local `make_doc` (26–35), the roundtrip roles assertion (41), all 10 remap tests (145–514).
- **Modify** `webapp/backend/tests/test_validate_api.py` — `_doc` (92–99), `_parallel_stop` (140–149), schema-2/role tests (18–67, 102–197).
- **Modify** `webapp/backend/tests/test_runner.py` — `test_persistence_forced_to_disk_csv` (92–109), `test_for_each_templated_roles_expand_before_run_substitution` (243–268).
- **Modify** fixtures `webapp/fixtures/{valid-od-growth,valid-control-blocks,invalid-roles,invalid-workflow}.json`.
- **Modify** generators `webapp/fixtures/gen_run.py` (`build`, 54–97) and `gen_torture.py` (`build`, 156–272), regenerate `ui-audit-run.json`/`ui-audit-torture.json`.
- **No edits** (green via `runsupport.make_doc`+runner alone): `test_runner_controls.py`, `test_runs_api.py`, `test_records_api.py`, `test_ws_api.py`, and the non-substitution `test_runner.py` tests.

**Interfaces:**

Consumes (engine, landed): `workflow_from_dict(d)->Workflow` (raises `WorkflowLoadError`/`UnknownRoleError`); `expand_dict_traced(d)->(expanded, trace)` (raises `WorkflowLoadError`); `validate(w)->None` (raises `ValidationError` with `.diagnostics: list[Diagnostic(category,path,message)]`); `RunOptions(*, log_sink, input_provider, output_dir, role_mapping: dict[str,str]={}, **knobs)`; `ExperimentRun(client, workflow, options)` (resolves roles+injectivity BEFORE validate, then validates+expands; non-injective/unbound→`WorkflowLoadError`, bad workflow→`ValidationError`); `LabClient.list_devices()->list[DeviceInfo]` where `DeviceInfo.id: str|None`, `DeviceInfo.type: str|None`.

Produces: `ExperimentDoc(doc_version: Literal[1], name, description, workflow: dict)` — no `roles` field, envelope order `[doc_version,name,description,workflow]`; `validate_doc(doc)->list[dict]` (`[]` clean, else `{category,path,message}` with remapped authored paths); `RunManager.start(experiment_id, lab, role_mapping)->str` (raises `PreflightError([{category:"mapping",...}])` before record creation; `StartValidationError(diags, record_id)` on engine rejection).

- [ ] **Step 1 — Rewrite `runsupport.make_doc` to schema 2 (the force-multiplier).**

Replace `make_doc` (55–77) verbatim (`HAPPY_BLOCKS`/`INPUT_BLOCKS`/`INVALID_BLOCKS`/`MAPPING`/`LAB`/`FAST_RUN_OPTIONS`/`default_fake`/`fake_registry`/`fake_client_factory` unchanged — their `device:"feed"/"meter"` are role names resolving against the default roles):

```python
def make_doc(
    blocks: list[dict[str, Any]],
    *,
    name: str = "Growth run",
    roles: dict[str, dict[str, str]] | None = None,
    streams: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A schema-2 experiment doc. Roles live INSIDE the workflow now (design 2026-07-20 §5);
    the envelope carries no `roles` key. `device:` fields hold role names the engine resolves
    via RunOptions.role_mapping at run start."""
    return {
        "doc_version": 1,
        "name": name,
        "workflow": {
            "schema_version": 2,
            "metadata": {"name": name},
            "persistence": {"default": "in_memory", "format": "jsonl"},
            "roles": (
                roles
                if roles is not None
                else {"feed": {"type": "pump"}, "meter": {"type": "densitometer"}}
            ),
            "streams": streams if streams is not None else {"od": {"units": "AU"}},
            "blocks": blocks,
        },
    }
```

- [ ] **Step 2 — Simplify `docs_store.py`.**

Imports (16–25) → drop `verb_catalog` and `from experiment_studio import roles as roles_mod`:
```python
from lab_devices.experiment import (
    ValidationError,
    WorkflowLoadError,
    validate,
    workflow_from_dict,
)
from lab_devices.experiment.expand import expand_dict_traced

from experiment_studio.db import Database
```
Delete `RoleDef` (29–30). `ExperimentDoc` loses `roles`:
```python
class ExperimentDoc(BaseModel):
    """Saved unit (§4.1): wraps the engine workflow JSON; `device` fields hold role names.
    Roles live inside `workflow` now (design 2026-07-20 §5) — the envelope has no `roles`."""

    doc_version: Literal[1]
    name: str = Field(min_length=1)
    description: str | None = None
    workflow: dict[str, Any]
```
Rewrite `validate_doc` (251–281):
```python
def validate_doc(doc: ExperimentDoc) -> list[dict[str, str]]:
    """§4.3: expand (traced) -> engine parse -> engine validate -> remap paths to authored.

    Roles live inside the workflow and the engine validates them (design 2026-07-20 §5), so
    there is no doc-level role check and no placeholder substitution here. The trace maps every
    expanded index back to the authored block so for_each/group_ref diagnostics collapse to one
    per authored block. `doc_version` stays 1 — the envelope version is independent of the
    workflow's `schema_version`."""
    try:
        expanded, trace = expand_dict_traced(doc.workflow)
    except WorkflowLoadError as exc:
        return [{"category": "expansion", "path": "workflow", "message": str(exc)}]
    try:
        workflow = workflow_from_dict(expanded)
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
```

- [ ] **Step 3 — Rebuild `runner.py`.**

Delete `from lab_devices.experiment.expand import expand_dict` (28) and `from experiment_studio.roles import substitute` (34); add `import copy`. Replace `_mapping_diagnostics` (101–116):
```python
def _mapping_shape_diagnostics(
    doc: ExperimentDoc, role_mapping: dict[str, str]
) -> list[dict[str, str]]:
    """§7.1.2 lab-independent checks: every declared role is mapped, and no mapping key names
    an undeclared role. Device EXISTENCE and TYPE need the live roster (the engine can't see
    the lab) and are checked in `_start_checked`."""
    roles = doc.workflow.get("roles", {})
    roles = roles if isinstance(roles, dict) else {}
    diagnostics: list[dict[str, str]] = []
    for role in roles:
        if role_mapping.get(role) is None:
            diagnostics.append(_diag(role, f"role {role!r} is not mapped to a device"))
    for extra in sorted(set(role_mapping) - set(roles)):
        diagnostics.append(_diag(extra, f"mapping references unknown role {extra!r}"))
    return diagnostics
```
In `start`, swap the call at ~265 to `_mapping_shape_diagnostics(doc, role_mapping)`. Rewrite the top of `_start_checked` (287–304) — roster yields id→type, folding existence+type into one lab pass; the `expand_dict`+`substitute` preprocessing is deleted:
```python
    roster = {
        device.id: device.type
        for device in await client.list_devices()
        if device.id
    }
    roles = doc.workflow.get("roles", {})
    roles = roles if isinstance(roles, dict) else {}
    roster_diags: list[dict[str, str]] = []
    for role, device_id in sorted(role_mapping.items()):
        spec = roles.get(role)
        rtype = spec.get("type") if isinstance(spec, dict) else None
        if device_id not in roster:
            roster_diags.append(_diag(role, f"device {device_id!r} not found in lab {lab!r}"))
        elif roster[device_id] != rtype:
            roster_diags.append(_diag(role, f"device {device_id!r} is not a {rtype!r}"))
    if roster_diags:
        raise PreflightError(roster_diags)
    workflow_dict = copy.deepcopy(doc.workflow)
    _force_disk_persistence(workflow_dict)  # §7.2 still applies to the run copy
```
In the artifact-writing block (322–339), write the disk-forced workflow dict (role names intact) and build the engine `Workflow` from it, passing the mapping:
```python
        (artifact_dir / "doc.json").write_text(json.dumps(stored["doc"], indent=2))
        (artifact_dir / "workflow.json").write_text(json.dumps(workflow_dict, indent=2))

        tee = TeeRunLogSink()
        inputs = WebInputProvider()
        options = RunOptions(
            log_sink=tee,
            input_provider=inputs,
            output_dir=artifact_dir,
            role_mapping=role_mapping,
            **self._run_options,
        )
        try:
            # The engine resolves roles (injectivity BEFORE validate), validates against the
            # real mapping, and expands (design 2026-07-20 §5.4).
            run = ExperimentRun(client, workflow_from_dict(workflow_dict), options)
        except (ValidationError, WorkflowLoadError) as exc:
```
The existing `except (ValidationError, WorkflowLoadError)` handler covers `UnknownRoleError` and the injectivity `WorkflowLoadError`, so the StartValidationError/failed-record path is unchanged.

- [ ] **Step 4 — Delete redundant modules.**
```bash
cd /Users/khamit/lab-devices/.claude/worktrees/group-param-types/webapp/backend
git rm experiment_studio/roles.py tests/test_roles.py
```
Coverage disposition: old `role_diagnostics` (unknown device type) is now the engine's `WorkflowLoadError`, re-covered by `test_doc_level_diagnostics` (Step 6). Role-name shape is no longer enforced anywhere (dropped by design — roles are typed declarations now). The walker/serializer sync check is moot (the walker is gone).

- [ ] **Step 5 — Migrate the four hand fixtures to schema 2.**

`webapp/fixtures/valid-od-growth.json`:
```json
{
  "doc_version": 1,
  "name": "OD growth curve",
  "description": "Feed once, then measure OD every 30 s until mean of last 3 crosses 0.6.",
  "workflow": {
    "schema_version": 2,
    "metadata": {"name": "OD growth curve"},
    "persistence": {"default": "in_memory", "format": "jsonl"},
    "roles": {"feed_pump": {"type": "pump"}, "od_meter": {"type": "densitometer"}},
    "streams": {"od": {"units": "AU"}},
    "blocks": [
      {"serial": {"children": [
        {"command": {"device": "feed_pump", "verb": "dispense", "params": {"volume_ml": 5}}},
        {"loop": {
          "until": "mean(od, last=3) > 0.6",
          "check": "after",
          "pace": "30s",
          "body": [
            {"measure": {"device": "od_meter", "verb": "measure", "into": "od"}},
            {"wait": {"duration": "5s"}}
          ]
        }}
      ]}}
    ]
  }
}
```
`valid-control-blocks.json` — same body as today, `schema_version: 2`, `"roles": {"od_meter": {"type": "densitometer"}}` moved inside `workflow` before `streams`, envelope `roles` removed.

`invalid-workflow.json`:
```json
{
  "doc_version": 1,
  "name": "Broken workflow",
  "description": null,
  "workflow": {
    "schema_version": 2,
    "roles": {"feed_pump": {"type": "pump"}, "od_meter": {"type": "densitometer"}},
    "blocks": [
      {"serial": {"children": [
        {"command": {"device": "feed_pump", "verb": "dispense"}},
        {"measure": {"device": "od_meter", "verb": "measure", "into": "od"}}
      ]}}
    ]
  }
}
```
→ `params`/`blocks[0].children[0]` + `declaration`/`blocks[0].children[1]`.

`invalid-roles.json` — repurposed to a single unknown-device-type case (role-name-shape / undeclared-role checks no longer exist as doc-level diagnostics):
```json
{
  "doc_version": 1,
  "name": "Broken roles",
  "description": null,
  "workflow": {"schema_version": 2, "roles": {"mixer": {"type": "stirrer"}}, "blocks": []}
}
```
→ `{"category":"schema","path":"workflow","message":"role 'mixer': unknown device type 'stirrer'; known types are ['densitometer', 'pump', 'valve']"}`.

- [ ] **Step 6 — Rewrite `test_validate_api.py`.**

Replace `_doc` (92–99) and `_parallel_stop` (140–149):
```python
def _doc(workflow: dict[str, Any], roles: dict[str, Any] | None = None) -> dict[str, Any]:
    wf = dict(workflow)
    if roles is not None:
        wf["roles"] = roles
    return {"doc_version": 1, "name": "t", "description": None, "workflow": wf}


def _parallel_stop(device_a: str, device_b: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "blocks": [
            {"parallel": {"children": [
                {"command": {"device": device_a, "verb": "stop"}},
                {"command": {"device": device_b, "verb": "stop"}},
            ]}},
        ],
    }
```
`test_valid_doc_is_clean`, `test_valid_control_blocks_doc_is_clean`, `test_morbidostat_example_is_clean`, `test_malformed_doc_is_422` unchanged (they load migrated fixtures / the real example). Rewrite the rest:
```python
async def test_doc_level_diagnostics(client: httpx.AsyncClient) -> None:
    """An unknown device type in `roles` is the engine's WorkflowLoadError now, surfaced as a
    single schema diagnostic (the old 3-way role_diagnostics is gone with roles.py)."""
    resp = await client.post("/api/validate", json=load_fixture("invalid-roles.json"))
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": False,
        "diagnostics": [
            {
                "category": "schema",
                "path": "workflow",
                "message": (
                    "role 'mixer': unknown device type 'stirrer'; "
                    "known types are ['densitometer', 'pump', 'valve']"
                ),
            }
        ],
    }


async def test_engine_diagnostics_pass_through_with_structural_paths(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post("/api/validate", json=load_fixture("invalid-workflow.json"))
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": False,
        "diagnostics": [
            {"category": "params", "path": "blocks[0].children[0]",
             "message": "missing required param 'volume_ml' for verb 'dispense'"},
            {"category": "declaration", "path": "blocks[0].children[1]",
             "message": "measure writes undeclared stream 'od'"},
        ],
    }


async def test_schema_two_is_accepted(client: httpx.AsyncClient) -> None:
    """The former 'reject schema 2' test: schema 2 is now the supported version."""
    resp = await client.post("/api/validate", json=_doc({"schema_version": 2, "blocks": []}))
    assert resp.json() == {"ok": True, "diagnostics": []}


async def test_unsupported_schema_version_is_schema_diagnostic(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post("/api/validate", json=_doc({"schema_version": 3, "blocks": []}))
    body = resp.json()
    assert body["ok"] is False
    diag = body["diagnostics"][0]
    assert diag["category"] == "schema" and diag["path"] == "workflow"
    assert "unsupported schema_version 3; expected 2" in diag["message"]


async def test_bad_expression_grammar_is_schema_diagnostic(client: httpx.AsyncClient) -> None:
    workflow = {
        "schema_version": 2,
        "streams": {"od": {"units": "AU"}},
        "blocks": [
            {"loop": {"until": "mean(od[-3:]) > 0.6", "body": [{"wait": {"duration": "1s"}}]}},
        ],
    }
    resp = await client.post("/api/validate", json=_doc(workflow))
    body = resp.json()
    assert body["ok"] is False and len(body["diagnostics"]) == 1
    diag = body["diagnostics"][0]
    assert diag["category"] == "schema" and diag["path"] == "workflow"
    assert "unexpected character" in diag["message"]


async def test_distinct_roles_of_same_type_are_clean(client: httpx.AsyncClient) -> None:
    roles = {"feed": {"type": "pump"}, "waste": {"type": "pump"}}
    resp = await client.post("/api/validate", json=_doc(_parallel_stop("feed", "waste"), roles))
    assert resp.json() == {"ok": True, "diagnostics": []}


async def test_same_role_in_parallel_lanes_hits_engine_affinity_check(
    client: httpx.AsyncClient,
) -> None:
    roles = {"feed": {"type": "pump"}}
    resp = await client.post("/api/validate", json=_doc(_parallel_stop("feed", "feed"), roles))
    body = resp.json()
    assert body["ok"] is False
    assert [d["category"] for d in body["diagnostics"]] == ["affinity"]
    assert body["diagnostics"][0]["path"] == "blocks[0]"


async def test_for_each_typed_role_var_validates_clean(client: httpx.AsyncClient) -> None:
    """A for_each over a typed role<densitometer> column replaces v1 od_meter_{t} string
    surgery (design §4). Concrete role names are declared, so it validates clean unbound (§5.4)."""
    workflow = {
        "schema_version": 2,
        "roles": {"od_meter_1": {"type": "densitometer"}, "od_meter_2": {"type": "densitometer"}},
        "streams": {"od_1": {"units": "AU"}, "od_2": {"units": "AU"}},
        "blocks": [
            {"for_each": {
                "vars": [
                    {"name": "meter", "kind": "role", "device_type": "densitometer"},
                    {"name": "od", "kind": "stream"},
                ],
                "in": [{"meter": "od_meter_1", "od": "od_1"}, {"meter": "od_meter_2", "od": "od_2"}],
                "body": [{"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"}}],
            }},
        ],
    }
    resp = await client.post("/api/validate", json=_doc(workflow))
    assert resp.json() == {"ok": True, "diagnostics": []}


async def test_malformed_for_each_yields_expansion_diagnostic(client: httpx.AsyncClient) -> None:
    workflow = {
        "schema_version": 2,
        "blocks": [{"for_each": {
            "vars": [{"name": "t", "kind": "int"}], "in": [],
            "body": [{"wait": {"duration": "1s"}}],
        }}],
    }
    resp = await client.post("/api/validate", json=_doc(workflow))
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": False,
        "diagnostics": [{"category": "expansion", "path": "workflow",
                         "message": "for_each 'in' must be a non-empty list"}],
    }


async def test_non_object_group_ref_body_yields_diagnostic_not_500(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post(
        "/api/validate", json=_doc({"schema_version": 2, "blocks": [{"group_ref": 42}]})
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False and body["diagnostics"]
```
Delete the old `test_distinct_roles_of_same_type_get_distinct_placeholders` and `test_for_each_templated_roles_expand_before_substitution` bodies.

- [ ] **Step 7 — Rewrite `test_docs_store.py`.**

Local `make_doc` (26–35):
```python
def make_doc(name: str = "OD growth curve", **overrides: Any) -> ExperimentDoc:
    payload: dict[str, Any] = {
        "doc_version": 1,
        "name": name,
        "description": "demo",
        "workflow": {"schema_version": 2, "roles": {"feed_pump": {"type": "pump"}}, "blocks": []},
    }
    payload.update(overrides)
    return ExperimentDoc.model_validate(payload)
```
`test_create_get_roundtrip` roles assertion (41): `assert created["doc"]["workflow"]["roles"] == {"feed_pump": {"type": "pump"}}`. The 10 remap tests (145–514) rewritten to schema-2 doc shapes with the verified authored paths — the full bodies (`test_a_diagnostic_inside_a_for_each_body_reports_the_authored_path`, `..._plain_group_ref_under_for_each_...`, `..._through_a_parametrized_group_...`, `..._no_arrow_...`, `..._for_each_inside_a_plain_groups_own_body_...`, `..._doubly_nested_...`, `..._unmappable_...`, `..._spaced_group_name_...` using a PARAMETRIZED group so the diagnostic keeps the head-form path, `..._dedup_key_includes_the_message_...` embedding a value-kind hole in an expression `nope_{t} > 1`, `..._plain_group_calling_a_parametrized_group_...`) are transcribed from the planning verification; each pins its exact authored path and (where relevant) message.

- [ ] **Step 8 — Rewrite the two device-substitution assertions in `test_runner.py`.**

`test_persistence_forced_to_disk_csv` (105): the run copy is no longer substituted, so the persisted `workflow.json` keeps the role name: `assert workflow["blocks"][0]["serial"]["children"][0]["command"]["device"] == "feed"`. Replace `test_for_each_templated_roles_expand_before_run_substitution` (243–268) with a schema-2 typed-role-var run whose oracle is that the engine resolves the templated roles and both devices are exercised:
```python
async def test_for_each_typed_role_var_runs_against_both_devices(
    env: SimpleNamespace,
) -> None:
    """A for_each over a typed role<densitometer> column (design §4) runs to completion; the
    engine resolves each row's concrete role to its mapped device — no webapp substitution."""
    env.fake.add_device("densitometer_2", "densitometer")
    roles = {"meter_1": {"type": "densitometer"}, "meter_2": {"type": "densitometer"}}
    streams = {"od_1": {"units": "AU"}, "od_2": {"units": "AU"}}
    blocks = [{"for_each": {
        "vars": [
            {"name": "meter", "kind": "role", "device_type": "densitometer"},
            {"name": "od", "kind": "stream"},
        ],
        "in": [{"meter": "meter_1", "od": "od_1"}, {"meter": "meter_2", "od": "od_2"}],
        "body": [{"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"}}],
    }}]
    mapping = {"meter_1": "densitometer_1", "meter_2": "densitometer_2"}
    experiment_id = await _create_doc(env, blocks, roles=roles, streams=streams)
    run_id = await env.manager.start(experiment_id, runsupport.LAB, mapping)
    await _finish(env)

    record = await RecordsStore(env.db, env.data_dir).get(run_id)
    assert record["status"] == "completed"
    measured = {device for device, cmd, _ in env.fake.calls if cmd == "measure"}
    assert measured == {"densitometer_1", "densitometer_2"}
    art = env.data_dir / f"runs/{run_id}"
    assert (art / "od_1.csv").is_file() and (art / "od_2.csv").is_file()
```

- [ ] **Step 9 — Migrate the fixture generators and regenerate.**

`gen_run.py::build` (54–97) — only the returned envelope changes (roles under `workflow`, `schema_version` 2, envelope loses `roles`). `gen_torture.py::build` (156–272) — module constants/helpers unchanged; the two `for_each` blocks become `vars`+typed rows, the `groups` dict becomes typed params (`service`/`wash cycle`/`deep_group` gain `params: [{name, kind:"int"}...]`; `long_label_group`/`empty_body_group` keep bare `body`), and roles move under `workflow`. The two `group_ref` args blocks stay (no locals → no `as` required, int args match typed params). Regenerate and self-verify:
```bash
cd /Users/khamit/lab-devices/.claude/worktrees/group-param-types
.venv/bin/python webapp/fixtures/gen_run.py
.venv/bin/python webapp/fixtures/gen_torture.py
cd webapp/backend && ../../.venv/bin/python -c "import json; from experiment_studio.docs_store import validate_doc, ExperimentDoc; assert validate_doc(ExperimentDoc.model_validate(json.load(open('../fixtures/ui-audit-run.json'))))==[]; print('run fixture clean')"
../../.venv/bin/python -c "import json; from lab_devices.experiment import workflow_from_dict; from lab_devices.experiment.expand import expand_dict; workflow_from_dict(expand_dict(json.load(open('../fixtures/ui-audit-torture.json'))['workflow'])); print('torture parses')"
```

- [ ] **Step 10 — Full webapp-backend gate; confirm baseline empty; commit.**
```bash
cd /Users/khamit/lab-devices/.claude/worktrees/group-param-types/webapp/backend
../../.venv/bin/python -m pytest -q
../../.venv/bin/python -m mypy
../../.venv/bin/python -m ruff check .
```
Expected: pytest `0 failed` (every name in `.superpowers/sdd/webapp-backend-red.txt` passing), mypy `Success`, ruff `All checks passed!`. Commit on `feat/studio-typed-params`.

**Gate at task end:** the full webapp-backend gate — pytest (0 failed, baseline empty), mypy, ruff — all green.

### Task S2: Frontend data model speaks schema 2

The coupled type-and-data core. Because this is a self-contained TS mirror and `tsc -b` type-checks **every** file under `src` including `*.test.ts`, the schema-2 shapes ripple through the whole type layer at once. Everything that would otherwise fail `tsc` or turn a green test red lands here. The designed typed *editors* are S3; here the three group/for_each Inspector forms get correct **compile-and-round-trip shims** only.

**Files (source):** `types/doc.ts` (new typed shapes); `builder/tree.ts` (`ForEachNode` vars/rows, `GroupRefNode` +as, seeds); `builder/convert.ts` (schema-2 import/export, roles-in-workflow, DocContent); `stores/docStore.ts` (groups shape params+locals, `setGroupParams` typed, new `setGroupLocals`, roles `device?`); `stores/draftStorage.ts` (non-v2 discard); `builder/summary.ts` (for_each reads vars/rows); `builder/paths.ts` (`GroupsMap` → `{ body }`); `builder/Inspector.tsx` (GroupProperties/ForEachForm/GroupRefForm compile shims; delete `forEachItemsWarning`); `run/PreflightPanel.tsx` (`doc.roles` → `doc.workflow.roles`, 3 sites).

**Files (fixtures — shared with S1; verify-only if S1 migrated them):** `webapp/fixtures/{valid-od-growth,valid-control-blocks,invalid-roles,invalid-workflow}.json`, `gen_torture.py`, `gen_run.py`.

**Files (tests):** rewrite `builder/convert.test.ts`, `stores/docStore.test.ts`, `builder/files.test.ts`, `stores/draftStorage.test.ts`; mechanically migrate `builder/paths.test.ts`, `builder/__tests__/torture.test.ts`, `builder/summary.test.ts`, `shell/urlSyncRules.test.ts`, `shell/urlFocus.test.ts`, `stores/runStore.test.ts` (verify `shell/bootstrap.test.ts` — its `content()` is a `DocContent` draft keeping flat `roles`, likely no change).

**Interfaces:**

Consumes (engine PR 1): `examples/morbidostat.json` is schema 2 with `workflow.roles`, typed group `params`, group `locals`, `for_each` `vars`+rows. `workflow_to_dict` key order is `[schema_version, metadata, persistence, defaults, roles, streams, groups, blocks]` (all conditional except schema_version/blocks).

Produces (exact signatures):
```ts
// types/doc.ts
export type ParamValue = number | string | boolean
export type ParamKind = 'int' | 'number' | 'bool' | 'string' | 'role' | 'stream' | 'binding'
export const VALUE_KINDS = ['int', 'number', 'bool', 'string'] as const
export const REFERENCE_KINDS = ['role', 'stream', 'binding'] as const
export interface ParamDeclJson { name: string; kind: ParamKind; device_type?: string }
export interface LocalDeclJson { kind: 'stream' | 'binding'; init?: string; units?: string; persistence?: string }
export interface RoleDeclJson { type: string; device?: string }
export interface GroupJson { params?: ParamDeclJson[]; locals?: Record<string, LocalDeclJson>; body: BlockJson[] }
export interface GroupRefBody { name: string; as?: string; args?: Record<string, ParamValue> }
export interface ForEachBody { vars: ParamDeclJson[]; in: Array<Record<string, ParamValue>>; body: BlockJson[] }
export interface WorkflowJson { schema_version: number; metadata?: Record<string, unknown>; persistence?: Record<string, unknown>; roles?: Record<string, RoleDeclJson>; streams?: Record<string, StreamDeclJson>; groups?: Record<string, GroupJson>; defaults?: { retry?: RetryJson }; blocks: BlockJson[] }
export interface ExperimentDocJson { doc_version: number; name: string; description: string | null; workflow: WorkflowJson }
// builder/tree.ts
export interface ForEachNode extends NodeBase { kind: 'for_each'; vars: ParamDeclJson[]; rows: Array<Record<string, ParamValue>>; body: BlockNode[] }
export interface GroupRefNode extends NodeBase { kind: 'group_ref'; name: string; as: string | null; args: Record<string, ParamValue> }
// builder/convert.ts
export type GroupDef = { params: ParamDeclJson[]; locals: Record<string, LocalDeclJson>; body: BlockNode[] }
export interface DocContent { name: string; description: string | null; roles: Record<string, RoleDeclJson>; streams: Record<string, { units: string | null; persistence?: string | null }>; tree: BlockNode[]; persistence?: WorkflowJson['persistence']; defaults?: WorkflowJson['defaults']; metadata?: WorkflowJson['metadata']; groups?: Record<string, GroupDef> }
export function docToTree(doc: ExperimentDocJson): DocContent
export function treeToDoc(content: DocContent): ExperimentDocJson
// stores/docStore.ts
setGroupParams: (name: string, params: ParamDeclJson[]) => void
setGroupLocals: (name: string, locals: Record<string, LocalDeclJson>) => void
addRole: (name: string, type: string, device?: string) => string | null
// builder/paths.ts
export type GroupsMap = Record<string, { body: BlockNode[] }>
```
The contract's "DocContent drops the top-level roles field" means the emitted **envelope** loses `roles`; `DocContent` (the editor form) KEEPS a flat `roles` field (gaining `device?`), because docStore's `selectContent`/`snapshotOf`/`partialize` must include it; `treeToDoc` places `content.roles` under `workflow.roles`.

**Steps** (abbreviated — full test bodies and the complete `convert.ts` import/export were verified during planning and are transcribed into the task brief):

1. [ ] Confirm the baseline red set: `cd webapp/frontend && npm test 2>&1 | tail -5` → `2 failed` (the two morbidostat byte-for-byte round-trips).
2. [ ] **Rewrite the data-layer tests to the schema-2 target first (RED)** — `files.test.ts` (roles into workflow, key-order test drops `roles`), `draftStorage.test.ts` (v `2`; add a v1-discard test), `convert.test.ts` (typed for_each rows; typed group params+locals+`as`; plain param-less group_ref; role-with-device round-trip; "emits roles inside the workflow" assertion), `docStore.test.ts` (`setGroupParams`/`setGroupLocals` typed+dirty; `groupRef()` helper node shape `{ as: null, args: {} }`; `emptyDocContent` groups `{ params: [], locals: {}, body: [] }`).
3. [ ] **doc.ts** — the Produces shapes; delete `RoleDefJson` and the envelope `roles`.
4. [ ] **tree.ts** — retype the two nodes; reseed for_each `{ vars: [{name:'tube',kind:'int'}], rows: [{tube:1},{tube:2},{tube:3}] }`, group_ref `{ name:'', as:null, args:{} }`; `newGroupRefNode` sets `as:null`.
5. [ ] **convert.ts** — full import/export rewrite: `docToTree` accepts `schema_version===2`, reads roles from `wf.roles`, imports typed params/locals/for_each-rows/group_ref-`as`; `treeToDoc` emits `schema_version:2`, writes roles into `workflow.roles` with the engine key order, DocContent keeps flat `roles`.
6. [ ] **docStore.ts** — `DocSnapshot.roles: Record<string, RoleDeclJson>`, `.groups: Record<string, GroupDef>`; `setGroupParams` typed; new `setGroupLocals`; `addRole(name,type,device?)`; `addGroup` seeds `{ params:[], locals:{}, body:[] }`; `setActiveList` preserves locals. `selectContent`/`snapshotOf`/`partialize` already carry `roles`+`groups`; the new fields nest inside them, so no new top-level key — the docStore.ts:133-138 silent-drop hazard is closed by construction, guarded by the step-2 `setGroupLocals … dirty` test.
7. [ ] **draftStorage.ts** — `Draft.v: 2`; `parseDraft` returns null if `parsed.v !== 2`.
8. [ ] **Source ripple** — `summary.ts` for_each reads `vars`/`rows`; `paths.ts` `GroupsMap` → `{ body }`; `PreflightPanel.tsx` `doc.roles`→`doc.workflow.roles`; Inspector **compile shims** for the three forms (read-only summaries; delete `forEachItemsWarning`). Palette/Canvas `.params.join` still compiles (renders `[object Object]`, fixed in S3).
9. [ ] **Fixtures + peripheral tests** (verify-only for shared fixtures if S1 migrated them; migrate `paths.test.ts`/`summary.test.ts`/`urlSyncRules.test.ts`/`urlFocus.test.ts`/`runStore.test.ts`).
10. [ ] **Gate green**: `npm run build` (tsc clean), `npm test` (0 failed — the 2 baseline pass), `npm run lint` (0 errors).
11. [ ] Commit `feat(studio): frontend data model speaks workflow schema 2 (W17)`.

**Gate at task end:** `tsc -b` clean, full vitest green, lint zero errors.

### Task S3: Typed group/for_each/role UI

Replace the S2 compile shims with the designed typed editors, and fix runtime param-name rendering. Inspector/Palette/Canvas/RolesSection changes are DOM wiring, which this app verifies with the probe harness, not vitest (vitest is node-only, pure functions). So automated TDD targets small **pure helpers** extracted for the editors; the forms are gated by `lint` + `build` + `npm run capture`.

**Files:** `builder/groupArgs.ts` (new pure helpers) + `builder/groupArgs.test.ts` (new); `builder/Inspector.tsx` (real GroupProperties/GroupRefForm/ForEachForm); `builder/RolesSection.tsx` (confirm workflow-store source); `builder/Palette.tsx`, `builder/Canvas.tsx` (typed param names).

**Interfaces:** Consumes S2's `ParamKind`/`ParamDeclJson`/`LocalDeclJson`/`RoleDeclJson`, `setGroupParams`/`setGroupLocals`/`addRole`, typed `groups`/`roles` store fields, `ForEachNode.vars`/`.rows`, `GroupRefNode.as`/`.args`. Reuses `StreamIntoPicker` and the `ActionForm` role `<select>` pattern.

Produces (`groupArgs.ts`):
```ts
export type ArgEditor = 'role' | 'stream' | 'number' | 'integer' | 'bool' | 'text'
export function argEditorFor(kind: ParamKind): ArgEditor            // int→integer, number→number, bool→bool, string/binding→text, stream→stream, role→role
export function defaultArgValue(kind: ParamKind): ParamValue        // int/number→0, bool→false, else ''
export function asRequired(group: { locals: Record<string, LocalDeclJson> } | undefined): boolean  // true iff ≥1 local (design §6)
export function rolesOfType(roles: Record<string, RoleDeclJson>, deviceType: string | undefined): string[]
export function emptyRow(vars: ParamDeclJson[]): Record<string, ParamValue>
```

**Steps:**
1. [ ] **groupArgs.test.ts (RED)** — discriminating pure-logic tests for all six helpers (each kind→editor mapping; `asRequired` true only with locals; `rolesOfType` filters by declared type; `emptyRow` seeds one typed cell per var; `defaultArgValue` typed zero). Run → module-not-found.
2. [ ] **groupArgs.ts** — implement per the signatures; test green; commit `feat(studio): typed group-arg editor helpers`.
3. [ ] **Inspector `GroupProperties`** — typed param editor (name + kind `<select>` + `device_type` only when `kind==='role'`) via `setGroupParams`; locals editor (name + stream/binding + `init`/`units`) via `setGroupLocals`.
4. [ ] **Inspector `GroupRefForm`** — group `<select>` + `as` visibly required when `asRequired(groups[node.name])`; one kind-aware editor per param via `argEditorFor`: role → role `<select>` filtered by `rolesOfType(roles, p.device_type)`; stream → `StreamIntoPicker`; integer/number → `NumberField`; bool → bool `<select>`; text → `TextField`. Carry args by name on group switch. Commit `feat(studio): typed group param + kind-aware group_ref arg editors (W17)`.
5. [ ] **Inspector `ForEachForm`** — typed `vars` editor + a row grid (one typed column per var, cell editor via `argEditorFor`); "Add row" appends `emptyRow(node.vars)`; editing a var name/kind remaps every row key and re-seeds changed cells; patches via `patchBlock(node.uid, { vars, rows })`. Remove the JSON textarea.
6. [ ] **RolesSection.tsx** — confirm it consumes `useDocStore((s) => s.roles)` (S2's workflow-roles source); keep device-type grouping; no envelope assumption remains.
7. [ ] **Palette.tsx / Canvas.tsx** — render `group.params.map((p) => p.name).join(', ')` (fixes the `[object Object]` the S2 shims left).
8. [ ] **Gate green** — `npm run lint` (0 errors), `npm run build` (tsc+vite clean), `npm test` (full suite incl. `groupArgs.test.ts`), `npm run capture` on a doc exercising typed params/locals/role-column for_each (no R4 sibling-height or R5 contrast regressions on the new editors/grid).
9. [ ] Commit `feat(studio): typed for_each row grid, roles-from-workflow, typed param rendering (W17)`.

**Gate at task end:** lint clean, build clean, vitest green, probe capture clean.

### Task S4: Integration sweep — both webapp CI jobs green

**Files:** none new — run the full gates end to end, fix any straggler, commit the branch PR-ready.

- [ ] **Step 1: Full backend gate** — `cd webapp/backend && ../../.venv/bin/python -m pytest -q && ../../.venv/bin/python -m mypy && ../../.venv/bin/python -m ruff check .` → pytest 0 failed (baseline empty), mypy Success, ruff clean.
- [ ] **Step 2: Full frontend gate** — `cd webapp/frontend && npm run lint && npm test && npm run build` → lint 0 errors, vitest 0 failed, build exit 0.
- [ ] **Step 3: Shared-fixture consistency** — regenerate deterministically and confirm no diff:
```
cd /Users/khamit/lab-devices/.claude/worktrees/group-param-types
.venv/bin/python webapp/fixtures/gen_run.py && .venv/bin/python webapp/fixtures/gen_torture.py
git diff --stat webapp/fixtures/
```
Expected: no diff (committed generated fixtures match a fresh regeneration).
- [ ] **Step 4: Engine suite unperturbed** — `cd /Users/khamit/lab-devices/.claude/worktrees/group-param-types && .venv/bin/python -m pytest -q` → `943 passed` (or more), 0 failed.
- [ ] **Step 5: Commit stragglers; confirm PR-ready** — `git add -A && git commit -m "chore(studio): integration sweep — both webapp CI jobs green" || echo "nothing to commit"; git log --oneline feat/group-param-types..HEAD`.

**Gate at task end:** backend gate green, frontend gate green, engine suite green, fixtures consistent.
