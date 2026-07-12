# Experiment Studio W5 — Run + Records UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Run tab (preflight role→device mapping, live run controls, live uPlot chart, event log, operator-input dialog, terminal report) and Records tab (table + full record viewer), consuming the W4 run backend — plus the W3/W4 carry-forward fixes and the FakeLab-backed dev-server walkthrough that is the W5 gate.

**Architecture:** All new UI state lives in two new zustand stores (`runStore`, `recordsStore`) plus a tiny `navStore` for cross-tab jumps. The WS feed is folded by a pure reducer (`applyMessage`) that is fully unit-tested; the WebSocket lifecycle is a thin reconnecting wrapper. Charts are uPlot behind one shared `StreamChart` component fed by a pure `alignSeries` helper. The record viewer reuses the builder's pure helpers (`docToTree`, `blockSummary`, `childSlots`) via a new presentational `WorkflowSnapshot` — the editable Canvas is NOT reused (it is hard-wired to the doc store + dnd). Backend gets two small additions: a mapping-memory read endpoint and a normalized 422 envelope.

**Tech Stack:** React 19 + TS 6 + Vite 8 + Tailwind 4 (existing), zustand 5, uPlot (new dep), vitest 4 node-env pure-logic tests (NO jsdom — spec §11; components are exercised by the scripted playwright walkthrough in Task 12). Backend: FastAPI + aiosqlite (existing).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md`. Engine semantics win; the webapp adapts (spec header).
- Branch: `feat/experiment-studio-5-run-records-ui` off `main`.
- Backend gates (own venv): `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy . && .venv/bin/python -m ruff check .` — line length ≤ 100 everywhere (src AND tests).
- Frontend gates: `cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build`.
- Engine (`src/lab_devices/`) and root `tests/` MUST NOT change in this increment.
- Vitest stays `environment: 'node'`; tests are pure-logic only (reducers, helpers, stores). Do not add jsdom/@testing-library.
- Commit prefix `feat(studio):` / `fix(studio):` / `test(studio):` / `docs(studio):`.
- No barrel files; direct-path imports (repo convention).
- Wire-contract facts (from W4, verified): `POST /api/runs` → 201 `{run_id}`; controls → 204; 409 carries `active_run_id`; 422 `preflight_failed`/`validation_failed` carry `diagnostics` (and `record_id` for the latter); WS messages `{type:"event",seq,timestamp,kind,block_id,data}` and `{type:"status",seq,status}` share one seq counter; WS closes 1000 after terminal status, 4404 for unknown run; `?since=N` replays `seq > N`; record statuses `running|completed|failed|aborted|cancelled|interrupted`; `active_payload.status` is only `running|paused`.

---

### Task 1: Backend — mapping-memory read endpoint + normalized 422 envelope

**Files:**
- Modify: `webapp/backend/experiment_studio/records.py` (add `load_mapping` after `save_mapping`, line ~160)
- Modify: `webapp/backend/experiment_studio/api/experiments.py` (new route)
- Modify: `webapp/backend/experiment_studio/app.py` (RequestValidationError handler)
- Modify: `docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md` (§6 amendments)
- Test: `webapp/backend/tests/test_records.py`, `webapp/backend/tests/test_experiments_api.py`, `webapp/backend/tests/test_runs_api.py`

**Interfaces:**
- Consumes: `RecordsStore` (db + mappings table, W4), `get_records_store` dep (`api/deps.py`), `get_store` (experiments router).
- Produces: `GET /api/experiments/{experiment_id}/mappings/{lab}` → 200 `{role: device_id}` (`{}` when none; 404 `unknown_experiment`); ALL body-shape 422s now return `{detail: str, code: "invalid_request"}` (Task 2's client relies on `code` always being present on errors).

- [ ] **Step 1: Write the failing tests**

Append to `webapp/backend/tests/test_records.py` (match its existing fixture style — it constructs `Database`/`RecordsStore` directly; reuse the file's existing db/store fixture names, adapting the snippet's setup lines if the file already provides one):

```python
async def test_load_mapping_roundtrip(tmp_path: Path) -> None:
    db = await Database.connect(tmp_path / "studio.db")
    try:
        store = RecordsStore(db, tmp_path)
        assert await store.load_mapping("exp-1", "lab_a") == {}
        await store.save_mapping("exp-1", "lab_a", {"feed": "pump_1", "meter": "densitometer_1"})
        await store.save_mapping("exp-1", "lab_b", {"feed": "pump_9"})
        assert await store.load_mapping("exp-1", "lab_a") == {
            "feed": "pump_1",
            "meter": "densitometer_1",
        }
        assert await store.load_mapping("exp-1", "lab_b") == {"feed": "pump_9"}
        assert await store.load_mapping("other", "lab_a") == {}
    finally:
        await db.close()
```

Append to `webapp/backend/tests/test_experiments_api.py` (it has a `client` fixture posting docs; reuse its existing doc-payload helper if present, else inline a minimal valid doc — same shape as `runsupport.make_doc`):

```python
async def test_experiment_mappings_endpoint(
    client: httpx.AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    doc = runsupport.make_doc(runsupport.HAPPY_BLOCKS)
    created = (await client.post("/api/experiments", json=doc)).json()
    resp = await client.get(f"/api/experiments/{created['id']}/mappings/lab_a")
    assert resp.status_code == 200 and resp.json() == {}
    store = RecordsStore(app.state.db, tmp_path)
    await store.save_mapping(created["id"], "lab_a", {"feed": "pump_1"})
    resp = await client.get(f"/api/experiments/{created['id']}/mappings/lab_a")
    assert resp.json() == {"feed": "pump_1"}
    resp = await client.get("/api/experiments/nope/mappings/lab_a")
    assert resp.status_code == 404 and resp.json()["code"] == "unknown_experiment"
```

(Imports needed at top of that file if absent: `import runsupport`, `from fastapi import FastAPI`, `from pathlib import Path`, `from experiment_studio.records import RecordsStore`. NOTE: `app.state.db` exists only after the first request touches `get_db`/`get_store` — the POST above guarantees it.)

Append to `webapp/backend/tests/test_runs_api.py`:

```python
async def test_body_shape_422_is_normalized(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/runs", json={"experiment_id": "x", "lab": "lab_a"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "invalid_request"
    assert isinstance(body["detail"], str) and "role_mapping" in body["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_records.py::test_load_mapping_roundtrip tests/test_experiments_api.py::test_experiment_mappings_endpoint tests/test_runs_api.py::test_body_shape_422_is_normalized -v`
Expected: FAIL — `AttributeError: 'RecordsStore' object has no attribute 'load_mapping'`; 404 route missing; 422 body has `detail` as list, no `code`.

- [ ] **Step 3: Implement**

`records.py` — after `save_mapping`:

```python
    async def load_mapping(self, experiment_id: str, lab: str) -> dict[str, str]:
        """S2 mapping memory read: last device per role for (experiment, lab); {} if none."""
        cur = await self._db.conn.execute(
            "SELECT role, device_id FROM mappings WHERE experiment_id = ? AND lab = ?",
            (experiment_id, lab),
        )
        return {row["role"]: row["device_id"] for row in await cur.fetchall()}
```

`api/experiments.py` — add imports `from experiment_studio.api.deps import get_records_store` and `from experiment_studio.records import RecordsStore`, then append:

```python
@router.get("/{experiment_id}/mappings/{lab}")
async def experiment_mappings(
    experiment_id: str,
    lab: str,
    store: ExperimentsStore = Depends(get_store),
    records: RecordsStore = Depends(get_records_store),
) -> dict[str, str]:
    """S2 mapping-memory read for preflight pre-fill (§9.4; §6 amended during W5)."""
    await store.get(experiment_id)  # 404 unknown_experiment when absent
    return await records.load_mapping(experiment_id, lab)
```

`app.py` — add `from fastapi.exceptions import RequestValidationError` and handler (near the other custom handlers):

```python
async def _request_validation_handler(request: Request, exc: Exception) -> JSONResponse:
    """Normalize FastAPI body-shape 422s to the §6 envelope (amended during W5): the
    frontend branches on `code`, and the default list-shaped `detail` broke that."""
    assert isinstance(exc, RequestValidationError)
    errors = exc.errors()
    first: dict[str, Any] = errors[0] if errors else {}
    loc = ".".join(str(part) for part in first.get("loc", ()))
    msg = str(first.get("msg", "invalid request body"))
    return JSONResponse(
        status_code=422,
        content={"detail": f"{loc}: {msg}" if loc else msg, "code": "invalid_request"},
    )
```

Register in `create_app` alongside the other custom handlers:

```python
    app.add_exception_handler(RequestValidationError, _request_validation_handler)
```

- [ ] **Step 4: Spec amendments** (same commit)

In §6 table, after the `POST /api/validate` row, add:

```
| `GET /api/experiments/{id}/mappings/{lab}` | S2 mapping memory read: `{role: device_id}` remembered from the last successful start of this experiment on this lab; `{}` when none (amended 2026-07-12 during W5: §9.4's preflight pre-fill needs a read endpoint; the table had none) |
```

In §6, extend the closing errors paragraph:

```
Errors are structured `{detail, code}`; request-body validation failures are normalized
to this envelope with `code: "invalid_request"` (amended 2026-07-12 during W5 — FastAPI's
default list-shaped 422 broke the client's branch-on-`code` rule). The frontend renders
explicit error states with retry (never infinite spinners).
```

- [ ] **Step 5: Run the full backend gate**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy . && .venv/bin/python -m ruff check . && awk 'length > 100 {print FILENAME": "FNR; bad=1} END {exit bad}' experiment_studio/**/*.py tests/*.py`
Expected: all pass (suite grows 118 → 121).

- [ ] **Step 6: Commit**

```bash
git add webapp/backend docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md
git commit -m "feat(studio): mapping-memory read endpoint + normalized invalid_request 422 envelope"
```

---

### Task 2: Frontend foundation — client hardening, run/record types, REST modules

**Files:**
- Modify: `webapp/frontend/src/api/client.ts`
- Create: `webapp/frontend/src/types/runs.ts`, `webapp/frontend/src/types/records.ts`
- Create: `webapp/frontend/src/api/runs.ts`, `webapp/frontend/src/api/records.ts`
- Test: `webapp/frontend/src/api/client.test.ts` (extend)

**Interfaces:**
- Consumes: `Diagnostic`, `ExperimentDocJson` from `src/types/doc.ts`; `LabDevice` from `src/types/labs.ts`.
- Produces (used by every later task):
  - `ApiError` gains `diagnostics: Diagnostic[] | null`, `activeRunId: string | null`, `recordId: string | null`.
  - `patchJson<T>(path, body)` exported from client.
  - `request` tolerates ANY empty 2xx body (W3 carry-forward), not just 204.
  - types: `RunStatus`, `TERMINAL_STATUSES`, `PendingInput`, `ActiveRunPayload`, `RunEventMsg`, `RunStatusMsg`, `RunWsMsg`, `RecordEvent` (runs.ts); `RecordRow`, `RecordReport`, `RecordDetail`, `StreamSeries`, `RecordStreams` (records.ts).
  - api fns: `startRun`, `getActiveRun`, `pauseRun`, `resumeRun`, `abortRun`, `submitRunInput`, `savedMapping` (runs.ts); `listRecords`, `getRecord`, `renameRecord`, `deleteRecord`, `recordEvents`, `recordStreams`, `recordDownloadUrl` (records.ts).

- [ ] **Step 1: Write the failing tests** — extend `src/api/client.test.ts` with a stubbed `fetch`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getJson, postJson, toApiError } from './client'

const stubFetch = (resp: Response) => vi.stubGlobal('fetch', vi.fn().mockResolvedValue(resp))
afterEach(() => vi.unstubAllGlobals())

describe('request', () => {
  it('parses a JSON body', async () => {
    stubFetch(new Response('{"a":1}', { status: 200 }))
    expect(await getJson<{ a: number }>('/api/x')).toEqual({ a: 1 })
  })
  it('returns undefined for 204', async () => {
    stubFetch(new Response(null, { status: 204 }))
    expect(await postJson<void>('/api/x', {})).toBeUndefined()
  })
  it('returns undefined for an empty 200 body', async () => {
    stubFetch(new Response('', { status: 200 }))
    expect(await getJson<void>('/api/x')).toBeUndefined()
  })
  it('parses a JSON null body', async () => {
    stubFetch(new Response('null', { status: 200 }))
    expect(await getJson<unknown>('/api/x')).toBeNull()
  })
  it('throws ApiError with envelope extras on failure', async () => {
    const body = {
      detail: 'preflight failed', code: 'preflight_failed',
      diagnostics: [{ category: 'mapping', path: "roles['feed']", message: 'unmapped' }],
    }
    stubFetch(new Response(JSON.stringify(body), { status: 422 }))
    const err = await getJson('/api/runs').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).code).toBe('preflight_failed')
    expect((err as ApiError).diagnostics).toEqual(body.diagnostics)
  })
})

describe('toApiError extras', () => {
  it('captures active_run_id and record_id', async () => {
    const resp = new Response(
      JSON.stringify({ detail: 'busy', code: 'run_active', active_run_id: 'r1', record_id: 'c1' }),
      { status: 409 },
    )
    const err = await toApiError('/api/runs', resp)
    expect(err.activeRunId).toBe('r1')
    expect(err.recordId).toBe('c1')
  })
  it('leaves extras null when absent or malformed', async () => {
    const resp = new Response(JSON.stringify({ detail: 'x', diagnostics: 'nope' }), { status: 422 })
    const err = await toApiError('/api/x', resp)
    expect(err.diagnostics).toBeNull()
    expect(err.activeRunId).toBeNull()
  })
})
```

- [ ] **Step 2: Run to verify failure** — `cd webapp/frontend && npx vitest run src/api/client.test.ts` — Expected: FAIL (`diagnostics` undefined; empty-200 test throws JSON parse error).

- [ ] **Step 3: Implement `client.ts` changes**

```ts
import type { Diagnostic } from '../types/doc'

export interface ApiErrorExtras {
  diagnostics?: Diagnostic[] | null
  activeRunId?: string | null
  recordId?: string | null
}

export class ApiError extends Error {
  status: number
  code: string | null
  diagnostics: Diagnostic[] | null
  activeRunId: string | null
  recordId: string | null

  constructor(status: number, message: string, code: string | null = null, extras: ApiErrorExtras = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.diagnostics = extras.diagnostics ?? null
    this.activeRunId = extras.activeRunId ?? null
    this.recordId = extras.recordId ?? null
  }
}

const isDiagnostic = (d: unknown): d is Diagnostic =>
  d !== null && typeof d === 'object' &&
  typeof (d as Diagnostic).category === 'string' &&
  typeof (d as Diagnostic).path === 'string' &&
  typeof (d as Diagnostic).message === 'string'

export async function toApiError(path: string, resp: Response): Promise<ApiError> {
  let message = `${path}: HTTP ${resp.status}`
  let code: string | null = null
  const extras: ApiErrorExtras = {}
  try {
    const body: unknown = await resp.json()
    if (body !== null && typeof body === 'object') {
      const rec = body as Record<string, unknown>
      if (typeof rec.detail === 'string' && rec.detail.length > 0) message = rec.detail
      if (typeof rec.code === 'string') code = rec.code
      if (Array.isArray(rec.diagnostics) && rec.diagnostics.every(isDiagnostic)) {
        extras.diagnostics = rec.diagnostics
      }
      if (typeof rec.active_run_id === 'string') extras.activeRunId = rec.active_run_id
      if (typeof rec.record_id === 'string') extras.recordId = rec.record_id
    }
  } catch {
    // non-JSON body (proxy error page, empty body) — keep the generic message
  }
  return new ApiError(resp.status, message, code, extras)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init)
  if (!resp.ok) throw await toApiError(path, resp)
  if (resp.status === 204) return undefined as T
  const text = await resp.text()
  if (text === '') return undefined as T // W3 carry-forward: empty 2xx body is legal
  return JSON.parse(text) as T
}
```

Keep `jsonInit`/`getJson`/`postJson`/`putJson`/`deleteJson`/`getHealth` unchanged and add:

```ts
export const patchJson = <T>(path: string, body: unknown) => request<T>(path, jsonInit('PATCH', body))
```

- [ ] **Step 4: Create `src/types/runs.ts`**

```ts
/** Wire types for the run pipeline (§6, §7.4, §7.5). Mirrors the W4 backend exactly. */

export type RunStatus =
  | 'running' | 'paused'
  | 'completed' | 'failed' | 'aborted' | 'cancelled' | 'interrupted'

export const TERMINAL_STATUSES: ReadonlySet<string> = new Set([
  'completed', 'failed', 'aborted', 'cancelled', 'interrupted',
])

export interface PendingInput {
  name: string
  type: 'bool' | 'int' | 'float' | 'enum'
  prompt: string | null
  min: number | null
  max: number | null
  choices: string[] | null
  block_id: string
}

export interface ActiveRunPayload {
  run_id: string
  record_id: string
  experiment: { id: string; name: string }
  lab: string
  status: 'running' | 'paused'
  seq: number
  pending_input: PendingInput | null
}

export interface RunEventMsg {
  type: 'event'
  seq: number
  timestamp: number
  kind: string
  block_id: string | null
  data: Record<string, unknown>
}

export interface RunStatusMsg {
  type: 'status'
  seq: number
  status: string
}

export type RunWsMsg = RunEventMsg | RunStatusMsg

/** A run_log.jsonl line (GET /api/records/{id}/events) — an event without the WS envelope. */
export interface RecordEvent {
  timestamp: number
  kind: string
  block_id: string | null
  data: Record<string, unknown>
}
```

- [ ] **Step 5: Create `src/types/records.ts`**

```ts
import type { Diagnostic, ExperimentDocJson } from './doc'

export interface RecordRow {
  id: string
  name: string
  experiment_id: string | null
  experiment_name: string
  lab: string
  role_mapping: Record<string, string>
  status: string
  started_at: string
  ended_at: string | null
  dir: string
}

export interface RecordReport {
  status: string
  error: string | null
  finalize_errors: string[]
  persistence_errors: string[]
  diagnostics: Diagnostic[]
  clock_origin: number | null
  started_at: string
  ended_at: string
  experiment_name: string
  lab: string
  role_mapping: Record<string, string>
}

export interface RecordDetail extends RecordRow {
  report: RecordReport | null
  doc: ExperimentDocJson | null
}

export interface StreamSeries {
  t: number[]
  v: number[]
  units: string | null
}

export type RecordStreams = Record<string, StreamSeries>
```

- [ ] **Step 6: Create `src/api/runs.ts` and `src/api/records.ts`**

```ts
// src/api/runs.ts
import { getJson, postJson } from './client'
import type { ActiveRunPayload } from '../types/runs'

export interface StartRunBody {
  experiment_id: string
  lab: string
  role_mapping: Record<string, string>
}

export const startRun = (body: StartRunBody) => postJson<{ run_id: string }>('/api/runs', body)
export const getActiveRun = () => getJson<ActiveRunPayload | null>('/api/runs/active')
export const pauseRun = (id: string) => postJson<void>(`/api/runs/${id}/pause`, {})
export const resumeRun = (id: string) => postJson<void>(`/api/runs/${id}/resume`, {})
export const abortRun = (id: string) => postJson<void>(`/api/runs/${id}/abort`, {})
export const submitRunInput = (id: string, value: boolean | number | string) =>
  postJson<void>(`/api/runs/${id}/input`, { value })
export const savedMapping = (experimentId: string, lab: string) =>
  getJson<Record<string, string>>(
    `/api/experiments/${experimentId}/mappings/${encodeURIComponent(lab)}`,
  )
```

```ts
// src/api/records.ts
import { deleteJson, getJson, patchJson } from './client'
import type { RecordEvent } from '../types/runs'
import type { RecordDetail, RecordRow, RecordStreams } from '../types/records'

export const listRecords = () => getJson<RecordRow[]>('/api/records')
export const getRecord = (id: string) => getJson<RecordDetail>(`/api/records/${id}`)
export const renameRecord = (id: string, name: string) =>
  patchJson<RecordRow>(`/api/records/${id}`, { name })
export const deleteRecord = (id: string) => deleteJson(`/api/records/${id}`)
export const recordEvents = (id: string) => getJson<RecordEvent[]>(`/api/records/${id}/events`)
export const recordStreams = (id: string) => getJson<RecordStreams>(`/api/records/${id}/streams`)
export const recordDownloadUrl = (id: string) => `/api/records/${id}/download`
```

- [ ] **Step 7: Run the frontend gate** — `cd webapp/frontend && npm run lint && npm run typecheck && npm test` — Expected: all green (suite 58 → 64-ish).

- [ ] **Step 8: Commit**

```bash
git add webapp/frontend/src
git commit -m "feat(studio): API client envelope extras + run/record wire types and REST modules"
```

---

### Task 3: WS feed reducer (pure) + reconnecting socket wrapper + dev WS proxy

**Files:**
- Create: `webapp/frontend/src/run/reducer.ts`
- Create: `webapp/frontend/src/api/runSocket.ts`
- Modify: `webapp/frontend/vite.config.ts` (WS proxying)
- Test: `webapp/frontend/src/run/reducer.test.ts`

**Interfaces:**
- Consumes: `RunWsMsg`, `RunEventMsg`, `TERMINAL_STATUSES` from `src/types/runs.ts`.
- Produces: `FeedState`, `emptyFeed(status?)`, `applyMessage(s, msg): FeedState` (reducer.ts); `RunSocket` class + `RunSocketHandlers` (runSocket.ts). **Mutability contract:** `applyMessage` returns a NEW top-level `FeedState` object but appends to the `events` / per-stream sample arrays IN PLACE; `rev` increments on every accepted message so subscribers re-render without O(n) copies per message (multi-hour runs stream thousands of events).

- [ ] **Step 1: Write the failing tests** — `src/run/reducer.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { applyMessage, emptyFeed, type FeedState } from './reducer'
import type { RunWsMsg } from '../types/runs'

const ev = (seq: number, kind: string, data: Record<string, unknown> = {}, ts = seq): RunWsMsg =>
  ({ type: 'event', seq, timestamp: ts, kind, block_id: null, data })
const st = (seq: number, status: string): RunWsMsg => ({ type: 'status', seq, status })

const feedAll = (msgs: RunWsMsg[], s: FeedState = emptyFeed()): FeedState =>
  msgs.reduce(applyMessage, s)

describe('applyMessage', () => {
  it('accumulates events, origin from the first event, rev per message', () => {
    const s = feedAll([ev(0, 'run_started', {}, 10.5), ev(1, 'block_started', {}, 11)])
    expect(s.origin).toBe(10.5)
    expect(s.lastSeq).toBe(1)
    expect(s.events.map((e) => e.kind)).toEqual(['run_started', 'block_started'])
    expect(s.rev).toBe(2)
  })
  it('drops replay duplicates (seq <= lastSeq) without touching state', () => {
    const s1 = feedAll([ev(0, 'run_started'), ev(1, 'block_started')])
    const s2 = applyMessage(s1, ev(1, 'block_started'))
    expect(s2).toBe(s1)
  })
  it('folds measure_recorded into per-stream samples', () => {
    const s = feedAll([
      ev(0, 'run_started', {}, 0),
      ev(1, 'measure_recorded', { stream: 'od', value: 0.5 }, 5),
      ev(2, 'measure_recorded', { stream: 'od', value: 0.7 }, 10),
      ev(3, 'measure_recorded', { stream: 'temp', value: 37 }, 10),
    ])
    expect(s.samples.od).toEqual({ t: [5, 10], v: [0.5, 0.7] })
    expect(s.samples.temp).toEqual({ t: [10], v: [37] })
  })
  it('status messages update status and flag terminal', () => {
    let s = feedAll([ev(0, 'run_started'), st(1, 'paused')])
    expect(s.status).toBe('paused')
    expect(s.terminal).toBe(false)
    s = applyMessage(s, st(2, 'completed'))
    expect(s.status).toBe('completed')
    expect(s.terminal).toBe(true)
  })
  it('replay then live merge is seamless across a reconnect overlap', () => {
    const msgs = [ev(0, 'run_started'), ev(1, 'measure_recorded', { stream: 'od', value: 1 }),
      st(2, 'paused'), st(3, 'running'), ev(4, 'block_finished')]
    const once = feedAll(msgs)
    const twice = feedAll([...msgs.slice(2)], feedAll(msgs.slice(0, 4))) // overlap 2..3
    expect(twice.lastSeq).toBe(once.lastSeq)
    expect(twice.events.length).toBe(once.events.length)
    expect(twice.samples).toEqual(once.samples)
  })
})
```

- [ ] **Step 2: Run to verify failure** — `npx vitest run src/run/reducer.test.ts` — Expected: FAIL (module not found).

- [ ] **Step 3: Implement `src/run/reducer.ts`**

```ts
/** Pure fold over the run WS feed (§7.5). Returns a new top-level object per accepted
 * message but appends to events/sample arrays IN PLACE (rev signals appends) so long
 * runs don't pay O(n) copies per message. `seq <= lastSeq` drops replay duplicates. */
import { TERMINAL_STATUSES, type RunWsMsg, type RunEventMsg } from '../types/runs'

export interface StreamSamples {
  t: number[]
  v: number[]
}

export interface FeedState {
  lastSeq: number
  rev: number
  origin: number | null
  lastTimestamp: number | null
  status: string
  terminal: boolean
  events: RunEventMsg[]
  samples: Record<string, StreamSamples>
}

export const emptyFeed = (status = 'running'): FeedState => ({
  lastSeq: -1,
  rev: 0,
  origin: null,
  lastTimestamp: null,
  status,
  terminal: false,
  events: [],
  samples: {},
})

export function applyMessage(s: FeedState, msg: RunWsMsg): FeedState {
  if (msg.seq <= s.lastSeq) return s
  if (msg.type === 'status') {
    return {
      ...s,
      lastSeq: msg.seq,
      rev: s.rev + 1,
      status: msg.status,
      terminal: s.terminal || TERMINAL_STATUSES.has(msg.status),
    }
  }
  s.events.push(msg)
  let samples = s.samples
  if (msg.kind === 'measure_recorded') {
    const stream = String(msg.data.stream)
    const series = samples[stream] ?? { t: [], v: [] }
    series.t.push(msg.timestamp)
    series.v.push(Number(msg.data.value))
    if (!(stream in samples)) samples = { ...samples, [stream]: series }
  }
  return {
    ...s,
    lastSeq: msg.seq,
    rev: s.rev + 1,
    origin: s.origin ?? msg.timestamp,
    lastTimestamp: msg.timestamp,
    samples,
  }
}
```

- [ ] **Step 4: Implement `src/api/runSocket.ts`**

```ts
/** Reconnecting WebSocket for /api/runs/{id}/events (§7.5). Close 1000 = terminal
 * (buffer drained after the final status), 4404 = not the active run; anything else
 * is transport loss → reconnect with ?since=<lastSeq> after a backoff. */
import type { RunWsMsg } from '../types/runs'

export interface RunSocketHandlers {
  onMessage: (msg: RunWsMsg) => void
  onTerminal: () => void
  onGone: () => void
}

export class RunSocket {
  private ws: WebSocket | null = null
  private stopped = false
  private retryMs = 500
  private timer: ReturnType<typeof setTimeout> | null = null

  constructor(
    private readonly runId: string,
    private readonly lastSeq: () => number,
    private readonly handlers: RunSocketHandlers,
  ) {}

  connect(): void {
    if (this.stopped) return
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/api/runs/${this.runId}/events?since=${this.lastSeq()}`
    const ws = new WebSocket(url)
    this.ws = ws
    ws.onmessage = (e: MessageEvent<string>) => {
      this.retryMs = 500
      this.handlers.onMessage(JSON.parse(e.data) as RunWsMsg)
    }
    ws.onclose = (e: CloseEvent) => {
      if (this.stopped || this.ws !== ws) return
      if (e.code === 1000) this.handlers.onTerminal()
      else if (e.code === 4404) this.handlers.onGone()
      else {
        this.timer = setTimeout(() => this.connect(), this.retryMs)
        this.retryMs = Math.min(this.retryMs * 2, 5000)
      }
    }
  }

  close(): void {
    this.stopped = true
    if (this.timer !== null) clearTimeout(this.timer)
    this.ws?.close()
  }
}
```

- [ ] **Step 5: Enable WS proxying in `vite.config.ts`** (the string shorthand does not proxy WebSocket upgrades):

```ts
  server: {
    proxy: { '/api': { target: 'http://localhost:8000', ws: true } },
  },
```

- [ ] **Step 6: Run gate** — `npm run lint && npm run typecheck && npm test` — Expected: green.

- [ ] **Step 7: Commit**

```bash
git add webapp/frontend/src webapp/frontend/vite.config.ts
git commit -m "feat(studio): run WS feed reducer + reconnecting socket wrapper"
```

---

### Task 4: runStore — attach / start / controls / input / terminal report

**Files:**
- Create: `webapp/frontend/src/stores/runStore.ts`
- Test: `webapp/frontend/src/stores/runStore.test.ts`

**Interfaces:**
- Consumes: Task 2 api fns + types; Task 3 `applyMessage`/`emptyFeed`/`RunSocket`; `getRecord` from `src/api/records.ts`.
- Produces (components in Tasks 6-9 read exactly these):

```ts
export interface RunUiState {
  phase: 'unknown' | 'idle' | 'active' | 'terminal'
  runId: string | null
  recordId: string | null
  experiment: { id: string; name: string } | null
  lab: string | null
  feed: FeedState
  lastWallMs: number | null            // Date.now() at the last accepted message
  pendingInput: PendingInput | null
  inputError: string | null
  streamUnits: Record<string, string | null>
  report: RecordReport | null
  recordName: string | null
  startBusy: boolean
  controlBusy: boolean
  startError: string | null
  startDiagnostics: Diagnostic[] | null
  attach: () => Promise<void>
  start: (body: StartRunBody) => Promise<void>
  pause: () => Promise<void>
  resume: () => Promise<void>
  abort: () => Promise<void>
  submit: (value: boolean | number | string) => Promise<boolean>
  dismiss: () => void                  // terminal → idle (back to preflight)
}
export const useRunStore: UseBoundStore<StoreApi<RunUiState>>
export function setSocketFactoryForTests(f: SocketFactory | null): void
```

- [ ] **Step 1: Write the failing tests** — `src/stores/runStore.test.ts`. Stub `fetch` per-path and inject a fake socket factory:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setSocketFactoryForTests, useRunStore } from './runStore'
import type { RunSocketHandlers } from '../api/runSocket'
import type { RunWsMsg } from '../types/runs'

const ACTIVE = {
  run_id: 'r1', record_id: 'r1', experiment: { id: 'e1', name: 'OD growth' },
  lab: 'lab_a', status: 'running', seq: 1, pending_input: null,
}
const RECORD = {
  id: 'r1', name: 'OD growth — now', experiment_id: 'e1', experiment_name: 'OD growth',
  lab: 'lab_a', role_mapping: {}, status: 'completed', started_at: '', ended_at: '',
  dir: 'runs/r1', report: { status: 'completed', error: null, finalize_errors: [],
    persistence_errors: [], diagnostics: [], clock_origin: 0, started_at: '', ended_at: '',
    experiment_name: 'OD growth', lab: 'lab_a', role_mapping: {} },
  doc: { doc_version: 1, name: 'OD growth', description: null, roles: {},
    workflow: { schema_version: 1, blocks: [], streams: { od: { units: 'AU' } } } },
}

let sockets: { runId: string; handlers: RunSocketHandlers; connected: boolean }[]
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })

beforeEach(() => {
  sockets = []
  setSocketFactoryForTests((runId, _lastSeq, handlers) => {
    const record = { runId, handlers, connected: false }
    sockets.push(record)
    return { connect: () => { record.connected = true }, close: () => {} }
  })
  useRunStore.getState().dismiss() // reset to idle baseline between tests
})
afterEach(() => {
  setSocketFactoryForTests(null)
  vi.unstubAllGlobals()
})

const push = (msg: RunWsMsg) => sockets[0].handlers.onMessage(msg)

describe('runStore', () => {
  it('attach adopts an active run and opens a socket', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) =>
      url.includes('/api/records/') ? json(RECORD) : json(ACTIVE)))
    await useRunStore.getState().attach()
    const s = useRunStore.getState()
    expect(s.phase).toBe('active')
    expect(s.runId).toBe('r1')
    expect(s.streamUnits).toEqual({ od: 'AU' })
    expect(sockets).toHaveLength(1)
    expect(sockets[0].connected).toBe(true)
  })
  it('attach with no active run lands in idle', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(null)))
    await useRunStore.getState().attach()
    expect(useRunStore.getState().phase).toBe('idle')
  })
  it('events fold into the feed; terminal close fetches the report', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) =>
      url.includes('/api/records/') ? json(RECORD) : json(ACTIVE)))
    await useRunStore.getState().attach()
    push({ type: 'event', seq: 0, timestamp: 1, kind: 'run_started', block_id: null, data: {} })
    push({ type: 'status', seq: 1, status: 'completed' })
    sockets[0].handlers.onTerminal()
    await vi.waitFor(() => expect(useRunStore.getState().phase).toBe('terminal'))
    expect(useRunStore.getState().report?.status).toBe('completed')
  })
  it('input_requested refetches the pending input from /runs/active', async () => {
    const pending = { ...ACTIVE, pending_input: { name: 'target', type: 'int', prompt: 'n?',
      min: 1, max: 10, choices: null, block_id: 'b1' } }
    let calls = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/api/records/')) return json(RECORD)
      calls += 1
      return json(calls === 1 ? ACTIVE : pending)
    }))
    await useRunStore.getState().attach()
    push({ type: 'event', seq: 0, timestamp: 1, kind: 'input_requested', block_id: 'b1',
      data: { name: 'target' } })
    await vi.waitFor(() =>
      expect(useRunStore.getState().pendingInput?.name).toBe('target'))
    push({ type: 'event', seq: 1, timestamp: 2, kind: 'input_bound', block_id: 'b1',
      data: { name: 'target', value: 5 } })
    expect(useRunStore.getState().pendingInput).toBeNull()
  })
  it('start surfaces 422 diagnostics without leaving idle', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        return new Response(JSON.stringify({ detail: 'preflight failed',
          code: 'preflight_failed',
          diagnostics: [{ category: 'mapping', path: "roles['feed']", message: 'unmapped' }],
        }), { status: 422 })
      }
      return json(null)
    }))
    await useRunStore.getState().attach()
    await useRunStore.getState().start({ experiment_id: 'e1', lab: 'lab_a', role_mapping: {} })
    const s = useRunStore.getState()
    expect(s.phase).toBe('idle')
    expect(s.startDiagnostics).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run to verify failure** — `npx vitest run src/stores/runStore.test.ts` — Expected: FAIL (module not found).

- [ ] **Step 3: Implement `src/stores/runStore.ts`**

```ts
/** Run-tab state: adopts the active run (refresh-proof via GET /runs/active + WS replay
 * from seq -1), folds the WS feed with the pure reducer, owns controls and the pending
 * operator input, and resolves the terminal report from the record row (§7, §9.4). */
import { create } from 'zustand'
import { ApiError } from '../api/client'
import {
  abortRun, getActiveRun, pauseRun, resumeRun, startRun, submitRunInput,
  type StartRunBody,
} from '../api/runs'
import { getRecord } from '../api/records'
import { RunSocket, type RunSocketHandlers } from '../api/runSocket'
import { applyMessage, emptyFeed, type FeedState } from '../run/reducer'
import type { Diagnostic, ExperimentDocJson } from '../types/doc'
import type { ActiveRunPayload, PendingInput, RunWsMsg } from '../types/runs'
import type { RecordReport } from '../types/records'

interface SocketLike {
  connect: () => void
  close: () => void
}
export type SocketFactory = (
  runId: string, lastSeq: () => number, handlers: RunSocketHandlers,
) => SocketLike

let socketFactory: SocketFactory = (runId, lastSeq, handlers) =>
  new RunSocket(runId, lastSeq, handlers)
export function setSocketFactoryForTests(f: SocketFactory | null): void {
  socketFactory = f ?? ((runId, lastSeq, handlers) => new RunSocket(runId, lastSeq, handlers))
}

export interface RunUiState {
  phase: 'unknown' | 'idle' | 'active' | 'terminal'
  runId: string | null
  recordId: string | null
  experiment: { id: string; name: string } | null
  lab: string | null
  feed: FeedState
  lastWallMs: number | null
  pendingInput: PendingInput | null
  inputError: string | null
  streamUnits: Record<string, string | null>
  report: RecordReport | null
  recordName: string | null
  startBusy: boolean
  controlBusy: boolean
  startError: string | null
  startDiagnostics: Diagnostic[] | null
  attach: () => Promise<void>
  start: (body: StartRunBody) => Promise<void>
  pause: () => Promise<void>
  resume: () => Promise<void>
  abort: () => Promise<void>
  submit: (value: boolean | number | string) => Promise<boolean>
  dismiss: () => void
}

let socket: SocketLike | null = null

const unitsOf = (doc: ExperimentDocJson | null): Record<string, string | null> =>
  Object.fromEntries(
    Object.entries(doc?.workflow.streams ?? {}).map(([k, s]) => [k, s.units ?? null]),
  )

export const useRunStore = create<RunUiState>()((set, get) => {
  const receive = (msg: RunWsMsg): void => {
    set((s) => ({ feed: applyMessage(s.feed, msg), lastWallMs: Date.now() }))
    if (msg.type !== 'event') return
    if (msg.kind === 'input_requested') {
      void getActiveRun().then((p) => {
        if (p !== null && p.run_id === get().runId && p.pending_input !== null) {
          set({ pendingInput: p.pending_input, inputError: null })
        }
      })
    } else if (msg.kind === 'input_bound') {
      set({ pendingInput: null, inputError: null })
    }
  }

  const openSocket = (runId: string): void => {
    socket?.close()
    socket = socketFactory(runId, () => get().feed.lastSeq, {
      onMessage: receive,
      onTerminal: () => {
        const recordId = get().recordId
        set({ phase: 'terminal' })
        if (recordId !== null) {
          void getRecord(recordId)
            .then((d) => set({ report: d.report, recordName: d.name }))
            .catch(() => set({ report: null }))
        }
      },
      onGone: () => void get().attach(),
    })
    socket.connect()
  }

  const adopt = (payload: ActiveRunPayload): void => {
    set({
      phase: 'active',
      runId: payload.run_id,
      recordId: payload.record_id,
      experiment: payload.experiment,
      lab: payload.lab,
      feed: emptyFeed(payload.status),
      lastWallMs: null,
      pendingInput: payload.pending_input,
      inputError: null,
      report: null,
      recordName: null,
      startError: null,
      startDiagnostics: null,
    })
    void getRecord(payload.record_id)
      .then((d) => set({ streamUnits: unitsOf(d.doc) }))
      .catch(() => set({ streamUnits: {} }))
    openSocket(payload.run_id)
  }

  return {
    phase: 'unknown',
    runId: null,
    recordId: null,
    experiment: null,
    lab: null,
    feed: emptyFeed(),
    lastWallMs: null,
    pendingInput: null,
    inputError: null,
    streamUnits: {},
    report: null,
    recordName: null,
    startBusy: false,
    controlBusy: false,
    startError: null,
    startDiagnostics: null,

    attach: async () => {
      try {
        const payload = await getActiveRun()
        if (payload === null) {
          if (get().phase !== 'terminal') set({ phase: 'idle' })
        } else if (payload.run_id !== get().runId || get().phase !== 'active') {
          adopt(payload)
        }
      } catch (e) {
        set({ phase: 'idle', startError: e instanceof Error ? e.message : String(e) })
      }
    },

    start: async (body) => {
      set({ startBusy: true, startError: null, startDiagnostics: null })
      try {
        await startRun(body)
        await get().attach()
      } catch (e) {
        if (e instanceof ApiError && e.code === 'run_active') {
          await get().attach() // adopt whoever is running (S8: one run per instance)
        } else if (e instanceof ApiError && e.diagnostics !== null) {
          set({ startError: e.message, startDiagnostics: e.diagnostics })
        } else {
          set({ startError: e instanceof Error ? e.message : String(e) })
        }
      } finally {
        set({ startBusy: false })
      }
    },

    pause: async () => {
      const id = get().runId
      if (id === null) return
      set({ controlBusy: true })
      try {
        await pauseRun(id)
      } catch {
        // status frame (or 404 on a just-finished run) resolves the true state
      } finally {
        set({ controlBusy: false })
      }
    },
    resume: async () => {
      const id = get().runId
      if (id === null) return
      set({ controlBusy: true })
      try {
        await resumeRun(id)
      } catch {
        // see pause()
      } finally {
        set({ controlBusy: false })
      }
    },
    abort: async () => {
      const id = get().runId
      if (id === null) return
      set({ controlBusy: true })
      try {
        await abortRun(id)
      } catch {
        // idempotent server-side; terminal frame arrives via WS
      } finally {
        set({ controlBusy: false })
      }
    },

    submit: async (value) => {
      const id = get().runId
      if (id === null) return false
      try {
        await submitRunInput(id, value)
        set({ pendingInput: null, inputError: null })
        return true
      } catch (e) {
        set({ inputError: e instanceof Error ? e.message : String(e) })
        return false // 422 invalid_value: request stays pending server-side (§7.4)
      }
    },

    dismiss: () => {
      socket?.close()
      socket = null
      set({
        phase: 'idle', runId: null, recordId: null, experiment: null, lab: null,
        feed: emptyFeed(), lastWallMs: null, pendingInput: null, inputError: null,
        streamUnits: {}, report: null, recordName: null,
        startBusy: false, controlBusy: false, startError: null, startDiagnostics: null,
      })
    },
  }
})
```

- [ ] **Step 4: Run to verify pass** — `npx vitest run src/stores/runStore.test.ts` — Expected: PASS.

- [ ] **Step 5: Full frontend gate** — `npm run lint && npm run typecheck && npm test && npm run build` — Expected: green.

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src
git commit -m "feat(studio): runStore — attach/start/controls/input/terminal lifecycle"
```

---

### Task 5: Records list — format helpers, recordsStore, table, nav store, App wiring

**Files:**
- Create: `webapp/frontend/src/records/format.ts`, `webapp/frontend/src/stores/recordsStore.ts`, `webapp/frontend/src/stores/navStore.ts`, `webapp/frontend/src/records/RecordsTable.tsx`, `webapp/frontend/src/records/RecordsTab.tsx`
- Modify: `webapp/frontend/src/App.tsx`
- Test: `webapp/frontend/src/records/format.test.ts`

**Interfaces:**
- Consumes: Task 2 `listRecords/renameRecord/deleteRecord/recordDownloadUrl`, `RecordRow`; `Tab` from `shell/TabShell`.
- Produces: `formatWhen(iso): string`, `formatDuration(startedIso, endedIso|null): string`, `formatElapsed(seconds): string`, `STATUS_STYLES: Record<string,string>` (format.ts); `useRecordsStore` with `{ items, error, loading, openId, refresh(), open(id|null), rename(id,name): Promise<string|null>, remove(id): Promise<string|null> }`; `useNavStore` with `{ tab: Tab, setTab(tab) }` — **Task 6/7 navigate via these**. `RecordsTab` renders the table, or a placeholder viewer panel when `openId !== null` (Task 10 replaces the placeholder).

- [ ] **Step 1: Write the failing tests** — `src/records/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { formatDuration, formatElapsed, formatWhen } from './format'

describe('format helpers', () => {
  it('formatWhen renders local-ish compact stamps', () => {
    expect(formatWhen('2026-07-12T14:03:22.123456+00:00')).toContain('2026-07-12')
  })
  it('formatElapsed renders s / m / h forms', () => {
    expect(formatElapsed(4)).toBe('4s')
    expect(formatElapsed(75)).toBe('1m 15s')
    expect(formatElapsed(3675)).toBe('1h 01m 15s')
  })
  it('formatDuration diffs ISO stamps and dashes when open-ended', () => {
    expect(formatDuration('2026-07-12T14:00:00+00:00', '2026-07-12T14:01:15+00:00')).toBe('1m 15s')
    expect(formatDuration('2026-07-12T14:00:00+00:00', null)).toBe('—')
  })
})
```

- [ ] **Step 2: Run to verify failure** — `npx vitest run src/records/format.test.ts` — FAIL (module not found).

- [ ] **Step 3: Implement `src/records/format.ts`**

```ts
/** Record/run time formatting. Statuses use the reserved status palette semantics
 * (good/serious/etc) via Tailwind classes; a chip never carries color alone — the
 * status word is always printed. */

export function formatWhen(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const rest = s % 60
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m ${String(rest).padStart(2, '0')}s`
  if (m > 0) return `${m}m ${rest}s`
  return `${rest}s`
}

export function formatDuration(startedIso: string, endedIso: string | null): string {
  if (endedIso === null) return '—'
  const start = new Date(startedIso).getTime()
  const end = new Date(endedIso).getTime()
  if (Number.isNaN(start) || Number.isNaN(end)) return '—'
  return formatElapsed((end - start) / 1000)
}

export const STATUS_STYLES: Record<string, string> = {
  running: 'bg-blue-100 text-blue-700',
  paused: 'bg-slate-200 text-slate-600',
  completed: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-red-100 text-red-700',
  aborted: 'bg-amber-100 text-amber-700',
  cancelled: 'bg-slate-200 text-slate-600',
  interrupted: 'bg-violet-100 text-violet-700',
}
```

(`format.ts` stays a pure `.ts` module — the `StatusChip` JSX component that consumes `STATUS_STYLES` lives in `RecordsTable.tsx`, Step 5.)

- [ ] **Step 4: Implement `src/stores/navStore.ts` and `src/stores/recordsStore.ts`**

```ts
// src/stores/navStore.ts
/** App-global tab selection so any feature (e.g. the run terminal panel) can jump tabs. */
import { create } from 'zustand'
import type { Tab } from '../shell/TabShell'

interface NavState {
  tab: Tab
  setTab: (tab: Tab) => void
}

export const useNavStore = create<NavState>()((set) => ({
  tab: 'Devices',
  setTab: (tab) => set({ tab }),
}))
```

```ts
// src/stores/recordsStore.ts
import { create } from 'zustand'
import { deleteRecord, listRecords, renameRecord } from '../api/records'
import type { RecordRow } from '../types/records'

interface RecordsState {
  items: RecordRow[] | null
  error: string | null
  loading: boolean
  openId: string | null
  refresh: () => Promise<void>
  open: (id: string | null) => void
  rename: (id: string, name: string) => Promise<string | null>
  remove: (id: string) => Promise<string | null>
}

const msg = (e: unknown): string => (e instanceof Error ? e.message : String(e))

export const useRecordsStore = create<RecordsState>()((set, get) => ({
  items: null,
  error: null,
  loading: false,
  openId: null,

  refresh: async () => {
    set({ loading: true, error: null })
    try {
      set({ items: await listRecords(), loading: false })
    } catch (e) {
      set({ error: msg(e), loading: false })
    }
  },

  open: (openId) => set({ openId }),

  rename: async (id, name) => {
    try {
      const row = await renameRecord(id, name)
      set({ items: (get().items ?? []).map((r) => (r.id === id ? row : r)) })
      return null
    } catch (e) {
      return msg(e)
    }
  },

  remove: async (id) => {
    try {
      await deleteRecord(id)
      set({
        items: (get().items ?? []).filter((r) => r.id !== id),
        openId: get().openId === id ? null : get().openId,
      })
      return null
    } catch (e) {
      return msg(e)
    }
  },
}))
```

- [ ] **Step 5: Implement `src/records/RecordsTable.tsx`** — table per §9.5; inline rename follows the Enter-commit/Escape-cancel convention WITH the cancelled-ref guard (the same fix Task 11 applies to the builder panels):

```tsx
import { useRef, useState } from 'react'
import { recordDownloadUrl } from '../api/records'
import { useRecordsStore } from '../stores/recordsStore'
import type { RecordRow } from '../types/records'
import { STATUS_STYLES, formatDuration, formatWhen } from './format'

export function StatusChip(props: { status: string }) {
  const cls = STATUS_STYLES[props.status] ?? 'bg-slate-200 text-slate-600'
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs ${cls}`}>{props.status}</span>
  )
}

function NameCell(props: { row: RecordRow }) {
  const rename = useRecordsStore((s) => s.rename)
  const open = useRecordsStore((s) => s.open)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(props.row.name)
  const [error, setError] = useState<string | null>(null)
  const cancelled = useRef(false)

  const commit = async () => {
    if (cancelled.current) {
      cancelled.current = false
      setEditing(false)
      return
    }
    const err = draft && draft !== props.row.name ? await rename(props.row.id, draft) : null
    setError(err)
    if (err === null) setEditing(false)
  }

  if (editing) {
    return (
      <div>
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void commit()}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void commit()
            if (e.key === 'Escape') {
              cancelled.current = true
              setEditing(false)
            }
          }}
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-sm"
        />
        {error && <p className="text-xs text-red-600">{error}</p>}
      </div>
    )
  }
  return (
    <div className="flex items-center gap-1">
      <button onClick={() => open(props.row.id)} className="truncate text-left text-sm hover:underline">
        {props.row.name}
      </button>
      <button
        title="Rename record"
        onClick={() => {
          setDraft(props.row.name)
          setEditing(true)
        }}
        className="text-xs text-slate-300 hover:text-slate-600"
      >
        ✎
      </button>
    </div>
  )
}

export function RecordsTable() {
  const items = useRecordsStore((s) => s.items)
  const error = useRecordsStore((s) => s.error)
  const loading = useRecordsStore((s) => s.loading)
  const refresh = useRecordsStore((s) => s.refresh)
  const remove = useRecordsStore((s) => s.remove)
  const [rowError, setRowError] = useState<string | null>(null)

  if (error !== null) {
    return (
      <div className="rounded-lg border border-red-200 bg-white p-6 text-center text-sm">
        <p className="mb-2 text-red-700">{error}</p>
        <button onClick={() => void refresh()} className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100">
          Retry
        </button>
      </div>
    )
  }
  if (items === null) return <p className="p-6 text-sm text-slate-400">loading records…</p>
  if (items.length === 0) {
    return <p className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-500">No records yet — run an experiment first.</p>
  }
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      {rowError && <p className="px-3 pt-2 text-xs text-red-600">{rowError}</p>}
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-xs text-slate-500">
            <th className="px-3 py-2">Name</th>
            <th className="px-3 py-2">Experiment</th>
            <th className="px-3 py-2">Lab</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Started</th>
            <th className="px-3 py-2">Duration</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr key={row.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
              <td className="max-w-64 px-3 py-1.5"><NameCell row={row} /></td>
              <td className="px-3 py-1.5 text-slate-500">{row.experiment_name}</td>
              <td className="px-3 py-1.5 text-slate-500">{row.lab}</td>
              <td className="px-3 py-1.5"><StatusChip status={row.status} /></td>
              <td className="px-3 py-1.5 text-slate-500">{formatWhen(row.started_at)}</td>
              <td className="px-3 py-1.5 text-slate-500">{formatDuration(row.started_at, row.ended_at)}</td>
              <td className="px-3 py-1.5 text-right">
                <a
                  href={recordDownloadUrl(row.id)}
                  title="Download zip"
                  className="mr-2 text-xs text-slate-400 hover:text-slate-700"
                >
                  ⬇
                </a>
                <button
                  title="Delete record"
                  onClick={() => {
                    if (!window.confirm(`Delete record '${row.name}' and its artifacts?`)) return
                    void remove(row.id).then(setRowError)
                  }}
                  className="text-xs text-slate-300 hover:text-red-600"
                >
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {loading && <p className="px-3 py-1 text-xs text-slate-400">refreshing…</p>}
    </div>
  )
}
```

- [ ] **Step 6: Implement `src/records/RecordsTab.tsx`** (viewer placeholder until Task 10):

```tsx
import { useEffect } from 'react'
import { useRecordsStore } from '../stores/recordsStore'
import { RecordsTable } from './RecordsTable'

export function RecordsTab() {
  const openId = useRecordsStore((s) => s.openId)
  useEffect(() => {
    void useRecordsStore.getState().refresh()
  }, [])
  if (openId !== null) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
        <button onClick={() => useRecordsStore.getState().open(null)} className="mb-2 text-xs hover:underline">← back to records</button>
        <p>record viewer lands in a later task</p>
      </div>
    )
  }
  return <RecordsTable />
}
```

- [ ] **Step 7: Rewire `src/App.tsx`** — tab state moves to navStore; Records mounts for real (Run keeps its placeholder until Task 6):

```tsx
import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api/client'
import { describeHealth } from './api/health'
import { TabShell } from './shell/TabShell'
import { BuilderTab } from './builder/BuilderTab'
import { DevicesTab } from './devices/DevicesTab'
import { RecordsTab } from './records/RecordsTab'
import { useLabsStore } from './stores/labsStore'
import { useNavStore } from './stores/navStore'

export default function App() {
  const tab = useNavStore((s) => s.tab)
  const setTab = useNavStore((s) => s.setTab)
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)
  const lab = useLabsStore((s) => s.selected)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  return (
    <TabShell active={tab} onSelect={setTab} statusLine={describeHealth(health, error)} lab={lab}>
      {tab === 'Devices' && <DevicesTab />}
      {tab === 'Builder' && <BuilderTab />}
      {tab === 'Run' && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          Run controls land in the next task.
        </div>
      )}
      {tab === 'Records' && <RecordsTab />}
    </TabShell>
  )
}
```

- [ ] **Step 8: Gate + commit**

Run: `npm run lint && npm run typecheck && npm test && npm run build` — green.

```bash
git add webapp/frontend/src
git commit -m "feat(studio): records list — store, table with rename/delete/download, nav store"
```

---

### Task 6: Run tab shell + preflight panel

**Files:**
- Create: `webapp/frontend/src/run/preflight.ts`, `webapp/frontend/src/run/PreflightPanel.tsx`, `webapp/frontend/src/run/RunTab.tsx`
- Modify: `webapp/frontend/src/App.tsx` (mount RunTab)
- Test: `webapp/frontend/src/run/preflight.test.ts`

**Interfaces:**
- Consumes: `useLabsStore` (`selected`, `devices`, `refreshDevices`); `listExperiments`/`getExperiment`/`validateDoc` from `src/api/studio.ts`; `savedMapping`, `useRunStore.start`, `useDocStore` (`serverId` for the default experiment); `Diagnostic`.
- Produces: `buildMappingRows(roles, devices, chosen): MappingRow[]`, `prefillMapping(roles, devices, saved): Record<string,string>`, `mappingComplete(rows): boolean` where `MappingRow = { role: string; type: string; options: LabDevice[]; selected: string | null }`; `RunTab` (phase switch; Task 7 provides `RunView`, until then active phase renders a minimal status line).

- [ ] **Step 1: Write the failing tests** — `src/run/preflight.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { buildMappingRows, mappingComplete, prefillMapping } from './preflight'
import type { LabDevice } from '../types/labs'

const dev = (id: string, type: string): LabDevice =>
  ({ id, type, port: null, connected: true, model: null, firmware: null })
const DEVICES = [dev('pump_1', 'pump'), dev('pump_2', 'pump'), dev('densitometer_1', 'densitometer')]
const ROLES = { feed: { type: 'pump' }, meter: { type: 'densitometer' } }

describe('buildMappingRows', () => {
  it('filters options by role type and keeps only valid selections', () => {
    const rows = buildMappingRows(ROLES, DEVICES, { feed: 'pump_2', meter: 'thermostat_1' })
    expect(rows.map((r) => r.role)).toEqual(['feed', 'meter'])
    expect(rows[0].options.map((d) => d.id)).toEqual(['pump_1', 'pump_2'])
    expect(rows[0].selected).toBe('pump_2')
    expect(rows[1].selected).toBeNull() // wrong-type selection dropped
  })
  it('handles a null roster', () => {
    const rows = buildMappingRows(ROLES, null, {})
    expect(rows[0].options).toEqual([])
  })
})

describe('prefillMapping', () => {
  it('keeps saved entries only when present in the roster with the right type', () => {
    expect(
      prefillMapping(ROLES, DEVICES, { feed: 'pump_9', meter: 'densitometer_1', ghost: 'x_1' }),
    ).toEqual({ meter: 'densitometer_1' })
  })
})

describe('mappingComplete', () => {
  it('true only when every role has a selection', () => {
    const rows = buildMappingRows(ROLES, DEVICES, { feed: 'pump_1', meter: 'densitometer_1' })
    expect(mappingComplete(rows)).toBe(true)
    expect(mappingComplete(buildMappingRows(ROLES, DEVICES, { feed: 'pump_1' }))).toBe(false)
  })
})
```

- [ ] **Step 2: Run to verify failure** — `npx vitest run src/run/preflight.test.ts` — FAIL.

- [ ] **Step 3: Implement `src/run/preflight.ts`**

```ts
/** Pure preflight-mapping helpers (§9.4): options filtered by role type, saved-mapping
 * pre-fill applies only where the device still exists in the roster with the right type. */
import type { LabDevice } from '../types/labs'

export interface MappingRow {
  role: string
  type: string
  options: LabDevice[]
  selected: string | null
}

export function buildMappingRows(
  roles: Record<string, { type: string }>,
  devices: LabDevice[] | null,
  chosen: Record<string, string>,
): MappingRow[] {
  return Object.entries(roles).map(([role, def]) => {
    const options = (devices ?? []).filter((d) => d.type === def.type)
    const candidate = chosen[role]
    const selected =
      candidate !== undefined && options.some((d) => d.id === candidate) ? candidate : null
    return { role, type: def.type, options, selected }
  })
}

export function prefillMapping(
  roles: Record<string, { type: string }>,
  devices: LabDevice[] | null,
  saved: Record<string, string>,
): Record<string, string> {
  const out: Record<string, string> = {}
  for (const row of buildMappingRows(roles, devices, saved)) {
    if (row.selected !== null) out[row.role] = row.selected
  }
  return out
}

export const mappingComplete = (rows: MappingRow[]): boolean =>
  rows.length > 0 && rows.every((r) => r.selected !== null)
```

- [ ] **Step 4: Implement `src/run/PreflightPanel.tsx`**

Behavior (all fetch errors render inline with the message; nothing spins forever):
- On mount: `listExperiments()`; default selection = `useDocStore.getState().serverId` when it appears in the list, else first item; also `refreshDevices()` when a lab is selected.
- On experiment or lab change: `getExperiment(id)` → keep `doc`; `validateDoc(doc)` → `{ok, diagnostics}`; `savedMapping(id, lab)` (errors → `{}`) merged via `prefillMapping` into the `chosen` state (user picks override prefill).
- Start enabled iff: lab selected, validation `ok`, `mappingComplete(rows)`, `!startBusy`.
- On Start: `useRunStore.getState().start({experiment_id, lab, role_mapping})`; afterwards render `startError` + `startDiagnostics` from the store (server is the final authority — its 422 diagnostics render in the same list as the local validate ones).

```tsx
import { useCallback, useEffect, useState } from 'react'
import { getExperiment, listExperiments, validateDoc } from '../api/studio'
import { savedMapping } from '../api/runs'
import { useDocStore } from '../stores/docStore'
import { useLabsStore } from '../stores/labsStore'
import { useNavStore } from '../stores/navStore'
import { useRunStore } from '../stores/runStore'
import type { Diagnostic, ExperimentDocJson, ExperimentSummary } from '../types/doc'
import { buildMappingRows, mappingComplete, prefillMapping } from './preflight'

export function PreflightPanel() {
  const lab = useLabsStore((s) => s.selected)
  const devices = useLabsStore((s) => s.devices)
  const devicesError = useLabsStore((s) => s.devicesError)
  const startBusy = useRunStore((s) => s.startBusy)
  const startError = useRunStore((s) => s.startError)
  const startDiagnostics = useRunStore((s) => s.startDiagnostics)

  const [experiments, setExperiments] = useState<ExperimentSummary[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [doc, setDoc] = useState<ExperimentDocJson | null>(null)
  const [docError, setDocError] = useState<string | null>(null)
  const [diagnostics, setDiagnostics] = useState<Diagnostic[] | null>(null)
  const [validating, setValidating] = useState(false)
  const [chosen, setChosen] = useState<Record<string, string>>({})

  useEffect(() => {
    listExperiments()
      .then((items) => {
        setExperiments(items)
        const builderId = useDocStore.getState().serverId
        const fallback = items.length > 0 ? items[0].id : null
        setSelectedId(items.some((i) => i.id === builderId) ? builderId : fallback)
      })
      .catch((e: unknown) => setListError(e instanceof Error ? e.message : String(e)))
    if (useLabsStore.getState().selected !== null) void useLabsStore.getState().refreshDevices()
  }, [])

  const loadSelection = useCallback((id: string, currentLab: string | null) => {
    setDoc(null)
    setDocError(null)
    setDiagnostics(null)
    setChosen({})
    setValidating(true)
    getExperiment(id)
      .then(async (res) => {
        setDoc(res.doc)
        const [validation, saved] = await Promise.all([
          validateDoc(res.doc),
          currentLab !== null ? savedMapping(id, currentLab).catch(() => ({})) : Promise.resolve({}),
        ])
        setDiagnostics(validation.diagnostics)
        setChosen(prefillMapping(res.doc.roles, useLabsStore.getState().devices, saved))
      })
      .catch((e: unknown) => setDocError(e instanceof Error ? e.message : String(e)))
      .finally(() => setValidating(false))
  }, [])

  useEffect(() => {
    if (selectedId !== null) loadSelection(selectedId, lab)
  }, [selectedId, lab, loadSelection])

  if (lab === null) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-500">
        <p className="mb-2">Select a lab first.</p>
        <button onClick={() => useNavStore.getState().setTab('Devices')} className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100">
          Go to Devices
        </button>
      </div>
    )
  }

  const rows = doc !== null ? buildMappingRows(doc.roles, devices, chosen) : []
  const clean = diagnostics !== null && diagnostics.length === 0
  const canStart = clean && mappingComplete(rows) && !startBusy && selectedId !== null
  const problems = [...(diagnostics ?? []), ...(startDiagnostics ?? [])]

  return (
    <div className="mx-auto max-w-2xl space-y-4 rounded-lg border border-slate-200 bg-white p-6">
      <h2 className="text-sm font-semibold">Start a run on {lab}</h2>
      {listError && <p className="text-xs text-red-600">{listError}</p>}
      {experiments !== null && experiments.length === 0 && (
        <p className="text-sm text-slate-500">No saved experiments — build one first.</p>
      )}
      {experiments !== null && experiments.length > 0 && (
        <label className="block text-xs">
          <span className="mb-0.5 block text-slate-500">Experiment</span>
          <select
            value={selectedId ?? ''}
            onChange={(e) => setSelectedId(e.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          >
            {experiments.map((e) => (
              <option key={e.id} value={e.id}>{e.name}</option>
            ))}
          </select>
        </label>
      )}
      {docError && <p className="text-xs text-red-600">{docError}</p>}
      {devicesError && <p className="text-xs text-red-600">{devicesError}</p>}
      {doc !== null && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-slate-500">Role mapping</p>
          {rows.length === 0 && <p className="text-xs text-slate-400">this experiment defines no roles</p>}
          {rows.map((row) => (
            <label key={row.role} className="flex items-center gap-2 text-xs">
              <span className="w-32 truncate font-mono">{row.role}</span>
              <span className="w-24 text-slate-400">{row.type}</span>
              <select
                value={row.selected ?? ''}
                onChange={(e) =>
                  setChosen((c) => ({ ...c, [row.role]: e.target.value }))
                }
                className="flex-1 rounded border border-slate-300 px-2 py-1"
              >
                <option value="" disabled>
                  {row.options.length === 0 ? `no ${row.type} devices in ${lab}` : 'pick a device…'}
                </option>
                {row.options.map((d) => (
                  <option key={d.id} value={d.id}>{d.id}</option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}
      <div className="text-xs">
        {validating && <span className="text-slate-400">validating…</span>}
        {clean && !validating && <span className="text-emerald-700">✓ workflow valid</span>}
      </div>
      {problems.length > 0 && (
        <ul className="max-h-40 space-y-0.5 overflow-y-auto rounded border border-red-100 bg-red-50 p-2 text-xs">
          {problems.map((d, i) => (
            <li key={i}>
              <span className="mr-1 rounded bg-white px-1 font-mono text-[10px]">{d.category}</span>
              <span className="mr-1 font-mono text-[10px] text-slate-400">{d.path}</span>
              {d.message}
            </li>
          ))}
        </ul>
      )}
      {startError && <p className="text-xs text-red-600">{startError}</p>}
      <button
        disabled={!canStart}
        onClick={() => {
          if (selectedId === null) return
          const role_mapping = Object.fromEntries(
            rows.filter((r) => r.selected !== null).map((r) => [r.role, r.selected as string]),
          )
          void useRunStore.getState().start({ experiment_id: selectedId, lab, role_mapping })
        }}
        className="w-full rounded bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-40"
      >
        {startBusy ? 'Starting…' : 'Start run'}
      </button>
    </div>
  )
}
```

- [ ] **Step 5: Implement `src/run/RunTab.tsx`** and mount in `App.tsx`

```tsx
import { useEffect } from 'react'
import { useRunStore } from '../stores/runStore'
import { PreflightPanel } from './PreflightPanel'

export function RunTab() {
  const phase = useRunStore((s) => s.phase)
  useEffect(() => {
    void useRunStore.getState().attach()
  }, [])
  if (phase === 'unknown') {
    return <p className="p-6 text-sm text-slate-400">checking for an active run…</p>
  }
  if (phase === 'idle') return <PreflightPanel />
  // 'active' | 'terminal' — RunView lands in the next task
  return <p className="p-6 text-sm text-slate-400">run view lands in the next task</p>
}
```

In `App.tsx` replace the Run placeholder branch with `{tab === 'Run' && <RunTab />}` (add the import, drop the placeholder div).

- [ ] **Step 6: Gate + commit**

Run: `npm run lint && npm run typecheck && npm test && npm run build` — green.

```bash
git add webapp/frontend/src
git commit -m "feat(studio): run preflight — experiment picker, role mapping with prefill, start gating"
```

---

### Task 7: Active run view — header, controls, event log, terminal report

**Files:**
- Create: `webapp/frontend/src/run/describeEvent.ts`, `webapp/frontend/src/run/EventLog.tsx`, `webapp/frontend/src/run/RunView.tsx`
- Modify: `webapp/frontend/src/run/RunTab.tsx` (mount RunView)
- Test: `webapp/frontend/src/run/describeEvent.test.ts`

**Interfaces:**
- Consumes: `useRunStore` (Task 4), `formatElapsed`/`StatusChip` (Task 5 — import `StatusChip` from `../records/RecordsTable`), `useNavStore`, `useRecordsStore`.
- Produces: `describeEvent(e: {kind, data}): string` covering EVERY engine event kind; `EventLog` props `{ events: ReadonlyArray<{timestamp:number; kind:string; block_id:string|null; data:Record<string,unknown>}>, origin: number | null, rev: number }` — reused verbatim by the record viewer (Task 10); `RunView` (no props).

- [ ] **Step 1: Write the failing tests** — `src/run/describeEvent.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { describeEvent } from './describeEvent'

const d = (kind: string, data: Record<string, unknown> = {}) => describeEvent({ kind, data })

describe('describeEvent', () => {
  it('covers run lifecycle', () => {
    expect(d('run_started')).toBe('run started')
    expect(d('run_finished', { status: 'completed' })).toBe('run finished: completed')
    expect(d('paused')).toBe('run paused')
    expect(d('resumed')).toBe('run resumed')
    expect(d('abort_requested')).toBe('abort requested')
  })
  it('covers block execution', () => {
    expect(d('block_started')).toBe('block started')
    expect(d('block_finished')).toBe('block finished')
    expect(d('block_failed', { error: 'boom' })).toBe('block failed: boom')
    expect(d('invariant_violation', { error: 'busy' })).toBe('invariant violation: busy')
    expect(d('mode_opened', { device: 'thermostat_1', verb: 'hold' })).toBe('thermostat_1: mode hold opened')
    expect(d('mode_closed', { device: 'thermostat_1', verb: 'hold' })).toBe('thermostat_1: mode hold closed')
    expect(d('measure_recorded', { stream: 'od', value: 0.5321 })).toBe('od = 0.5321')
    expect(d('input_requested', { name: 'target' })).toBe("operator input requested: 'target'")
    expect(d('input_bound', { name: 'target', value: 5 })).toBe('target = 5')
  })
  it('covers the finalizer', () => {
    expect(d('finalize_started')).toBe('finalize started')
    expect(d('finalize_finished', { errors: 0 })).toBe('finalize finished (0 errors)')
    expect(d('job_cancelled', { device: 'pump_1', verb: 'dispense' })).toBe('pump_1: job dispense cancelled')
    expect(d('teardown_issued', { device: 'pump_1', verb: 'stop' })).toBe('pump_1: teardown stop issued')
    expect(d('sweep_command', { device: 'pump_1', verb: 'stop' })).toBe('pump_1: sweep stop')
    expect(d('finalize_step_failed', { device: 'pump_1', verb: 'stop', error: 'timeout' }))
      .toBe('pump_1: finalize stop failed: timeout')
  })
  it('falls back to kind + data for unknown kinds', () => {
    expect(d('mystery', { a: 1 })).toBe('mystery {"a":1}')
    expect(d('mystery')).toBe('mystery')
  })
})
```

- [ ] **Step 2: Run to verify failure** — `npx vitest run src/run/describeEvent.test.ts` — FAIL.

- [ ] **Step 3: Implement `src/run/describeEvent.ts`**

```ts
/** Human-readable one-liners for engine RunEvents (§9.4 event log). One case per kind
 * emitted by the engine (run.py / execute.py / finalize.py); unknown kinds degrade to
 * `kind {json}` so a future engine event never renders blank. */

interface EventLike {
  kind: string
  data: Record<string, unknown>
}

const s = (v: unknown): string => String(v)

export function describeEvent(e: EventLike): string {
  const d = e.data
  switch (e.kind) {
    case 'run_started': return 'run started'
    case 'run_finished': return `run finished: ${s(d.status)}`
    case 'paused': return 'run paused'
    case 'resumed': return 'run resumed'
    case 'abort_requested': return 'abort requested'
    case 'block_started': return 'block started'
    case 'block_finished': return 'block finished'
    case 'block_failed': return `block failed: ${s(d.error)}`
    case 'invariant_violation': return `invariant violation: ${s(d.error)}`
    case 'mode_opened': return `${s(d.device)}: mode ${s(d.verb)} opened`
    case 'mode_closed': return `${s(d.device)}: mode ${s(d.verb)} closed`
    case 'measure_recorded': return `${s(d.stream)} = ${s(d.value)}`
    case 'input_requested': return `operator input requested: '${s(d.name)}'`
    case 'input_bound': return `${s(d.name)} = ${s(d.value)}`
    case 'finalize_started': return 'finalize started'
    case 'finalize_finished': return `finalize finished (${s(d.errors)} errors)`
    case 'job_cancelled': return `${s(d.device)}: job ${s(d.verb)} cancelled`
    case 'teardown_issued': return `${s(d.device)}: teardown ${s(d.verb)} issued`
    case 'sweep_command': return `${s(d.device)}: sweep ${s(d.verb)}`
    case 'finalize_step_failed':
      return `${s(d.device)}: finalize ${s(d.verb)} failed: ${s(d.error)}`
    default: {
      const extra = Object.keys(d).length > 0 ? ` ${JSON.stringify(d)}` : ''
      return `${e.kind}${extra}`
    }
  }
}
```

- [ ] **Step 4: Implement `src/run/EventLog.tsx`**

```tsx
/** Scrolling event log (§9.4): last 500 events, auto-scroll pinned to the bottom unless
 * the pointer is over the log (pause-on-hover). Reused by the record viewer with a
 * static list (rev stays constant there). */
import { useEffect, useRef, useState } from 'react'
import { formatElapsed } from '../records/format'
import { describeEvent } from './describeEvent'

export interface LogEvent {
  timestamp: number
  kind: string
  block_id: string | null
  data: Record<string, unknown>
}

const KIND_COLOR: Record<string, string> = {
  block_failed: 'text-red-700',
  invariant_violation: 'text-red-700',
  finalize_step_failed: 'text-red-700',
  measure_recorded: 'text-blue-700',
  input_requested: 'text-amber-700',
  input_bound: 'text-amber-700',
}

export function EventLog(props: { events: ReadonlyArray<LogEvent>; origin: number | null; rev: number }) {
  const box = useRef<HTMLDivElement | null>(null)
  const [hovered, setHovered] = useState(false)

  useEffect(() => {
    if (!hovered && box.current !== null) box.current.scrollTop = box.current.scrollHeight
  }, [props.rev, hovered])

  const shown = props.events.slice(-500)
  return (
    <div
      ref={box}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="h-64 overflow-y-auto rounded-lg border border-slate-200 bg-white p-2 font-mono text-xs"
    >
      {shown.length === 0 && <p className="text-slate-400">no events yet</p>}
      {shown.map((e, i) => (
        <div key={`${props.events.length - shown.length + i}`} className="flex gap-2 py-px">
          <span className="w-20 shrink-0 text-right text-slate-400">
            {props.origin !== null ? `+${formatElapsed(e.timestamp - props.origin)}` : ''}
          </span>
          <span className={`min-w-0 flex-1 ${KIND_COLOR[e.kind] ?? 'text-slate-700'}`}>
            {describeEvent(e)}
            {e.block_id !== null && <span className="ml-1 text-slate-400">[{e.block_id}]</span>}
          </span>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 5: Implement `src/run/RunView.tsx`**

```tsx
/** Active-run screen (§9.4): status header + controls, event log, terminal report.
 * The live chart slot is filled by Task 9; the input dialog by Task 8. */
import { useEffect, useState } from 'react'
import { useNavStore } from '../stores/navStore'
import { useRecordsStore } from '../stores/recordsStore'
import { useRunStore } from '../stores/runStore'
import { StatusChip } from '../records/RecordsTable'
import { formatElapsed } from '../records/format'
import { EventLog } from './EventLog'

function Elapsed() {
  const feed = useRunStore((s) => s.feed)
  const lastWallMs = useRunStore((s) => s.lastWallMs)
  const [, tick] = useState(0)
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [])
  if (feed.origin === null || feed.lastTimestamp === null) return null
  const base = feed.lastTimestamp - feed.origin
  const drift =
    !feed.terminal && lastWallMs !== null ? (Date.now() - lastWallMs) / 1000 : 0
  return <span className="font-mono text-sm text-slate-500">{formatElapsed(base + drift)}</span>
}

export function RunView() {
  const experiment = useRunStore((s) => s.experiment)
  const lab = useRunStore((s) => s.lab)
  const feed = useRunStore((s) => s.feed)
  const phase = useRunStore((s) => s.phase)
  const controlBusy = useRunStore((s) => s.controlBusy)
  const report = useRunStore((s) => s.report)
  const recordId = useRunStore((s) => s.recordId)

  const buttonClass =
    'rounded border border-slate-300 bg-white px-3 py-1 text-xs hover:bg-slate-100 disabled:opacity-40'

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{experiment?.name ?? 'experiment'}</p>
          <p className="text-xs text-slate-400">lab: {lab}</p>
        </div>
        <StatusChip status={feed.status} />
        <Elapsed />
        <span className="ml-auto flex gap-1">
          {phase === 'active' && feed.status === 'running' && (
            <button className={buttonClass} disabled={controlBusy}
              onClick={() => void useRunStore.getState().pause()}>Pause</button>
          )}
          {phase === 'active' && feed.status === 'paused' && (
            <button className={buttonClass} disabled={controlBusy}
              onClick={() => void useRunStore.getState().resume()}>Resume</button>
          )}
          {phase === 'active' && (
            <button
              className={`${buttonClass} text-red-700`}
              disabled={controlBusy}
              onClick={() => {
                if (window.confirm('Abort this run? The finalizer will tear devices down.')) {
                  void useRunStore.getState().abort()
                }
              }}
            >
              Abort
            </button>
          )}
          {phase === 'terminal' && (
            <button className={buttonClass} onClick={() => useRunStore.getState().dismiss()}>
              New run
            </button>
          )}
        </span>
      </div>

      {phase === 'terminal' && (
        <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
          <p className="mb-1 font-semibold">
            Run finished: <StatusChip status={report?.status ?? feed.status} />
          </p>
          {report?.error && <p className="text-xs text-red-700">error: {report.error}</p>}
          {report !== null && report.finalize_errors.length > 0 && (
            <p className="text-xs text-amber-700">
              finalize errors: {report.finalize_errors.join('; ')}
            </p>
          )}
          {report !== null && report.persistence_errors.length > 0 && (
            <p className="text-xs text-amber-700">
              persistence errors: {report.persistence_errors.join('; ')}
            </p>
          )}
          {recordId !== null && (
            <button
              onClick={() => {
                useRecordsStore.getState().open(recordId)
                useNavStore.getState().setTab('Records')
              }}
              className="mt-2 rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100"
            >
              Open record
            </button>
          )}
        </div>
      )}

      {/* Task 9 replaces this placeholder with the live StreamChart */}
      <EventLog events={feed.events} origin={feed.origin} rev={feed.rev} />
    </div>
  )
}
```

In `RunTab.tsx`, replace the active/terminal placeholder line with `return <RunView />` (add the import).

- [ ] **Step 6: Gate + commit**

Run: `npm run lint && npm run typecheck && npm test && npm run build` — green.

```bash
git add webapp/frontend/src
git commit -m "feat(studio): active-run view — status header, controls, event log, terminal report"
```

---

### Task 8: Operator input dialog

**Files:**
- Create: `webapp/frontend/src/run/inputValue.ts`, `webapp/frontend/src/run/InputDialog.tsx`
- Modify: `webapp/frontend/src/run/RunView.tsx` (mount dialog)
- Test: `webapp/frontend/src/run/inputValue.test.ts`

**Interfaces:**
- Consumes: `PendingInput` (Task 2), `useRunStore.submit` (Task 4).
- Produces: `validateInputValue(input: PendingInput, raw: string | boolean): { ok: true; value: boolean | number | string } | { ok: false; error: string }` — a client-side mirror of the engine's `validate_input_value` (bool: real boolean; enum: string ∈ choices; int: integer, bool rejected; float: finite number; min/max bounds on int/float). The server remains the authority (§7.4): a server 422 keeps the dialog open with the error.

- [ ] **Step 1: Write the failing tests** — `src/run/inputValue.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { validateInputValue } from './inputValue'
import type { PendingInput } from '../types/runs'

const req = (over: Partial<PendingInput>): PendingInput => ({
  name: 'x', type: 'int', prompt: null, min: null, max: null, choices: null,
  block_id: 'b1', ...over,
})

describe('validateInputValue', () => {
  it('int: parses integers, rejects floats and garbage, enforces bounds', () => {
    expect(validateInputValue(req({ type: 'int' }), '5')).toEqual({ ok: true, value: 5 })
    expect(validateInputValue(req({ type: 'int' }), '5.5').ok).toBe(false)
    expect(validateInputValue(req({ type: 'int' }), 'abc').ok).toBe(false)
    expect(validateInputValue(req({ type: 'int', min: 1, max: 10 }), '11').ok).toBe(false)
    expect(validateInputValue(req({ type: 'int', min: 1 }), '0').ok).toBe(false)
  })
  it('float: parses finite numbers, enforces bounds', () => {
    expect(validateInputValue(req({ type: 'float' }), '0.6')).toEqual({ ok: true, value: 0.6 })
    expect(validateInputValue(req({ type: 'float' }), 'inf').ok).toBe(false)
    expect(validateInputValue(req({ type: 'float', max: 1 }), '1.5').ok).toBe(false)
  })
  it('bool: requires an actual boolean', () => {
    expect(validateInputValue(req({ type: 'bool' }), true)).toEqual({ ok: true, value: true })
    expect(validateInputValue(req({ type: 'bool' }), 'true').ok).toBe(false)
  })
  it('enum: string must be one of choices when given', () => {
    const e = req({ type: 'enum', choices: ['a', 'b'] })
    expect(validateInputValue(e, 'a')).toEqual({ ok: true, value: 'a' })
    expect(validateInputValue(e, 'c').ok).toBe(false)
    expect(validateInputValue(req({ type: 'enum', choices: null }), 'anything').ok).toBe(true)
  })
})
```

- [ ] **Step 2: Run to verify failure** — `npx vitest run src/run/inputValue.test.ts` — FAIL.

- [ ] **Step 3: Implement `src/run/inputValue.ts`**

```ts
/** Client-side mirror of the engine's validate_input_value (§7.4) so obviously-bad
 * values never round-trip; the server 422 (invalid_value) remains the authority. */
import type { PendingInput } from '../types/runs'

export type InputCheck =
  | { ok: true; value: boolean | number | string }
  | { ok: false; error: string }

const bounds = (input: PendingInput, n: number): InputCheck => {
  if (input.min !== null && n < input.min) return { ok: false, error: `must be ≥ ${input.min}` }
  if (input.max !== null && n > input.max) return { ok: false, error: `must be ≤ ${input.max}` }
  return { ok: true, value: n }
}

export function validateInputValue(input: PendingInput, raw: string | boolean): InputCheck {
  switch (input.type) {
    case 'bool':
      return typeof raw === 'boolean'
        ? { ok: true, value: raw }
        : { ok: false, error: 'pick yes or no' }
    case 'enum': {
      if (typeof raw !== 'string' || raw === '') return { ok: false, error: 'pick a choice' }
      if (input.choices !== null && !input.choices.includes(raw)) {
        return { ok: false, error: `must be one of: ${input.choices.join(', ')}` }
      }
      return { ok: true, value: raw }
    }
    case 'int': {
      const text = typeof raw === 'string' ? raw.trim() : ''
      if (!/^[+-]?\d+$/.test(text)) return { ok: false, error: 'enter a whole number' }
      return bounds(input, Number(text))
    }
    case 'float': {
      const text = typeof raw === 'string' ? raw.trim() : ''
      const n = Number(text)
      if (text === '' || !Number.isFinite(n)) return { ok: false, error: 'enter a number' }
      return bounds(input, n)
    }
  }
}
```

- [ ] **Step 4: Implement `src/run/InputDialog.tsx`**

```tsx
/** Modal for a pending OperatorInput (§9.4). Not dismissable by Escape/backdrop — the
 * run is parked on it — but it can be hidden behind the banner button and reopened. A
 * server 422 (invalid_value) keeps it open: the request stays pending (§7.4). */
import { useState } from 'react'
import { useRunStore } from '../stores/runStore'
import type { PendingInput } from '../types/runs'
import { validateInputValue } from './inputValue'

function Widget(props: {
  input: PendingInput
  raw: string | boolean
  setRaw: (v: string | boolean) => void
}) {
  const { input, raw, setRaw } = props
  if (input.type === 'bool') {
    return (
      <div className="flex gap-3 text-sm">
        {[true, false].map((v) => (
          <label key={String(v)} className="flex items-center gap-1">
            <input type="radio" checked={raw === v} onChange={() => setRaw(v)} />
            {v ? 'yes' : 'no'}
          </label>
        ))}
      </div>
    )
  }
  if (input.type === 'enum') {
    return (
      <select
        value={typeof raw === 'string' ? raw : ''}
        onChange={(e) => setRaw(e.target.value)}
        className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
      >
        <option value="" disabled>pick…</option>
        {(input.choices ?? []).map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
    )
  }
  const hint = [
    input.min !== null ? `min ${input.min}` : null,
    input.max !== null ? `max ${input.max}` : null,
  ].filter(Boolean).join(', ')
  return (
    <div>
      <input
        autoFocus
        value={typeof raw === 'string' ? raw : ''}
        onChange={(e) => setRaw(e.target.value)}
        inputMode={input.type === 'int' ? 'numeric' : 'decimal'}
        className="w-full rounded border border-slate-300 px-2 py-1 font-mono text-sm"
      />
      {hint && <p className="mt-0.5 text-[10px] text-slate-400">{hint}</p>}
    </div>
  )
}

export function InputDialog() {
  const pending = useRunStore((s) => s.pendingInput)
  const serverError = useRunStore((s) => s.inputError)
  const [raw, setRaw] = useState<string | boolean>('')
  const [localError, setLocalError] = useState<string | null>(null)
  const [hidden, setHidden] = useState(false)
  const [busy, setBusy] = useState(false)
  const [forName, setForName] = useState<string | null>(null)

  if (pending === null) return null
  if (forName !== pending.name) {
    // a new request arrived — reset widget state for it
    setForName(pending.name)
    setRaw(pending.type === 'bool' ? true : '')
    setLocalError(null)
    setHidden(false)
    return null
  }
  if (hidden) {
    return (
      <button
        onClick={() => setHidden(false)}
        className="w-full rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-left text-sm text-amber-800"
      >
        ⌨ Operator input required: '{pending.name}' — click to answer
      </button>
    )
  }

  const submit = async () => {
    const check = validateInputValue(pending, raw)
    if (!check.ok) {
      setLocalError(check.error)
      return
    }
    setLocalError(null)
    setBusy(true)
    await useRunStore.getState().submit(check.value)
    setBusy(false)
  }

  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/30">
      <div className="w-96 rounded-lg bg-white p-4 shadow-xl">
        <div className="mb-2 flex items-start justify-between">
          <h2 className="text-sm font-semibold">Operator input: {pending.name}</h2>
          <button onClick={() => setHidden(true)} title="Hide (the run stays paused on this input)"
            className="text-slate-400 hover:text-slate-700">—</button>
        </div>
        {pending.prompt && <p className="mb-2 text-sm text-slate-600">{pending.prompt}</p>}
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
        >
          <Widget input={pending} raw={raw} setRaw={setRaw} />
          {(localError ?? serverError) && (
            <p className="mt-1 text-xs text-red-600">{localError ?? serverError}</p>
          )}
          <button
            type="submit"
            disabled={busy}
            className="mt-3 w-full rounded bg-blue-600 py-1.5 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-40"
          >
            Submit
          </button>
        </form>
      </div>
    </div>
  )
}
```

NOTE for the implementer: the `forName !== pending.name` reset-during-render returns `null` for one frame and re-renders with fresh state — this is the sanctioned React pattern for resetting state on prop change without an effect; do not convert it to a `useEffect`. (Repeated prompts with the same binding name across loop iterations reuse the widget state; that is acceptable — the value is usually similar.)

- [ ] **Step 5: Mount in `RunView.tsx`** — add `import { InputDialog } from './InputDialog'` and render `<InputDialog />` as the first child inside the top-level `<div className="space-y-3">`.

- [ ] **Step 6: Gate + commit**

Run: `npm run lint && npm run typecheck && npm test && npm run build` — green.

```bash
git add webapp/frontend/src
git commit -m "feat(studio): operator-input dialog with typed widgets and engine-mirrored validation"
```

---

### Task 9: Live chart — uPlot, series alignment, stream colors

**Files:**
- Modify: `webapp/frontend/package.json` (add `uplot`)
- Create: `webapp/frontend/src/charts/align.ts`, `webapp/frontend/src/charts/StreamChart.tsx`
- Modify: `webapp/frontend/src/run/RunView.tsx` (replace the chart placeholder comment)
- Test: `webapp/frontend/src/charts/align.test.ts`

**Interfaces:**
- Consumes: `useRunStore` feed (`samples`, `origin`, `rev`, `streamUnits`).
- Produces: `alignSeries(series: NamedSeries[]): uPlotData` where `NamedSeries = { label: string; t: number[]; v: number[] }` and `uPlotData = [number[], ...(number | null)[][]]` (x = union of timestamps, per-series `null` gaps); `StreamChart` props `{ series: Array<{ label: string; units: string | null; t: number[]; v: number[] }>; height?: number }` — timestamps must already be **elapsed seconds** (caller subtracts the origin). Task 10 reuses `StreamChart` for the record viewer.
- Chart design (dataviz method, light mode): fixed-order categorical palette `['#2a78d6', '#1baf7a', '#eda100', '#008300', '#4a3aa7', '#e34948']` assigned by series index — a stream keeps its color as streams appear (color follows the entity); 2px lines, no fills; hairline grid `#e1e0d9`; axis/tick ink `#898781`; ONE y-axis (all streams share it — lab streams are typically same-scale; a second measure never gets a second axis); uPlot's built-in cursor crosshair + legend = the hover layer; legend always present for ≥ 2 series and uPlot's legend click already toggles series visibility (§9.4 "legend toggles"); series identity is never color-alone (legend labels name every stream and include units).

- [ ] **Step 1: Install uplot**

Run: `cd webapp/frontend && npm install uplot`
Expected: `uplot` (^1.6.x) added to dependencies.

- [ ] **Step 2: Write the failing tests** — `src/charts/align.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { alignSeries } from './align'

describe('alignSeries', () => {
  it('merges timestamps into a sorted union x with null gaps', () => {
    const data = alignSeries([
      { label: 'od', t: [0, 10, 20], v: [1, 2, 3] },
      { label: 'temp', t: [10, 30], v: [37, 38] },
    ])
    expect(data[0]).toEqual([0, 10, 20, 30])
    expect(data[1]).toEqual([1, 2, 3, null])
    expect(data[2]).toEqual([null, 37, null, 38])
  })
  it('handles a single series and empty input', () => {
    expect(alignSeries([{ label: 'od', t: [1], v: [5] }])).toEqual([[1], [5]])
    expect(alignSeries([])).toEqual([[]])
  })
  it('deduplicates shared timestamps', () => {
    const data = alignSeries([
      { label: 'a', t: [1, 2], v: [10, 20] },
      { label: 'b', t: [2], v: [99] },
    ])
    expect(data[0]).toEqual([1, 2])
    expect(data[2]).toEqual([null, 99])
  })
})
```

- [ ] **Step 3: Run to verify failure** — `npx vitest run src/charts/align.test.ts` — FAIL.

- [ ] **Step 4: Implement `src/charts/align.ts`**

```ts
/** Align N time-series onto one x-array for uPlot: x = sorted union of timestamps,
 * missing points are null (uPlot renders gaps). Pure and chart-lib-agnostic. */

export interface NamedSeries {
  label: string
  t: number[]
  v: number[]
}

export type UPlotData = [number[], ...(number | null)[][]]

export function alignSeries(series: NamedSeries[]): UPlotData {
  const xs = Array.from(new Set(series.flatMap((s) => s.t))).sort((a, b) => a - b)
  const index = new Map(xs.map((x, i) => [x, i]))
  const columns = series.map((s) => {
    const col: (number | null)[] = new Array<number | null>(xs.length).fill(null)
    for (let i = 0; i < s.t.length; i++) col[index.get(s.t[i]) as number] = s.v[i]
    return col
  })
  return [xs, ...columns]
}
```

- [ ] **Step 5: Implement `src/charts/StreamChart.tsx`**

```tsx
/** Shared uPlot wrapper for the live run chart and the record viewer (§9.4, §9.5).
 * x is elapsed seconds; one shared y axis; built-in cursor crosshair + legend
 * (legend click toggles a series). Colors: fixed-order categorical palette. */
import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { alignSeries, type NamedSeries } from './align'
import { formatElapsed } from '../records/format'

export const SERIES_COLORS = [
  '#2a78d6', '#1baf7a', '#eda100', '#008300', '#4a3aa7', '#e34948',
] as const

export interface ChartSeries extends NamedSeries {
  units: string | null
}

const AXIS = {
  stroke: '#898781',
  grid: { stroke: '#e1e0d9', width: 1 },
  ticks: { stroke: '#e1e0d9', width: 1 },
} as const

export function StreamChart(props: { series: ChartSeries[]; height?: number }) {
  const host = useRef<HTMLDivElement | null>(null)
  const plot = useRef<uPlot | null>(null)
  const height = props.height ?? 260
  const shape = props.series.map((s) => `${s.label}|${s.units ?? ''}`).join(',')

  useEffect(() => {
    const el = host.current
    if (el === null || props.series.length === 0) return
    const opts: uPlot.Options = {
      width: Math.max(el.clientWidth, 320),
      height,
      scales: { x: { time: false } },
      axes: [
        { ...AXIS, values: (_u, ticks) => ticks.map((t) => formatElapsed(t)) },
        { ...AXIS },
      ],
      series: [
        { label: 'elapsed', value: (_u, v) => (v === null ? '—' : formatElapsed(v)) },
        ...props.series.map((s, i) => ({
          label: s.units ? `${s.label} (${s.units})` : s.label,
          stroke: SERIES_COLORS[i % SERIES_COLORS.length],
          width: 2,
          points: { show: false },
        })),
      ],
    }
    const u = new uPlot(opts, alignSeries(props.series), el)
    plot.current = u
    const onResize = () => u.setSize({ width: Math.max(el.clientWidth, 320), height })
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      u.destroy()
      plot.current = null
    }
    // recreate only when the series set changes; data updates go through setData below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shape, height])

  useEffect(() => {
    plot.current?.setData(alignSeries(props.series))
  })

  if (props.series.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg border border-slate-200 bg-white text-xs text-slate-400">
        no samples yet
      </div>
    )
  }
  return <div ref={host} className="rounded-lg border border-slate-200 bg-white p-2" />
}
```

(oxlint may not know the `react-hooks/exhaustive-deps` directive — if `npm run lint` complains about the comment itself, drop the comment line; the dep array is deliberate.)

- [ ] **Step 6: Wire into `RunView.tsx`** — replace the `{/* Task 9 replaces this placeholder with the live StreamChart */}` comment with a `LiveChart` element, and add this component in the same file:

```tsx
function LiveChart() {
  // feed is a fresh top-level object per accepted message (rev bump) — subscribing to it
  // re-renders on every in-place sample append without copying the arrays
  const feed = useRunStore((s) => s.feed)
  const streamUnits = useRunStore((s) => s.streamUnits)
  const origin = feed.origin ?? 0
  const series = Object.entries(feed.samples).map(([label, s]) => ({
    label,
    units: streamUnits[label] ?? null,
    t: s.t.map((t) => t - origin),
    v: s.v,
  }))
  return <StreamChart series={series} />
}
```

Add imports: `import { StreamChart } from '../charts/StreamChart'`.

- [ ] **Step 7: Gate + commit**

Run: `npm run lint && npm run typecheck && npm test && npm run build` — green (build now bundles uplot + its css).

```bash
git add webapp/frontend/package.json webapp/frontend/package-lock.json webapp/frontend/src
git commit -m "feat(studio): live uPlot stream chart with aligned multi-series feed"
```

---

### Task 10: Record viewer

**Files:**
- Create: `webapp/frontend/src/records/WorkflowSnapshot.tsx`, `webapp/frontend/src/records/RecordViewer.tsx`
- Modify: `webapp/frontend/src/records/RecordsTab.tsx` (mount viewer)
- Test: none new (all logic reused is already tested: `docToTree`, `blockSummary`, `alignSeries`, `describeEvent`, format helpers; the viewer is exercised in the Task 12 walkthrough)

**Interfaces:**
- Consumes: `getRecord`/`recordEvents`/`recordStreams`/`recordDownloadUrl` (Task 2), `StreamChart` (Task 9), `EventLog` (Task 7), `StatusChip`/format (Task 5), `docToTree`+`DocConvertError` from `builder/convert`, `blockSummary` from `builder/summary`, `childSlots`+`BlockNode` from `builder/tree`.
- Produces: `RecordViewer` props `{ id: string }`; `WorkflowSnapshot` props `{ doc: ExperimentDocJson | null }` (read-only tree render — §9.5).

- [ ] **Step 1: Implement `src/records/WorkflowSnapshot.tsx`**

The editable Canvas is store-and-dnd-coupled by design, so the snapshot is a small
presentational tree over the same pure helpers (this is the seam `summary.ts` was built
for). Serial children stack; Parallel children render as side-by-side lanes; Loop and
Branch render as framed containers (Branch with then/else lanes) — visual grammar per
§9.3, minus every interaction.

```tsx
import type { ExperimentDocJson } from '../types/doc'
import { DocConvertError, docToTree } from '../builder/convert'
import { blockSummary } from '../builder/summary'
import type { BlockNode } from '../builder/tree'

function NodeCard(props: { node: BlockNode }) {
  const { node } = props
  const timing = [
    node.gapAfter !== null ? `gap ${node.gapAfter}` : null,
    node.startOffset !== null ? `offset ${node.startOffset}` : null,
  ].filter(Boolean).join(' · ')
  return (
    <div className="rounded border border-slate-200 bg-white px-2 py-1">
      <p className="text-xs">
        {blockSummary(node)}
        {node.label !== null && <span className="ml-1 text-slate-400">“{node.label}”</span>}
        {timing && <span className="ml-1 text-[10px] text-slate-400">{timing}</span>}
      </p>
      {node.kind === 'serial' && <NodeList items={node.children} />}
      {node.kind === 'parallel' && (
        <div className="mt-1 flex gap-2 overflow-x-auto">
          {node.children.map((lane) => (
            <div key={lane.uid} className="min-w-40 flex-1 rounded border border-dashed border-slate-200 p-1">
              <NodeCard node={lane} />
            </div>
          ))}
        </div>
      )}
      {node.kind === 'loop' && <NodeList items={node.body} />}
      {node.kind === 'branch' && (
        <div className="mt-1 flex gap-2 overflow-x-auto">
          <div className="min-w-40 flex-1 rounded border border-dashed border-slate-200 p-1">
            <p className="text-[10px] text-slate-400">then</p>
            <NodeList items={node.then} />
          </div>
          {node.else !== null && (
            <div className="min-w-40 flex-1 rounded border border-dashed border-slate-200 p-1">
              <p className="text-[10px] text-slate-400">else</p>
              <NodeList items={node.else} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function NodeList(props: { items: BlockNode[] }) {
  if (props.items.length === 0) return <p className="mt-1 text-[10px] text-slate-300">empty</p>
  return (
    <div className="mt-1 space-y-1 pl-2">
      {props.items.map((n) => (
        <NodeCard key={n.uid} node={n} />
      ))}
    </div>
  )
}

export function WorkflowSnapshot(props: { doc: ExperimentDocJson | null }) {
  if (props.doc === null) {
    return <p className="text-xs text-slate-400">no workflow snapshot in this record</p>
  }
  try {
    const tree = docToTree(props.doc)
    return (
      <div className="space-y-1">
        {tree.map((n) => (
          <NodeCard key={n.uid} node={n} />
        ))}
      </div>
    )
  } catch (e) {
    const msg = e instanceof DocConvertError ? e.message : String(e)
    return <p className="text-xs text-amber-700">cannot render the snapshot: {msg}</p>
  }
}
```

- [ ] **Step 2: Implement `src/records/RecordViewer.tsx`**

```tsx
/** Record viewer (§9.5): chart from /streams, log from /events, report summary, and the
 * workflow snapshot rendered read-only. Every fetch failure renders inline with retry. */
import { useCallback, useEffect, useState } from 'react'
import { getRecord, recordDownloadUrl, recordEvents, recordStreams } from '../api/records'
import { useRecordsStore } from '../stores/recordsStore'
import type { RecordEvent } from '../types/runs'
import type { RecordDetail, RecordStreams } from '../types/records'
import { EventLog } from '../run/EventLog'
import { StreamChart } from '../charts/StreamChart'
import { StatusChip } from './RecordsTable'
import { formatDuration, formatWhen } from './format'
import { WorkflowSnapshot } from './WorkflowSnapshot'

export function RecordViewer(props: { id: string }) {
  const [detail, setDetail] = useState<RecordDetail | null>(null)
  const [events, setEvents] = useState<RecordEvent[] | null>(null)
  const [streams, setStreams] = useState<RecordStreams | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setError(null)
    Promise.all([getRecord(props.id), recordEvents(props.id), recordStreams(props.id)])
      .then(([d, e, s]) => {
        setDetail(d)
        setEvents(e)
        setStreams(s)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [props.id])
  useEffect(load, [load])

  if (error !== null) {
    return (
      <div className="rounded-lg border border-red-200 bg-white p-6 text-center text-sm">
        <p className="mb-2 text-red-700">{error}</p>
        <button onClick={load} className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100">Retry</button>
      </div>
    )
  }
  if (detail === null || events === null || streams === null) {
    return <p className="p-6 text-sm text-slate-400">loading record…</p>
  }

  const origin = detail.report?.clock_origin ??
    (events.length > 0 ? events[0].timestamp : 0)
  const series = Object.entries(streams).map(([label, s]) => ({
    label,
    units: s.units,
    t: s.t.map((t) => t - origin),
    v: s.v,
  }))

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-2">
        <button
          onClick={() => useRecordsStore.getState().open(null)}
          className="text-xs text-slate-500 hover:underline"
        >
          ← records
        </button>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{detail.name}</p>
          <p className="text-xs text-slate-400">
            {detail.experiment_name} · {detail.lab} · {formatWhen(detail.started_at)} ·{' '}
            {formatDuration(detail.started_at, detail.ended_at)}
          </p>
        </div>
        <StatusChip status={detail.status} />
        <a
          href={recordDownloadUrl(detail.id)}
          className="ml-auto rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100"
        >
          Download zip
        </a>
      </div>

      {detail.report !== null &&
        (detail.report.error !== null ||
          detail.report.finalize_errors.length > 0 ||
          detail.report.persistence_errors.length > 0 ||
          detail.report.diagnostics.length > 0) && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          {detail.report.error !== null && <p>error: {detail.report.error}</p>}
          {detail.report.finalize_errors.map((e, i) => (
            <p key={`f${i}`}>finalize: {e}</p>
          ))}
          {detail.report.persistence_errors.map((e, i) => (
            <p key={`p${i}`}>persistence: {e}</p>
          ))}
          {detail.report.diagnostics.map((d, i) => (
            <p key={`d${i}`}>
              <span className="font-mono">{d.category} {d.path}</span> {d.message}
            </p>
          ))}
        </div>
      )}

      <StreamChart series={series} />
      <EventLog events={events} origin={events.length > 0 ? events[0].timestamp : null} rev={0} />

      <div className="rounded-lg border border-slate-200 bg-white p-3">
        <p className="mb-2 text-xs font-semibold text-slate-500">Workflow snapshot</p>
        <WorkflowSnapshot doc={detail.doc} />
        <p className="mt-2 text-[10px] text-slate-400">
          roles: {Object.entries(detail.role_mapping).map(([r, d]) => `${r} → ${d}`).join(', ') || '—'}
        </p>
      </div>
    </div>
  )
}
```

NOTE: the EventLog `origin` uses the first log event's timestamp, not `clock_origin` — the run log starts at `run_started` which IS the origin event; for the chart, `clock_origin` from the report is authoritative (stream CSV timestamps can precede the first UI-visible event only in pathological cases; the fallback keeps interrupted records rendering).

- [ ] **Step 3: Mount in `RecordsTab.tsx`** — replace the placeholder branch:

```tsx
  if (openId !== null) return <RecordViewer id={openId} />
```

(add `import { RecordViewer } from './RecordViewer'`; drop the placeholder block.)

- [ ] **Step 4: Gate + commit**

Run: `npm run lint && npm run typecheck && npm test && npm run build` — green.

```bash
git add webapp/frontend/src
git commit -m "feat(studio): record viewer — chart, event log, report summary, read-only workflow snapshot"
```

---

### Task 11: Builder carry-forward polish (W3/W4 final-review triage)

**Files:**
- Modify: `webapp/frontend/src/builder/tree.ts` (export `replaceSlot`), `webapp/frontend/src/builder/refs.ts` (dedupe `mapNodes`), `webapp/frontend/src/stores/docStore.ts` (removeBlock walk + history pause helpers), `webapp/frontend/src/builder/RolesPanel.tsx`, `webapp/frontend/src/builder/StreamsPanel.tsx` (Escape-cancel flag), `webapp/frontend/src/builder/LoadDialog.tsx` (clear serverId on delete-of-open-doc), `webapp/frontend/src/builder/Toolbar.tsx` (save-as undo hygiene), `webapp/frontend/src/builder/ProblemsPanel.tsx` (dim stale diagnostics)
- Test: `webapp/frontend/src/builder/tree.test.ts`, `webapp/frontend/src/stores/docStore.test.ts` (extend)

**Interfaces:**
- Consumes: everything existing.
- Produces: `replaceSlot(node, slot, list): BlockNode` exported from `tree.ts`; `pauseHistory()` / `resumeHistory()` exported from `docStore.ts`. No other public-surface changes — the rest is behavior fixes.

- [ ] **Step 1: Write the failing tests**

Append to `src/builder/tree.test.ts`:

```ts
import { newStructureNode, replaceSlot, type SerialNode } from './tree' // merge into existing imports

it('replaceSlot swaps the named slot and throws for leaf kinds', () => {
  const serial = newStructureNode('serial')
  const wait = newStructureNode('wait')
  const out = replaceSlot(serial, 'children', [wait]) as SerialNode
  expect(out.children).toHaveLength(1)
  expect(out.uid).toBe(serial.uid)
  expect(() => replaceSlot(wait, 'children', [])).toThrow(/no child slot/)
})
```

Append to `src/stores/docStore.test.ts`:

```ts
import { pauseHistory, resumeHistory } from './docStore' // merge into existing imports
import { newStructureNode } from '../builder/tree'

it('pauseHistory suppresses undo tracking until resumeHistory', () => {
  newDoc()
  pauseHistory()
  useDocStore.getState().setName('renamed while paused')
  resumeHistory()
  undo()
  expect(useDocStore.getState().name).toBe('renamed while paused')
})

it('removeBlock clears selection when the removed container held it', () => {
  newDoc()
  const serial = newStructureNode('serial')
  useDocStore.getState().insertBlock(serial, { parentUid: null, slot: 'blocks', index: 0 })
  const wait = newStructureNode('wait')
  useDocStore.getState().insertBlock(wait, { parentUid: serial.uid, slot: 'children', index: 0 })
  useDocStore.getState().select(wait.uid)
  useDocStore.getState().removeBlock(serial.uid)
  expect(useDocStore.getState().selectedUid).toBeNull()
  expect(useDocStore.getState().tree).toHaveLength(0)
})
```

- [ ] **Step 2: Run to verify failure** — `npx vitest run src/builder/tree.test.ts src/stores/docStore.test.ts` — FAIL (`replaceSlot`/`pauseHistory` not exported; selection test may already pass — keep it as a pin either way).

- [ ] **Step 3: Implement the fixes**

(a) `tree.ts:119` — `function replaceSlot(` → `export function replaceSlot(`.

(b) `refs.ts` — collapse `mapNodes` onto the shared helper:

```ts
import { childSlots, replaceSlot, visitNodes, type BlockNode } from './tree'

function mapNodes(tree: BlockNode[], fn: (node: BlockNode) => BlockNode): BlockNode[] {
  return tree.map((node) => {
    let out = fn(node)
    for (const [slot, children] of childSlots(out)) {
      out = replaceSlot(out, slot, mapNodes(children, fn))
    }
    return out
  })
}
```

(c) `docStore.ts` — `removeBlock` uses the tuple it already gets (drops the second whole-tree walk); `findNode` import goes away:

```ts
      removeBlock: (uid) =>
        set((s) => {
          const [tree, removed] = removeNode(s.tree, uid)
          const selectionGone =
            s.selectedUid !== null && removed !== null && containsUid(removed, s.selectedUid)
          return { tree, selectedUid: selectionGone ? null : s.selectedUid }
        }),
```

And next to `undo`/`redo`:

```ts
export const pauseHistory = (): void => temporalStore.getState().pause()
export const resumeHistory = (): void => temporalStore.getState().resume()
```

(d) `RolesPanel.tsx` and `StreamsPanel.tsx` — Escape-cancel flag (Escape currently unmounts the input and the browser blur still commits the rename). In both files add `useRef` and change the rename input handlers:

```tsx
  const cancelled = useRef(false)
```

```tsx
              onBlur={() => {
                if (cancelled.current) {
                  cancelled.current = false
                  return
                }
                commitRename(name)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitRename(name)
                if (e.key === 'Escape') {
                  cancelled.current = true
                  setEditing(null)
                }
              }}
```

(imports: `import { useRef, useState } from 'react'`).

(e) `LoadDialog.tsx` — deleting the currently-open experiment must clear `serverId` (otherwise the next Save PUTs a deleted id and 404s) and mark the doc dirty:

```ts
  const remove = async (item: ExperimentSummary) => {
    if (!window.confirm(`Delete experiment '${item.name}'? Records are kept.`)) return
    try {
      await deleteExperiment(item.id)
      if (useDocStore.getState().serverId === item.id) {
        // server copy is gone: next Save must create, and the open doc is unsaved now
        useDocStore.setState({ serverId: null, savedSnapshot: '' })
      }
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }
```

(f) `Toolbar.tsx` — save-as must not leave undo entries for its name juggling (today a failed save-as leaves 2). Import `pauseHistory, resumeHistory` from the docStore and wrap:

```ts
  const saveAs = () => {
    const newName = window.prompt('Save as…', `${name} (copy)`)
    if (!newName) return
    const previousName = useDocStore.getState().name
    void run(async () => {
      pauseHistory()
      try {
        useDocStore.getState().setName(newName)
        const snapshot = snapshotOf(selectContent(useDocStore.getState()))
        try {
          const res = await createExperiment(selectDoc(useDocStore.getState()))
          markSaved(res.id, snapshot)
        } catch (e) {
          useDocStore.getState().setName(previousName)
          throw e
        }
      } finally {
        resumeHistory()
      }
    })
  }
```

(g) `ProblemsPanel.tsx` — when validation is unavailable the listed diagnostics are from the last successful call and may be stale; dim them and say so:

```tsx
      {open && (
        <ul className={`max-h-40 overflow-y-auto border-t border-red-100 px-3 py-1${validationError ? ' opacity-50' : ''}`}>
          {validationError && (
            <li className="py-0.5 text-xs text-amber-700">
              {validationError} — the problems below are from the last successful check and may be stale
            </li>
          )}
```

(rest of the list unchanged).

- [ ] **Step 4: Gate + commit**

Run: `npm run lint && npm run typecheck && npm test && npm run build` — green (whole suite; the refs/convert golden tests pin the mapNodes refactor).

```bash
git add webapp/frontend/src
git commit -m "fix(studio): builder carry-forwards — replaceSlot reuse, removeBlock walk, escape-cancel renames, delete-of-open-doc, save-as undo hygiene, stale-diagnostics dimming"
```

---

### Task 12: tsconfig app/test split, FakeLab dev server, scripted walkthrough, final gates

**Files:**
- Modify: `webapp/frontend/tsconfig.app.json`, `webapp/frontend/tsconfig.json`
- Create: `webapp/frontend/tsconfig.test.json`
- Create: `webapp/backend/tests/devserver.py`
- Scratchpad only (not committed): playwright walkthrough script + screenshots

**Interfaces:**
- Consumes: `runsupport` harness (fake registry/client factory/FakeLab), `create_app`, `Settings`, dependency seams `get_db`/`get_run_manager` (`api/deps.py`) and `get_labs_service` (`api/labs.py`).
- Produces: `python tests/devserver.py` = the FakeLab-backed dev server the W5 gate runs against (§12 W5); app-code tsconfig no longer sees node globals (W3 carry-forward).

- [ ] **Step 1: tsconfig split**

`tsconfig.app.json` — drop `"node"` from `types` and exclude tests (app code can no longer accidentally use node globals; test files keep them via the new project):

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "target": "es2023",
    "lib": ["ES2023", "DOM"],
    "module": "esnext",
    "types": ["vite/client"],
    "allowArbitraryExtensions": true,
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "erasableSyntaxOnly": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts", "src/**/*.test.tsx"]
}
```

New `tsconfig.test.json` (checks ALL of src — tests import app modules — with node types):

```json
{
  "extends": "./tsconfig.app.json",
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.test.tsbuildinfo",
    "types": ["vite/client", "node"]
  },
  "include": ["src"],
  "exclude": []
}
```

`tsconfig.json` — add the reference:

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" },
    { "path": "./tsconfig.test.json" }
  ]
}
```

Run `npm run typecheck` — if `tsc -b` objects to the reference layout (references normally want `composite`), fall back to checking the test project separately: set `"typecheck": "tsc -b tsconfig.app.json tsconfig.node.json && tsc -p tsconfig.test.json"` and `"build": "tsc -b tsconfig.app.json tsconfig.node.json && vite build"` in `package.json` and remove the third reference. Either layout is acceptable; green gates decide.

- [ ] **Step 2: Create `webapp/backend/tests/devserver.py`**

Lives in `tests/` so `import runsupport` resolves for both the interpreter (script dir on sys.path) and mypy (sibling module).

```python
"""FakeLab-backed dev server — the W5 manual-gate backend (spec §12 W5).

Usage:
    cd webapp/backend && .venv/bin/python tests/devserver.py [--port 8000]

Serves the real app (API only; run `npm run dev` in webapp/frontend for the UI)
with labs/runs wired to an in-process FakeLab (pump_1 + densitometer_1). Data
lands in webapp/backend/.devdata — delete the directory to reset.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI

import runsupport
from experiment_studio.api.deps import get_db, get_run_manager
from experiment_studio.api.labs import get_labs_service
from experiment_studio.app import create_app
from experiment_studio.config import Settings
from experiment_studio.db import Database
from experiment_studio.labs import LabsService
from experiment_studio.runner import RunManager

DATA_DIR = Path(__file__).resolve().parents[1] / ".devdata"


async def _online(name: str) -> bool:
    return True


def build_app() -> FastAPI:
    app = create_app(Settings(static_dir=None, data_dir=DATA_DIR))
    fake = runsupport.default_fake()
    registry = runsupport.fake_registry()
    factory = runsupport.fake_client_factory(fake)
    holder: dict[str, RunManager] = {}

    async def dev_run_manager(db: Database = Depends(get_db)) -> RunManager:
        if "manager" not in holder:
            holder["manager"] = RunManager(
                db,
                DATA_DIR,
                registry,
                client_factory=factory,
                run_options={"job_poll_interval": 0.05, "job_poll_max": 0.2},
            )
        return holder["manager"]

    def dev_labs_service() -> LabsService:
        return LabsService(registry, client_factory=factory, probe=_online)

    app.dependency_overrides[get_run_manager] = dev_run_manager
    app.dependency_overrides[get_labs_service] = dev_labs_service
    return app


app = build_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    uvicorn.run(app, host="127.0.0.1", port=parser.parse_args().port)
```

Add `.devdata/` to `webapp/backend/.gitignore` (create or extend the file).

NOTE: the lifespan still builds a real (unused) RunManager/LabsService on app.state — the dependency overrides win for every route; the idle real objects are harmless and their shutdown is guarded.

- [ ] **Step 3: Backend gate** — `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy . && .venv/bin/python -m ruff check .` — green (devserver.py is type-checked and linted; not collected by pytest).

- [ ] **Step 4: Scripted walkthrough (the W5 gate)** — scratchpad playwright script, NOT committed. Recipe (adapt W3's `walk.mjs` pattern: `npm init -y && npm i playwright && npx playwright install chromium` in a scratchpad dir; `hasText` is case-insensitive; screenshots after each phase):

1. Start backend: `cd webapp/backend && .venv/bin/python tests/devserver.py` (background). Start frontend: `cd webapp/frontend && npm run dev` (background; port 5173, `/api` + WS proxied).
2. Seed the walkthrough experiment via `curl -X POST localhost:8000/api/experiments -H 'Content-Type: application/json' -d @seed.json` with:

```json
{
  "doc_version": 1,
  "name": "W5 walkthrough",
  "description": null,
  "roles": {"feed": {"type": "pump"}, "meter": {"type": "densitometer"}},
  "workflow": {
    "schema_version": 1,
    "metadata": {"name": "W5 walkthrough"},
    "persistence": {"default": "in_memory", "format": "jsonl"},
    "streams": {"od": {"units": "AU"}},
    "blocks": [
      {"serial": {"children": [
        {"operator_input": {"name": "target", "type": "int", "prompt": "Target cycles?", "min": 1, "max": 10}},
        {"command": {"device": "feed", "verb": "dispense", "params": {"volume_ml": 1}}},
        {"loop": {"count": 12, "check": "before", "body": [
          {"measure": {"device": "meter", "verb": "measure", "into": "od"}},
          {"wait": {"duration": "400ms"}}
        ]}}
      ]}}
    ]
  }
}
```

3. Walkthrough assertions (each numbered step = screenshot):
   1. Devices tab: select `lab_a`; device table lists `pump_1` and `densitometer_1`.
   2. Run tab: preflight shows "W5 walkthrough", role rows `feed`/`meter` with typed dropdowns; Start disabled while unmapped; map both → validation chip "workflow valid"; Start enabled.
   3. Start → input dialog "Target cycles?" appears. Submit `11` → inline "must be ≤ 10", dialog stays. Submit `5` → dialog closes; event log shows `target = 5`.
   4. Live chart renders (uPlot canvas present, legend "od (AU)"); event log auto-scrolls with `od = …` lines.
   5. Pause → status chip `paused`; Resume → `running`.
   6. Mid-run browser reload → Run tab reattaches: status header back, event log replayed from seq 0 (count matches pre-reload), chart repopulated.
   7. Run completes → terminal panel "Run finished: completed", "Open record" jumps to Records with the viewer open: chart, event log, report-free (no error box), workflow snapshot showing serial→input/command/loop structure, role mapping line.
   8. Back to list: rename the record (Enter commits; a second rename attempt cancelled with Escape leaves the name unchanged); download returns HTTP 200 `application/zip` (assert via in-page `fetch`).
   9. Start a second run of the same experiment: preflight dropdowns are PRE-FILLED from mapping memory (both selects already chosen). Start, then Abort (confirm) → terminal panel `aborted`; Records list shows the `aborted` row.
   10. Delete the aborted record (confirm) → row gone.
4. Also verify zero unexpected console errors (the only tolerated noise: none — the fake roster is wired, unlike W3).

- [ ] **Step 5: Full final gates + engine-untouched check**

```bash
cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy . && .venv/bin/python -m ruff check .
cd ../frontend && npm run lint && npm run typecheck && npm test && npm run build
cd ../.. && git diff main --stat -- src/ tests/   # MUST be empty (engine untouched)
```

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/tsconfig*.json webapp/frontend/package.json webapp/backend/tests/devserver.py webapp/backend/.gitignore
git commit -m "feat(studio): tsconfig app/test split + FakeLab-backed dev server for the W5 gate"
```

---

## Self-Review

**Spec coverage (§ → task):** §9.4 preflight (experiment picker, typed role dropdowns, prefill from mappings, validate status, Start gating) → T1/T6; §9.4 active run (status header, elapsed, pause/resume/abort-with-confirm, live chart from `measure_recorded`, event log with auto-scroll/pause-on-hover, input dialog typed widgets with min/max/choices, terminal report + record link) → T4/T7/T8/T9; §9.5 records (table with rename/delete/download, viewer: chart from /streams, log from /events, report summary, read-only snapshot) → T5/T10; §7.5 WS contract client-side (replay `?since`, shared seq, close 1000/4404, reconnect) → T3/T4; §7.4 input flow (422 stays pending) → T4/T8; §10 error handling (retryable error states, no infinite spinners, offline lab state) → T5/T6/T10; §11 frontend tests pure-logic incl. "WS reducer (replay + live merge)" → T3; §12 W5 gate "vitest + manual run against FakeLab-backed dev server" → T12. Carry-forwards: client tests/empty-body + two-422-shapes → T1 (server-side normalize) + T2; tsconfig split → T12; replaceSlot/removeBlock/Escape-cancel/serverId-clear/stale-dimming/save-as-undo → T11; mapping-memory read endpoint + spec amendment → T1.
**Placeholder scan:** no TBDs; every code step carries the actual code. Two deliberate late-mount placeholders (Run placeholder in T5's App.tsx, viewer placeholder in T5's RecordsTab) are replaced by named later tasks (T6, T10).
**Type consistency:** `FeedState`/`applyMessage` (T3) match runStore usage (T4) and `LiveChart` (T9); `EventLog` props `{events, origin, rev}` match T7 definition and T10 usage; `StatusChip` lives in `RecordsTable.tsx` (T5) and is imported by T7/T10; `PendingInput` (T2) matches T8's `validateInputValue`; `MappingRow` (T6) internal-only; `savedMapping` (T2) matches T1's endpoint path.

## Execution

Subagent-driven (user pre-authorized): superpowers:subagent-driven-development, fresh implementer per task, reviewer per task, fable whole-branch final review, then PR + self-merge. Ledger: `.superpowers/sdd/progress.md`.

