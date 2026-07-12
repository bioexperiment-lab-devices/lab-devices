# Experiment Studio W6 — Integration & Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the studio image deployable behind lab-bridge's prefix-stripping Caddy route, land the W5 final-review polish tickets, sync the studio version to releases, and ship operator docs — so the lab-bridge integration (companion spec `lab_devices_server: docs/superpowers/specs/2026-07-12-experiment-studio-integration.md`) can deploy `0.2.1` to preprod for the live smoke.

**Architecture:** No new subsystems. Frontend gains URL-prefix portability (relative asset/API/WS URLs) and five small UX/robustness fixes; backend gains four hardening fixes from the W4/W5 review triage; release-please learns to stamp the studio package version. The engine (`src/`) is untouched.

**Tech Stack:** existing — FastAPI backend (`webapp/backend`), React 19 + Vite 8 + TS frontend (`webapp/frontend`), oxlint (not eslint), vitest 4 (node env, TZ=UTC), release-please (python type).

## Global Constraints

- **Engine untouched:** `git diff main -- src/ tests/` must stay empty all branch long.
- **Backend gate:** `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .` — mypy takes NO path argument (pyproject `files=["experiment_studio"]`; `mypy .` drags in never-gated tests).
- **Frontend gate:** `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build` (2 known oxlint fast-refresh warnings are expected, exit code 0).
- **Line length ≤ 100** in backend src (ruff enforces; tests too by convention).
- **TS constraints:** `erasableSyntaxOnly` (no parameter properties), `verbatimModuleSyntax` (`import type` for types).
- **Suites at branch base:** backend 121 pytest, frontend 96 vitest. Every task leaves both green.
- Branch: `feat/experiment-studio-6-integration` off `main` (post-PR#15 + release 0.2.0).
- Commit style: `fix(studio): …` / `feat(studio): …` / `docs: …` (release-please scans these; the branch must produce at least one `fix`/`feat` so 0.2.1 gets cut).

---

### Task 1: Frontend sub-path portability (relative asset/API/WS URLs)

The deployed app sits at `https://<host>/studio/` behind `uri strip_prefix /studio` (see companion lab-bridge spec). Today the SPA emits absolute `/assets/*` and `/api/*` URLs, which escape the prefix. Fix: build with a relative Vite base and resolve every API/WS/download URL against the document base. The app keeps working unchanged at `/` (dev server, `docker run`).

**Files:**
- Modify: `webapp/frontend/vite.config.ts`
- Modify: `webapp/frontend/src/api/client.ts`
- Modify: `webapp/frontend/src/api/records.ts`
- Modify: `webapp/frontend/src/api/runSocket.ts`
- Test: `webapp/frontend/src/api/client.test.ts` (assertions update + new `apiPath` tests)
- Test: `webapp/frontend/src/stores/runStore.test.ts` (assertion updates only)

**Interfaces:**
- Produces: `export const apiPath = (path: string): string` in `src/api/client.ts` — turns an app-absolute `'/api/...'` path into a base-relative `'api/...'` one. Task 5 reuses it (timeout wrapper keeps calling `fetch(apiPath(path), …)`).

- [ ] **Step 1: Write failing tests for `apiPath` + updated fetch expectations**

In `webapp/frontend/src/api/client.test.ts` add (top-level, next to the existing describe blocks):

```ts
import { apiPath } from './client'

describe('apiPath', () => {
  it('strips the leading slash so fetch resolves against the document base', () => {
    expect(apiPath('/api/labs')).toBe('api/labs')
    expect(apiPath('/api/runs/xyz/events?since=3')).toBe('api/runs/xyz/events?since=3')
  })
  it('leaves already-relative paths alone', () => {
    expect(apiPath('api/labs')).toBe('api/labs')
  })
})
```

Then update every fetch-mock assertion in `client.test.ts` and `src/stores/runStore.test.ts` that expects a path starting with `'/api'` to expect the same path without the leading slash (`'api/...'`). There are ~15 sites across the two files; a mechanical find (`grep -n "'/api" src/api/client.test.ts src/stores/runStore.test.ts`) lists them. Do NOT touch assertions on `ApiError.message` — error messages keep the original `'/api/...'` path (see Step 3).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp/frontend && npm test -- --run src/api/client.test.ts`
Expected: FAIL — `apiPath` is not exported yet (and the flipped path assertions fail against the current absolute-path fetch calls).

- [ ] **Step 3: Implement**

`vite.config.ts` — add `base` above `plugins`:

```ts
export default defineConfig({
  base: './', // deployable behind a prefix-stripping proxy (lab-bridge /studio route)
  plugins: [react(), tailwindcss()],
  ...
```

`src/api/client.ts` — add below the `isDiagnostic` helper:

```ts
/** App-absolute '/api/...' → base-relative 'api/...': resolved by fetch/href against the
 * document base URL, so the SPA works both at '/' and behind a prefix-stripping proxy
 * (deployed at /studio/ — companion lab-bridge integration spec). */
export const apiPath = (path: string): string => path.replace(/^\//, '')
```

In `request()` change the fetch line only (error messages keep the original path):

```ts
  const resp = await fetch(apiPath(path), init)
```

`src/api/records.ts` — download href resolves relatively too:

```ts
import { apiPath, deleteJson, getJson, patchJson } from './client'
...
export const recordDownloadUrl = (id: string) => apiPath(`/api/records/${id}/download`)
```

`src/api/runSocket.ts` — in `connect()`, replace the two URL lines with:

```ts
    const url = new URL(
      apiPath(`/api/runs/${this.runId}/events?since=${this.lastSeq()}`),
      window.location.href,
    )
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(url)
```

and add `import { apiPath } from './client'` at the top. (No client-side routing exists, so `window.location.href` is always the app base — `/` or `/studio/`.)

- [ ] **Step 4: Run the full frontend gate**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: all green. Then verify the built entry uses relative URLs:

Run: `grep -o 'src="[^"]*"' webapp/frontend/dist/index.html`
Expected: `src="./assets/...js"` (relative, not `/assets/...`).

- [ ] **Step 5: Backend smoke — SPA still serves at root**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q`
Expected: 121 passed (nothing backend-side changed; this pins no regression from the dist shape).

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend
git commit -m "feat(studio): sub-path portability — relative asset/API/WS URLs"
```

---

### Task 2: Backend hardening — terminal-window guard, artifact containment, zip off-loop, /api JSON 404, dead code, .dockerignore

Five W4/W5-triage carries, all in `webapp/backend` (+ one root `.dockerignore` line).

**Files:**
- Modify: `webapp/backend/experiment_studio/runner.py` (guard + delete `is_lab_busy`)
- Modify: `webapp/backend/experiment_studio/records.py` (`artifact_dir` containment, `delete` reuse)
- Modify: `webapp/backend/experiment_studio/api/records.py` (`build_zip` via `asyncio.to_thread`)
- Modify: `webapp/backend/experiment_studio/app.py` (`/api` exact path → JSON 404)
- Modify: `.dockerignore` (add `**/tests`)
- Test: `webapp/backend/tests/test_runner_guards.py` (new), `webapp/backend/tests/test_records_api.py` (extend), `webapp/backend/tests/test_app_spa.py` (extend where the existing SPA-fallback tests live — locate with `grep -rn "index.html" webapp/backend/tests`)

**Interfaces:**
- Produces: `RecordsStore.artifact_dir(record)` now RAISES `UnknownRecordError` when the stored dir escapes `data_dir` (all four callers in `api/records.py` get the 404 mapping for free via the existing exception handler).
- Removes: `RunManager.is_lab_busy` (dead — `api/labs.py` inlines the check; verified zero references outside `runner.py`).

- [ ] **Step 1: Write failing tests**

New `webapp/backend/tests/test_runner_guards.py`:

```python
"""W6: active() hides the finalization window (status is only ever running|paused)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from experiment_studio.runner import ActiveRun, RunManager, UnknownRunError


def _stub_active(status: str, task: asyncio.Task[None]) -> ActiveRun:
    stub = cast(Any, object())
    return ActiveRun(
        run_id="r1",
        record_id="r1",
        experiment_id="e1",
        experiment_name="exp",
        lab="lab",
        role_mapping={},
        status=status,
        run=stub,
        tee=stub,
        inputs=stub,
        client=stub,
        artifact_dir=Path("."),
        task=task,
    )


@pytest.mark.parametrize("status", ["completed", "failed", "aborted", "cancelled", "interrupted"])
async def test_active_hides_terminal_finalization_window(status: str) -> None:
    manager = RunManager(cast(Any, None), Path("."), cast(Any, None))
    task = asyncio.create_task(asyncio.sleep(30))
    try:
        manager._current = _stub_active(status, task)
        assert manager.active() is None
        assert manager.active_payload() is None
        with pytest.raises(UnknownRunError):
            manager._require_active("r1")
    finally:
        task.cancel()


async def test_active_still_returns_running_and_paused() -> None:
    manager = RunManager(cast(Any, None), Path("."), cast(Any, None))
    task = asyncio.create_task(asyncio.sleep(30))
    try:
        for status in ("running", "paused"):
            manager._current = _stub_active(status, task)
            current = manager.active()
            assert current is not None and current.status == status
    finally:
        task.cancel()
```

(Match the suite's async convention — if existing tests use `@pytest.mark.asyncio` or anyio markers, mirror the file header of `webapp/backend/tests/test_runner.py` exactly.)

In the records API test module add containment cases (adapt fixture names to the module's existing ones — it already has a client + seeded record helper):

```python
async def test_escaping_artifact_dir_is_refused(client, seeded_record_row) -> None:
    """Row doctored to point outside data_dir -> 404 on all artifact readers, delete keeps row-removal semantics but never touches the outside path."""
    record_id = seeded_record_row  # helper returns the id of a completed record
    db = ...  # the test app's Database handle, same way existing tests reach it
    await db.conn.execute(
        "UPDATE records SET dir = ? WHERE id = ?", ("../outside", record_id)
    )
    await db.conn.commit()
    for path in (f"/api/records/{record_id}/events",
                 f"/api/records/{record_id}/streams",
                 f"/api/records/{record_id}/download"):
        resp = await client.get(path)
        assert resp.status_code == 404
        assert resp.json()["code"] == "unknown_record"
    resp = await client.delete(f"/api/records/{record_id}")
    assert resp.status_code == 204  # row deleted; escaping dir untouched
    assert (await client.get(f"/api/records/{record_id}")).status_code == 404
```

And in the SPA/static test module:

```python
async def test_api_exact_path_is_json_404(client) -> None:
    resp = await client.get("/api")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
```

NOTE: the SPA tests construct the app WITH a static dir; reuse that fixture — without `static_dir` the `/api` path 404s trivially and proves nothing.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q tests/test_runner_guards.py -x`
Expected: FAIL — `active()` currently returns the terminal-status run. The records containment test fails on `/download` (500 or 200) and `/events` (200 `[]`), and `/api` returns 200 HTML.

- [ ] **Step 3: Implement**

`runner.py` — above `class RunManager`:

```python
_TERMINAL_STATUSES = frozenset({"completed", "failed", "aborted", "cancelled", "interrupted"})
```

In `active()`:

```python
    def active(self) -> ActiveRun | None:
        current = self._current
        if current is None or current.task is None or current.task.done():
            return None
        if current.status in _TERMINAL_STATUSES:
            return None  # finalization window (§7.1.5): run is over, task still flushing
        return current
```

Delete the `is_lab_busy` method entirely.

`records.py` — replace `artifact_dir` and the tail of `delete`:

```python
    def artifact_dir(self, record: dict[str, Any]) -> Path:
        target = (self._data_dir / str(record["dir"])).resolve()
        if not target.is_relative_to(self._data_dir.resolve()):
            raise UnknownRecordError(f"record {record['id']!r} artifact dir escapes data dir")
        return target
```

```python
    async def delete(self, record_id: str) -> None:
        record = await self.get(record_id)
        await self._db.conn.execute(
            "DELETE FROM records WHERE id = ?", (record_id,)
        )
        await self._db.conn.commit()
        try:
            target = self.artifact_dir(record)
        except UnknownRecordError:
            return  # row removed; never touch a path outside data_dir
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
```

`api/records.py` — add `import asyncio` and change the download line:

```python
    payload = await asyncio.to_thread(build_zip, store.artifact_dir(record))
```

`app.py` `_mount_spa` — first line of `spa()`:

```python
        if path == "api" or path.startswith("api/"):
```

`.dockerignore` — replace the bare `tests` line with:

```
**/tests
```

(the bare root-only pattern let `webapp/backend/tests` leak into the image).

- [ ] **Step 4: Run the backend gate**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all green, suite count grew by the new tests. Also confirm dead code is gone:
Run: `grep -rn "is_lab_busy" webapp/ | grep -v .venv` → no hits.

- [ ] **Step 5: Commit**

```bash
git add webapp/backend .dockerignore
git commit -m "fix(studio): terminal-window active() guard, artifact-dir containment, zip off-loop, /api JSON 404"
```

---

### Task 3: Version seam — release-please stamps the studio package

`/api/health` reports `studio: 0.1.0` while images tag 0.2.x. Make release-please rewrite the backend package version in lockstep (single release stream, S9).

**Files:**
- Modify: `release-please-config.json`
- Modify: `webapp/backend/pyproject.toml:7`
- Modify: `webapp/backend/tests/test_health.py:12`

- [ ] **Step 1: Un-pin the health test (write the failing-forward test first)**

`test_health.py` — replace the exact-pin assertion:

```python
from importlib.metadata import version
...
    assert body["studio"] == version("experiment-studio")
```

(The endpoint and the test now read the same metadata — the test can never drift again, whatever release-please stamps.)

- [ ] **Step 2: Run it**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q tests/test_health.py`
Expected: PASS already (both sides read installed metadata) — this step pins the un-drift property, not a behavior change.

- [ ] **Step 3: Wire release-please**

`release-please-config.json`:

```json
{
  "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
  "packages": {
    ".": {
      "release-type": "python",
      "extra-files": ["webapp/backend/pyproject.toml"]
    }
  }
}
```

`webapp/backend/pyproject.toml` line 7 — annotate for the generic updater and sync to the current release:

```toml
version = "0.2.0" # x-release-please-version
```

- [ ] **Step 4: Reinstall + full backend gate**

Run: `cd webapp/backend && .venv/bin/pip install -e . -q && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: green (reinstall refreshes the editable-install metadata to 0.2.0).

- [ ] **Step 5: Commit**

```bash
git add release-please-config.json webapp/backend/pyproject.toml webapp/backend/tests/test_health.py
git commit -m "fix(studio): release-please stamps experiment-studio version (health seam)"
```

---

### Task 4: Preflight prefill survives a late roster + 409-adopt store test

W5 ticket (a) — most consequential: with a localStorage-persisted lab, `loadSelection` snapshots `devices` once; if the roster fetch resolves after, the saved S2 mapping is silently dropped. Plus ticket (e): pin the 409→adopt path in `runStore`.

**Files:**
- Modify: `webapp/frontend/src/run/preflight.ts` (new pure helper)
- Modify: `webapp/frontend/src/run/PreflightPanel.tsx`
- Test: `webapp/frontend/src/run/preflight.test.ts`
- Test: `webapp/frontend/src/stores/runStore.test.ts`

**Interfaces:**
- Produces: `mergePrefill(chosen, roles, devices, saved): Record<string, string>` in `preflight.ts` — returns `chosen` untouched unless it is empty AND `devices` is non-null, in which case it computes `prefillMapping(roles, devices, saved)`.

- [ ] **Step 1: Write failing tests**

`preflight.test.ts` (extend, mirroring its existing fixtures for `LabDevice`):

```ts
describe('mergePrefill', () => {
  const roles = { feed: { type: 'pump' } }
  const devices = [{ id: 'pump_1', type: 'pump' }] as LabDevice[]

  it('fills an empty selection once the roster arrives', () => {
    expect(mergePrefill({}, roles, devices, { feed: 'pump_1' })).toEqual({ feed: 'pump_1' })
  })
  it('does nothing while the roster is still loading', () => {
    expect(mergePrefill({}, roles, null, { feed: 'pump_1' })).toEqual({})
  })
  it('never clobbers an existing selection', () => {
    const chosen = { feed: 'pump_2' }
    expect(mergePrefill(chosen, roles, devices, { feed: 'pump_1' })).toBe(chosen)
  })
})
```

`runStore.test.ts` — add the 409-adopt case using the file's existing module mocks + `setSocketFactoryForTests` pattern (copy the setup of the nearest `start()` test):

```ts
it('adopts the already-active run on 409 run_active', async () => {
  vi.mocked(startRun).mockRejectedValueOnce(
    new ApiError(409, 'a run is already active', 'run_active', { activeRunId: 'other' }),
  )
  vi.mocked(getActiveRun).mockResolvedValueOnce(activePayload({ run_id: 'other' }))
  await useRunStore.getState().start(startBody())
  const s = useRunStore.getState()
  expect(s.phase).toBe('active')
  expect(s.runId).toBe('other')
  expect(s.startError).toBeNull()
})
```

(`activePayload`/`startBody` = whatever fixture helpers the file already uses; reuse them verbatim.)

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd webapp/frontend && npm test -- --run src/run/preflight.test.ts src/stores/runStore.test.ts`
Expected: `mergePrefill` FAILS (not exported). The 409 test may already PASS (the code path exists — this is a coverage pin per the W5 triage); if it passes, note that in the task report and keep it.

- [ ] **Step 3: Implement**

`preflight.ts` — append:

```ts
/** W6 (a): apply the prefill once the roster arrives without clobbering user picks —
 * loadSelection snapshots the devices list once; a slow roster fetch used to silently
 * drop the saved S2 mapping. */
export function mergePrefill(
  chosen: Record<string, string>,
  roles: Record<string, { type: string }>,
  devices: LabDevice[] | null,
  saved: Record<string, string>,
): Record<string, string> {
  if (devices === null || Object.keys(chosen).length > 0) return chosen
  return prefillMapping(roles, devices, saved)
}
```

`PreflightPanel.tsx`:

1. Add state next to `chosen`: `const [saved, setSaved] = useState<Record<string, string>>({})`
2. In `loadSelection`, reset it with the other resets: `setSaved({})`
3. In the `.then(async (res) => { ... })` body, after the `Promise.all` resolves and the token check passes, keep the existing `setChosen(prefillMapping(...))` line and add `setSaved(saved)` — the `Promise.all` destructuring already names the mapping `saved`; rename the destructured variable to `savedMap` to avoid shadowing the new state, i.e.:

```ts
        const [validation, savedMap] = await Promise.all([...])
        if (gen.current !== token) return
        setDiagnostics(validation.diagnostics)
        setSaved(savedMap)
        setChosen(prefillMapping(res.doc.roles, useLabsStore.getState().devices, savedMap))
```

4. Add the late-roster effect after the `loadSelection`-trigger effect:

```ts
  // W6 (a): re-apply the prefill when the roster lands after loadSelection resolved.
  useEffect(() => {
    if (doc === null) return
    setChosen((c) => mergePrefill(c, doc.roles, devices, saved))
  }, [doc, devices, saved])
```

5. Import `mergePrefill` from `./preflight`.

- [ ] **Step 4: Run the frontend gate**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src
git commit -m "fix(studio): preflight prefill survives late roster load; pin 409-adopt path"
```

---

### Task 5: UI polish wave — viewer origin fallback, log-truncation hint, fetch timeouts, uid fallback, tsconfig strict

Tickets (c), (g), (f), the `crypto.randomUUID` secure-context carry, and (b).

**Files:**
- Modify: `webapp/frontend/src/records/RecordViewer.tsx`
- Modify: `webapp/frontend/src/run/EventLog.tsx`
- Modify: `webapp/frontend/src/api/client.ts`, `src/api/labs.ts`
- Modify: `webapp/frontend/src/builder/tree.ts:98`
- Modify: `webapp/frontend/tsconfig.app.json`, `tsconfig.node.json`
- Test: `webapp/frontend/src/api/client.test.ts`

- [ ] **Step 1: Write failing test for the timeout mapping**

`client.test.ts`:

```ts
it('maps a fetch TimeoutError to a retryable ApiError', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(
    new DOMException('The operation timed out.', 'TimeoutError'),
  ))
  await expect(getJson('/api/labs')).rejects.toMatchObject({
    name: 'ApiError',
    status: 0,
    message: '/api/labs: request timed out',
  })
})
```

Run: `npm test -- --run src/api/client.test.ts` → FAIL (raw DOMException propagates today).

- [ ] **Step 2: Implement all five**

`client.ts` — replace `request()`:

```ts
const DEFAULT_TIMEOUT_MS = 30_000 // generous: guards hangs, not slow agents

async function request<T>(
  path: string, init?: RequestInit, timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(apiPath(path), { signal: AbortSignal.timeout(timeoutMs), ...init })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'TimeoutError') {
      throw new ApiError(0, `${path}: request timed out`)
    }
    throw e
  }
  if (!resp.ok) throw await toApiError(path, resp)
  if (resp.status === 204) return undefined as T
  const text = await resp.text()
  if (text === '') return undefined as T // W3 carry-forward: empty 2xx body is legal
  return JSON.parse(text) as T
}
```

Thread an optional timeout through the helpers (keep the existing exports' shapes otherwise):

```ts
export const getJson = <T>(path: string, timeoutMs?: number) => request<T>(path, undefined, timeoutMs)
export const postJson = <T>(path: string, body: unknown, timeoutMs?: number) =>
  request<T>(path, jsonInit('POST', body), timeoutMs)
```

(`putJson`/`patchJson`/`deleteJson` unchanged unless their signature forces the same optional param — match the file.)

`labs.ts` — a live bus rescan is legitimately slow:

```ts
export const labDiscover = (lab: string) =>
  postJson<LabDevice[]>(`/api/labs/${encodeURIComponent(lab)}/discover`, {}, 120_000)
```

`RecordViewer.tsx` — replace the `origin` computation (ticket (c): interrupted records have no report and no run log, but stream CSVs exist; their first timestamps are the engine clock):

```ts
  const firstTs = Object.values(streams)
    .map((s) => s.t[0])
    .filter((t): t is number => t !== undefined)
  const origin =
    detail.report?.clock_origin ??
    (events.length > 0 ? events[0].timestamp : firstTs.length > 0 ? Math.min(...firstTs) : 0)
```

`EventLog.tsx` — ticket (g), insert before the empty-state line inside the scroll box:

```tsx
      {props.events.length > shown.length && (
        <p className="text-slate-400">
          … showing last {shown.length} of {props.events.length} events (download the zip for the full log)
        </p>
      )}
```

`tree.ts` — `crypto.randomUUID` exists only in secure contexts (https/localhost); plain-http LAN access must not crash the builder:

```ts
export const newUid = (): string =>
  typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `uid-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
```

`tsconfig.app.json` — add to `compilerOptions` (ticket (b); verified 0 strict errors on the current tree): `"strict": true`. Same addition in `tsconfig.node.json`. (`tsconfig.test.json` extends the app config.)

- [ ] **Step 3: Run the frontend gate**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: green. If `strict` surfaces new errors (tree drifted since the probe), fix them in place — they will be null-guard-shaped; do not switch strict back off.

- [ ] **Step 4: Commit**

```bash
git add webapp/frontend
git commit -m "fix(studio): viewer origin fallback, log-truncation hint, fetch timeouts, uid fallback, tsconfig strict"
```

---

### Task 6: Docs — spec amendments + operator/deployment guide

**Files:**
- Modify: `docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md`
- Modify: `webapp/README.md`

- [ ] **Step 1: Spec amendments** (each marked `(amended 2026-07-12 during W6: …)` inline, matching the existing amendment style):

1. **§5 runtime env:** replace the `STUDIO_PORT` sentence with the real surface: `STUDIO_DATA_DIR=/data` (volume), `STUDIO_STATIC_DIR` (set in-image; unset in dev = API-only), `LAB_DEVICES_DISCOVERY_URL` (engine default already points at the in-stack roster). Port is fixed at 8000 in the image CMD.
2. **§5 (new paragraph):** the SPA emits **relative** asset/API/WS URLs, so the image runs both at `/` and behind a prefix-stripping proxy; deployment route + snippets live in the companion spec `lab-bridge: docs/superpowers/specs/2026-07-12-experiment-studio-integration.md`.
3. **§3 stack table:** oxlint (not eslint) in the frontend-gates row; React 19/Vite 8 in the frontend row.
4. **§6 `GET /api/runs/active`:** note it returns `null` during the terminal finalization window too (W6 guard) — `status` in the payload is only ever `running|paused`.
5. **§9.4:** documented deviation — an experiment with zero roles can never Start (the mapping gate requires ≥1 mapped role by design).
6. **§9.5:** viewer chart origin precedence: `report.clock_origin` → first log event → min first stream timestamp → 0.

- [ ] **Step 2: `webapp/README.md`** — extend with two sections (keep the existing dev/gates/image content):

```markdown
## Deployment

One container serves API + SPA on port 8000. Persistent state lives entirely under
`STUDIO_DATA_DIR` (SQLite + run artifacts) — mount a volume there.

| Env | Default | Meaning |
|---|---|---|
| `STUDIO_DATA_DIR` | `/data` | SQLite db + `runs/<id>/` artifact dirs |
| `STUDIO_STATIC_DIR` | set in-image | built SPA; unset = API only (dev) |
| `LAB_DEVICES_DISCOVERY_URL` | `http://siteapp:8000/api/clients/` | lab roster endpoint |

All URLs the SPA emits are relative: the app works at `/` and behind a
prefix-stripping reverse proxy (lab-bridge serves it at `/studio/` — see that repo's
`docs/superpowers/specs/2026-07-12-experiment-studio-integration.md`). The app is
single-user: one active run per instance (second start → 409); auth belongs to the
proxy edge. Run exactly one replica per data dir.

## Operating (the four tabs)

1. **Devices** — pick the lab (persisted), inspect its device roster, or Rediscover
   (live bus rescan; refused with 409 while that lab runs an experiment).
2. **Builder** — define roles (name + device type) and streams (name + units), then
   drag verbs/structure blocks onto the canvas. Save/validate as you go: diagnostics
   badge blocks running, never saving.
3. **Run** — pick a saved experiment, map every role to a live device (pre-filled
   from the last run on that lab), Start. Live chart + event log + pause/resume/abort;
   operator-input prompts pop a dialog. A finished run shows its report and links to
   the record.
4. **Records** — one record per run: rename, delete, download zip (doc, workflow,
   run log, report, stream CSVs), or open the viewer (chart, log, report, read-only
   workflow snapshot).
```

- [ ] **Step 3: Gates untouched-code check**

Run: `git diff main -- src/ tests/` → empty. Frontend/backend gates unaffected by docs; skip re-running.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md webapp/README.md
git commit -m "docs: W6 spec amendments + studio operator/deployment guide"
```

---

### Task 7 (controller): PR, merge, release 0.2.1, image verification

- [ ] Full gates at branch HEAD (backend + frontend + `git diff main -- src/ tests/` empty).
- [ ] Push branch, open PR `feat(studio): W6 — integration polish, sub-path portability, operator docs`; wait for CI 7/7 (incl. webapp-image build).
- [ ] Final whole-branch review (fable) per SDD; fix wave if needed.
- [ ] Merge PR → release-please PR appears → merge it → verify the release workflow's `image` job pushed `ghcr.io/bioexperiment-lab-devices/experiment-studio:0.2.1`:
      `docker manifest inspect` equivalent via the ghcr token probe (anonymous 200), and check `webapp/backend/pyproject.toml` was stamped `0.2.1` in the release commit.
- [ ] Notify the lab-bridge session/user that `0.2.1` is live (their §5.2 merge gate).

### Task 8 (controller): preprod live smoke — W6 gate

Blocked on the lab-bridge deploy (other session). Then, from this session:

- [ ] Edge checks: `https://<preprod-host>/studio` → 308 → `/studio/` → 302 to `/login` (anonymous).
- [ ] In-stack REST smoke via `ssh khamit@111.88.145.138` + `docker exec` curl against `http://studio:8000` (trusted internal surface, same stance as the roster): health → labs roster shows `windows_arm64_test_client` → device roster (rediscover first — stale-cache gotcha) → create a minimal experiment doc (pump + densitometer roles) → validate → start with a real mapping → poll `/api/runs/active` + record → completion → record row `completed`, artifacts present, zip downloads.
- [ ] Device prep before the run if the agent's safety gates trip (pump `set_calibration` re-confirm, valve `home`, densitometer blank) — use the jupyter-container python client as in [[preprod-test-setup]].
- [ ] Record the outcome in the ledger; update memory (W6 shipped, preprod smoke result).
