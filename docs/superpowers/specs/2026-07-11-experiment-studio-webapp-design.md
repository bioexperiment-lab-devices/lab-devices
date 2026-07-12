# Experiment Studio — Web App Design

- **Date:** 2026-07-11
- **Status:** Approved for planning
- **Parent spec:** `2026-07-07-experiment-orchestrator-design.md` (as amended) and
  `2026-07-08-experiment-orchestrator-5-control-plane-design.md`. The engine
  (`lab_devices.experiment`, v1 complete on main) is the substrate; this doc designs the
  operator-facing web application on top of it. Where engine semantics are concerned, the
  engine specs win; the webapp adapts to them and never re-implements them.
- **Repo placement:** `webapp/` in this repository. Shipped as a single container image
  `ghcr.io/bioexperiment-lab-devices/experiment-studio`, integrated as one service in the
  lab-bridge docker-compose stack.

## 1. Scope

A single-user web application ("Experiment Studio") that lets a lab operator:

- **Discover** labs (via the lab-bridge roster) and the devices behind each lab agent.
- **Build** experiment workflows visually from drag-and-drop blocks — actions, measurements,
  waits, loops, branches, and **serial/parallel containers** (parallel supports **N lanes**,
  not just two) — with named measurement streams assignable to measurements.
- **Save/load** experiments and use saved experiments as starting points (duplicate,
  save-as).
- **Run** an experiment with pause / resume / abort, answer mid-run operator-input prompts,
  and watch a live chart of measurement streams plus a live event log.
- **Keep records**: one record per run (logs + results + workflow snapshot), which the
  operator can view, rename, delete, and download as a zip.

Out of scope for v1 (§13): auth/multi-user, reusable groups (`GroupRef`) editing,
expression autocomplete, concurrent runs, record comparison overlays, closed-loop recovery
UI. No engine feature work beyond the small public accessors in §4.4.

## 2. Settled decisions

User-settled at brainstorm (2026-07-11):

| # | Decision | Choice |
|---|---|---|
| S1 | Builder technology | **Custom tree builder** (dnd-kit), not Blockly / React Flow. Serial renders as a vertical stack, Parallel as **N side-by-side lanes** with add/remove-lane affordances. Rationale: maps 1:1 onto the engine's tree AST (no bidirectional translation layer), parallelism is *spatially* visible (Blockly stacks statement arms vertically), and param forms generate from the verb registry. |
| S2 | Device references | **Symbolic roles.** Workflows never contain concrete device ids. The builder defines roles (name + device type); blocks reference roles. Before each run the operator maps every role to a live device of that type. Mapping memory (pre-filled from the previous run of the same experiment+lab) is a **nice-to-have**, not core — may slip to a late increment without redesign. |
| S3 | Packaging | **Single image**: multi-stage Docker build; FastAPI serves both the API and the built frontend. One compose service, one caddy route. |
| S4 | v1 feature scope | Core blocks + **Branch (if/else)** + **OperatorInput with run-time prompts**. Stream-statistics conditions (e.g. `mean(od, last=5) > 0.6` in Loop `until` / Branch `if`) are first-class in expression fields. Groups and expression autocomplete deferred. |
| S5 | Stream persistence | **All streams are always recorded.** The builder exposes no persistence knobs; the streams panel is name + units only. The backend forces disk persistence on every run (§7.2). |
| S6 | Records placement | Four top-level tabs — Devices, Builder, Run, Records — stepper-styled but freely navigable. Records is its own tab so Run stays focused on the active run. |
| S7 | Run-log durability | Run log is written to disk **once, at run finish**, from the in-memory tee (§7.3). Streams are engine-flushed to disk every ~30 s throughout. A backend crash mid-run loses only the event-log tail, never stream data. Accepted for a single-user tool. |
| S8 | Concurrency | **One active run per app instance.** Starting a second run returns HTTP 409. Matches the engine's refuse-when-busy stance. |
| S9 | Release stream | Single release-please stream (the existing one). Every GitHub release builds and pushes the image tagged `<version>` and `latest`. No separate webapp versioning. |
| S10 | App name | `experiment-studio`; python package `experiment_studio`. |

## 3. Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI, uvicorn | The engine is asyncio and runs **in-process** — a browser refresh or closed laptop never touches a running experiment. One language across engine and API. Pydantic request/response models. |
| Live updates | WebSocket (FastAPI native) | Push run events + samples; supports replay-on-reconnect (§7.5). |
| Metadata store | SQLite via `aiosqlite` | Single user; two small tables plus a nice-to-have mapping table (§8.1). Hand-rolled `PRAGMA user_version` migrations, no ORM/alembic. |
| Run artifacts | Plain directories (§8.2) | The engine's own disk sinks already produce them; downloads are just zips. |
| Frontend | React 18 + TypeScript + Vite | Mainstream, reliable to generate and maintain. |
| Styling | Tailwind CSS | Utility-first, no design system to maintain. |
| Drag & drop | dnd-kit | Handles nested sortable trees; the canvas tree *is* the AST. |
| State | zustand + zundo | Document store with undo/redo via snapshots. |
| Charts | uPlot | Tiny, fast time-series; one live chart + record viewer. |

Dev mode: `vite dev` proxies `/api` to uvicorn on `:8000`; production serves built assets
from the image (no CORS anywhere).

## 4. Experiment document & roles

### 4.1 Document schema (webapp-owned, `doc_version: 1`)

The saved unit wraps the engine workflow JSON; the engine stays role-unaware:

```json
{
  "doc_version": 1,
  "name": "OD growth curve",
  "description": null,
  "roles": {
    "feed_pump": { "type": "pump" },
    "od_meter":  { "type": "densitometer" }
  },
  "workflow": {
    "schema_version": 1,
    "blocks": [ /* engine block JSON; every `device` field holds a ROLE NAME */ ],
    "streams": { "od": { "units": "AU" } },
    "metadata": { "name": "OD growth curve" },
    "persistence": { "default": "in_memory", "format": "jsonl" }
  }
}
```

- `workflow` is exactly the engine schema (`workflow_to_dict` shape, `SCHEMA_VERSION`
  pinned) except `device` fields hold role names. The webapp overwrites the `persistence`
  section on every run copy (§7.2), so whatever is stored there is inert.
- Role names: non-empty, unique, `[a-z][a-z0-9_]*` (they must survive placeholder
  substitution and read well in blocks). Role `type` ∈ the verb catalog's device types.
- `streams` entries carry `units` only (S5). `StreamDecl.persistence` is never written by
  the builder.

### 4.2 Role semantics in the builder

- The palette contains one section per defined role, offering that role's device-type verbs
  (from the catalog, §4.4) as Command/Measure blocks pre-bound to the role, plus a
  structure section (Serial, Parallel, Loop, Branch, Wait, OperatorInput).
- Renaming a role rewrites every referencing block (single undo step). Deleting a role that
  is still referenced is refused with a count of referencing blocks.
- Roles are cheap: "add role" asks for name + device type and immediately extends the
  palette.

### 4.3 Draft validation without a lab (placeholder substitution)

`POST /api/validate` (stateless, takes a full doc) gives the builder real engine
validation with no devices attached:

1. Deep-copy the workflow; replace each role name with a **distinct placeholder id** of its
   type: the i-th role of type `pump` becomes `pump_0`, `pump_1`, … (engine derives type as
   `device_id.rsplit("_", 1)[0]`, so this shape is load-bearing; distinct ids per role keep
   the validator's parallel-occupancy and mode-lifetime checks accurate).
2. Run engine `workflow_from_dict` + `validate()`; also validate doc-level rules the engine
   cannot see (role-name shape, unknown role referenced by a block, role type absent from
   catalog).
3. Return diagnostics as `{category, path, message}`. Engine paths are structural
   (`blocks[0].children[2]`), independent of device ids, so the frontend maps them onto
   canvas blocks directly. Doc-level diagnostics use the same path grammar.

The builder calls this debounced (~500 ms after edits settle); diagnostics render as badges
on offending blocks plus a problems panel. Validation failures never block saving — only
running.

### 4.4 Library addition (rides along in W1)

Two small public accessors in `lab_devices.experiment` (with tests, same gates as the
library):

- `verb_catalog() -> dict` — device type → verb → `{params: [{name, type, required}],
  kind: "command" | "measure", result_field}` derived from the private registry. Measure
  verbs are the `measurement=True` traits.
- `expression_functions() -> dict` — the stat-function names and window forms the
  expression language accepts (whatever the validator accepts is what this returns).

The webapp's `GET /api/catalog` is a thin serialization of these plus nothing else — the
palette and expression help can never drift from the engine.

## 5. Repo layout, packaging, CI

```
webapp/
  backend/
    pyproject.toml            # package `experiment-studio` (not published to PyPI)
    experiment_studio/
      app.py                  # FastAPI factory, static mount, lifespan (db + startup sweep)
      config.py               # env: STUDIO_DATA_DIR (default /data), port, discovery URL
      db.py                   # aiosqlite pool, migrations
      catalog.py              # /api/catalog from lab_devices accessors
      labs.py                 # LabRegistry/Console wrappers, roster cache, discover
      docs_store.py           # experiments CRUD + validation orchestration
      roles.py                # placeholder + real substitution, doc-level checks
      runner.py               # RunManager singleton (§7)
      sinks.py                # TeeRunLogSink (§7.3)
      inputs.py               # WebInputProvider (§7.4)
      records.py              # records CRUD, zip download, artifact readers
      api/                    # routers: labs, catalog, experiments, validate, runs, records, ws
    tests/
  frontend/
    src/
      api/                    # typed client + WS wrapper
      types/                  # hand-written TS mirrors of doc v1 + engine schema v1
      stores/                 # docStore (undo), labsStore, runStore, recordsStore
      shell/                  # tab shell, lab indicator
      devices/  builder/  run/  records/
    package.json  vite.config.ts  ...
  fixtures/                   # golden doc-v1 fixtures shared by backend + frontend tests (§11)
  Dockerfile                  # stage 1: node build; stage 2: python + engine + built assets
```

- **Root library pyproject untouched.** `webapp/backend/pyproject.toml` depends on
  `bioexperiment-lab-devices` as a path dependency (`../..`) for dev; the Docker build
  installs the library from the local source tree, so the image always ships the exact
  matching engine.
- **Backend gates mirror the library:** pytest, mypy, ruff, line length ≤ 100.
  **Frontend gates:** `tsc --noEmit`, eslint, vitest, `vite build`.
- **CI:** two new PR jobs (webapp-backend, webapp-frontend) that trigger on `webapp/**`
  changes; a release-triggered job builds the image and pushes
  `ghcr.io/bioexperiment-lab-devices/experiment-studio:{version,latest}` (S9).
- **Runtime env:** `STUDIO_DATA_DIR=/data` (volume), `LAB_DEVICES_DISCOVERY_URL` (engine
  default already points at the in-stack siteapp roster), `STUDIO_PORT` (default 8000).
  No auth (S3 — authelia guards the edge; same trust model as the internal roster).

## 6. Backend API surface

All under `/api`; SPA served at `/` (catch-all to `index.html`).

| Endpoint | Behavior |
|---|---|
| `GET /api/health` | liveness + version |
| `GET /api/labs` | roster names + host/port + online probe |
| `GET /api/labs/{lab}/devices` | agent's device roster (stale last-attach view, per agent semantics) |
| `POST /api/labs/{lab}/discover` | live bus rescan; 409 while a run is active on that lab |
| `GET /api/catalog` | §4.4 payload |
| `GET/POST /api/experiments`, `GET/PUT/DELETE /api/experiments/{id}`, `POST /api/experiments/{id}/duplicate` | CRUD on docs (§8.1); PUT is whole-doc replace; duplicate suffixes the name |
| `POST /api/validate` | §4.3; body = doc, response = `{ok, diagnostics[]}` |
| `POST /api/runs` | body `{experiment_id, lab, role_mapping}`; 409 `{active_run_id}` if busy; 422 if mapping incomplete/mistyped; otherwise creates record + starts run, returns `{run_id}` |
| `GET /api/runs/active` | `null` or `{run_id, record_id, experiment, lab, status, seq, pending_input}` — everything a freshly-loaded browser needs to reattach |
| `POST /api/runs/{id}/pause` / `resume` / `abort` | engine `pause()/resume()/abort()`; 404 if not the active run; abort is idempotent |
| `POST /api/runs/{id}/input` | body `{value}`; resolves the pending `InputRequest` (§7.4); 409 if none pending |
| `WS /api/runs/{id}/events?since=N` | replays buffered events with `seq > N`, then live-streams (§7.5) |
| `GET /api/records` | list with metadata (§8.1) |
| `PATCH /api/records/{id}` | rename |
| `DELETE /api/records/{id}` | delete row + artifact dir |
| `GET /api/records/{id}/download` | zip of the artifact dir, filename from record name |
| `GET /api/records/{id}/events` | parsed `run_log.jsonl` (record viewer) |
| `GET /api/records/{id}/streams` | parsed stream series `{name: {t: [...], v: [...], units}}` (record viewer chart) |

Errors are structured `{detail, code}`; the frontend renders explicit error states with
retry (never infinite spinners).

## 7. Run pipeline

### 7.1 RunManager

Process singleton owning at most one `(LabClient, ExperimentRun, asyncio.Task)`.
`start()`:

1. Reject with 409 if a run is active (S8).
2. Load doc; verify `role_mapping` covers every role, each device id's derived type matches
   the role type, and each id exists in the lab's current device roster (fresh
   `list_devices` call).
3. Create record row (`status="running"`) + artifact dir `runs/<uuid>/` (§8.2); write
   `doc.json` (source doc) and `workflow.json` (substituted engine JSON) immediately.
4. Deep-copy workflow, substitute role → device id, force persistence (§7.2), build
   `RunOptions(log_sink=TeeRunLogSink(...), input_provider=WebInputProvider(...),
   output_dir=<dir>)`, construct `ExperimentRun` (validates), and spawn
   `asyncio.create_task(execute())`.
5. On task completion (any status): write `run_log.jsonl` from the tee's memory list
   (`run_event_to_dict`), write `report.json` (status, error strings, finalize +
   persistence errors, clock origin, wall started/ended), update the record row, broadcast
   a terminal WS status, drop the client.

`ExperimentRun` construction can raise `ValidationError` before any task exists — that maps
to 422 and the record row is finalized as `failed` with the diagnostics in `report.json`.

### 7.2 Persistence forcing (S5)

On the run copy only: `persistence = {default: "disk", format: "csv"}` and every
`StreamDecl.persistence` cleared. Result: the **engine's own** `CsvStreamSink`s persist
every stream under the artifact dir (periodic ~30 s flush + guaranteed final flush at
finalize — engine design 5 semantics), while the run log stays on our tee because
`log_sink` is overridden (engine builds no disk log sink in that case). CSV chosen for
streams because records are downloaded by operators; the run log is `jsonl` (structured,
written by RunManager).

### 7.3 TeeRunLogSink

Sync `emit()` (RunLogSink protocol): append the event to an in-memory list **and** enqueue
`{seq, ...run_event_to_dict(e)}` onto the WS broadcast buffer. Monotonic `seq` from 0.
It must **never raise** (a raising sink can make a run un-abortable — engine Increment-5
lesson) and never block (pure list/deque appends; WS writers drain asynchronously).

### 7.4 WebInputProvider (OperatorInput)

`request(InputRequest)` parks an `asyncio.Future` as the single pending input, exposes it
via `GET /runs/active` (`pending_input = {name, type, prompt, min, max, choices,
block_id}`), and emits over WS (the engine already emits `input_requested`).
`POST /runs/{id}/input` validates the value with the engine's `validate_input_value` and
resolves the future (invalid → 422, future stays pending). Abort cancels the run task; the
awaited future is cancelled with it — no leak. The engine's fail-safe stance (no provider →
block fails) never triggers here since the provider is always wired.

### 7.5 WebSocket contract

- Server messages: `{type: "event", seq, timestamp, kind, block_id, data}` (one per
  RunEvent — this includes `measure_recorded {stream, value}`, which **is** the live chart
  feed; no second data path) and `{type: "status", status}` on lifecycle edges
  (running/paused/finished-with-outcome).
- `?since=N` replays every buffered event with `seq > N` before going live — refresh-proof.
  The buffer is the tee's in-memory list (bounded by run length; block-boundary events are
  small even for multi-day runs).
- Timestamps are the engine's **monotonic** clock. `report.json` records `clock_origin`
  (captured at start) + wall-clock `started_at`; charts plot elapsed = `t − clock_origin`.

### 7.6 Crash recovery

On startup, any record row still `running` is flipped to `interrupted` (its stream CSVs are
at most ~30 s stale; `run_log.jsonl` is absent — S7 accepted). The record viewer renders
whatever artifacts exist.

## 8. Storage

### 8.1 SQLite (`$STUDIO_DATA_DIR/studio.db`)

```
experiments(id TEXT PK, name TEXT UNIQUE, doc TEXT/*json*/, created_at, updated_at)
records(id TEXT PK, name TEXT, experiment_id TEXT/*nullable*/, experiment_name TEXT,
        lab TEXT, role_mapping TEXT/*json*/, status TEXT, started_at, ended_at,
        dir TEXT)
mappings(experiment_id, lab, role, device_id, PRIMARY KEY(experiment_id, lab, role))
```

- `records` snapshots `experiment_name` and keeps `experiment_id` nullable so deleting an
  experiment never orphans records. `status ∈ {running, completed, failed, aborted,
  cancelled, interrupted}` (engine statuses + our `interrupted`).
- `mappings` backs the S2 nice-to-have (pre-filled preflight); written on every successful
  start, read-only otherwise, lowest implementation priority.
- Default record name: `"<experiment name> — <local start time>"`, PATCH-renamable.

### 8.2 Artifact dir (`$STUDIO_DATA_DIR/runs/<uuid>/`)

```
doc.json          # source document (roles form)
workflow.json     # substituted engine workflow actually executed
run_log.jsonl     # full event log (written at finish, §7.1.5)
report.json       # outcome, errors, clock_origin, wall started/ended
<stream>.csv      # one per stream, engine-written (§7.2)
```

Download = zip of this directory. Delete removes row + directory.

## 9. Frontend

### 9.1 Shell

Four tabs styled as a stepper, freely navigable: **Devices → Builder → Run → Records**.
The selected lab is app-global state (chosen in Devices, shown in the shell header,
persisted to localStorage).

### 9.2 Devices tab

Lab picker from `/api/labs` (online badges) → device table (id, type, port, connected,
firmware from `identify`) and a global "Rediscover" button (confirm dialog; explains it
re-enumerates the bus). Per-device ping deferred to the v2 backlog (amended 2026-07-12
during W3: §6 defines no ping endpoint and the §6 table is the API contract). Read-only
otherwise — device control belongs to experiments.

### 9.3 Builder tab

Three panes:

- **Palette (left):** structure section (Serial, Parallel, Loop, Branch, Wait,
  OperatorInput) + one section per role listing its verbs as draggable Command/Measure
  chips + "add role". Roles panel (name, type, rename, delete-with-refusal) and Streams
  panel (add/rename/delete streams, units field) live here as collapsible sections.
- **Canvas (center):** the workflow tree. Serial containers stack children vertically;
  **Parallel containers render children as side-by-side lanes** (each lane is any block —
  in practice usually a Serial; an "+ lane" button appends one, empty lanes show a drop
  hint and a remove control). Loop/Branch render as framed containers (Branch with then/else
  lanes). Leaf blocks are cards: icon, role · verb, key params inline. Interactions: drag
  from palette to any legal slot, drag to reorder/re-parent, click to select, delete key,
  duplicate, collapse containers, undo/redo (zundo), diagnostic badges from the debounced
  validate call.
- **Inspector (right):** form for the selected block, generated from the catalog's
  ParamSpecs (number/int/string/bool widgets, required markers). Measure gets an
  `into`-stream picker (from declared streams, with inline "new stream"). Wait gets a
  duration field (`"5s"`, `"2min"` grammar — units ms|s|min|h; amended 2026-07-12 during
  W3: the original `"2m"` example was not the engine grammar). Loop gets count / until /
  pace / check-before-after;
  Branch gets its condition. Serial children get optional `gap_after`; Parallel children
  optional `start_offset`.

**Expression fields** (Loop `until`, Branch `if`, and any param accepting expressions) are
single-line text inputs with a help popover generated from `/api/catalog` + declared
streams: available stream names, bindings (OperatorInput names), stat functions, and window
syntax (`mean(od, last=5)`, `mean(od, last=30s)`) with one example each (S4: stream-statistics
conditions are first-class). Errors arrive via the same validate diagnostics.
(Amended 2026-07-11 during W2: the original bracket-window examples were not the engine
grammar; engine specs win.)

Toolbar: save, save-as, load (experiment list with search), duplicate, new, validation
status chip.

### 9.4 Run tab

- **No active run:** preflight panel — pick experiment (defaults to the one open in
  Builder), shows role → device dropdowns (filtered to matching type from the selected
  lab's roster, pre-filled from `mappings` when available) plus the doc's validation
  status (`/api/validate`; no separate endpoint — `POST /api/runs` is the final
  authority and 422s on anything preflight missed), then a big Start button (enabled
  when validation is clean and every role is mapped).
- **Active run:** status header (experiment, lab, state, elapsed), controls
  (Pause/Resume/Abort — abort confirms), **live chart** (uPlot; one series per stream,
  legend toggles, elapsed-time x-axis, fed from `measure_recorded` WS events), scrolling
  **event log** (human-readable renderings per event kind; auto-scroll with pause-on-hover),
  and an **input dialog** whenever `input_requested` arrives / `pending_input` is set
  (typed widget per request type, min/max/choices enforced, submit → `/input`).
- Terminal state shows the report (status, error, finalize/persistence errors) with a link
  to the record.

### 9.5 Records tab

Table (name, experiment, lab, status chip, started, duration) with rename (inline),
delete (confirm), download. Row click opens the viewer: chart rebuilt from
`/records/{id}/streams`, event log from `/records/{id}/events`, report summary, and the
workflow snapshot rendered read-only on the canvas component.

## 10. Error handling

- **Builder:** diagnostics as badges + problems panel; saving always allowed, running
  gated on zero errors.
- **Preflight:** mapping incompleteness / type mismatches / missing devices reported per
  role; Start disabled until clean.
- **Run:** engine semantics rule — block failure → finalizer teardowns → report. UI renders
  the report; the record persists for every outcome. Sink persistence errors surface on the
  report (engine behavior) and in `report.json`.
- **Transport:** WS auto-reconnects with `?since=<last seq>`; REST failures render retryable
  error states. Roster/agent unreachable → explicit offline states.
- **Server:** structured error responses; unexpected exceptions logged with stack traces;
  a failed start finalizes its record as `failed` rather than leaving a phantom `running`.

## 11. Testing

- **Backend (pytest, mirrors library gates):** ASGI-level tests via httpx `AsyncClient`;
  a fake `LabClient` transport reusing the engine tests' FakeLab call-recording patterns.
  Coverage: docs CRUD round-trips, validation diagnostics mapping (role → placeholder →
  path fidelity), run lifecycle end-to-end against the fake lab with zero-duration waits
  (start → events over WS → pause/resume → operator input → completion → record dir
  contents + zip), 409/422 guards, crash-sweep, records CRUD + download.
- **Frontend (vitest):** pure-logic tests — doc ↔ canvas-tree mapping, role
  rename/delete cascades, placeholder-path → block resolution, expression-help
  generation, WS reducer (replay + live merge). `tsc` + eslint + `vite build` as gates.
- **Cross-checked contract:** golden doc fixtures under `webapp/fixtures/` consumed by
  both backend (parse/validate) and frontend (type + mapping tests) so the two sides
  cannot drift on doc_version 1.
- **Live smoke (W6, manual/preprod):** one scripted run against
  `windows_arm64_test_client` via the preprod stack.

## 12. Implementation increments

Each increment: plan (docs/superpowers/plans/) → subagent-driven development → PR.

| # | Deliverable | Gate |
|---|---|---|
| W1 | Skeleton: `webapp/` layout, FastAPI app serving a hello SPA, Dockerfile, CI jobs (backend/frontend/image-push), `verb_catalog()` + `expression_functions()` in the library, `/api/catalog`, `/api/health`, `/api/labs*` | CI green incl. image build; catalog served from registry |
| W2 | Experiments backend: db layer, docs CRUD, roles module, `/api/validate` with placeholder substitution + doc-level checks | backend suite covers CRUD + diagnostics mapping |
| W3 | Builder UI: palette/canvas/inspector, roles + streams panels, N-lane parallel, expression fields + help, save/load/duplicate, diagnostics badges, undo/redo | vitest suite; manual walkthrough builds a real workflow doc |
| W4 | Run backend: RunManager, TeeRunLogSink, WebInputProvider, WS with replay, records store + artifacts + zip, crash sweep | lifecycle e2e tests incl. input + abort + record contents |
| W5 | Run + Records UI: preflight mapping, controls, live chart, event log, input dialog, records table + viewer | vitest + manual run against FakeLab-backed dev server |
| W6 | Integration: compose/caddy snippet + operator docs, preprod live smoke, mapping-memory nice-to-have if not landed, polish | scripted preprod run passes |

## 13. Deferred (v2 backlog)

Reusable groups (GroupRef) editing; expression autocomplete; concurrent runs / multi-user +
auth; record comparison overlays; closed-loop recovery UI (device-drop → rediscover →
resume); YAML/DSL import-export; Blockly-style keyboard-driven block entry; record
retention policies.
