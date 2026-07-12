# Experiment Studio W3 — Builder UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Builder tab of Experiment Studio — a drag-and-drop workflow editor
(palette / canvas / inspector), roles + streams panels, N-lane parallel containers,
expression fields with generated help, save/load/duplicate against the W2 backend,
debounced validation with per-block diagnostic badges, and undo/redo — plus the Devices
tab (lab picker + device roster) that no other increment covers.

**Architecture:** The canvas tree IS the engine AST (settled decision S1): a typed
`BlockNode` editor tree with stable uids converts losslessly to/from the doc-v1 JSON that
the W2 backend stores and validates. All tree operations (insert/move/remove/duplicate,
role/stream rename cascades, diagnostic-path resolution) are pure functions with vitest
coverage; React components are thin wrappers. State lives in one zustand store wrapped
with zundo for snapshot undo/redo; drag-and-drop uses @dnd-kit/core with explicit
per-slot droppables (no sortable abstraction).

**Tech Stack:** React 19 + TypeScript 6 + Vite 8, Tailwind CSS 4 (utility classes only),
zustand 5 + zundo 2, @dnd-kit/core 6, vitest 4 (node environment, pure-logic tests only),
oxlint. Backend is untouched in this increment.

## Global Constraints

- **Working directory for all frontend commands:** `webapp/frontend/`.
- **Gates (run all four before claiming a task done):**
  `npm run lint` (oxlint, warnings allowed / errors not), `npm run typecheck` (`tsc -b`),
  `npm test` (vitest run), `npm run build` (tsc + vite build).
- **Do not touch:** root `pyproject.toml`, `src/` (engine library), `webapp/backend/`
  (except nothing — W3 is frontend-only), `webapp/fixtures/` (read-only golden contract).
- **Code style:** match existing files — no semicolons, single quotes, 2-space indent,
  `import type` for type-only imports (tsconfig has `verbatimModuleSyntax`).
- **tsconfig has `erasableSyntaxOnly`:** NO enums, NO constructor parameter properties
  (`constructor(readonly x: number)` is a compile error — assign fields manually).
- **Files with React components use `.tsx`; pure logic goes in `.ts` files** (oxlint's
  react-refresh rule warns on mixed exports from component files).
- **Commit messages:** `feat(studio): <what>` / `test(studio): <what>`, ending with the
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
- **Vitest runs in `environment: 'node'`** — no jsdom, no component rendering tests.
  Testable logic must be pure functions in `.ts` modules.
- **Design doc:** `docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md`
  (§4 doc schema, §9.3 builder). Where this plan cites engine grammar, the engine source
  was verified on 2026-07-12 — trust the plan text over the spec's examples.

## Engine & doc grammar reference (verified against engine source)

Every task implicitly includes this section.

**Doc v1 envelope** (what `POST /api/experiments`, `PUT`, and `POST /api/validate` accept;
see `webapp/fixtures/valid-od-growth.json` for the golden example):

```json
{
  "doc_version": 1,
  "name": "OD growth curve",
  "description": null,
  "roles": {"feed_pump": {"type": "pump"}, "od_meter": {"type": "densitometer"}},
  "workflow": {
    "schema_version": 1,
    "metadata": {"name": "OD growth curve"},
    "persistence": {"default": "in_memory", "format": "jsonl"},
    "streams": {"od": {"units": "AU"}},
    "blocks": [ ... ]
  }
}
```

- Role names must match `[a-z][a-z0-9_]*`. Every block `device` field holds a ROLE name.
- The builder always writes `persistence: {"default": "in_memory", "format": "jsonl"}`
  (inert — the backend overwrites it on every run copy) and `metadata: {"name": <doc name>}`.
- Stream declarations carry `units` only (settled decision S5).

**Block JSON grammar** (engine `serialize.py`): a block object has EXACTLY ONE type key
plus optional timing keys `label`, `gap_after`, `start_offset` (the latter two are
duration strings). Type keys and bodies:

| key | body fields |
|---|---|
| `command` | `device`, `verb`, `params?` (object; omitted when empty) |
| `measure` | `device`, `verb` (default `"measure"`), `into` (stream name), `params?` |
| `operator_input` | `name`, `type` (`"int"`\|`"float"`\|`"bool"`\|`"enum"`), `prompt?`, `min?`, `max?`, `choices?` (each omitted when null) |
| `wait` | `duration` (duration string) |
| `serial` | `children` (block list) |
| `parallel` | `children` (block list — each child is one lane) |
| `loop` | `body` (block list), exactly one of `count` (int) / `until` (expression); `check` (`"before"`\|`"after"`, only emitted alongside `until`); `pace?` (duration) |
| `branch` | `if` (expression), `then` (block list), `else?` (block list, omitted — not null — when absent) |
| `group_ref` | `name` — **out of scope for the builder (v2)**; loading a doc containing one fails with a clear error |

**Durations:** `<number><unit>` with unit ∈ `ms|s|min|h` — e.g. `30s`, `5min`, `250ms`,
`1.5h`. **`2m` is INVALID** (the spec's §9.3 example is wrong; engine wins).

**Expressions** (Loop `until`, Branch `if`, expression-valued params): stat calls are
`fn(stream)` (all samples), `fn(stream, last=5)` (last N samples), `fn(stream, last=30s)`
(trailing duration). Functions: `count`, `last`, `max`, `mean`, `min` (served by
`GET /api/catalog` under `expression.functions`; window kinds under `expression.windows` =
`["all", "last_n", "duration"]`). Operators: `+ - * / < <= > >= == != and or not`, numeric
and boolean literals, and bare identifiers referencing operator-input bindings.
Empty string is an invalid expression.

**Param semantics** (engine validator): a param spec has `type` ∈
`number|int|string|bool`, `required` bool. `string` params accept ONLY string literals
(never expressions). `number`/`int`/`bool` params accept a JSON literal of that type OR a
string holding an expression of the matching type (number for int/number, boolean for
bool) — that is how operator-input bindings parameterize verbs.

**Diagnostics** (`POST /api/validate` → `{ok, diagnostics: [{category, path, message}]}`):
- Structural block paths: `blocks[0]`, `blocks[0].children[2]`, `blocks[0].body[1]`,
  `blocks[0].then[0]`, `blocks[0].else[1]` — slot names are exactly
  `children|body|then|else`.
- Param diagnostics append a suffix: `blocks[0].children[0] param 'volume_ml'`.
- Doc-level role diagnostics: path `roles['Feed_Pump']` (Python repr quoting).
- Workflow-level parse errors (fail-fast, e.g. an empty/invalid expression anywhere):
  ONE diagnostic with `category: "schema"`, `path: "workflow"`. The builder maps these to
  the problems panel only (no block badge) — accepted W2-settled behavior.
- An empty `blocks: []` workflow parses AND validates clean (verified) — a brand-new doc
  shows a green "valid" chip.

**Backend API** (all verified against `webapp/backend/experiment_studio/`):
`GET /api/catalog` → `{device_types: {<type>: {<verb>: {kind, params, result_field}}},
expression: {functions, windows}}`; `GET/POST /api/experiments` (list returns summaries
`{id, name, description, created_at, updated_at}`; create/GET-one/PUT return the same
plus `doc`); `PUT/DELETE /api/experiments/{id}`; `POST /api/experiments/{id}/duplicate`;
`POST /api/validate`; `GET /api/labs` → `[{name, host, port, online}]`;
`GET /api/labs/{lab}/devices` and `POST /api/labs/{lab}/discover` →
`[{id, type, port, connected, model, firmware}]` (port/connected/model/firmware nullable).
Errors are `{detail, code}`; relevant codes: `name_conflict` (409), `unknown_experiment`
(404), `unknown_lab` (404), `lab_offline`/`lab_unreachable`/`roster_unreachable` (502),
`agent_busy` (409). FastAPI request-validation errors (422) have a NON-string `detail`
list — the client must tolerate that.

## File structure

```
webapp/frontend/src/
  types/doc.ts            # TS mirrors of doc v1 + engine block JSON + API resources   (T1)
  types/catalog.ts        # /api/catalog payload types                                (T1)
  types/labs.ts           # /api/labs payload types                                   (T9)
  api/client.ts           # extend: ApiError {status, code}, postJson/putJson/deleteJson (T1)
  api/studio.ts           # typed endpoint functions (catalog/experiments/validate)   (T1)
  api/labs.ts             # typed endpoint functions (labs/devices/discover)          (T9)
  builder/tree.ts         # BlockNode model + pure tree ops                           (T2)
  builder/convert.ts      # docToTree / treeToDoc (+ DocConvertError)                 (T2)
  builder/refs.ts         # role/stream reference counting + rename cascades, bindings (T3)
  builder/paths.ts        # diagnostic path -> block uid resolution, mapDiagnostics   (T3)
  builder/exprHelp.ts     # expression-help model generation                          (T3)
  builder/summary.ts      # blockSummary() one-line card captions                     (T6)
  builder/params.ts       # param input <-> value coercion                            (T7)
  builder/dnd.ts          # DragPayload / slot droppable id helpers                   (T5)
  stores/docStore.ts      # zustand+zundo document store + undo/redo + dirty          (T4)
  stores/catalogStore.ts  # fetch-once catalog store                                  (T4)
  stores/labsStore.ts     # labs/devices store, selected lab in localStorage          (T9)
  builder/BuilderTab.tsx  # DndContext + 3-pane layout + keyboard shortcuts           (T6)
  builder/Palette.tsx     # structure + per-role verb chips + add-role                (T5)
  builder/RolesPanel.tsx  # roles list: rename / delete-with-refusal                  (T5)
  builder/StreamsPanel.tsx# streams list: add/rename/delete/units                     (T5)
  builder/Canvas.tsx      # recursive tree rendering, lanes, slots, selection         (T6)
  builder/DropSlot.tsx    # droppable insertion bar                                   (T6)
  builder/Inspector.tsx   # per-kind forms                                            (T7)
  builder/fields.tsx      # TextField/NumberishField/DurationField/ExpressionInput    (T7)
  builder/Toolbar.tsx     # name, undo/redo, validation chip, save/load/dup/new       (T8)
  builder/LoadDialog.tsx  # experiment list modal with search + delete                (T8)
  builder/ProblemsPanel.tsx # diagnostics list, click-to-select                       (T8)
  builder/useValidation.ts # debounced /api/validate wiring                           (T8)
  devices/DevicesTab.tsx  # lab picker + device table + rediscover                    (T9)
  shell/TabShell.tsx      # MODIFY: lab indicator chip in header                      (T9)
  App.tsx                 # MODIFY: mount BuilderTab (T8), DevicesTab (T9)
```

Tests co-locate as `<module>.test.ts` next to the module. Golden fixtures are read from
`webapp/fixtures/` via `readFileSync(new URL('../../../fixtures/<name>.json',
import.meta.url))` — this closes the W2 carry-forward that fixtures were backend-consumed
only.

---

### Task 1: Dependencies, shared types, API client

**Files:**
- Modify: `webapp/frontend/package.json` (via `npm install`)
- Modify: `webapp/frontend/vite.config.ts` (test include pattern)
- Create: `webapp/frontend/src/types/doc.ts`
- Create: `webapp/frontend/src/types/catalog.ts`
- Modify: `webapp/frontend/src/api/client.ts`
- Create: `webapp/frontend/src/api/studio.ts`
- Test: `webapp/frontend/src/api/client.test.ts`

**Interfaces:**
- Consumes: existing `client.ts` (`Health`, `getHealth` — keep both working; `health.ts`
  and `App.tsx` import them).
- Produces: `types/doc.ts` (`ParamValue`, `BlockJson`, `WorkflowJson`,
  `ExperimentDocJson`, `ExperimentSummary`, `ExperimentResource`, `Diagnostic`,
  `ValidateResponse`, `StreamDeclJson`, all body interfaces), `types/catalog.ts`
  (`ParamKind`, `ParamSpec`, `VerbSpec`, `Catalog`, `ExpressionInfo`), `api/client.ts`
  (`ApiError`, `getJson`, `postJson`, `putJson`, `deleteJson`, `toApiError`),
  `api/studio.ts` (`getCatalog`, `listExperiments`, `getExperiment`, `createExperiment`,
  `replaceExperiment`, `deleteExperiment`, `duplicateExperiment`, `validateDoc`).

- [ ] **Step 1: Install runtime dependencies**

```bash
cd webapp/frontend
npm install zustand@^5 zundo@^2 @dnd-kit/core@^6
```

Expected: `package.json` gains the three deps; `npm ls zustand zundo @dnd-kit/core` shows
all three resolved (zustand 5.x, zundo 2.x, @dnd-kit/core 6.x).

- [ ] **Step 2: Fix the vitest include pattern (W2 carry-forward)**

In `webapp/frontend/vite.config.ts` change the test block to:

```ts
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
  },
```

- [ ] **Step 3: Write the failing test for the API client**

Create `webapp/frontend/src/api/client.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { ApiError, toApiError } from './client'

describe('toApiError', () => {
  it('extracts the structured {detail, code} envelope', async () => {
    const resp = new Response(JSON.stringify({ detail: 'experiment name taken', code: 'name_conflict' }), {
      status: 409,
      headers: { 'Content-Type': 'application/json' },
    })
    const err = await toApiError('/api/experiments', resp)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(409)
    expect(err.code).toBe('name_conflict')
    expect(err.message).toBe('experiment name taken')
  })

  it('tolerates FastAPI 422 envelopes where detail is a list', async () => {
    const resp = new Response(JSON.stringify({ detail: [{ loc: ['body', 'name'], msg: 'required' }] }), {
      status: 422,
    })
    const err = await toApiError('/api/experiments', resp)
    expect(err.status).toBe(422)
    expect(err.code).toBeNull()
    expect(err.message).toBe('/api/experiments: HTTP 422')
  })

  it('tolerates non-JSON bodies', async () => {
    const resp = new Response('<html>boom</html>', { status: 502 })
    const err = await toApiError('/api/labs', resp)
    expect(err.status).toBe(502)
    expect(err.message).toBe('/api/labs: HTTP 502')
  })
})
```

- [ ] **Step 4: Run it to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL — `toApiError` / `ApiError` not exported.

- [ ] **Step 5: Rewrite `src/api/client.ts`**

Replace the whole file (keeping `Health` + `getHealth` exports intact):

```ts
export interface Health {
  status: string
  library: string
  studio: string
}

/** Structured backend error: the {detail, code} envelope from webapp design §6. */
export class ApiError extends Error {
  status: number
  code: string | null

  constructor(status: number, message: string, code: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export async function toApiError(path: string, resp: Response): Promise<ApiError> {
  let message = `${path}: HTTP ${resp.status}`
  let code: string | null = null
  try {
    const body: unknown = await resp.json()
    if (body !== null && typeof body === 'object') {
      const rec = body as Record<string, unknown>
      if (typeof rec.detail === 'string' && rec.detail.length > 0) message = rec.detail
      if (typeof rec.code === 'string') code = rec.code
    }
  } catch {
    // non-JSON body (proxy error page, empty body) — keep the generic message
  }
  return new ApiError(resp.status, message, code)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init)
  if (!resp.ok) throw await toApiError(path, resp)
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

const jsonInit = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const getJson = <T>(path: string) => request<T>(path)
export const postJson = <T>(path: string, body: unknown) => request<T>(path, jsonInit('POST', body))
export const putJson = <T>(path: string, body: unknown) => request<T>(path, jsonInit('PUT', body))
export const deleteJson = (path: string) => request<void>(path, { method: 'DELETE' })

export const getHealth = () => getJson<Health>('/api/health')
```

- [ ] **Step 6: Run the client tests to verify they pass**

Run: `cd webapp/frontend && npx vitest run src/api/client.test.ts src/api/health.test.ts`
Expected: PASS (3 new + 3 pre-existing).

- [ ] **Step 7: Create `src/types/doc.ts`**

```ts
/** Hand-written TS mirrors of doc v1 + engine workflow schema v1 (webapp design §4.1).
 * The block grammar mirrors the engine serializer: one type key per block plus optional
 * timing keys label/gap_after/start_offset. */

export type ParamValue = number | string | boolean

export interface CommandBody {
  device: string
  verb: string
  params?: Record<string, ParamValue>
}

export interface MeasureBody {
  device: string
  verb?: string
  into: string
  params?: Record<string, ParamValue>
}

export interface OperatorInputBody {
  name: string
  type: string // 'int' | 'float' | 'bool' | 'enum'
  prompt?: string
  min?: number
  max?: number
  choices?: string[]
}

export interface WaitBody {
  duration: string
}

export interface SerialBody {
  children: BlockJson[]
}

export interface ParallelBody {
  children: BlockJson[]
}

export interface LoopBody {
  body: BlockJson[]
  count?: number
  until?: string
  check?: string // 'before' | 'after'
  pace?: string
}

export interface BranchBody {
  if: string
  then: BlockJson[]
  else?: BlockJson[]
}

export interface GroupRefBody {
  name: string
}

export interface BlockJson {
  label?: string
  gap_after?: string
  start_offset?: string
  command?: CommandBody
  measure?: MeasureBody
  operator_input?: OperatorInputBody
  wait?: WaitBody
  serial?: SerialBody
  parallel?: ParallelBody
  loop?: LoopBody
  branch?: BranchBody
  group_ref?: GroupRefBody
}

export interface StreamDeclJson {
  units?: string | null
  persistence?: string | null
}

export interface WorkflowJson {
  schema_version: number
  metadata?: Record<string, unknown>
  persistence?: Record<string, unknown>
  streams?: Record<string, StreamDeclJson>
  groups?: Record<string, unknown>
  blocks: BlockJson[]
}

export interface RoleDefJson {
  type: string
}

export interface ExperimentDocJson {
  doc_version: number
  name: string
  description: string | null
  roles: Record<string, RoleDefJson>
  workflow: WorkflowJson
}

export interface ExperimentSummary {
  id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface ExperimentResource extends ExperimentSummary {
  doc: ExperimentDocJson
}

export interface Diagnostic {
  category: string
  path: string
  message: string
}

export interface ValidateResponse {
  ok: boolean
  diagnostics: Diagnostic[]
}
```

- [ ] **Step 8: Create `src/types/catalog.ts`**

```ts
/** GET /api/catalog payload (webapp design §4.4): thin serialization of the engine's
 * verb_catalog() and expression_functions(). */

export type ParamKind = 'number' | 'int' | 'string' | 'bool'

export interface ParamSpec {
  name: string
  type: ParamKind
  required: boolean
}

export interface VerbSpec {
  kind: 'command' | 'measure'
  params: ParamSpec[]
  result_field: string | null
}

export interface ExpressionInfo {
  functions: string[]
  windows: string[]
}

export interface Catalog {
  device_types: Record<string, Record<string, VerbSpec>>
  expression: ExpressionInfo
}
```

- [ ] **Step 9: Create `src/api/studio.ts`**

```ts
import { deleteJson, getJson, postJson, putJson } from './client'
import type { Catalog } from '../types/catalog'
import type {
  ExperimentDocJson,
  ExperimentResource,
  ExperimentSummary,
  ValidateResponse,
} from '../types/doc'

export const getCatalog = () => getJson<Catalog>('/api/catalog')

export const listExperiments = () => getJson<ExperimentSummary[]>('/api/experiments')

export const getExperiment = (id: string) =>
  getJson<ExperimentResource>(`/api/experiments/${id}`)

export const createExperiment = (doc: ExperimentDocJson) =>
  postJson<ExperimentResource>('/api/experiments', doc)

export const replaceExperiment = (id: string, doc: ExperimentDocJson) =>
  putJson<ExperimentResource>(`/api/experiments/${id}`, doc)

export const deleteExperiment = (id: string) => deleteJson(`/api/experiments/${id}`)

export const duplicateExperiment = (id: string) =>
  postJson<ExperimentResource>(`/api/experiments/${id}/duplicate`, {})

export const validateDoc = (doc: ExperimentDocJson) =>
  postJson<ValidateResponse>('/api/validate', doc)
```

- [ ] **Step 10: Run all four gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build`
Expected: all pass (oxlint may emit the pre-existing TabShell fast-refresh warning — exit 0).

- [ ] **Step 11: Commit**

```bash
git add webapp/frontend
git commit -m "feat(studio): builder deps, doc/catalog types, structured API client"
```

---

### Task 2: Block tree model + doc ↔ tree conversion

**Files:**
- Create: `webapp/frontend/src/builder/tree.ts`
- Create: `webapp/frontend/src/builder/convert.ts`
- Test: `webapp/frontend/src/builder/tree.test.ts`
- Test: `webapp/frontend/src/builder/convert.test.ts`

**Interfaces:**
- Consumes: `types/doc.ts` (`ParamValue`, `BlockJson`, `ExperimentDocJson`,
  `StreamDeclJson`, body types), `types/catalog.ts` (`VerbSpec`).
- Produces (later tasks call these EXACT names):
  - `tree.ts`: `BlockNode` (discriminated union on `kind`), `BlockKind`, `InputType`,
    `StructureKind`, `SlotRef {parentUid: string | null; slot: string; index: number}`
    (parentUid null = root list; root slot name is `'blocks'`), `ParentInfo
    {parent: BlockNode | null; slot: string; index: number}`, `newUid(): string`,
    `childSlots(node): Array<[string, BlockNode[]]>`, `visitNodes(tree, fn)`,
    `findNode(tree, uid): BlockNode | null`, `containsUid(node, uid): boolean`,
    `findLocation(tree, uid): ParentInfo | null`, `insertNode(tree, node, at): BlockNode[]`,
    `removeNode(tree, uid): [BlockNode[], BlockNode | null]`,
    `canDrop(tree, dragUid, at): boolean`, `moveNode(tree, uid, to): BlockNode[]`,
    `withFreshUids(node): BlockNode`, `duplicateNode(tree, uid): [BlockNode[], string | null]`,
    `updateNode(tree, uid, patch): BlockNode[]`, `newStructureNode(kind): BlockNode`,
    `newVerbNode(role, verb, spec): BlockNode`.
  - `convert.ts`: `DocContent {name; description; roles: Record<string, {type: string}>;
    streams: Record<string, {units: string | null}>; tree: BlockNode[]}`,
    `DocConvertError`, `docToTree(doc: ExperimentDocJson): DocContent`,
    `treeToDoc(content: DocContent): ExperimentDocJson`.
- Node field naming: camelCase for timing (`gapAfter`, `startOffset`), `inputType` (not
  `type`) on operator inputs, `condition` (not `if`) on branch. Loop nodes keep BOTH
  `count` and `until` so the inspector can switch modes without losing values; `mode:
  'count' | 'until'` decides which is emitted.

- [ ] **Step 1: Write `src/builder/tree.ts`**

```ts
/** Editor tree model: the canvas tree IS the engine AST (settled decision S1), with
 * stable uids for React keys, selection, and diagnostics mapping. All ops are pure and
 * return new trees (zustand/zundo snapshot immutability). */
import type { ParamValue } from '../types/doc'
import type { VerbSpec } from '../types/catalog'

export type InputType = 'int' | 'float' | 'bool' | 'enum'
export type StructureKind = 'serial' | 'parallel' | 'loop' | 'branch' | 'wait' | 'operator_input'

interface NodeBase {
  uid: string
  label: string | null
  gapAfter: string | null
  startOffset: string | null
}

export interface CommandNode extends NodeBase {
  kind: 'command'
  device: string
  verb: string
  params: Record<string, ParamValue>
}

export interface MeasureNode extends NodeBase {
  kind: 'measure'
  device: string
  verb: string
  into: string
  params: Record<string, ParamValue>
}

export interface OperatorInputNode extends NodeBase {
  kind: 'operator_input'
  name: string
  inputType: InputType
  prompt: string | null
  min: number | null
  max: number | null
  choices: string[] | null
}

export interface WaitNode extends NodeBase {
  kind: 'wait'
  duration: string
}

export interface SerialNode extends NodeBase {
  kind: 'serial'
  children: BlockNode[]
}

export interface ParallelNode extends NodeBase {
  kind: 'parallel'
  children: BlockNode[]
}

export interface LoopNode extends NodeBase {
  kind: 'loop'
  mode: 'count' | 'until'
  count: number
  until: string
  check: 'before' | 'after'
  pace: string | null
  body: BlockNode[]
}

export interface BranchNode extends NodeBase {
  kind: 'branch'
  condition: string
  then: BlockNode[]
  else: BlockNode[] | null
}

export type BlockNode =
  | CommandNode
  | MeasureNode
  | OperatorInputNode
  | WaitNode
  | SerialNode
  | ParallelNode
  | LoopNode
  | BranchNode

export type BlockKind = BlockNode['kind']

export interface SlotRef {
  parentUid: string | null
  slot: string
  index: number
}

export interface ParentInfo {
  parent: BlockNode | null
  slot: string
  index: number
}

export const newUid = (): string => crypto.randomUUID()

export function childSlots(node: BlockNode): Array<[string, BlockNode[]]> {
  switch (node.kind) {
    case 'serial':
    case 'parallel':
      return [['children', node.children]]
    case 'loop':
      return [['body', node.body]]
    case 'branch':
      return node.else === null
        ? [['then', node.then]]
        : [
            ['then', node.then],
            ['else', node.else],
          ]
    default:
      return []
  }
}

function replaceSlot(node: BlockNode, slot: string, list: BlockNode[]): BlockNode {
  if (node.kind === 'serial' || node.kind === 'parallel') return { ...node, children: list }
  if (node.kind === 'loop') return { ...node, body: list }
  if (node.kind === 'branch') {
    return slot === 'then' ? { ...node, then: list } : { ...node, else: list }
  }
  throw new Error(`${node.kind} has no child slot ${slot}`)
}

export function visitNodes(tree: BlockNode[], fn: (node: BlockNode) => void): void {
  for (const node of tree) {
    fn(node)
    for (const [, children] of childSlots(node)) visitNodes(children, fn)
  }
}

export function findNode(tree: BlockNode[], uid: string): BlockNode | null {
  for (const node of tree) {
    if (node.uid === uid) return node
    for (const [, children] of childSlots(node)) {
      const found = findNode(children, uid)
      if (found) return found
    }
  }
  return null
}

export function containsUid(node: BlockNode, uid: string): boolean {
  if (node.uid === uid) return true
  return childSlots(node).some(([, children]) => children.some((c) => containsUid(c, uid)))
}

export function findLocation(tree: BlockNode[], uid: string): ParentInfo | null {
  const inList = (list: BlockNode[], parent: BlockNode | null, slot: string): ParentInfo | null => {
    for (let i = 0; i < list.length; i++) {
      if (list[i].uid === uid) return { parent, slot, index: i }
      for (const [childSlot, children] of childSlots(list[i])) {
        const found = inList(children, list[i], childSlot)
        if (found) return found
      }
    }
    return null
  }
  return inList(tree, null, 'blocks')
}

const clampIndex = (index: number, length: number): number =>
  Math.max(0, Math.min(index, length))

export function insertNode(tree: BlockNode[], node: BlockNode, at: SlotRef): BlockNode[] {
  if (at.parentUid === null) {
    const out = [...tree]
    out.splice(clampIndex(at.index, out.length), 0, node)
    return out
  }
  let inserted = false
  const walkNode = (n: BlockNode): BlockNode => {
    let out = n
    for (const [slot, children] of childSlots(n)) {
      let list = children.map(walkNode)
      if (n.uid === at.parentUid && slot === at.slot) {
        list.splice(clampIndex(at.index, list.length), 0, node)
        inserted = true
      }
      out = replaceSlot(out, slot, list)
    }
    return out
  }
  const next = tree.map(walkNode)
  return inserted ? next : tree
}

export function removeNode(tree: BlockNode[], uid: string): [BlockNode[], BlockNode | null] {
  let removed: BlockNode | null = null
  const walkNode = (node: BlockNode): BlockNode => {
    let out = node
    for (const [slot, children] of childSlots(node)) {
      out = replaceSlot(out, slot, walkList(children))
    }
    return out
  }
  const walkList = (list: BlockNode[]): BlockNode[] => {
    const kept: BlockNode[] = []
    for (const node of list) {
      if (node.uid === uid) removed = node
      else kept.push(walkNode(node))
    }
    return kept
  }
  const next = walkList(tree)
  return removed ? [next, removed] : [tree, null]
}

export function canDrop(tree: BlockNode[], dragUid: string, at: SlotRef): boolean {
  const dragged = findNode(tree, dragUid)
  if (!dragged) return false
  if (at.parentUid === null) return true
  if (findNode(tree, at.parentUid) === null) return false
  return !containsUid(dragged, at.parentUid)
}

export function moveNode(tree: BlockNode[], uid: string, to: SlotRef): BlockNode[] {
  if (!canDrop(tree, uid, to)) return tree
  const from = findLocation(tree, uid)
  if (!from) return tree
  let index = to.index
  const sameList = (from.parent?.uid ?? null) === to.parentUid && from.slot === to.slot
  if (sameList && from.index < to.index) index -= 1
  const [without, node] = removeNode(tree, uid)
  if (!node) return tree
  return insertNode(without, node, { parentUid: to.parentUid, slot: to.slot, index })
}

export function withFreshUids(node: BlockNode): BlockNode {
  let out: BlockNode = { ...node, uid: newUid() }
  for (const [slot, children] of childSlots(out)) {
    out = replaceSlot(out, slot, children.map(withFreshUids))
  }
  return out
}

export function duplicateNode(tree: BlockNode[], uid: string): [BlockNode[], string | null] {
  const loc = findLocation(tree, uid)
  const node = findNode(tree, uid)
  if (!loc || !node) return [tree, null]
  const clone = withFreshUids(node)
  const at: SlotRef = { parentUid: loc.parent?.uid ?? null, slot: loc.slot, index: loc.index + 1 }
  return [insertNode(tree, clone, at), clone.uid]
}

export function updateNode(tree: BlockNode[], uid: string, patch: object): BlockNode[] {
  const walkNode = (node: BlockNode): BlockNode => {
    let out = node.uid === uid ? ({ ...node, ...patch } as BlockNode) : node
    for (const [slot, children] of childSlots(out)) {
      out = replaceSlot(out, slot, children.map(walkNode))
    }
    return out
  }
  return tree.map(walkNode)
}

const nodeBase = (): NodeBase => ({ uid: newUid(), label: null, gapAfter: null, startOffset: null })

export function newStructureNode(kind: StructureKind): BlockNode {
  const base = nodeBase()
  switch (kind) {
    case 'serial':
      return { ...base, kind, children: [] }
    case 'parallel':
      // Parallelism should be immediately visible (S1): start with two empty lanes.
      return {
        ...base,
        kind,
        children: [
          { ...nodeBase(), kind: 'serial', children: [] },
          { ...nodeBase(), kind: 'serial', children: [] },
        ],
      }
    case 'loop':
      return { ...base, kind, mode: 'count', count: 2, until: '', check: 'after', pace: null, body: [] }
    case 'branch':
      return { ...base, kind, condition: '', then: [], else: [] }
    case 'wait':
      return { ...base, kind, duration: '1s' }
    case 'operator_input':
      return { ...base, kind, name: 'value', inputType: 'float', prompt: null, min: null, max: null, choices: null }
  }
}

export function newVerbNode(role: string, verb: string, spec: VerbSpec): BlockNode {
  return spec.kind === 'measure'
    ? { ...nodeBase(), kind: 'measure', device: role, verb, into: '', params: {} }
    : { ...nodeBase(), kind: 'command', device: role, verb, params: {} }
}
```

- [ ] **Step 2: Write the failing tests for tree ops**

Create `webapp/frontend/src/builder/tree.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  canDrop,
  containsUid,
  duplicateNode,
  findLocation,
  findNode,
  insertNode,
  moveNode,
  newStructureNode,
  newVerbNode,
  removeNode,
  updateNode,
  withFreshUids,
  type BlockNode,
  type SerialNode,
  type ParallelNode,
  type LoopNode,
} from './tree'

const wait = (uid: string): BlockNode => ({
  uid, kind: 'wait', duration: '1s', label: null, gapAfter: null, startOffset: null,
})
const serial = (uid: string, children: BlockNode[]): SerialNode => ({
  uid, kind: 'serial', children, label: null, gapAfter: null, startOffset: null,
})
const loop = (uid: string, body: BlockNode[]): LoopNode => ({
  uid, kind: 'loop', mode: 'count', count: 2, until: '', check: 'after', pace: null,
  body, label: null, gapAfter: null, startOffset: null,
})

describe('tree ops', () => {
  it('finds nodes and locations in nested slots', () => {
    const tree = [serial('s1', [wait('w1'), loop('l1', [wait('w2')])])]
    expect(findNode(tree, 'w2')?.kind).toBe('wait')
    expect(findLocation(tree, 'w2')).toMatchObject({ slot: 'body', index: 0 })
    expect(findLocation(tree, 'w2')?.parent?.uid).toBe('l1')
    expect(findLocation(tree, 's1')).toMatchObject({ parent: null, slot: 'blocks', index: 0 })
    expect(containsUid(tree[0], 'w2')).toBe(true)
    expect(containsUid(tree[0], 'nope')).toBe(false)
  })

  it('inserts at root and into container slots without mutating the input', () => {
    const tree = [serial('s1', [])]
    const atRoot = insertNode(tree, wait('w1'), { parentUid: null, slot: 'blocks', index: 0 })
    expect(atRoot.map((n) => n.uid)).toEqual(['w1', 's1'])
    const nested = insertNode(atRoot, wait('w2'), { parentUid: 's1', slot: 'children', index: 0 })
    expect((findNode(nested, 's1') as SerialNode).children.map((n) => n.uid)).toEqual(['w2'])
    expect((findNode(atRoot, 's1') as SerialNode).children).toEqual([])
  })

  it('returns the same tree when the insert target does not exist', () => {
    const tree = [serial('s1', [])]
    expect(insertNode(tree, wait('w1'), { parentUid: 'ghost', slot: 'children', index: 0 })).toBe(tree)
  })

  it('removes nested nodes and reports the removed subtree', () => {
    const tree = [serial('s1', [wait('w1'), wait('w2')])]
    const [next, removed] = removeNode(tree, 'w1')
    expect(removed?.uid).toBe('w1')
    expect((findNode(next, 's1') as SerialNode).children.map((n) => n.uid)).toEqual(['w2'])
    const [same, none] = removeNode(tree, 'ghost')
    expect(same).toBe(tree)
    expect(none).toBeNull()
  })

  it('refuses to drop a container into its own subtree', () => {
    const inner = serial('inner', [])
    const tree = [serial('outer', [inner]), wait('w1')]
    expect(canDrop(tree, 'outer', { parentUid: 'inner', slot: 'children', index: 0 })).toBe(false)
    expect(canDrop(tree, 'outer', { parentUid: 'outer', slot: 'children', index: 0 })).toBe(false)
    expect(canDrop(tree, 'w1', { parentUid: 'inner', slot: 'children', index: 0 })).toBe(true)
    const illegal = moveNode(tree, 'outer', { parentUid: 'inner', slot: 'children', index: 0 })
    expect(illegal).toBe(tree)
  })

  it('adjusts the index when moving forward within the same list', () => {
    const tree = [wait('a'), wait('b'), wait('c')]
    const next = moveNode(tree, 'a', { parentUid: null, slot: 'blocks', index: 2 })
    expect(next.map((n) => n.uid)).toEqual(['b', 'a', 'c'])
    const back = moveNode(next, 'a', { parentUid: null, slot: 'blocks', index: 0 })
    expect(back.map((n) => n.uid)).toEqual(['a', 'b', 'c'])
  })

  it('moves nodes across parents', () => {
    const tree = [serial('s1', [wait('w1')]), serial('s2', [])]
    const next = moveNode(tree, 'w1', { parentUid: 's2', slot: 'children', index: 0 })
    expect((findNode(next, 's1') as SerialNode).children).toEqual([])
    expect((findNode(next, 's2') as SerialNode).children.map((n) => n.uid)).toEqual(['w1'])
  })

  it('duplicates a subtree with fresh uids right after the original', () => {
    const tree = [serial('s1', [wait('w1')])]
    const [next, cloneUid] = duplicateNode(tree, 's1')
    expect(next).toHaveLength(2)
    expect(cloneUid).not.toBeNull()
    expect(next[1].uid).toBe(cloneUid)
    const clone = next[1] as SerialNode
    expect(clone.children).toHaveLength(1)
    expect(clone.children[0].uid).not.toBe('w1')
    const fresh = withFreshUids(tree[0])
    expect(fresh.uid).not.toBe('s1')
  })

  it('patches node fields immutably', () => {
    const tree = [wait('w1')]
    const next = updateNode(tree, 'w1', { duration: '5min' })
    expect(next[0]).toMatchObject({ duration: '5min' })
    expect(tree[0]).toMatchObject({ duration: '1s' })
  })

  it('builds structure nodes with builder defaults', () => {
    const parallel = newStructureNode('parallel') as ParallelNode
    expect(parallel.children).toHaveLength(2)
    expect(parallel.children.every((lane) => lane.kind === 'serial')).toBe(true)
    const branch = newStructureNode('branch')
    expect(branch).toMatchObject({ condition: '', else: [] })
    expect(newStructureNode('wait')).toMatchObject({ duration: '1s' })
    const l = newStructureNode('loop')
    expect(l).toMatchObject({ mode: 'count', count: 2, check: 'after' })
  })

  it('builds command vs measure nodes from the verb spec kind', () => {
    const cmd = newVerbNode('feed_pump', 'dispense', { kind: 'command', params: [], result_field: null })
    expect(cmd).toMatchObject({ kind: 'command', device: 'feed_pump', verb: 'dispense', params: {} })
    const meas = newVerbNode('od_meter', 'measure', { kind: 'measure', params: [], result_field: 'absorbance' })
    expect(meas).toMatchObject({ kind: 'measure', device: 'od_meter', into: '' })
  })
})
```

- [ ] **Step 3: Run tree tests**

Run: `cd webapp/frontend && npx vitest run src/builder/tree.test.ts`
Expected: PASS (tree.ts was written in Step 1; if any fail, fix tree.ts — the tests
encode the intended semantics).

- [ ] **Step 4: Write `src/builder/convert.ts`**

```ts
/** Doc v1 JSON <-> editor tree. treeToDoc(docToTree(doc)) must round-trip the golden
 * fixture byte-for-byte (deep equality); emission rules mirror the engine serializer:
 * omit empty params, omit null timing keys, `check` only alongside `until`, `else`
 * omitted (not null) when absent. */
import type {
  BlockJson,
  BranchBody,
  CommandBody,
  ExperimentDocJson,
  LoopBody,
  MeasureBody,
  OperatorInputBody,
  StreamDeclJson,
} from '../types/doc'
import { newUid, type BlockNode, type InputType } from './tree'

export interface DocContent {
  name: string
  description: string | null
  roles: Record<string, { type: string }>
  streams: Record<string, { units: string | null }>
  tree: BlockNode[]
}

export class DocConvertError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'DocConvertError'
  }
}

const TIMING_KEYS = new Set(['label', 'gap_after', 'start_offset'])

export function docToTree(doc: ExperimentDocJson): DocContent {
  if (doc.doc_version !== 1) {
    throw new DocConvertError(`unsupported doc_version ${String(doc.doc_version)}`)
  }
  const wf = doc.workflow
  if (wf.schema_version !== 1) {
    throw new DocConvertError(`unsupported workflow schema_version ${String(wf.schema_version)}`)
  }
  if (wf.groups && Object.keys(wf.groups).length > 0) {
    throw new DocConvertError('workflow groups are not supported in the builder (v2 backlog)')
  }
  const streams: DocContent['streams'] = {}
  for (const [name, decl] of Object.entries(wf.streams ?? {})) {
    streams[name] = { units: decl.units ?? null }
  }
  const roles: DocContent['roles'] = {}
  for (const [name, role] of Object.entries(doc.roles)) roles[name] = { type: role.type }
  return {
    name: doc.name,
    description: doc.description ?? null,
    roles,
    streams,
    tree: (wf.blocks ?? []).map(blockToNode),
  }
}

function blockToNode(block: BlockJson): BlockNode {
  const keys = Object.keys(block).filter((k) => !TIMING_KEYS.has(k))
  if (keys.length !== 1) {
    throw new DocConvertError(`block must have exactly one type key, got [${keys.join(', ')}]`)
  }
  const kind = keys[0]
  const base = {
    uid: newUid(),
    label: block.label ?? null,
    gapAfter: block.gap_after ?? null,
    startOffset: block.start_offset ?? null,
  }
  switch (kind) {
    case 'command': {
      const b = block.command as CommandBody
      return { ...base, kind, device: b.device, verb: b.verb, params: { ...(b.params ?? {}) } }
    }
    case 'measure': {
      const b = block.measure as MeasureBody
      return {
        ...base,
        kind,
        device: b.device,
        verb: b.verb ?? 'measure',
        into: b.into ?? '',
        params: { ...(b.params ?? {}) },
      }
    }
    case 'operator_input': {
      const b = block.operator_input as OperatorInputBody
      return {
        ...base,
        kind,
        name: b.name,
        inputType: b.type as InputType,
        prompt: b.prompt ?? null,
        min: b.min ?? null,
        max: b.max ?? null,
        choices: b.choices ? [...b.choices] : null,
      }
    }
    case 'wait':
      return { ...base, kind, duration: block.wait?.duration ?? '' }
    case 'serial':
      return { ...base, kind, children: (block.serial?.children ?? []).map(blockToNode) }
    case 'parallel':
      return { ...base, kind, children: (block.parallel?.children ?? []).map(blockToNode) }
    case 'loop': {
      const b = block.loop as LoopBody
      return {
        ...base,
        kind,
        mode: b.until != null ? 'until' : 'count',
        count: b.count ?? 2,
        until: b.until ?? '',
        check: b.check === 'before' ? 'before' : 'after',
        pace: b.pace ?? null,
        body: (b.body ?? []).map(blockToNode),
      }
    }
    case 'branch': {
      const b = block.branch as BranchBody
      return {
        ...base,
        kind,
        condition: b.if,
        then: (b.then ?? []).map(blockToNode),
        else: b.else !== undefined ? b.else.map(blockToNode) : null,
      }
    }
    default:
      throw new DocConvertError(`unsupported block type '${kind}' in the builder`)
  }
}

export function treeToDoc(content: DocContent): ExperimentDocJson {
  const streams: Record<string, StreamDeclJson> = {}
  for (const [name, s] of Object.entries(content.streams)) streams[name] = { units: s.units }
  const roles: ExperimentDocJson['roles'] = {}
  for (const [name, role] of Object.entries(content.roles)) roles[name] = { type: role.type }
  return {
    doc_version: 1,
    name: content.name,
    description: content.description,
    roles,
    workflow: {
      schema_version: 1,
      metadata: { name: content.name },
      persistence: { default: 'in_memory', format: 'jsonl' },
      streams,
      blocks: content.tree.map(nodeToBlock),
    },
  }
}

export function nodeToBlock(node: BlockNode): BlockJson {
  const out: BlockJson = {}
  switch (node.kind) {
    case 'command': {
      const body: CommandBody = { device: node.device, verb: node.verb }
      if (Object.keys(node.params).length > 0) body.params = { ...node.params }
      out.command = body
      break
    }
    case 'measure': {
      const body: MeasureBody = { device: node.device, verb: node.verb, into: node.into }
      if (Object.keys(node.params).length > 0) body.params = { ...node.params }
      out.measure = body
      break
    }
    case 'operator_input': {
      const body: OperatorInputBody = { name: node.name, type: node.inputType }
      if (node.prompt !== null) body.prompt = node.prompt
      if (node.min !== null) body.min = node.min
      if (node.max !== null) body.max = node.max
      if (node.choices !== null) body.choices = [...node.choices]
      out.operator_input = body
      break
    }
    case 'wait':
      out.wait = { duration: node.duration }
      break
    case 'serial':
      out.serial = { children: node.children.map(nodeToBlock) }
      break
    case 'parallel':
      out.parallel = { children: node.children.map(nodeToBlock) }
      break
    case 'loop': {
      const body: LoopBody = { body: node.body.map(nodeToBlock) }
      if (node.mode === 'count') {
        body.count = node.count
      } else {
        body.until = node.until
        body.check = node.check
      }
      if (node.pace !== null) body.pace = node.pace
      out.loop = body
      break
    }
    case 'branch': {
      const body: BranchBody = { if: node.condition, then: node.then.map(nodeToBlock) }
      if (node.else !== null) body.else = node.else.map(nodeToBlock)
      out.branch = body
      break
    }
  }
  if (node.label !== null) out.label = node.label
  if (node.gapAfter !== null) out.gap_after = node.gapAfter
  if (node.startOffset !== null) out.start_offset = node.startOffset
  return out
}
```

- [ ] **Step 5: Write the conversion tests (golden fixture round-trip)**

Create `webapp/frontend/src/builder/convert.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import type { ExperimentDocJson } from '../types/doc'
import { DocConvertError, docToTree, nodeToBlock, treeToDoc } from './convert'
import type { LoopNode, MeasureNode, SerialNode } from './tree'

const fixture = (name: string): ExperimentDocJson =>
  JSON.parse(
    readFileSync(new URL(`../../../fixtures/${name}.json`, import.meta.url), 'utf8'),
  ) as ExperimentDocJson

describe('docToTree', () => {
  it('parses the golden fixture into an editor tree', () => {
    const content = docToTree(fixture('valid-od-growth'))
    expect(content.name).toBe('OD growth curve')
    expect(content.roles).toEqual({
      feed_pump: { type: 'pump' },
      od_meter: { type: 'densitometer' },
    })
    expect(content.streams).toEqual({ od: { units: 'AU' } })
    expect(content.tree).toHaveLength(1)
    const root = content.tree[0] as SerialNode
    expect(root.kind).toBe('serial')
    expect(root.children.map((c) => c.kind)).toEqual(['command', 'loop'])
    const loop = root.children[1] as LoopNode
    expect(loop).toMatchObject({
      mode: 'until',
      until: 'mean(od, last=3) > 0.6',
      check: 'after',
      pace: '30s',
    })
    const measure = loop.body[0] as MeasureNode
    expect(measure).toMatchObject({ device: 'od_meter', verb: 'measure', into: 'od' })
  })

  it('parses both invalid fixtures without throwing (they are diagnostics cases, not parse cases)', () => {
    expect(() => docToTree(fixture('invalid-roles'))).not.toThrow()
    expect(() => docToTree(fixture('invalid-workflow'))).not.toThrow()
  })

  it('assigns unique uids to every node', () => {
    const { tree } = docToTree(fixture('valid-od-growth'))
    const uids: string[] = []
    const visit = (nodes: typeof tree): void => {
      for (const n of nodes) {
        uids.push(n.uid)
        if (n.kind === 'serial' || n.kind === 'parallel') visit(n.children)
        if (n.kind === 'loop') visit(n.body)
        if (n.kind === 'branch') {
          visit(n.then)
          if (n.else) visit(n.else)
        }
      }
    }
    visit(tree)
    expect(new Set(uids).size).toBe(uids.length)
    expect(uids.length).toBe(5)
  })

  it('refuses docs that use groups or group_ref blocks', () => {
    const doc = fixture('valid-od-growth')
    doc.workflow.groups = { prep: { body: [] } }
    expect(() => docToTree(doc)).toThrow(DocConvertError)
    const doc2 = fixture('valid-od-growth')
    doc2.workflow.blocks = [{ group_ref: { name: 'prep' } }]
    expect(() => docToTree(doc2)).toThrow(/group_ref/)
  })
})

describe('treeToDoc', () => {
  it('round-trips the golden fixture exactly', () => {
    const raw = fixture('valid-od-growth')
    expect(treeToDoc(docToTree(raw))).toEqual(raw)
  })

  it('emits check only alongside until, and omits count in until mode', () => {
    const { tree } = docToTree(fixture('valid-od-growth'))
    const root = tree[0] as SerialNode
    const loop = root.children[1] as LoopNode
    const untilJson = nodeToBlock(loop)
    expect(untilJson.loop).toMatchObject({ until: 'mean(od, last=3) > 0.6', check: 'after' })
    expect(untilJson.loop).not.toHaveProperty('count')
    const countJson = nodeToBlock({ ...loop, mode: 'count', count: 3 })
    expect(countJson.loop).toMatchObject({ count: 3 })
    expect(countJson.loop).not.toHaveProperty('until')
    expect(countJson.loop).not.toHaveProperty('check')
  })

  it('omits empty params, null timing keys, and null else', () => {
    const { tree } = docToTree(fixture('valid-od-growth'))
    const root = tree[0] as SerialNode
    const measureJson = nodeToBlock((root.children[1] as LoopNode).body[0])
    expect(measureJson.measure).not.toHaveProperty('params')
    expect(measureJson).not.toHaveProperty('label')
    expect(measureJson).not.toHaveProperty('gap_after')
    const branchJson = nodeToBlock({
      uid: 'b', kind: 'branch', condition: 'last(od) > 1', then: [], else: null,
      label: null, gapAfter: null, startOffset: null,
    })
    expect(branchJson.branch).not.toHaveProperty('else')
    const withElse = nodeToBlock({
      uid: 'b', kind: 'branch', condition: 'last(od) > 1', then: [], else: [],
      label: null, gapAfter: null, startOffset: null,
    })
    expect(withElse.branch).toHaveProperty('else', [])
  })

  it('always stamps builder-owned metadata and persistence sections', () => {
    const doc = treeToDoc({ name: 'X', description: null, roles: {}, streams: {}, tree: [] })
    expect(doc.workflow.metadata).toEqual({ name: 'X' })
    expect(doc.workflow.persistence).toEqual({ default: 'in_memory', format: 'jsonl' })
    expect(doc.workflow.blocks).toEqual([])
    expect(doc.doc_version).toBe(1)
  })
})
```

- [ ] **Step 6: Run conversion tests**

Run: `cd webapp/frontend && npx vitest run src/builder/convert.test.ts`
Expected: PASS. The round-trip test is the golden contract — if it fails on key ordering,
remember `toEqual` ignores key order; a real failure means an emission rule is wrong.

- [ ] **Step 7: Run all four gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add webapp/frontend/src/builder webapp/frontend/src/types
git commit -m "feat(studio): builder block-tree model and doc round-trip conversion"
```

---

### Task 3: Reference cascades, diagnostic path resolution, expression help

**Files:**
- Create: `webapp/frontend/src/builder/refs.ts`
- Create: `webapp/frontend/src/builder/paths.ts`
- Create: `webapp/frontend/src/builder/exprHelp.ts`
- Test: `webapp/frontend/src/builder/refs.test.ts`
- Test: `webapp/frontend/src/builder/paths.test.ts`
- Test: `webapp/frontend/src/builder/exprHelp.test.ts`

**Interfaces:**
- Consumes: `builder/tree.ts` (`BlockNode`, `childSlots`, `visitNodes`), `types/doc.ts`
  (`Diagnostic`), `types/catalog.ts` (`ExpressionInfo`).
- Produces:
  - `refs.ts`: `countRoleRefs(tree, role): number`,
    `renameRoleRefs(tree, from, to): BlockNode[]`,
    `countStreamRefs(tree, stream): number`,
    `renameStreamRefs(tree, from, to): BlockNode[]`,
    `collectBindings(tree): string[]` (operator_input names, DFS order, deduped).
  - `paths.ts`: `ResolvedPath {uid: string | null; role: string | null; param: string | null}`,
    `resolveDiagnosticPath(tree, path): ResolvedPath`,
    `MappedDiagnostic extends Diagnostic {uid; role; param}`,
    `mapDiagnostics(tree, diags): MappedDiagnostic[]`,
    `diagnosticsByUid(diags): Map<string, MappedDiagnostic[]>`.
  - `exprHelp.ts`: `ExpressionHelp {streams: string[]; bindings: string[]; functions:
    Array<{name, example}>; windowForms: Array<{label, example}>}`,
    `buildExpressionHelp(expression: ExpressionInfo, streams: string[], bindings: string[]):
    ExpressionHelp`.

- [ ] **Step 1: Write the failing tests for refs**

Create `webapp/frontend/src/builder/refs.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { collectBindings, countRoleRefs, countStreamRefs, renameRoleRefs, renameStreamRefs } from './refs'
import type { BlockNode, CommandNode, LoopNode, MeasureNode, SerialNode } from './tree'

const base = { label: null, gapAfter: null, startOffset: null }
const cmd = (uid: string, device: string): CommandNode => ({
  uid, kind: 'command', device, verb: 'stop', params: {}, ...base,
})
const meas = (uid: string, device: string, into: string): MeasureNode => ({
  uid, kind: 'measure', device, verb: 'measure', into, params: {}, ...base,
})
const tree: BlockNode[] = [
  {
    uid: 's1', kind: 'serial', ...base,
    children: [
      cmd('c1', 'feed_pump'),
      {
        uid: 'l1', kind: 'loop', mode: 'until', count: 2, until: 'mean(od, last=3) > 0.6',
        check: 'after', pace: null, ...base,
        body: [
          meas('m1', 'od_meter', 'od'),
          { uid: 'oi1', kind: 'operator_input', name: 'feed_ml', inputType: 'float',
            prompt: null, min: null, max: null, choices: null, ...base },
          cmd('c2', 'feed_pump'),
        ],
      } satisfies LoopNode,
    ],
  } satisfies SerialNode,
]

describe('role refs', () => {
  it('counts command/measure blocks bound to a role', () => {
    expect(countRoleRefs(tree, 'feed_pump')).toBe(2)
    expect(countRoleRefs(tree, 'od_meter')).toBe(1)
    expect(countRoleRefs(tree, 'ghost')).toBe(0)
  })

  it('renames every referencing block in one pass', () => {
    const next = renameRoleRefs(tree, 'feed_pump', 'acid_pump')
    expect(countRoleRefs(next, 'feed_pump')).toBe(0)
    expect(countRoleRefs(next, 'acid_pump')).toBe(2)
    expect(countRoleRefs(tree, 'feed_pump')).toBe(2) // input untouched
  })
})

describe('stream refs', () => {
  it('counts measure blocks writing into a stream', () => {
    expect(countStreamRefs(tree, 'od')).toBe(1)
    expect(countStreamRefs(tree, 'ph')).toBe(0)
  })

  it('renames into fields but leaves expression text alone (validation catches those)', () => {
    const next = renameStreamRefs(tree, 'od', 'od600')
    expect(countStreamRefs(next, 'od600')).toBe(1)
    const loop = (next[0] as SerialNode).children[1] as LoopNode
    expect(loop.until).toBe('mean(od, last=3) > 0.6')
  })
})

describe('collectBindings', () => {
  it('collects operator_input names in DFS order, deduped', () => {
    expect(collectBindings(tree)).toEqual(['feed_ml'])
    const twice = [...tree, { uid: 'oi2', kind: 'operator_input' as const, name: 'feed_ml',
      inputType: 'float' as const, prompt: null, min: null, max: null, choices: null, ...base }]
    expect(collectBindings(twice)).toEqual(['feed_ml'])
  })
})
```

- [ ] **Step 2: Run refs tests to verify they fail**

Run: `cd webapp/frontend && npx vitest run src/builder/refs.test.ts`
Expected: FAIL — module `./refs` not found.

- [ ] **Step 3: Write `src/builder/refs.ts`**

```ts
/** Role/stream reference bookkeeping for the cascades in webapp design §4.2:
 * renaming rewrites referencing blocks; deleting is refused while references exist. */
import { childSlots, visitNodes, type BlockNode } from './tree'

function mapNodes(tree: BlockNode[], fn: (node: BlockNode) => BlockNode): BlockNode[] {
  return tree.map((node) => {
    let out = fn(node)
    for (const [slot, children] of childSlots(out)) {
      const mapped = mapNodes(children, fn)
      if (out.kind === 'serial' || out.kind === 'parallel') out = { ...out, children: mapped }
      else if (out.kind === 'loop') out = { ...out, body: mapped }
      else if (out.kind === 'branch') {
        out = slot === 'then' ? { ...out, then: mapped } : { ...out, else: mapped }
      }
    }
    return out
  })
}

export function countRoleRefs(tree: BlockNode[], role: string): number {
  let count = 0
  visitNodes(tree, (node) => {
    if ((node.kind === 'command' || node.kind === 'measure') && node.device === role) count++
  })
  return count
}

export function renameRoleRefs(tree: BlockNode[], from: string, to: string): BlockNode[] {
  return mapNodes(tree, (node) =>
    (node.kind === 'command' || node.kind === 'measure') && node.device === from
      ? { ...node, device: to }
      : node,
  )
}

export function countStreamRefs(tree: BlockNode[], stream: string): number {
  let count = 0
  visitNodes(tree, (node) => {
    if (node.kind === 'measure' && node.into === stream) count++
  })
  return count
}

export function renameStreamRefs(tree: BlockNode[], from: string, to: string): BlockNode[] {
  return mapNodes(tree, (node) =>
    node.kind === 'measure' && node.into === from ? { ...node, into: to } : node,
  )
}

export function collectBindings(tree: BlockNode[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  visitNodes(tree, (node) => {
    if (node.kind === 'operator_input' && node.name && !seen.has(node.name)) {
      seen.add(node.name)
      out.push(node.name)
    }
  })
  return out
}
```

NOTE for the implementer: `mapNodes` as written above rebuilds branch slots one at a
time; verify with the tests that a branch node with BOTH then and else children gets both
slots mapped (the `for` loop reads `childSlots(out)` after each reassignment, so the
second iteration sees the updated node — but `childSlots` for branch returns both slots
computed from the CURRENT `out`, so this works). If tests expose an issue, restructure to
compute all mapped slots first, then rebuild once.

- [ ] **Step 4: Run refs tests to verify they pass**

Run: `cd webapp/frontend && npx vitest run src/builder/refs.test.ts`
Expected: PASS.

- [ ] **Step 5: Write the failing tests for diagnostic paths**

Create `webapp/frontend/src/builder/paths.test.ts`. The path strings below are EXACTLY
what the backend emits (engine `validate.py` + studio `roles.py`) — do not "fix" them:

```ts
import { describe, expect, it } from 'vitest'
import { diagnosticsByUid, mapDiagnostics, resolveDiagnosticPath } from './paths'
import type { BlockNode, BranchNode, LoopNode, SerialNode } from './tree'

const base = { label: null, gapAfter: null, startOffset: null }
const wait = (uid: string): BlockNode => ({ uid, kind: 'wait', duration: '1s', ...base })
const tree: BlockNode[] = [
  {
    uid: 's1', kind: 'serial', ...base,
    children: [
      wait('w1'),
      {
        uid: 'l1', kind: 'loop', mode: 'count', count: 2, until: '', check: 'after',
        pace: null, body: [wait('w2')], ...base,
      } satisfies LoopNode,
      {
        uid: 'b1', kind: 'branch', condition: 'last(od) > 1', then: [wait('w3')],
        else: [wait('w4')], ...base,
      } satisfies BranchNode,
    ],
  } satisfies SerialNode,
]

describe('resolveDiagnosticPath', () => {
  it('resolves root and nested structural paths', () => {
    expect(resolveDiagnosticPath(tree, 'blocks[0]')).toEqual({ uid: 's1', role: null, param: null })
    expect(resolveDiagnosticPath(tree, 'blocks[0].children[1]').uid).toBe('l1')
    expect(resolveDiagnosticPath(tree, 'blocks[0].children[1].body[0]').uid).toBe('w2')
    expect(resolveDiagnosticPath(tree, 'blocks[0].children[2].then[0]').uid).toBe('w3')
    expect(resolveDiagnosticPath(tree, 'blocks[0].children[2].else[0]').uid).toBe('w4')
  })

  it('extracts the param suffix the engine appends to param diagnostics', () => {
    const r = resolveDiagnosticPath(tree, "blocks[0].children[0] param 'volume_ml'")
    expect(r.uid).toBe('w1')
    expect(r.param).toBe('volume_ml')
  })

  it('resolves role paths from the studio doc-level checks', () => {
    expect(resolveDiagnosticPath(tree, "roles['Feed_Pump']")).toEqual({
      uid: null, role: 'Feed_Pump', param: null,
    })
  })

  it('returns nulls for workflow-level and out-of-range paths', () => {
    expect(resolveDiagnosticPath(tree, 'workflow').uid).toBeNull()
    expect(resolveDiagnosticPath(tree, 'blocks[9]').uid).toBeNull()
    expect(resolveDiagnosticPath(tree, 'blocks[0].children[1].then[0]').uid).toBeNull()
    expect(resolveDiagnosticPath(tree, "groups['prep'].body[0]").uid).toBeNull()
  })
})

describe('mapDiagnostics', () => {
  it('attaches uids and groups by block', () => {
    const mapped = mapDiagnostics(tree, [
      { category: 'block', path: 'blocks[0].children[1]', message: 'loop is empty' },
      { category: 'schema', path: 'workflow', message: 'loop until: invalid expression' },
      { category: 'roles', path: "roles['x']", message: 'unknown device type' },
    ])
    expect(mapped[0].uid).toBe('l1')
    expect(mapped[1].uid).toBeNull()
    expect(mapped[2].role).toBe('x')
    const byUid = diagnosticsByUid(mapped)
    expect(byUid.get('l1')).toHaveLength(1)
    expect(byUid.has('')).toBe(false)
  })
})
```

- [ ] **Step 6: Run paths tests to verify they fail, then write `src/builder/paths.ts`**

Run: `cd webapp/frontend && npx vitest run src/builder/paths.test.ts` → FAIL (no module).

```ts
/** Resolve backend diagnostic paths (engine structural grammar + studio doc-level
 * grammar) onto editor tree uids. Unresolvable paths map to uid null and surface in the
 * problems panel only. */
import type { Diagnostic } from '../types/doc'
import { childSlots, type BlockNode } from './tree'

export interface ResolvedPath {
  uid: string | null
  role: string | null
  param: string | null
}

export interface MappedDiagnostic extends Diagnostic {
  uid: string | null
  role: string | null
  param: string | null
}

const NONE: ResolvedPath = { uid: null, role: null, param: null }

export function resolveDiagnosticPath(tree: BlockNode[], path: string): ResolvedPath {
  const roleMatch = /^roles\['(.+)'\]$/.exec(path)
  if (roleMatch) return { uid: null, role: roleMatch[1], param: null }

  const paramMatch = /^(.*?) param '([^']+)'/.exec(path)
  const structural = paramMatch ? paramMatch[1] : path
  const param = paramMatch ? paramMatch[2] : null

  if (!/^blocks\[\d+\](?:\.(?:children|body|then|else)\[\d+\])*$/.test(structural)) {
    return param ? { ...NONE, param } : NONE
  }
  const tokens = structural.match(/(?:^blocks|\.(?:children|body|then|else))\[\d+\]/g) ?? []
  let node: BlockNode | null = null
  for (const token of tokens) {
    const bracket = token.indexOf('[')
    const slot = token.startsWith('.') ? token.slice(1, bracket) : 'blocks'
    const index = Number(token.slice(bracket + 1, -1))
    let list: BlockNode[] | null
    if (slot === 'blocks') {
      list = tree
    } else if (node) {
      list = childSlots(node).find(([name]) => name === slot)?.[1] ?? null
    } else {
      list = null
    }
    if (!list || index < 0 || index >= list.length) return { ...NONE, param }
    node = list[index]
  }
  return { uid: node?.uid ?? null, role: null, param }
}

export function mapDiagnostics(tree: BlockNode[], diags: Diagnostic[]): MappedDiagnostic[] {
  return diags.map((d) => ({ ...d, ...resolveDiagnosticPath(tree, d.path) }))
}

export function diagnosticsByUid(diags: MappedDiagnostic[]): Map<string, MappedDiagnostic[]> {
  const out = new Map<string, MappedDiagnostic[]>()
  for (const d of diags) {
    if (!d.uid) continue
    const list = out.get(d.uid) ?? []
    list.push(d)
    out.set(d.uid, list)
  }
  return out
}
```

- [ ] **Step 7: Run paths tests to verify they pass**

Run: `cd webapp/frontend && npx vitest run src/builder/paths.test.ts`
Expected: PASS.

- [ ] **Step 8: Write the failing tests for expression help, then `src/builder/exprHelp.ts`**

Create `webapp/frontend/src/builder/exprHelp.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { buildExpressionHelp } from './exprHelp'

const expression = { functions: ['count', 'last', 'max', 'mean', 'min'], windows: ['all', 'last_n', 'duration'] }

describe('buildExpressionHelp', () => {
  it('uses the first declared stream in examples', () => {
    const help = buildExpressionHelp(expression, ['temp', 'od'], ['feed_ml'])
    expect(help.streams).toEqual(['temp', 'od'])
    expect(help.bindings).toEqual(['feed_ml'])
    const mean = help.functions.find((f) => f.name === 'mean')
    expect(mean?.example).toBe('mean(temp, last=5) > 0.6')
    expect(help.windowForms.map((w) => w.example)).toEqual([
      'mean(temp)',
      'mean(temp, last=5)',
      'mean(temp, last=30s)',
    ])
  })

  it('falls back to a placeholder stream when none are declared', () => {
    const help = buildExpressionHelp(expression, [], [])
    expect(help.functions.find((f) => f.name === 'count')?.example).toBe('count(od) >= 10')
  })

  it('covers every function and window the catalog reports, even unknown future ones', () => {
    const help = buildExpressionHelp(
      { functions: ['mean', 'stddev'], windows: ['all', 'exotic'] }, ['od'], [],
    )
    expect(help.functions.map((f) => f.name)).toEqual(['mean', 'stddev'])
    expect(help.functions[1].example).toBe('stddev(od)')
    expect(help.windowForms).toHaveLength(2)
  })
})
```

Run to verify FAIL, then create `webapp/frontend/src/builder/exprHelp.ts`:

```ts
/** Expression-help popover content (webapp design §9.3): generated from /api/catalog's
 * expression payload + declared streams + operator-input bindings so it can never drift
 * from the engine grammar. Window forms verified against the engine parser:
 * fn(stream) = all samples, fn(stream, last=5) = last N, fn(stream, last=30s) = duration. */
import type { ExpressionInfo } from '../types/catalog'

export interface ExpressionHelp {
  streams: string[]
  bindings: string[]
  functions: Array<{ name: string; example: string }>
  windowForms: Array<{ label: string; example: string }>
}

export function buildExpressionHelp(
  expression: ExpressionInfo,
  streams: string[],
  bindings: string[],
): ExpressionHelp {
  const s = streams[0] ?? 'od'
  const fnExamples: Record<string, string> = {
    mean: `mean(${s}, last=5) > 0.6`,
    last: `last(${s}) > 0.5`,
    min: `min(${s}, last=30s) < 0.1`,
    max: `max(${s}) < 1.2`,
    count: `count(${s}) >= 10`,
  }
  const windowExamples: Record<string, { label: string; example: string }> = {
    all: { label: 'all samples', example: `mean(${s})` },
    last_n: { label: 'last N samples', example: `mean(${s}, last=5)` },
    duration: { label: 'trailing duration', example: `mean(${s}, last=30s)` },
  }
  return {
    streams,
    bindings,
    functions: expression.functions.map((name) => ({
      name,
      example: fnExamples[name] ?? `${name}(${s})`,
    })),
    windowForms: expression.windows.map(
      (w) => windowExamples[w] ?? { label: w, example: `mean(${s})` },
    ),
  }
}
```

- [ ] **Step 9: Run all four gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add webapp/frontend/src/builder
git commit -m "feat(studio): role/stream cascades, diagnostic path mapping, expression help"
```

---

### Task 4: Document store (zustand + zundo) and catalog store

**Files:**
- Create: `webapp/frontend/src/stores/docStore.ts`
- Create: `webapp/frontend/src/stores/catalogStore.ts`
- Test: `webapp/frontend/src/stores/docStore.test.ts`

**Interfaces:**
- Consumes: `builder/tree.ts` (ops + `BlockNode`, `SlotRef`), `builder/convert.ts`
  (`DocContent`, `treeToDoc`), `builder/refs.ts` (cascades), `builder/paths.ts`
  (`MappedDiagnostic`), `api/studio.ts` (`getCatalog`), `types/catalog.ts`.
- Produces (components in T5-T8 use these EXACT names):
  - `docStore.ts`:
    - `useDocStore` — zustand hook; state = `DocSnapshot` fields (`name`, `description`,
      `roles`, `streams`, `tree`) + `serverId: string | null`, `savedSnapshot: string`,
      `selectedUid: string | null`, `collapsed: Record<string, boolean>`,
      `diagnostics: MappedDiagnostic[]`, `validating: boolean`,
      `validationError: string | null` + actions:
      `setName(name)`, `setDescription(d)`, `insertBlock(node, at)`, `moveBlock(uid, to)`,
      `removeBlock(uid)`, `duplicateBlock(uid)`, `patchBlock(uid, patch)`,
      `addRole(name, type): string | null` (returns error text or null),
      `renameRole(from, to): string | null`, `removeRole(name): string | null`,
      `addStream(name, units): string | null`, `renameStream(from, to): string | null`,
      `removeStream(name): string | null`, `setStreamUnits(name, units)`,
      `select(uid)`, `toggleCollapsed(uid)`, `setDiagnostics(diags)`,
      `setValidating(v)`, `setValidationError(e)`, `markSaved(serverId)`.
    - Module functions: `loadDoc(content: DocContent, serverId: string | null)`,
      `newDoc()`, `undo()`, `redo()`, `useTemporal<T>(selector): T` (reactive hook over
      the zundo store).
    - Selectors: `selectContent(state): DocContent`, `selectDoc(state):
      ExperimentDocJson` (= `treeToDoc(selectContent(state))`), `selectDirty(state):
      boolean`, `snapshotOf(content: DocContent): string`.
    - `ROLE_NAME_RE = /^[a-z][a-z0-9_]*$/` and `STREAM_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/`
      exported for inline form hints.
  - `catalogStore.ts`: `useCatalogStore` with `{catalog: Catalog | null, error: string |
    null, loading: boolean, load(): Promise<void>}` (load is idempotent fetch-once).

**Design notes (implementer must follow):**
- zundo wraps the store: `create<EditorState>()(temporal(stateCreator, options))`.
  `partialize` keeps ONLY the five `DocSnapshot` fields; `equality` is
  `(a, b) => JSON.stringify(a) === JSON.stringify(b)` so selection/diagnostics writes
  never create undo steps; `limit: 100`.
- Every store action is ONE `set()` call → one undo step (this is what makes "renaming a
  role rewrites every referencing block" a single undo step, spec §4.2).
- Dirty is DERIVED (`selectDirty` compares `snapshotOf(selectContent(state))` against
  `savedSnapshot`), never stored — undo back to the saved state correctly reads clean.
- If TypeScript complains about `useDocStore.temporal`, use the zundo-documented cast:
  `(useDocStore as unknown as { temporal: StoreApi<TemporalState<DocSnapshot>> }).temporal`
  in ONE place (a module-level `temporalStore` const) and route everything through it.

- [ ] **Step 1: Write the failing store tests**

Create `webapp/frontend/src/stores/docStore.test.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import { docToTree } from '../builder/convert'
import { newStructureNode } from '../builder/tree'
import {
  loadDoc,
  newDoc,
  redo,
  selectDirty,
  selectDoc,
  undo,
  useDocStore,
} from './docStore'

const store = () => useDocStore.getState()

beforeEach(() => {
  newDoc()
})

describe('docStore', () => {
  it('starts as a clean untitled doc that serializes to a valid empty doc', () => {
    expect(selectDirty(store())).toBe(false)
    const doc = selectDoc(store())
    expect(doc.doc_version).toBe(1)
    expect(doc.workflow.blocks).toEqual([])
  })

  it('tracks dirty through edits and back through undo', () => {
    store().setName('Growth curve')
    expect(selectDirty(store())).toBe(true)
    undo()
    expect(store().name).toBe('Untitled experiment')
    expect(selectDirty(store())).toBe(false)
    redo()
    expect(store().name).toBe('Growth curve')
  })

  it('selection changes do not create undo steps', () => {
    store().insertBlock(newStructureNode('wait'), { parentUid: null, slot: 'blocks', index: 0 })
    const uid = store().tree[0].uid
    store().select(null)
    store().select(uid)
    undo()
    expect(store().tree).toEqual([])
  })

  it('insertBlock selects the inserted block', () => {
    const node = newStructureNode('wait')
    store().insertBlock(node, { parentUid: null, slot: 'blocks', index: 0 })
    expect(store().selectedUid).toBe(node.uid)
  })

  it('removeBlock clears selection when the selected node goes away', () => {
    const node = newStructureNode('serial')
    store().insertBlock(node, { parentUid: null, slot: 'blocks', index: 0 })
    store().removeBlock(node.uid)
    expect(store().selectedUid).toBeNull()
    expect(store().tree).toEqual([])
  })

  it('role lifecycle: add, rename cascades in one undo step, delete refused while referenced', () => {
    expect(store().addRole('feed_pump', 'pump')).toBeNull()
    expect(store().addRole('feed_pump', 'pump')).toMatch(/exists/)
    expect(store().addRole('Feed', 'pump')).toMatch(/must match/)
    store().insertBlock(
      { uid: 'c1', kind: 'command', device: 'feed_pump', verb: 'stop', params: {},
        label: null, gapAfter: null, startOffset: null },
      { parentUid: null, slot: 'blocks', index: 0 },
    )
    expect(store().removeRole('feed_pump')).toMatch(/1 block/)
    expect(store().renameRole('feed_pump', 'acid_pump')).toBeNull()
    expect(store().roles).toHaveProperty('acid_pump')
    expect(store().roles).not.toHaveProperty('feed_pump')
    expect(selectDoc(store()).workflow.blocks[0].command?.device).toBe('acid_pump')
    undo() // single step: role map + block rewrite together
    expect(store().roles).toHaveProperty('feed_pump')
    expect(selectDoc(store()).workflow.blocks[0].command?.device).toBe('feed_pump')
    store().removeBlock('c1')
    expect(store().removeRole('feed_pump')).toBeNull()
  })

  it('stream lifecycle mirrors roles: rename cascades measure.into, delete refused while referenced', () => {
    expect(store().addStream('od', 'AU')).toBeNull()
    expect(store().addStream('od', null)).toMatch(/exists/)
    store().insertBlock(
      { uid: 'm1', kind: 'measure', device: 'od_meter', verb: 'measure', into: 'od',
        params: {}, label: null, gapAfter: null, startOffset: null },
      { parentUid: null, slot: 'blocks', index: 0 },
    )
    expect(store().removeStream('od')).toMatch(/1 block/)
    expect(store().renameStream('od', 'od600')).toBeNull()
    expect(selectDoc(store()).workflow.blocks[0].measure?.into).toBe('od600')
    expect(selectDoc(store()).workflow.streams).toHaveProperty('od600')
    store().setStreamUnits('od600', 'mAU')
    expect(store().streams.od600.units).toBe('mAU')
    store().removeBlock('m1')
    expect(store().removeStream('od600')).toBeNull()
  })

  it('loadDoc replaces state, clears history, and reads clean; markSaved clears dirty', () => {
    store().setName('scratch')
    loadDoc(
      docToTree({
        doc_version: 1, name: 'Loaded', description: null,
        roles: { p: { type: 'pump' } },
        workflow: { schema_version: 1, blocks: [] },
      }),
      'id-123',
    )
    expect(store().name).toBe('Loaded')
    expect(store().serverId).toBe('id-123')
    expect(selectDirty(store())).toBe(false)
    undo() // history cleared — nothing to undo
    expect(store().name).toBe('Loaded')
    store().setName('Loaded v2')
    expect(selectDirty(store())).toBe(true)
    store().markSaved('id-123')
    expect(selectDirty(store())).toBe(false)
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webapp/frontend && npx vitest run src/stores/docStore.test.ts`
Expected: FAIL — module `./docStore` not found.

- [ ] **Step 3: Write `src/stores/docStore.ts`**

```ts
/** Single document store for the builder. The temporal (zundo) wrapper snapshots ONLY
 * the document fields, so undo/redo never touches selection, diagnostics, or save
 * bookkeeping. Dirty state is derived by comparing against the last saved snapshot. */
import { create } from 'zustand'
import { useStore, type StoreApi } from 'zustand'
import { temporal, type TemporalState } from 'zundo'
import type { ExperimentDocJson } from '../types/doc'
import type { MappedDiagnostic } from '../builder/paths'
import { treeToDoc, type DocContent } from '../builder/convert'
import {
  containsUid,
  duplicateNode,
  findNode,
  insertNode,
  moveNode,
  removeNode,
  updateNode,
  type BlockNode,
  type SlotRef,
} from '../builder/tree'
import {
  countRoleRefs,
  countStreamRefs,
  renameRoleRefs,
  renameStreamRefs,
} from '../builder/refs'

export const ROLE_NAME_RE = /^[a-z][a-z0-9_]*$/
export const STREAM_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/

export interface DocSnapshot {
  name: string
  description: string | null
  roles: Record<string, { type: string }>
  streams: Record<string, { units: string | null }>
  tree: BlockNode[]
}

export interface EditorState extends DocSnapshot {
  serverId: string | null
  savedSnapshot: string
  selectedUid: string | null
  collapsed: Record<string, boolean>
  diagnostics: MappedDiagnostic[]
  validating: boolean
  validationError: string | null
  setName: (name: string) => void
  setDescription: (description: string | null) => void
  insertBlock: (node: BlockNode, at: SlotRef) => void
  moveBlock: (uid: string, to: SlotRef) => void
  removeBlock: (uid: string) => void
  duplicateBlock: (uid: string) => void
  patchBlock: (uid: string, patch: object) => void
  addRole: (name: string, type: string) => string | null
  renameRole: (from: string, to: string) => string | null
  removeRole: (name: string) => string | null
  addStream: (name: string, units: string | null) => string | null
  renameStream: (from: string, to: string) => string | null
  removeStream: (name: string) => string | null
  setStreamUnits: (name: string, units: string | null) => void
  select: (uid: string | null) => void
  toggleCollapsed: (uid: string) => void
  setDiagnostics: (diags: MappedDiagnostic[]) => void
  setValidating: (v: boolean) => void
  setValidationError: (e: string | null) => void
  markSaved: (serverId: string) => void
}

export const selectContent = (s: DocSnapshot): DocContent => ({
  name: s.name,
  description: s.description,
  roles: s.roles,
  streams: s.streams,
  tree: s.tree,
})

export const snapshotOf = (content: DocContent): string =>
  JSON.stringify({
    name: content.name,
    description: content.description,
    roles: content.roles,
    streams: content.streams,
    tree: content.tree,
  })

export const selectDoc = (s: DocSnapshot): ExperimentDocJson => treeToDoc(selectContent(s))

export const selectDirty = (s: EditorState): boolean =>
  snapshotOf(selectContent(s)) !== s.savedSnapshot

const emptyContent = (): DocContent => ({
  name: 'Untitled experiment',
  description: null,
  roles: {},
  streams: {},
  tree: [],
})

const renameKey = <V>(rec: Record<string, V>, from: string, to: string): Record<string, V> =>
  Object.fromEntries(Object.entries(rec).map(([k, v]) => [k === from ? to : k, v]))

const removeKey = <V>(rec: Record<string, V>, key: string): Record<string, V> =>
  Object.fromEntries(Object.entries(rec).filter(([k]) => k !== key))

export const useDocStore = create<EditorState>()(
  temporal(
    (set, get) => ({
      ...emptyContent(),
      serverId: null,
      savedSnapshot: snapshotOf(emptyContent()),
      selectedUid: null,
      collapsed: {},
      diagnostics: [],
      validating: false,
      validationError: null,

      setName: (name) => set({ name }),
      setDescription: (description) => set({ description }),

      insertBlock: (node, at) =>
        set((s) => ({ tree: insertNode(s.tree, node, at), selectedUid: node.uid })),

      moveBlock: (uid, to) => set((s) => ({ tree: moveNode(s.tree, uid, to) })),

      removeBlock: (uid) =>
        set((s) => {
          const [tree] = removeNode(s.tree, uid)
          const removed = findNode(s.tree, uid)
          const selectionGone =
            s.selectedUid !== null && removed !== null && containsUid(removed, s.selectedUid)
          return { tree, selectedUid: selectionGone ? null : s.selectedUid }
        }),

      duplicateBlock: (uid) =>
        set((s) => {
          const [tree, cloneUid] = duplicateNode(s.tree, uid)
          return { tree, selectedUid: cloneUid ?? s.selectedUid }
        }),

      patchBlock: (uid, patch) => set((s) => ({ tree: updateNode(s.tree, uid, patch) })),

      addRole: (name, type) => {
        if (!ROLE_NAME_RE.test(name)) return `role name must match [a-z][a-z0-9_]*`
        if (name in get().roles) return `role '${name}' already exists`
        set((s) => ({ roles: { ...s.roles, [name]: { type } } }))
        return null
      },

      renameRole: (from, to) => {
        if (from === to) return null
        if (!ROLE_NAME_RE.test(to)) return `role name must match [a-z][a-z0-9_]*`
        if (to in get().roles) return `role '${to}' already exists`
        set((s) => ({
          roles: renameKey(s.roles, from, to),
          tree: renameRoleRefs(s.tree, from, to),
        }))
        return null
      },

      removeRole: (name) => {
        const refs = countRoleRefs(get().tree, name)
        if (refs > 0) return `role '${name}' is used by ${refs} block${refs === 1 ? '' : 's'}`
        set((s) => ({ roles: removeKey(s.roles, name) }))
        return null
      },

      addStream: (name, units) => {
        if (!STREAM_NAME_RE.test(name)) return `stream name must be an identifier`
        if (name in get().streams) return `stream '${name}' already exists`
        set((s) => ({ streams: { ...s.streams, [name]: { units } } }))
        return null
      },

      renameStream: (from, to) => {
        if (from === to) return null
        if (!STREAM_NAME_RE.test(to)) return `stream name must be an identifier`
        if (to in get().streams) return `stream '${to}' already exists`
        set((s) => ({
          streams: renameKey(s.streams, from, to),
          tree: renameStreamRefs(s.tree, from, to),
        }))
        return null
      },

      removeStream: (name) => {
        const refs = countStreamRefs(get().tree, name)
        if (refs > 0) return `stream '${name}' is used by ${refs} block${refs === 1 ? '' : 's'}`
        set((s) => ({ streams: removeKey(s.streams, name) }))
        return null
      },

      setStreamUnits: (name, units) =>
        set((s) => ({
          streams: name in s.streams ? { ...s.streams, [name]: { units } } : s.streams,
        })),

      select: (uid) => set({ selectedUid: uid }),
      toggleCollapsed: (uid) =>
        set((s) => ({ collapsed: { ...s.collapsed, [uid]: !s.collapsed[uid] } })),
      setDiagnostics: (diagnostics) => set({ diagnostics }),
      setValidating: (validating) => set({ validating }),
      setValidationError: (validationError) => set({ validationError }),
      markSaved: (serverId) =>
        set((s) => ({ serverId, savedSnapshot: snapshotOf(selectContent(s)) })),
    }),
    {
      partialize: (state): DocSnapshot => ({
        name: state.name,
        description: state.description,
        roles: state.roles,
        streams: state.streams,
        tree: state.tree,
      }),
      equality: (a, b) => JSON.stringify(a) === JSON.stringify(b),
      limit: 100,
    },
  ),
)

const temporalStore = (
  useDocStore as unknown as { temporal: StoreApi<TemporalState<DocSnapshot>> }
).temporal

export const undo = (): void => temporalStore.getState().undo()
export const redo = (): void => temporalStore.getState().redo()

export function useTemporal<T>(selector: (s: TemporalState<DocSnapshot>) => T): T {
  return useStore(temporalStore, selector)
}

export function loadDoc(content: DocContent, serverId: string | null): void {
  useDocStore.setState({
    ...content,
    serverId,
    savedSnapshot: snapshotOf(content),
    selectedUid: null,
    collapsed: {},
    diagnostics: [],
    validating: false,
    validationError: null,
  })
  temporalStore.getState().clear()
}

export function newDoc(): void {
  loadDoc(emptyContent(), null)
}
```

- [ ] **Step 4: Run store tests**

Run: `cd webapp/frontend && npx vitest run src/stores/docStore.test.ts`
Expected: PASS. If `useDocStore.temporal` fails to typecheck without the cast, the cast
shown is the sanctioned workaround; do not disable type checking.

- [ ] **Step 5: Write `src/stores/catalogStore.ts`**

```ts
/** Fetch-once cache of GET /api/catalog. The palette and inspector generate themselves
 * from this payload (webapp design §4.4) — there is no other source of verb truth. */
import { create } from 'zustand'
import { getCatalog } from '../api/studio'
import type { Catalog } from '../types/catalog'

interface CatalogState {
  catalog: Catalog | null
  error: string | null
  loading: boolean
  load: () => Promise<void>
}

export const useCatalogStore = create<CatalogState>()((set, get) => ({
  catalog: null,
  error: null,
  loading: false,
  load: async () => {
    if (get().catalog !== null || get().loading) return
    set({ loading: true, error: null })
    try {
      set({ catalog: await getCatalog(), loading: false })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e), loading: false })
    }
  },
}))
```

- [ ] **Step 6: Run all four gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add webapp/frontend/src/stores
git commit -m "feat(studio): document store with zundo undo/redo and catalog store"
```

---

### Task 5: Drag payload types, Palette, Roles panel, Streams panel

**Files:**
- Create: `webapp/frontend/src/builder/dnd.ts`
- Create: `webapp/frontend/src/builder/Palette.tsx`
- Create: `webapp/frontend/src/builder/RolesPanel.tsx`
- Create: `webapp/frontend/src/builder/StreamsPanel.tsx`
- Test: `webapp/frontend/src/builder/dnd.test.ts`

**Interfaces:**
- Consumes: `stores/docStore.ts` (`useDocStore`, `ROLE_NAME_RE`), `stores/catalogStore.ts`,
  `builder/tree.ts` (`StructureKind`), `types/catalog.ts` (`VerbSpec`).
- Produces:
  - `dnd.ts`: `DragPayload` =
    `{ source: 'palette-structure'; kind: StructureKind }`
    | `{ source: 'palette-verb'; role: string; verb: string; verbKind: 'command' | 'measure' }`
    | `{ source: 'canvas'; uid: string }`;
    `slotDroppableId(at: SlotRef): string` (format `slot|<parentUid or ~root>|<slot>|<index>`)
    and `parseSlotDroppableId(id: string): SlotRef | null`;
    `blockDraggableId(uid: string): string` (format `block|<uid>`).
  - `Palette.tsx`: `export function Palette()` — no props; reads stores directly. Renders
    structure chips, one section per role with verb chips, "add role" inline form, and
    embeds `<RolesPanel/>` + `<StreamsPanel/>` as collapsible sections.
  - `RolesPanel.tsx`: `export function RolesPanel()`; `StreamsPanel.tsx`:
    `export function StreamsPanel()`.
- These components mount ONLY inside BuilderTab's `<DndContext>` (Task 6); `useDraggable`
  outside a DndContext is a runtime error, so nothing may render Palette before Task 6
  wires it (App.tsx still shows the placeholder — that is fine).

**UX contract (spec §9.3):** palette = structure section (Serial, Parallel, Loop, Branch,
Wait, OperatorInput) + one section per defined role listing that role's device-type verbs
as draggable chips (command ▸ / measure ◉ icons) + "add role" (name + type → immediately
extends the palette). Roles panel: rename (cascades), delete refused with the count.
Streams panel: add/rename/delete streams + units field, nothing else (S5).

- [ ] **Step 1: Write `src/builder/dnd.ts` with tests first**

Create `webapp/frontend/src/builder/dnd.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { blockDraggableId, parseSlotDroppableId, slotDroppableId } from './dnd'

describe('slot droppable ids', () => {
  it('round-trips root and container slots', () => {
    const root = { parentUid: null, slot: 'blocks', index: 3 }
    expect(parseSlotDroppableId(slotDroppableId(root))).toEqual(root)
    const nested = { parentUid: 'abc-123', slot: 'children', index: 0 }
    expect(parseSlotDroppableId(slotDroppableId(nested))).toEqual(nested)
  })

  it('rejects non-slot ids', () => {
    expect(parseSlotDroppableId(blockDraggableId('abc'))).toBeNull()
    expect(parseSlotDroppableId('junk')).toBeNull()
  })
})
```

Run `npx vitest run src/builder/dnd.test.ts` → FAIL, then create `src/builder/dnd.ts`:

```ts
/** Drag-and-drop wire types. Draggables carry DragPayload in dnd-kit's data; droppables
 * are insertion slots encoded in the droppable id so onDragEnd needs no lookups. */
import type { SlotRef, StructureKind } from './tree'

export type DragPayload =
  | { source: 'palette-structure'; kind: StructureKind }
  | { source: 'palette-verb'; role: string; verb: string; verbKind: 'command' | 'measure' }
  | { source: 'canvas'; uid: string }

const ROOT = '~root'

export const slotDroppableId = (at: SlotRef): string =>
  `slot|${at.parentUid ?? ROOT}|${at.slot}|${at.index}`

export function parseSlotDroppableId(id: string): SlotRef | null {
  const parts = id.split('|')
  if (parts.length !== 4 || parts[0] !== 'slot') return null
  const index = Number(parts[3])
  if (!Number.isInteger(index) || index < 0) return null
  return { parentUid: parts[1] === ROOT ? null : parts[1], slot: parts[2], index }
}

export const blockDraggableId = (uid: string): string => `block|${uid}`
```

Run the dnd tests again → PASS.

- [ ] **Step 2: Create `src/builder/RolesPanel.tsx`**

```tsx
import { useState } from 'react'
import { useDocStore } from '../stores/docStore'

/** Inline rename/delete list for roles (spec §4.2): rename cascades through every
 * referencing block in one undo step; delete is refused with a reference count. */
export function RolesPanel() {
  const roles = useDocStore((s) => s.roles)
  const renameRole = useDocStore((s) => s.renameRole)
  const removeRole = useDocStore((s) => s.removeRole)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  const commitRename = (from: string) => {
    const err = draft && draft !== from ? renameRole(from, draft) : null
    setError(err)
    if (!err) setEditing(null)
  }

  const entries = Object.entries(roles)
  if (entries.length === 0) {
    return <p className="px-1 text-xs text-slate-400">No roles yet — add one above.</p>
  }
  return (
    <ul className="space-y-1">
      {entries.map(([name, role]) => (
        <li key={name} className="flex items-center gap-1 text-sm">
          {editing === name ? (
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={() => commitRename(name)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitRename(name)
                if (e.key === 'Escape') setEditing(null)
              }}
              className="w-28 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
            />
          ) : (
            <button
              title="Rename role"
              onClick={() => {
                setEditing(name)
                setDraft(name)
                setError(null)
              }}
              className="rounded px-1 font-mono text-xs hover:bg-slate-200"
            >
              {name}
            </button>
          )}
          <span className="text-xs text-slate-400">{role.type}</span>
          <button
            title="Delete role"
            onClick={() => setError(removeRole(name))}
            className="ml-auto rounded px-1 text-xs text-slate-400 hover:bg-red-50 hover:text-red-600"
          >
            ✕
          </button>
        </li>
      ))}
      {error && <li className="text-xs text-red-600">{error}</li>}
    </ul>
  )
}
```

- [ ] **Step 3: Create `src/builder/StreamsPanel.tsx`**

```tsx
import { useState } from 'react'
import { useDocStore } from '../stores/docStore'

/** Streams are name + units only (settled decision S5) — persistence is forced by the
 * backend on every run, so the builder exposes no knobs for it. */
export function StreamsPanel() {
  const streams = useDocStore((s) => s.streams)
  const addStream = useDocStore((s) => s.addStream)
  const renameStream = useDocStore((s) => s.renameStream)
  const removeStream = useDocStore((s) => s.removeStream)
  const setStreamUnits = useDocStore((s) => s.setStreamUnits)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [newName, setNewName] = useState('')
  const [newUnits, setNewUnits] = useState('')

  const commitRename = (from: string) => {
    const err = draft && draft !== from ? renameStream(from, draft) : null
    setError(err)
    if (!err) setEditing(null)
  }

  const add = () => {
    if (!newName) return
    const err = addStream(newName, newUnits || null)
    setError(err)
    if (!err) {
      setNewName('')
      setNewUnits('')
    }
  }

  return (
    <div className="space-y-1">
      <ul className="space-y-1">
        {Object.entries(streams).map(([name, s]) => (
          <li key={name} className="flex items-center gap-1 text-sm">
            {editing === name ? (
              <input
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => commitRename(name)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitRename(name)
                  if (e.key === 'Escape') setEditing(null)
                }}
                className="w-24 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
              />
            ) : (
              <button
                title="Rename stream"
                onClick={() => {
                  setEditing(name)
                  setDraft(name)
                  setError(null)
                }}
                className="rounded px-1 font-mono text-xs hover:bg-slate-200"
              >
                {name}
              </button>
            )}
            <input
              value={s.units ?? ''}
              placeholder="units"
              onChange={(e) => setStreamUnits(name, e.target.value || null)}
              className="w-14 rounded border border-slate-200 px-1 py-0.5 text-xs"
            />
            <button
              title="Delete stream"
              onClick={() => setError(removeStream(name))}
              className="ml-auto rounded px-1 text-xs text-slate-400 hover:bg-red-50 hover:text-red-600"
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
      <div className="flex items-center gap-1">
        <input
          value={newName}
          placeholder="stream name"
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          className="w-24 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
        />
        <input
          value={newUnits}
          placeholder="units"
          onChange={(e) => setNewUnits(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          className="w-14 rounded border border-slate-300 px-1 py-0.5 text-xs"
        />
        <button onClick={add} className="rounded bg-slate-200 px-2 py-0.5 text-xs hover:bg-slate-300">
          Add
        </button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
```

- [ ] **Step 4: Create `src/builder/Palette.tsx`**

```tsx
import { useState, type ReactNode } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { useCatalogStore } from '../stores/catalogStore'
import { useDocStore } from '../stores/docStore'
import type { StructureKind } from './tree'
import type { DragPayload } from './dnd'
import { RolesPanel } from './RolesPanel'
import { StreamsPanel } from './StreamsPanel'

const STRUCTURE: Array<{ kind: StructureKind; title: string; icon: string }> = [
  { kind: 'serial', title: 'Serial', icon: '≡' },
  { kind: 'parallel', title: 'Parallel', icon: '∥' },
  { kind: 'loop', title: 'Loop', icon: '↻' },
  { kind: 'branch', title: 'Branch', icon: '⑂' },
  { kind: 'wait', title: 'Wait', icon: '⏱' },
  { kind: 'operator_input', title: 'Operator input', icon: '⌨' },
]

function Chip(props: { id: string; payload: DragPayload; children: ReactNode }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: props.id,
    data: props.payload,
  })
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={
        'cursor-grab select-none rounded border border-slate-300 bg-white px-2 py-1 text-xs shadow-sm ' +
        (isDragging ? 'opacity-40' : 'hover:border-slate-400')
      }
    >
      {props.children}
    </div>
  )
}

function Section(props: { title: string; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(props.defaultOpen ?? true)
  return (
    <section className="border-b border-slate-200 pb-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-1 py-1 text-xs font-semibold uppercase tracking-wide text-slate-500"
      >
        {props.title}
        <span>{open ? '−' : '+'}</span>
      </button>
      {open && <div className="px-1">{props.children}</div>}
    </section>
  )
}

function AddRoleForm() {
  const catalog = useCatalogStore((s) => s.catalog)
  const addRole = useDocStore((s) => s.addRole)
  const [name, setName] = useState('')
  const [type, setType] = useState('')
  const [error, setError] = useState<string | null>(null)
  const types = Object.keys(catalog?.device_types ?? {})
  const add = () => {
    if (!name || !type) return
    const err = addRole(name, type)
    setError(err)
    if (!err) setName('')
  }
  return (
    <div className="mt-2 space-y-1">
      <div className="flex items-center gap-1">
        <input
          value={name}
          placeholder="role name"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          className="w-24 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
        />
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="rounded border border-slate-300 px-1 py-0.5 text-xs"
        >
          <option value="">type…</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <button onClick={add} className="rounded bg-slate-200 px-2 py-0.5 text-xs hover:bg-slate-300">
          Add
        </button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}

export function Palette() {
  const catalog = useCatalogStore((s) => s.catalog)
  const catalogError = useCatalogStore((s) => s.error)
  const roles = useDocStore((s) => s.roles)

  return (
    <aside className="w-64 shrink-0 space-y-2 overflow-y-auto border-r border-slate-200 bg-slate-50 p-2">
      <Section title="Structure">
        <div className="flex flex-wrap gap-1">
          {STRUCTURE.map((s) => (
            <Chip
              key={s.kind}
              id={`palette-structure-${s.kind}`}
              payload={{ source: 'palette-structure', kind: s.kind }}
            >
              <span className="mr-1 opacity-60">{s.icon}</span>
              {s.title}
            </Chip>
          ))}
        </div>
      </Section>
      <Section title="Roles">
        {catalogError && <p className="text-xs text-red-600">catalog unavailable: {catalogError}</p>}
        {Object.entries(roles).map(([role, def]) => {
          const verbs = catalog?.device_types[def.type]
          return (
            <div key={role} className="mb-2">
              <p className="py-1 font-mono text-xs text-slate-600">
                {role} <span className="text-slate-400">· {def.type}</span>
              </p>
              {verbs ? (
                <div className="flex flex-wrap gap-1">
                  {Object.entries(verbs).map(([verb, spec]) => (
                    <Chip
                      key={verb}
                      id={`palette-verb-${role}-${verb}`}
                      payload={{
                        source: 'palette-verb',
                        role,
                        verb,
                        verbKind: spec.kind,
                      }}
                    >
                      <span className="mr-1 opacity-60">{spec.kind === 'measure' ? '◉' : '▸'}</span>
                      {verb}
                    </Chip>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-amber-600">unknown device type '{def.type}'</p>
              )}
            </div>
          )
        })}
        <AddRoleForm />
      </Section>
      <Section title="Manage roles" defaultOpen={false}>
        <RolesPanel />
      </Section>
      <Section title="Streams" defaultOpen={false}>
        <StreamsPanel />
      </Section>
    </aside>
  )
}
```

- [ ] **Step 5: Run all four gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build`
Expected: all pass (components are typechecked/linted/built; behavior is exercised in the
Task 10 walkthrough).

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/builder
git commit -m "feat(studio): palette with role-driven verb chips, roles and streams panels"
```

---

### Task 6: Canvas, drop slots, block summaries, BuilderTab assembly

**Files:**
- Create: `webapp/frontend/src/builder/summary.ts`
- Create: `webapp/frontend/src/builder/DropSlot.tsx`
- Create: `webapp/frontend/src/builder/Canvas.tsx`
- Create: `webapp/frontend/src/builder/BuilderTab.tsx`
- Test: `webapp/frontend/src/builder/summary.test.ts`

**Interfaces:**
- Consumes: everything from T2-T5 (`tree.ts` ops incl. `canDrop`/`newStructureNode`/
  `newVerbNode`/`findNode`, `dnd.ts` ids + `DragPayload`, `paths.ts`
  `diagnosticsByUid`, `docStore`, `catalogStore`, `Palette`).
- Produces: `summary.ts` (`blockSummary(node: BlockNode): string`,
  `formatParams(params, max?): string`), `DropSlot.tsx`
  (`DropSlot({at, horizontal, hint})`), `Canvas.tsx` (`Canvas()`), `BuilderTab.tsx`
  (`BuilderTab()` — Task 7 will replace the inspector placeholder `<aside
  data-slot="inspector">…` with `<Inspector/>`, Task 8 the toolbar placeholder `<div
  data-slot="toolbar">` with `<Toolbar/>` and mount `<ProblemsPanel/>` after the pane
  row).

**Canvas UX contract (spec §9.3):** serial = vertical stack; parallel = N side-by-side
lanes with `+ lane` appender, empty lanes show a drop hint and a remove control;
loop/branch = framed containers (branch with then/else lanes, `+ add else` when absent);
leaf blocks are cards (icon in summary text, role · verb, key params inline); click
selects; Delete key removes; per-card duplicate/delete controls; containers collapse;
undo/redo on Cmd/Ctrl+Z / Shift+Cmd+Z / Ctrl+Y; diagnostic badges show per-block error
counts with messages in the tooltip.

- [ ] **Step 1: Write the failing summary tests**

Create `webapp/frontend/src/builder/summary.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { blockSummary, formatParams } from './summary'
import type { BlockNode } from './tree'

const base = { label: null, gapAfter: null, startOffset: null }

describe('formatParams', () => {
  it('shows up to two params and an ellipsis beyond', () => {
    expect(formatParams({})).toBe('')
    expect(formatParams({ volume_ml: 5 })).toBe('volume_ml=5')
    expect(formatParams({ a: 1, b: 'cw', c: true })).toBe('a=1, b=cw, …')
  })
})

describe('blockSummary', () => {
  it('describes each block kind', () => {
    const cases: Array<[BlockNode, string]> = [
      [{ uid: 'x', kind: 'command', device: 'feed_pump', verb: 'dispense', params: { volume_ml: 5 }, ...base },
        '▸ feed_pump · dispense (volume_ml=5)'],
      [{ uid: 'x', kind: 'measure', device: 'od_meter', verb: 'measure', into: 'od', params: {}, ...base },
        '◉ od_meter · measure → od'],
      [{ uid: 'x', kind: 'measure', device: 'od_meter', verb: 'measure', into: '', params: {}, ...base },
        '◉ od_meter · measure → ?'],
      [{ uid: 'x', kind: 'wait', duration: '30s', ...base }, '⏱ wait 30s'],
      [{ uid: 'x', kind: 'operator_input', name: 'feed_ml', inputType: 'float', prompt: null, min: null, max: null, choices: null, ...base },
        '⌨ input feed_ml (float)'],
      [{ uid: 'x', kind: 'serial', children: [], ...base }, '≡ Serial · 0'],
      [{ uid: 'x', kind: 'parallel', children: [], ...base }, '∥ Parallel · 0 lanes'],
      [{ uid: 'x', kind: 'loop', mode: 'count', count: 3, until: '', check: 'after', pace: null, body: [], ...base },
        '↻ Loop ×3'],
      [{ uid: 'x', kind: 'loop', mode: 'until', count: 2, until: 'mean(od, last=3) > 0.6', check: 'after', pace: null, body: [], ...base },
        '↻ Loop until mean(od, last=3) > 0.6'],
      [{ uid: 'x', kind: 'branch', condition: '', then: [], else: null, ...base }, '⑂ If …'],
    ]
    for (const [node, expected] of cases) expect(blockSummary(node)).toBe(expected)
  })
})
```

- [ ] **Step 2: Run to verify failure, then write `src/builder/summary.ts`**

```ts
/** One-line captions for canvas cards and the drag overlay. Pure so it is testable and
 * reusable by the record viewer's read-only canvas in W5. */
import type { ParamValue } from '../types/doc'
import type { BlockNode } from './tree'

export function formatParams(params: Record<string, ParamValue>, max = 2): string {
  const entries = Object.entries(params)
  const shown = entries.slice(0, max).map(([k, v]) => `${k}=${String(v)}`)
  if (entries.length > max) shown.push('…')
  return shown.join(', ')
}

export function blockSummary(node: BlockNode): string {
  switch (node.kind) {
    case 'command': {
      const params = formatParams(node.params)
      return `▸ ${node.device} · ${node.verb}${params ? ` (${params})` : ''}`
    }
    case 'measure':
      return `◉ ${node.device} · ${node.verb} → ${node.into || '?'}`
    case 'wait':
      return `⏱ wait ${node.duration}`
    case 'operator_input':
      return `⌨ input ${node.name} (${node.inputType})`
    case 'serial':
      return `≡ Serial · ${node.children.length}`
    case 'parallel':
      return `∥ Parallel · ${node.children.length} lanes`
    case 'loop':
      return node.mode === 'count' ? `↻ Loop ×${node.count}` : `↻ Loop until ${node.until || '…'}`
    case 'branch':
      return `⑂ If ${node.condition || '…'}`
  }
}
```

Run: `npx vitest run src/builder/summary.test.ts` → PASS.

- [ ] **Step 3: Create `src/builder/DropSlot.tsx`**

```tsx
import { useDroppable } from '@dnd-kit/core'
import { useDocStore } from '../stores/docStore'
import { canDrop, type SlotRef } from './tree'
import { slotDroppableId, type DragPayload } from './dnd'

/** Insertion bar between blocks (or a dashed hint box for empty lists). Highlights only
 * when the active drag may legally drop here — a container can never enter its own
 * subtree. */
export function DropSlot(props: { at: SlotRef; horizontal: boolean; hint: boolean }) {
  const { at, horizontal, hint } = props
  const { setNodeRef, isOver, active } = useDroppable({ id: slotDroppableId(at) })
  const tree = useDocStore((s) => s.tree)
  const payload = (active?.data.current ?? null) as DragPayload | null
  const legal =
    payload !== null && (payload.source !== 'canvas' || canDrop(tree, payload.uid, at))
  const highlight = isOver && legal
  if (hint) {
    return (
      <div
        ref={setNodeRef}
        className={
          'm-1 flex-1 rounded border border-dashed px-2 py-3 text-center text-xs ' +
          (highlight
            ? 'border-blue-400 bg-blue-50 text-blue-500'
            : 'border-slate-200 text-slate-300')
        }
      >
        drop here
      </div>
    )
  }
  return (
    <div
      ref={setNodeRef}
      className={
        (horizontal ? 'mx-0.5 w-2 self-stretch ' : 'my-0.5 h-2 ') +
        'shrink-0 rounded transition-colors ' +
        (highlight ? 'bg-blue-400' : isOver ? 'bg-red-200' : 'bg-transparent')
      }
    />
  )
}
```

- [ ] **Step 4: Create `src/builder/Canvas.tsx`**

```tsx
import { Fragment, createContext, useContext, useMemo } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { useDocStore } from '../stores/docStore'
import { diagnosticsByUid, type MappedDiagnostic } from './paths'
import { blockDraggableId, type DragPayload } from './dnd'
import { DropSlot } from './DropSlot'
import { blockSummary } from './summary'
import { newStructureNode, type BlockNode, type BranchNode, type ParallelNode } from './tree'

const DiagContext = createContext<Map<string, MappedDiagnostic[]>>(new Map())

export function Canvas() {
  const tree = useDocStore((s) => s.tree)
  const select = useDocStore((s) => s.select)
  const diagnostics = useDocStore((s) => s.diagnostics)
  const byUid = useMemo(() => diagnosticsByUid(diagnostics), [diagnostics])
  return (
    <DiagContext.Provider value={byUid}>
      <div
        className="min-w-0 flex-1 overflow-auto bg-slate-100 p-4"
        onClick={() => select(null)}
      >
        {tree.length === 0 && (
          <p className="mb-2 rounded border border-dashed border-slate-300 p-8 text-center text-sm text-slate-400">
            Drag blocks from the palette to start building.
          </p>
        )}
        <BlockList parentUid={null} slot="blocks" items={tree} />
      </div>
    </DiagContext.Provider>
  )
}

function BlockList(props: { parentUid: string | null; slot: string; items: BlockNode[] }) {
  const { parentUid, slot, items } = props
  return (
    <div className="flex flex-col">
      <DropSlot at={{ parentUid, slot, index: 0 }} horizontal={false} hint={items.length === 0} />
      {items.map((node, i) => (
        <Fragment key={node.uid}>
          <BlockView node={node} />
          <DropSlot at={{ parentUid, slot, index: i + 1 }} horizontal={false} hint={false} />
        </Fragment>
      ))}
    </div>
  )
}

function BlockView({ node }: { node: BlockNode }) {
  const select = useDocStore((s) => s.select)
  const selected = useDocStore((s) => s.selectedUid === node.uid)
  const collapsed = useDocStore((s) => Boolean(s.collapsed[node.uid]))
  const toggleCollapsed = useDocStore((s) => s.toggleCollapsed)
  const duplicateBlock = useDocStore((s) => s.duplicateBlock)
  const removeBlock = useDocStore((s) => s.removeBlock)
  const diags = useContext(DiagContext).get(node.uid) ?? []
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: blockDraggableId(node.uid),
    data: { source: 'canvas', uid: node.uid } satisfies DragPayload,
  })
  const isContainer =
    node.kind === 'serial' || node.kind === 'parallel' || node.kind === 'loop' || node.kind === 'branch'
  return (
    <div
      id={`block-${node.uid}`}
      ref={setNodeRef}
      onClick={(e) => {
        e.stopPropagation()
        select(node.uid)
      }}
      className={
        'rounded border bg-white text-sm shadow-sm ' +
        (selected ? 'border-blue-500 ring-1 ring-blue-300 ' : 'border-slate-300 ') +
        (isDragging ? 'opacity-40' : '')
      }
    >
      <div {...listeners} {...attributes} className="flex cursor-grab items-center gap-1 px-2 py-1">
        {isContainer && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              toggleCollapsed(node.uid)
            }}
            className="text-xs text-slate-400 hover:text-slate-700"
          >
            {collapsed ? '▸' : '▾'}
          </button>
        )}
        <span className="truncate">{blockSummary(node)}</span>
        {node.label && <span className="truncate text-xs italic text-slate-400">“{node.label}”</span>}
        <span className="ml-auto flex items-center gap-1">
          {diags.length > 0 && (
            <span
              title={diags.map((d) => d.message).join('\n')}
              className="rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white"
            >
              {diags.length}
            </span>
          )}
          <button
            title="Duplicate"
            onClick={(e) => {
              e.stopPropagation()
              duplicateBlock(node.uid)
            }}
            className="text-xs text-slate-300 hover:text-slate-600"
          >
            ⧉
          </button>
          <button
            title="Delete"
            onClick={(e) => {
              e.stopPropagation()
              removeBlock(node.uid)
            }}
            className="text-xs text-slate-300 hover:text-red-600"
          >
            ✕
          </button>
        </span>
      </div>
      {!collapsed && isContainer && <ContainerBody node={node} />}
      {collapsed && isContainer && (
        <p className="px-2 pb-1 text-xs text-slate-400">…collapsed…</p>
      )}
    </div>
  )
}

function ContainerBody({ node }: { node: BlockNode }) {
  switch (node.kind) {
    case 'serial':
      return (
        <div className="px-2 pb-2">
          <BlockList parentUid={node.uid} slot="children" items={node.children} />
        </div>
      )
    case 'parallel':
      return (
        <div className="px-2 pb-2">
          <ParallelLanes node={node} />
        </div>
      )
    case 'loop':
      return (
        <div className="ml-2 border-l-2 border-slate-200 px-2 pb-2">
          <BlockList parentUid={node.uid} slot="body" items={node.body} />
        </div>
      )
    case 'branch':
      return <BranchLanes node={node} />
    default:
      return null
  }
}

function ParallelLanes({ node }: { node: ParallelNode }) {
  const removeBlock = useDocStore((s) => s.removeBlock)
  const insertBlock = useDocStore((s) => s.insertBlock)
  const isEmptyLane = (lane: BlockNode) => lane.kind === 'serial' && lane.children.length === 0
  return (
    <div className="flex items-stretch overflow-x-auto">
      <DropSlot
        at={{ parentUid: node.uid, slot: 'children', index: 0 }}
        horizontal
        hint={node.children.length === 0}
      />
      {node.children.map((lane, i) => (
        <Fragment key={lane.uid}>
          <div className="min-w-48 flex-1 rounded border border-dashed border-slate-200 p-1">
            <div className="flex items-center justify-between px-1 text-[10px] uppercase text-slate-400">
              <span>lane {i + 1}</span>
              {isEmptyLane(lane) && (
                <button
                  title="Remove lane"
                  onClick={(e) => {
                    e.stopPropagation()
                    removeBlock(lane.uid)
                  }}
                  className="hover:text-red-600"
                >
                  ✕
                </button>
              )}
            </div>
            <BlockView node={lane} />
          </div>
          <DropSlot at={{ parentUid: node.uid, slot: 'children', index: i + 1 }} horizontal hint={false} />
        </Fragment>
      ))}
      <button
        title="Add lane"
        onClick={(e) => {
          e.stopPropagation()
          insertBlock(newStructureNode('serial'), {
            parentUid: node.uid,
            slot: 'children',
            index: node.children.length,
          })
        }}
        className="m-1 shrink-0 self-center rounded border border-dashed border-slate-300 px-2 py-1 text-xs text-slate-400 hover:text-slate-600"
      >
        + lane
      </button>
    </div>
  )
}

function BranchLanes({ node }: { node: BranchNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  return (
    <div className="flex gap-2 px-2 pb-2">
      <div className="min-w-48 flex-1">
        <p className="text-[10px] uppercase text-slate-400">then</p>
        <BlockList parentUid={node.uid} slot="then" items={node.then} />
      </div>
      <div className="min-w-48 flex-1">
        {node.else === null ? (
          <button
            onClick={(e) => {
              e.stopPropagation()
              patchBlock(node.uid, { else: [] })
            }}
            className="mt-4 rounded border border-dashed border-slate-300 px-2 py-1 text-xs text-slate-400 hover:text-slate-600"
          >
            + add else
          </button>
        ) : (
          <>
            <p className="flex items-center justify-between text-[10px] uppercase text-slate-400">
              <span>else</span>
              {node.else.length === 0 && (
                <button
                  title="Remove else"
                  onClick={(e) => {
                    e.stopPropagation()
                    patchBlock(node.uid, { else: null })
                  }}
                  className="hover:text-red-600"
                >
                  ✕
                </button>
              )}
            </p>
            <BlockList parentUid={node.uid} slot="else" items={node.else} />
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Create `src/builder/BuilderTab.tsx`**

```tsx
import { useEffect, useState } from 'react'
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { redo, undo, useDocStore } from '../stores/docStore'
import { useCatalogStore } from '../stores/catalogStore'
import { parseSlotDroppableId, type DragPayload } from './dnd'
import { findNode, newStructureNode, newVerbNode } from './tree'
import { blockSummary } from './summary'
import { Palette } from './Palette'
import { Canvas } from './Canvas'

const STRUCTURE_TITLES: Record<string, string> = {
  serial: 'Serial',
  parallel: 'Parallel',
  loop: 'Loop',
  branch: 'Branch',
  wait: 'Wait',
  operator_input: 'Operator input',
}

function dragLabel(payload: DragPayload): string {
  if (payload.source === 'palette-structure') return STRUCTURE_TITLES[payload.kind] ?? payload.kind
  if (payload.source === 'palette-verb') return `${payload.role} · ${payload.verb}`
  const node = findNode(useDocStore.getState().tree, payload.uid)
  return node ? blockSummary(node) : 'block'
}

export function BuilderTab() {
  const loadCatalog = useCatalogStore((s) => s.load)
  const catalog = useCatalogStore((s) => s.catalog)
  useEffect(() => {
    void loadCatalog()
  }, [loadCatalog])

  const [dragPayload, setDragPayload] = useState<DragPayload | null>(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (
        t &&
        (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)
      ) {
        return
      }
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        if (e.shiftKey) redo()
        else undo()
        return
      }
      if (mod && e.key.toLowerCase() === 'y') {
        e.preventDefault()
        redo()
        return
      }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        const s = useDocStore.getState()
        if (s.selectedUid) {
          e.preventDefault()
          s.removeBlock(s.selectedUid)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const onDragStart = (e: DragStartEvent) =>
    setDragPayload((e.active.data.current ?? null) as DragPayload | null)

  const onDragEnd = (e: DragEndEvent) => {
    setDragPayload(null)
    const payload = (e.active.data.current ?? null) as DragPayload | null
    if (!payload || !e.over) return
    const at = parseSlotDroppableId(String(e.over.id))
    if (!at) return
    const s = useDocStore.getState()
    if (payload.source === 'canvas') {
      s.moveBlock(payload.uid, at)
      return
    }
    if (payload.source === 'palette-structure') {
      s.insertBlock(newStructureNode(payload.kind), at)
      return
    }
    const roleType = s.roles[payload.role]?.type
    const spec = roleType ? catalog?.device_types[roleType]?.[payload.verb] : undefined
    if (spec) s.insertBlock(newVerbNode(payload.role, payload.verb, spec), at)
  }

  return (
    <div className="flex h-[calc(100vh-9rem)] flex-col gap-2">
      <div data-slot="toolbar" />
      <DndContext
        sensors={sensors}
        collisionDetection={pointerWithin}
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onDragCancel={() => setDragPayload(null)}
      >
        <div className="flex min-h-0 flex-1 overflow-hidden rounded-lg border border-slate-200 bg-white">
          <Palette />
          <Canvas />
          <aside
            data-slot="inspector"
            className="w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-slate-50 p-3"
          />
        </div>
        <DragOverlay>
          {dragPayload && (
            <div className="rounded border border-slate-300 bg-white px-2 py-1 text-xs shadow-lg">
              {dragLabel(dragPayload)}
            </div>
          )}
        </DragOverlay>
      </DndContext>
    </div>
  )
}
```

- [ ] **Step 6: Run all four gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add webapp/frontend/src/builder
git commit -m "feat(studio): builder canvas with N-lane parallel, dnd slots, block cards"
```

---

### Task 7: Inspector with catalog-generated forms and expression fields

**Files:**
- Create: `webapp/frontend/src/builder/params.ts`
- Create: `webapp/frontend/src/builder/fields.tsx`
- Create: `webapp/frontend/src/builder/Inspector.tsx`
- Modify: `webapp/frontend/src/builder/BuilderTab.tsx` (replace the `data-slot="inspector"`
  placeholder `<aside>` with `<Inspector />` and add the import)
- Test: `webapp/frontend/src/builder/params.test.ts`

**Interfaces:**
- Consumes: `docStore` (`patchBlock`, `addStream`, `setDescription`, selectors),
  `catalogStore`, `tree.ts` (`findNode`, `findLocation`), `refs.ts` (`collectBindings`),
  `exprHelp.ts`, `types/catalog.ts` (`ParamKind`, `ParamSpec`).
- Produces:
  - `params.ts`: `DURATION_RE = /^\d+(\.\d+)?(ms|s|min|h)$/`,
    `coerceParamInput(text: string, kind: ParamKind): ParamValue | undefined`
    (`undefined` = remove the param), `paramInputText(value: ParamValue | undefined): string`.
  - `fields.tsx`: `TextField({value, onCommit, placeholder?, mono?})` (commit on
    blur/Enter, Escape reverts — keeps undo history one step per field commit),
    `NumberField({value: number | null, onCommit, integer?, min?, placeholder?})`,
    `DurationField({value: string | null, onCommit, allowEmpty?, placeholder?})` (soft
    hint when text does not match `DURATION_RE`; the engine stays authoritative),
    `ExpressionInput({value, onCommit, placeholder?})` (mono text input + ƒ button
    opening a help popover generated by `buildExpressionHelp` from catalog + declared
    streams + operator-input bindings),
    `FieldRow({label, required?, children})` (label + control layout).
  - `Inspector.tsx`: `Inspector()`.

**Param semantics recap (from the grammar reference):** `string` params are literal-only
text inputs. `int`/`number` params use `ExpressionInput` + `coerceParamInput`: a numeric
literal commits as a JSON number, anything else commits as an expression string. `bool`
params render a select (unset when optional / true / false) with an ƒ toggle switching to
expression mode; a string value always renders in expression mode. Empty input removes
the param — the validator reports missing REQUIRED params on the block badge, which is
the desired UX.

- [ ] **Step 1: Write the failing coercion tests**

Create `webapp/frontend/src/builder/params.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { DURATION_RE, coerceParamInput, paramInputText } from './params'

describe('coerceParamInput', () => {
  it('removes params on empty input', () => {
    expect(coerceParamInput('', 'number')).toBeUndefined()
    expect(coerceParamInput('   ', 'string')).toBeUndefined()
  })

  it('keeps string params literal', () => {
    expect(coerceParamInput('cw', 'string')).toBe('cw')
    expect(coerceParamInput('5', 'string')).toBe('5')
  })

  it('commits numeric literals as numbers and everything else as expressions', () => {
    expect(coerceParamInput('5', 'number')).toBe(5)
    expect(coerceParamInput('-2.5', 'number')).toBe(-2.5)
    expect(coerceParamInput('5', 'int')).toBe(5)
    expect(coerceParamInput('2.5', 'int')).toBe('2.5') // not an int literal → expression
    expect(coerceParamInput('feed_ml * 2', 'number')).toBe('feed_ml * 2')
  })

  it('handles bool literals and bool expressions', () => {
    expect(coerceParamInput('true', 'bool')).toBe(true)
    expect(coerceParamInput('false', 'bool')).toBe(false)
    expect(coerceParamInput('mean(od) > 1', 'bool')).toBe('mean(od) > 1')
  })
})

describe('paramInputText', () => {
  it('is the inverse presentation of stored values', () => {
    expect(paramInputText(undefined)).toBe('')
    expect(paramInputText(5)).toBe('5')
    expect(paramInputText(true)).toBe('true')
    expect(paramInputText('feed_ml * 2')).toBe('feed_ml * 2')
  })
})

describe('DURATION_RE', () => {
  it('matches the engine duration grammar (ms|s|min|h — NOT m)', () => {
    for (const ok of ['30s', '5min', '250ms', '1.5h']) expect(DURATION_RE.test(ok)).toBe(true)
    for (const bad of ['2m', '5 s', 's', '5', '5sec']) expect(DURATION_RE.test(bad)).toBe(false)
  })
})
```

- [ ] **Step 2: Run to verify failure, then write `src/builder/params.ts`**

```ts
/** Param input coercion for the "smart" inspector fields: numeric literals become JSON
 * numbers, anything else is kept as an expression string (the engine accepts expression
 * strings for number/int/bool params — that is how operator-input bindings are used).
 * String params are literal-only per the engine validator. */
import type { ParamValue } from '../types/doc'
import type { ParamKind } from '../types/catalog'

export const DURATION_RE = /^\d+(\.\d+)?(ms|s|min|h)$/

export function coerceParamInput(text: string, kind: ParamKind): ParamValue | undefined {
  const t = text.trim()
  if (t === '') return undefined
  if (kind === 'string') return text
  if (kind === 'int' && /^-?\d+$/.test(t)) return Number(t)
  if (kind === 'number' && /^-?\d+(\.\d+)?$/.test(t)) return Number(t)
  if (kind === 'bool') {
    if (t === 'true') return true
    if (t === 'false') return false
  }
  return text
}

export function paramInputText(value: ParamValue | undefined): string {
  return value === undefined ? '' : String(value)
}
```

Run: `npx vitest run src/builder/params.test.ts` → PASS.

- [ ] **Step 3: Create `src/builder/fields.tsx`**

```tsx
import { useEffect, useState, type ReactNode } from 'react'
import { useCatalogStore } from '../stores/catalogStore'
import { useDocStore } from '../stores/docStore'
import { collectBindings } from './refs'
import { buildExpressionHelp } from './exprHelp'
import { DURATION_RE } from './params'

const inputClass =
  'w-full rounded border border-slate-300 bg-white px-1.5 py-0.5 text-xs focus:border-blue-400 focus:outline-none'

export function FieldRow(props: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <label className="block py-1 text-xs">
      <span className="mb-0.5 block text-slate-500">
        {props.label}
        {props.required && <span className="text-red-500"> *</span>}
      </span>
      {props.children}
    </label>
  )
}

export function TextField(props: {
  value: string
  onCommit: (v: string) => void
  placeholder?: string
  mono?: boolean
}) {
  const [draft, setDraft] = useState(props.value)
  useEffect(() => setDraft(props.value), [props.value])
  const commit = () => {
    if (draft !== props.value) props.onCommit(draft)
  }
  return (
    <input
      value={draft}
      placeholder={props.placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit()
        if (e.key === 'Escape') setDraft(props.value)
      }}
      className={inputClass + (props.mono ? ' font-mono' : '')}
    />
  )
}

export function NumberField(props: {
  value: number | null
  onCommit: (v: number | null) => void
  integer?: boolean
  min?: number
  placeholder?: string
}) {
  const text = props.value === null ? '' : String(props.value)
  return (
    <TextField
      mono
      value={text}
      placeholder={props.placeholder}
      onCommit={(t) => {
        const trimmed = t.trim()
        if (trimmed === '') {
          props.onCommit(null)
          return
        }
        const n = Number(trimmed)
        if (Number.isNaN(n)) return
        if (props.integer && !Number.isInteger(n)) return
        if (props.min !== undefined && n < props.min) return
        props.onCommit(n)
      }}
    />
  )
}

export function DurationField(props: {
  value: string | null
  onCommit: (v: string | null) => void
  allowEmpty?: boolean
  placeholder?: string
}) {
  const value = props.value ?? ''
  const invalid = value !== '' && !DURATION_RE.test(value)
  return (
    <div>
      <TextField
        mono
        value={value}
        placeholder={props.placeholder ?? 'e.g. 30s, 5min, 250ms, 1.5h'}
        onCommit={(t) => {
          const trimmed = t.trim()
          if (trimmed === '' && props.allowEmpty) props.onCommit(null)
          else props.onCommit(trimmed)
        }}
      />
      {invalid && <p className="mt-0.5 text-[10px] text-amber-600">expected &lt;number&gt;ms|s|min|h</p>}
    </div>
  )
}

export function ExpressionInput(props: {
  value: string
  onCommit: (v: string) => void
  placeholder?: string
}) {
  const [open, setOpen] = useState(false)
  const streams = useDocStore((s) => s.streams)
  const tree = useDocStore((s) => s.tree)
  const expression = useCatalogStore((s) => s.catalog?.expression ?? null)
  const help = expression
    ? buildExpressionHelp(expression, Object.keys(streams), collectBindings(tree))
    : null
  return (
    <div className="relative">
      <div className="flex items-center gap-1">
        <TextField
          mono
          value={props.value}
          onCommit={props.onCommit}
          placeholder={props.placeholder ?? 'expression'}
        />
        <button
          type="button"
          title="Expression help"
          onClick={() => setOpen(!open)}
          className="shrink-0 rounded border border-slate-300 px-1 text-xs text-slate-500 hover:bg-slate-200"
        >
          ƒ
        </button>
      </div>
      {open && help && (
        <div className="absolute right-0 z-10 mt-1 w-72 rounded border border-slate-300 bg-white p-2 text-xs shadow-lg">
          <p className="font-semibold text-slate-600">Streams</p>
          <p className="mb-1 font-mono text-slate-500">
            {help.streams.length > 0 ? help.streams.join(', ') : '— none declared —'}
          </p>
          <p className="font-semibold text-slate-600">Bindings (operator inputs)</p>
          <p className="mb-1 font-mono text-slate-500">
            {help.bindings.length > 0 ? help.bindings.join(', ') : '— none —'}
          </p>
          <p className="font-semibold text-slate-600">Functions</p>
          <ul className="mb-1">
            {help.functions.map((f) => (
              <li key={f.name} className="flex justify-between gap-2">
                <span className="font-mono">{f.name}</span>
                <span className="font-mono text-slate-400">{f.example}</span>
              </li>
            ))}
          </ul>
          <p className="font-semibold text-slate-600">Windows</p>
          <ul>
            {help.windowForms.map((w) => (
              <li key={w.label} className="flex justify-between gap-2">
                <span>{w.label}</span>
                <span className="font-mono text-slate-400">{w.example}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Create `src/builder/Inspector.tsx`**

```tsx
import { useState } from 'react'
import { useCatalogStore } from '../stores/catalogStore'
import { useDocStore } from '../stores/docStore'
import type { ParamSpec } from '../types/catalog'
import type { ParamValue } from '../types/doc'
import { coerceParamInput, paramInputText } from './params'
import {
  DurationField,
  ExpressionInput,
  FieldRow,
  NumberField,
  TextField,
} from './fields'
import {
  findLocation,
  findNode,
  type BlockNode,
  type BranchNode,
  type CommandNode,
  type InputType,
  type LoopNode,
  type MeasureNode,
  type OperatorInputNode,
  type WaitNode,
} from './tree'

const KIND_TITLES: Record<BlockNode['kind'], string> = {
  command: 'Command',
  measure: 'Measure',
  operator_input: 'Operator input',
  wait: 'Wait',
  serial: 'Serial',
  parallel: 'Parallel',
  loop: 'Loop',
  branch: 'Branch',
}

export function Inspector() {
  const selectedUid = useDocStore((s) => s.selectedUid)
  const tree = useDocStore((s) => s.tree)
  const node = selectedUid ? findNode(tree, selectedUid) : null
  return (
    <aside className="w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-slate-50 p-3">
      {node ? <BlockForm key={node.uid} node={node} /> : <DocProperties />}
    </aside>
  )
}

function DocProperties() {
  const description = useDocStore((s) => s.description)
  const setDescription = useDocStore((s) => s.setDescription)
  const roles = useDocStore((s) => s.roles)
  const streams = useDocStore((s) => s.streams)
  const tree = useDocStore((s) => s.tree)
  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold text-slate-700">Experiment</h2>
      <FieldRow label="Description">
        <textarea
          defaultValue={description ?? ''}
          onBlur={(e) => setDescription(e.target.value || null)}
          rows={3}
          className="w-full rounded border border-slate-300 px-1.5 py-0.5 text-xs"
        />
      </FieldRow>
      <p className="mt-2 text-xs text-slate-400">
        {Object.keys(roles).length} roles · {Object.keys(streams).length} streams ·{' '}
        {tree.length} top-level blocks
      </p>
      <p className="mt-4 text-xs text-slate-400">Select a block to edit its parameters.</p>
    </div>
  )
}

function BlockForm({ node }: { node: BlockNode }) {
  const tree = useDocStore((s) => s.tree)
  const patchBlock = useDocStore((s) => s.patchBlock)
  const loc = findLocation(tree, node.uid)
  const parentKind = loc?.parent?.kind ?? null
  const showGapAfter = parentKind === null || parentKind === 'serial'
  const showStartOffset = parentKind === 'parallel'
  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold text-slate-700">{KIND_TITLES[node.kind]}</h2>
      <KindBody node={node} />
      <h3 className="mt-3 border-t border-slate-200 pt-2 text-xs font-semibold uppercase text-slate-400">
        Timing & label
      </h3>
      <FieldRow label="Label">
        <TextField
          value={node.label ?? ''}
          onCommit={(v) => patchBlock(node.uid, { label: v || null })}
          placeholder="optional display name"
        />
      </FieldRow>
      {showGapAfter && (
        <FieldRow label="Gap after">
          <DurationField
            value={node.gapAfter}
            allowEmpty
            onCommit={(v) => patchBlock(node.uid, { gapAfter: v })}
          />
        </FieldRow>
      )}
      {showStartOffset && (
        <FieldRow label="Start offset">
          <DurationField
            value={node.startOffset}
            allowEmpty
            onCommit={(v) => patchBlock(node.uid, { startOffset: v })}
          />
        </FieldRow>
      )}
    </div>
  )
}

function KindBody({ node }: { node: BlockNode }) {
  switch (node.kind) {
    case 'command':
    case 'measure':
      return <ActionForm node={node} />
    case 'wait':
      return <WaitForm node={node} />
    case 'operator_input':
      return <OperatorInputForm node={node} />
    case 'loop':
      return <LoopForm node={node} />
    case 'branch':
      return <BranchForm node={node} />
    case 'serial':
      return <p className="text-xs text-slate-400">{node.children.length} children — drag blocks on the canvas.</p>
    case 'parallel':
      return <p className="text-xs text-slate-400">{node.children.length} lanes — manage lanes on the canvas.</p>
  }
}

function ActionForm({ node }: { node: CommandNode | MeasureNode }) {
  const roles = useDocStore((s) => s.roles)
  const patchBlock = useDocStore((s) => s.patchBlock)
  const catalog = useCatalogStore((s) => s.catalog)
  const roleType = roles[node.device]?.type
  const verbs = roleType ? (catalog?.device_types[roleType] ?? {}) : {}
  const sameKindVerbs = Object.entries(verbs).filter(
    ([, spec]) => (spec.kind === 'measure') === (node.kind === 'measure'),
  )
  const sameTypeRoles = Object.entries(roles)
    .filter(([, def]) => def.type === roleType)
    .map(([name]) => name)
  const spec = verbs[node.verb]
  return (
    <div>
      {roleType === undefined && (
        <p className="mb-1 text-xs text-red-600">unknown role '{node.device}'</p>
      )}
      <FieldRow label="Role">
        <select
          value={node.device}
          onChange={(e) => patchBlock(node.uid, { device: e.target.value })}
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
        >
          {!sameTypeRoles.includes(node.device) && <option value={node.device}>{node.device}</option>}
          {sameTypeRoles.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </FieldRow>
      <FieldRow label="Verb">
        <select
          value={node.verb}
          onChange={(e) => patchBlock(node.uid, { verb: e.target.value })}
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
        >
          {sameKindVerbs.every(([v]) => v !== node.verb) && (
            <option value={node.verb}>{node.verb}</option>
          )}
          {sameKindVerbs.map(([verb]) => (
            <option key={verb} value={verb}>
              {verb}
            </option>
          ))}
        </select>
      </FieldRow>
      {node.kind === 'measure' && <IntoPicker node={node} />}
      {spec ? (
        <ParamFields node={node} specs={spec.params} />
      ) : (
        <p className="text-xs text-amber-600">verb not in catalog — params not editable</p>
      )}
    </div>
  )
}

function IntoPicker({ node }: { node: MeasureNode }) {
  const streams = useDocStore((s) => s.streams)
  const addStream = useDocStore((s) => s.addStream)
  const patchBlock = useDocStore((s) => s.patchBlock)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [units, setUnits] = useState('')
  const [error, setError] = useState<string | null>(null)
  const names = Object.keys(streams)
  const create = () => {
    const err = addStream(name, units || null)
    setError(err)
    if (!err) {
      patchBlock(node.uid, { into: name })
      setAdding(false)
      setName('')
      setUnits('')
    }
  }
  return (
    <FieldRow label="Into stream" required>
      <select
        value={adding ? '__new__' : node.into}
        onChange={(e) => {
          if (e.target.value === '__new__') setAdding(true)
          else {
            setAdding(false)
            patchBlock(node.uid, { into: e.target.value })
          }
        }}
        className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
      >
        {node.into === '' && !adding && <option value="">— pick a stream —</option>}
        {names.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
        <option value="__new__">+ new stream…</option>
      </select>
      {adding && (
        <div className="mt-1 flex items-center gap-1">
          <input
            value={name}
            placeholder="name"
            onChange={(e) => setName(e.target.value)}
            className="w-20 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
          />
          <input
            value={units}
            placeholder="units"
            onChange={(e) => setUnits(e.target.value)}
            className="w-14 rounded border border-slate-300 px-1 py-0.5 text-xs"
          />
          <button onClick={create} className="rounded bg-slate-200 px-2 py-0.5 text-xs hover:bg-slate-300">
            Add
          </button>
        </div>
      )}
      {error && <p className="text-[10px] text-red-600">{error}</p>}
    </FieldRow>
  )
}

function ParamFields({ node, specs }: { node: CommandNode | MeasureNode; specs: ParamSpec[] }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  const setParam = (name: string, value: ParamValue | undefined) => {
    const params = { ...node.params }
    if (value === undefined) delete params[name]
    else params[name] = value
    patchBlock(node.uid, { params })
  }
  const known = new Set(specs.map((s) => s.name))
  const unknown = Object.keys(node.params).filter((k) => !known.has(k))
  return (
    <div>
      <h3 className="mt-2 text-xs font-semibold uppercase text-slate-400">Params</h3>
      {specs.length === 0 && <p className="text-xs text-slate-400">no params</p>}
      {specs.map((spec) => (
        <FieldRow key={spec.name} label={`${spec.name} (${spec.type})`} required={spec.required}>
          <ParamInput
            spec={spec}
            value={node.params[spec.name]}
            onCommit={(v) => setParam(spec.name, v)}
          />
        </FieldRow>
      ))}
      {unknown.map((name) => (
        <FieldRow key={name} label={`${name} (unknown)`}>
          <div className="flex items-center gap-1">
            <span className="flex-1 truncate font-mono text-xs text-amber-700">
              {paramInputText(node.params[name])}
            </span>
            <button
              title="Remove unknown param"
              onClick={() => setParam(name, undefined)}
              className="text-xs text-slate-400 hover:text-red-600"
            >
              ✕
            </button>
          </div>
        </FieldRow>
      ))}
    </div>
  )
}

function ParamInput(props: {
  spec: ParamSpec
  value: ParamValue | undefined
  onCommit: (v: ParamValue | undefined) => void
}) {
  const { spec, value, onCommit } = props
  const [exprMode, setExprMode] = useState(typeof value === 'string')
  if (spec.type === 'string') {
    return (
      <TextField
        value={typeof value === 'string' ? value : paramInputText(value)}
        onCommit={(t) => onCommit(coerceParamInput(t, 'string'))}
        placeholder={spec.required ? 'required' : 'optional'}
      />
    )
  }
  if (spec.type === 'bool' && !exprMode && typeof value !== 'string') {
    const current = value === true ? 'true' : value === false ? 'false' : ''
    return (
      <div className="flex items-center gap-1">
        <select
          value={current}
          onChange={(e) => {
            const v = e.target.value
            onCommit(v === '' ? undefined : v === 'true')
          }}
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
        >
          <option value="">— unset —</option>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
        <button
          type="button"
          title="Use an expression"
          onClick={() => setExprMode(true)}
          className="shrink-0 rounded border border-slate-300 px-1 text-xs text-slate-500 hover:bg-slate-200"
        >
          ƒ
        </button>
      </div>
    )
  }
  return (
    <ExpressionInput
      value={paramInputText(value)}
      onCommit={(t) => onCommit(coerceParamInput(t, spec.type))}
      placeholder={spec.required ? 'required' : 'optional'}
    />
  )
}

function WaitForm({ node }: { node: WaitNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  return (
    <FieldRow label="Duration" required>
      <DurationField value={node.duration} onCommit={(v) => patchBlock(node.uid, { duration: v ?? '' })} />
    </FieldRow>
  )
}

function OperatorInputForm({ node }: { node: OperatorInputNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  const numeric = node.inputType === 'int' || node.inputType === 'float'
  const setType = (t: InputType) => {
    const patch: Partial<OperatorInputNode> = { inputType: t }
    if (t !== 'enum') patch.choices = null
    if (t === 'enum' || t === 'bool') {
      patch.min = null
      patch.max = null
    }
    patchBlock(node.uid, patch)
  }
  return (
    <div>
      <FieldRow label="Binding name" required>
        <TextField
          mono
          value={node.name}
          onCommit={(v) => patchBlock(node.uid, { name: v })}
          placeholder="identifier, e.g. feed_ml"
        />
      </FieldRow>
      <FieldRow label="Type" required>
        <select
          value={node.inputType}
          onChange={(e) => setType(e.target.value as InputType)}
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
        >
          <option value="int">int</option>
          <option value="float">float</option>
          <option value="bool">bool</option>
          <option value="enum">enum</option>
        </select>
      </FieldRow>
      <FieldRow label="Prompt">
        <TextField
          value={node.prompt ?? ''}
          onCommit={(v) => patchBlock(node.uid, { prompt: v || null })}
          placeholder="shown to the operator"
        />
      </FieldRow>
      {numeric && (
        <>
          <FieldRow label="Min">
            <NumberField
              value={node.min}
              integer={node.inputType === 'int'}
              onCommit={(v) => patchBlock(node.uid, { min: v })}
            />
          </FieldRow>
          <FieldRow label="Max">
            <NumberField
              value={node.max}
              integer={node.inputType === 'int'}
              onCommit={(v) => patchBlock(node.uid, { max: v })}
            />
          </FieldRow>
        </>
      )}
      {node.inputType === 'enum' && (
        <FieldRow label="Choices (one per line)" required>
          <textarea
            defaultValue={(node.choices ?? []).join('\n')}
            onBlur={(e) =>
              patchBlock(node.uid, {
                choices: e.target.value
                  .split('\n')
                  .map((line) => line.trim())
                  .filter((line) => line !== ''),
              })
            }
            rows={3}
            className="w-full rounded border border-slate-300 px-1.5 py-0.5 font-mono text-xs"
          />
        </FieldRow>
      )}
    </div>
  )
}

function LoopForm({ node }: { node: LoopNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  return (
    <div>
      <FieldRow label="Repeat" required>
        <div className="flex gap-3 text-xs">
          <label className="flex items-center gap-1">
            <input
              type="radio"
              checked={node.mode === 'count'}
              onChange={() => patchBlock(node.uid, { mode: 'count' })}
            />
            count
          </label>
          <label className="flex items-center gap-1">
            <input
              type="radio"
              checked={node.mode === 'until'}
              onChange={() => patchBlock(node.uid, { mode: 'until' })}
            />
            until
          </label>
        </div>
      </FieldRow>
      {node.mode === 'count' ? (
        <FieldRow label="Count" required>
          <NumberField
            value={node.count}
            integer
            min={1}
            onCommit={(v) => patchBlock(node.uid, { count: v ?? 1 })}
          />
        </FieldRow>
      ) : (
        <>
          <FieldRow label="Until" required>
            <ExpressionInput
              value={node.until}
              onCommit={(v) => patchBlock(node.uid, { until: v })}
              placeholder="mean(od, last=5) > 0.6"
            />
          </FieldRow>
          <FieldRow label="Check condition">
            <select
              value={node.check}
              onChange={(e) => patchBlock(node.uid, { check: e.target.value as 'before' | 'after' })}
              className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
            >
              <option value="after">after each pass</option>
              <option value="before">before each pass</option>
            </select>
          </FieldRow>
        </>
      )}
      <FieldRow label="Pace (min. loop period)">
        <DurationField value={node.pace} allowEmpty onCommit={(v) => patchBlock(node.uid, { pace: v })} />
      </FieldRow>
    </div>
  )
}

function BranchForm({ node }: { node: BranchNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  return (
    <div>
      <FieldRow label="If" required>
        <ExpressionInput
          value={node.condition}
          onCommit={(v) => patchBlock(node.uid, { condition: v })}
          placeholder="last(od) > 0.5"
        />
      </FieldRow>
      {node.else === null ? (
        <button
          onClick={() => patchBlock(node.uid, { else: [] })}
          className="rounded border border-dashed border-slate-300 px-2 py-1 text-xs text-slate-500 hover:text-slate-700"
        >
          + add else lane
        </button>
      ) : (
        <button
          disabled={node.else.length > 0}
          title={node.else.length > 0 ? 'Empty the else lane first' : undefined}
          onClick={() => patchBlock(node.uid, { else: null })}
          className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-500 enabled:hover:text-red-600 disabled:opacity-40"
        >
          remove else lane
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Wire the inspector into `BuilderTab.tsx`**

Replace the placeholder line

```tsx
          <aside
            data-slot="inspector"
            className="w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-slate-50 p-3"
          />
```

with

```tsx
          <Inspector />
```

and add `import { Inspector } from './Inspector'` to the imports.

- [ ] **Step 6: Run all four gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add webapp/frontend/src/builder
git commit -m "feat(studio): inspector with catalog-generated param forms and expression help"
```

---

### Task 8: Toolbar (save/load/duplicate/new), problems panel, debounced validation, App wiring

**Files:**
- Create: `webapp/frontend/src/builder/useValidation.ts`
- Create: `webapp/frontend/src/builder/Toolbar.tsx`
- Create: `webapp/frontend/src/builder/LoadDialog.tsx`
- Create: `webapp/frontend/src/builder/ProblemsPanel.tsx`
- Modify: `webapp/frontend/src/builder/BuilderTab.tsx` (toolbar + validation + problems)
- Modify: `webapp/frontend/src/App.tsx` (mount BuilderTab)

**Interfaces:**
- Consumes: `api/studio.ts` (all experiment endpoints + `validateDoc`), `api/client.ts`
  (`ApiError`), `stores/docStore.ts` (`selectDoc`, `selectDirty`, `loadDoc`, `newDoc`,
  `undo`, `redo`, `useTemporal`, actions), `builder/convert.ts` (`docToTree`,
  `DocConvertError`), `builder/paths.ts` (`mapDiagnostics`).
- Produces: `useValidation()` hook (call ONCE from BuilderTab), `Toolbar()`,
  `LoadDialog({onClose})`, `ProblemsPanel()` (self-contained: renders nothing when there
  are no diagnostics; expands from a slim bar).

**Behavior contract (spec §9.3, §10):** validation is debounced ~500 ms after edits
settle and NEVER blocks saving — only running (W5's concern). Save = PUT when the doc has
a `serverId`, else POST; a 409 `name_conflict` shows an inline error suggesting rename or
Save-as. Save-as = POST under a new name and switches editing to the new copy. Duplicate =
backend duplicate endpoint, then loads the copy. New/Load warn on unsaved changes.
Problems-panel rows with a block uid select that block and scroll it into view.

- [ ] **Step 1: Create `src/builder/useValidation.ts`**

```ts
/** Debounced draft validation (webapp design §4.3): 500 ms after edits settle, POST the
 * doc to /api/validate and map diagnostics onto the CURRENT tree. A monotonically
 * increasing sequence guards against stale responses racing fresh edits. */
import { useEffect, useRef } from 'react'
import { validateDoc } from '../api/studio'
import { selectDoc, useDocStore } from '../stores/docStore'
import { mapDiagnostics } from './paths'

export function useValidation(): void {
  const name = useDocStore((s) => s.name)
  const description = useDocStore((s) => s.description)
  const roles = useDocStore((s) => s.roles)
  const streams = useDocStore((s) => s.streams)
  const tree = useDocStore((s) => s.tree)
  const seq = useRef(0)

  useEffect(() => {
    const id = ++seq.current
    useDocStore.getState().setValidating(true)
    const timer = setTimeout(() => {
      const doc = selectDoc(useDocStore.getState())
      validateDoc(doc)
        .then((resp) => {
          if (seq.current !== id) return
          const state = useDocStore.getState()
          state.setDiagnostics(mapDiagnostics(state.tree, resp.diagnostics))
          state.setValidationError(null)
          state.setValidating(false)
        })
        .catch((e: unknown) => {
          if (seq.current !== id) return
          const state = useDocStore.getState()
          state.setValidationError(e instanceof Error ? e.message : String(e))
          state.setValidating(false)
        })
    }, 500)
    return () => clearTimeout(timer)
  }, [name, description, roles, streams, tree])
}
```

- [ ] **Step 2: Create `src/builder/ProblemsPanel.tsx`**

```tsx
import { useState } from 'react'
import { useDocStore } from '../stores/docStore'

/** Bottom problems strip: every diagnostic from the last validate call. Rows that
 * resolved to a block select it and scroll it into view; doc-level rows (path
 * `workflow`, unknown structural paths) are listed under their raw path. */
export function ProblemsPanel() {
  const diagnostics = useDocStore((s) => s.diagnostics)
  const validationError = useDocStore((s) => s.validationError)
  const select = useDocStore((s) => s.select)
  const [open, setOpen] = useState(false)
  if (diagnostics.length === 0 && validationError === null) return null
  return (
    <div className="rounded-lg border border-red-200 bg-white">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-red-700"
      >
        <span>⚠ {validationError ? 'validation unavailable' : `${diagnostics.length} problem${diagnostics.length === 1 ? '' : 's'}`}</span>
        <span className="ml-auto text-slate-400">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <ul className="max-h-40 overflow-y-auto border-t border-red-100 px-3 py-1">
          {validationError && <li className="py-0.5 text-xs text-amber-700">{validationError}</li>}
          {diagnostics.map((d, i) => (
            <li key={i} className="py-0.5 text-xs">
              <button
                disabled={d.uid === null}
                onClick={() => {
                  if (!d.uid) return
                  select(d.uid)
                  document
                    .getElementById(`block-${d.uid}`)
                    ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
                }}
                className="text-left enabled:hover:underline disabled:cursor-default"
              >
                <span className="mr-1 rounded bg-slate-200 px-1 font-mono text-[10px]">{d.category}</span>
                <span className="mr-1 font-mono text-[10px] text-slate-400">{d.path}</span>
                {d.message}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Create `src/builder/LoadDialog.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { deleteExperiment, getExperiment, listExperiments } from '../api/studio'
import type { ExperimentSummary } from '../types/doc'
import { loadDoc, selectDirty, useDocStore } from '../stores/docStore'
import { DocConvertError, docToTree } from './convert'

export function LoadDialog(props: { onClose: () => void }) {
  const [items, setItems] = useState<ExperimentSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const refresh = () => {
    setError(null)
    listExperiments()
      .then(setItems)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }
  useEffect(refresh, [])

  const open = async (id: string) => {
    if (selectDirty(useDocStore.getState()) && !window.confirm('Discard unsaved changes?')) return
    try {
      const res = await getExperiment(id)
      loadDoc(docToTree(res.doc), res.id)
      props.onClose()
    } catch (e) {
      setError(
        e instanceof DocConvertError
          ? `cannot open in the builder: ${e.message}`
          : e instanceof Error
            ? e.message
            : String(e),
      )
    }
  }

  const remove = async (item: ExperimentSummary) => {
    if (!window.confirm(`Delete experiment '${item.name}'? Records are kept.`)) return
    try {
      await deleteExperiment(item.id)
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const shown = (items ?? []).filter(
    (i) =>
      i.name.toLowerCase().includes(search.toLowerCase()) ||
      (i.description ?? '').toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-black/30"
      onClick={props.onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="max-h-[70vh] w-[28rem] overflow-y-auto rounded-lg bg-white p-4 shadow-xl"
      >
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Load experiment</h2>
          <button onClick={props.onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>
        <input
          autoFocus
          value={search}
          placeholder="search…"
          onChange={(e) => setSearch(e.target.value)}
          className="mb-2 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />
        {error && <p className="mb-2 text-xs text-red-600">{error}</p>}
        {items === null && !error && <p className="text-xs text-slate-400">loading…</p>}
        {items !== null && shown.length === 0 && (
          <p className="text-xs text-slate-400">no experiments{search ? ' match' : ' saved yet'}</p>
        )}
        <ul className="divide-y divide-slate-100">
          {shown.map((item) => (
            <li key={item.id} className="flex items-center gap-2 py-1.5">
              <button onClick={() => void open(item.id)} className="min-w-0 flex-1 text-left">
                <p className="truncate text-sm">{item.name}</p>
                <p className="truncate text-xs text-slate-400">
                  {item.description ?? 'no description'} · updated {item.updated_at.slice(0, 16)}
                </p>
              </button>
              <button
                title="Delete experiment"
                onClick={() => void remove(item)}
                className="text-xs text-slate-300 hover:text-red-600"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Create `src/builder/Toolbar.tsx`**

```tsx
import { useState } from 'react'
import { ApiError } from '../api/client'
import { createExperiment, duplicateExperiment, replaceExperiment } from '../api/studio'
import {
  loadDoc,
  newDoc,
  redo,
  selectDirty,
  selectDoc,
  undo,
  useDocStore,
  useTemporal,
} from '../stores/docStore'
import { docToTree } from './convert'
import { TextField } from './fields'
import { LoadDialog } from './LoadDialog'

function ValidationChip() {
  const validating = useDocStore((s) => s.validating)
  const validationError = useDocStore((s) => s.validationError)
  const count = useDocStore((s) => s.diagnostics.length)
  if (validating) {
    return <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-500">validating…</span>
  }
  if (validationError !== null) {
    return <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">validation unavailable</span>
  }
  if (count > 0) {
    return (
      <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-700">
        {count} problem{count === 1 ? '' : 's'}
      </span>
    )
  }
  return <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">valid</span>
}

const buttonClass =
  'rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-40 disabled:hover:bg-white'

export function Toolbar() {
  const name = useDocStore((s) => s.name)
  const setName = useDocStore((s) => s.setName)
  const serverId = useDocStore((s) => s.serverId)
  const markSaved = useDocStore((s) => s.markSaved)
  const dirty = useDocStore(selectDirty)
  const canUndo = useTemporal((t) => t.pastStates.length > 0)
  const canRedo = useTemporal((t) => t.futureStates.length > 0)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loadOpen, setLoadOpen] = useState(false)

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'name_conflict') {
        setError(`name already taken — rename the experiment or use Save as`)
      } else {
        setError(e instanceof Error ? e.message : String(e))
      }
    } finally {
      setBusy(false)
    }
  }

  const save = () =>
    run(async () => {
      const state = useDocStore.getState()
      const doc = selectDoc(state)
      const res = state.serverId
        ? await replaceExperiment(state.serverId, doc)
        : await createExperiment(doc)
      markSaved(res.id)
    })

  const saveAs = () => {
    const newName = window.prompt('Save as…', `${name} (copy)`)
    if (!newName) return
    void run(async () => {
      useDocStore.getState().setName(newName)
      const res = await createExperiment(selectDoc(useDocStore.getState()))
      markSaved(res.id)
    })
  }

  const duplicate = () =>
    run(async () => {
      const id = useDocStore.getState().serverId
      if (!id) return
      const res = await duplicateExperiment(id)
      loadDoc(docToTree(res.doc), res.id)
    })

  const fresh = () => {
    if (selectDirty(useDocStore.getState()) && !window.confirm('Discard unsaved changes?')) return
    newDoc()
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="w-64">
        <TextField value={name} onCommit={setName} placeholder="experiment name" />
      </div>
      {dirty && <span title="Unsaved changes" className="text-amber-500">●</span>}
      <ValidationChip />
      {error && <span className="truncate text-xs text-red-600">{error}</span>}
      <span className="ml-auto flex items-center gap-1">
        <button className={buttonClass} disabled={!canUndo} onClick={undo} title="Undo (⌘Z)">
          ↶
        </button>
        <button className={buttonClass} disabled={!canRedo} onClick={redo} title="Redo (⇧⌘Z)">
          ↷
        </button>
        <button className={buttonClass} disabled={busy} onClick={fresh}>
          New
        </button>
        <button className={buttonClass} disabled={busy} onClick={() => setLoadOpen(true)}>
          Load
        </button>
        <button className={buttonClass} disabled={busy} onClick={() => void save()}>
          Save
        </button>
        <button className={buttonClass} disabled={busy} onClick={saveAs}>
          Save as
        </button>
        <button
          className={buttonClass}
          disabled={busy || serverId === null}
          title={serverId === null ? 'Save first' : 'Duplicate on the server and open the copy'}
          onClick={() => void duplicate()}
        >
          Duplicate
        </button>
      </span>
      {loadOpen && <LoadDialog onClose={() => setLoadOpen(false)} />}
    </div>
  )
}
```

- [ ] **Step 5: Wire toolbar + validation + problems into `BuilderTab.tsx`**

- Add imports: `import { Toolbar } from './Toolbar'`, `import { ProblemsPanel } from
  './ProblemsPanel'`, `import { useValidation } from './useValidation'`.
- Inside `BuilderTab()`, add `useValidation()` right after the catalog-loading
  `useEffect`.
- Replace `<div data-slot="toolbar" />` with `<Toolbar />`.
- After the `</DndContext>` closing tag (still inside the outer flex column), add
  `<ProblemsPanel />`.

- [ ] **Step 6: Mount the builder in `src/App.tsx`**

Replace the whole file:

```tsx
import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api/client'
import { describeHealth } from './api/health'
import { TabShell, type Tab } from './shell/TabShell'
import { BuilderTab } from './builder/BuilderTab'

const PLACEHOLDERS: Partial<Record<Tab, string>> = {
  Devices: 'Lab roster and device discovery arrive with the Devices tab (this increment).',
  Run: 'Run controls, live chart, and prompts arrive in increments W4-W5.',
  Records: 'Run records arrive in increment W5.',
}

export default function App() {
  const [tab, setTab] = useState<Tab>('Builder')
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  return (
    <TabShell active={tab} onSelect={setTab} statusLine={describeHealth(health, error)}>
      {tab === 'Builder' ? (
        <BuilderTab />
      ) : (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          {PLACEHOLDERS[tab]}
        </div>
      )}
    </TabShell>
  )
}
```

(The default tab becomes Builder for this increment; Task 9 rewires Devices and restores
Devices as the natural first tab.)

- [ ] **Step 7: Run all four gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build`
Expected: all pass.

- [ ] **Step 8: Smoke the dev stack manually (quick sanity, full walkthrough is Task 10)**

```bash
cd webapp/backend && STUDIO_DATA_DIR=$(mktemp -d) .venv/bin/python -m uvicorn --factory experiment_studio.app:create_app --port 8000 &
cd webapp/frontend && npm run dev &
curl -s localhost:8000/api/catalog | head -c 200
```

Expected: catalog JSON served; vite dev server starts. Kill both afterwards.

- [ ] **Step 9: Commit**

```bash
git add webapp/frontend/src
git commit -m "feat(studio): builder toolbar with save/load/duplicate, debounced validation, problems panel"
```

---

### Task 9: Devices tab, labs store, shell lab indicator

**Scope rationale:** spec §9.2 (Devices tab) is not assigned to any increment in §12, the
W1 App shell promised it for "W1/W3", and W5's preflight needs an app-global selected
lab — so it lands here. **Deliberate omission:** §9.2 mentions a per-device ping, but §6
defines no ping endpoint and the API table is the contract — per-device ping is deferred
(noted in the spec amendment in Task 10). Rediscover uses the existing
`POST /api/labs/{lab}/discover`.

**Files:**
- Create: `webapp/frontend/src/types/labs.ts`
- Create: `webapp/frontend/src/api/labs.ts`
- Create: `webapp/frontend/src/stores/labsStore.ts`
- Create: `webapp/frontend/src/devices/DevicesTab.tsx`
- Modify: `webapp/frontend/src/shell/TabShell.tsx` (lab chip in header)
- Modify: `webapp/frontend/src/App.tsx` (mount DevicesTab, default tab Devices)

**Interfaces:**
- Consumes: `api/client.ts` (`getJson`, `postJson`).
- Produces: `types/labs.ts` (`LabSummary {name, host, port, online}`, `LabDevice {id,
  type, port, connected, model, firmware}` — port/connected/model/firmware nullable),
  `api/labs.ts` (`listLabs()`, `labDevices(lab)`, `labDiscover(lab)`),
  `stores/labsStore.ts` (`useLabsStore` with `labs`, `labsError`, `loadingLabs`,
  `selected`, `devices`, `devicesError`, `loadingDevices`, `discovering`,
  `refreshLabs()`, `selectLab(name)`, `refreshDevices()`, `rediscover()`; `selected`
  persists to localStorage key `studio.selectedLab`). W5 reads `selected` for run
  preflight.

- [ ] **Step 1: Create `src/types/labs.ts`**

```ts
/** GET /api/labs and /api/labs/{lab}/devices payloads (webapp design §6). */

export interface LabSummary {
  name: string
  host: string
  port: number
  online: boolean
}

export interface LabDevice {
  id: string
  type: string
  port: string | null
  connected: boolean | null
  model: string | null
  firmware: string | null
}
```

- [ ] **Step 2: Create `src/api/labs.ts`**

```ts
import { getJson, postJson } from './client'
import type { LabDevice, LabSummary } from '../types/labs'

export const listLabs = () => getJson<LabSummary[]>('/api/labs')

export const labDevices = (lab: string) =>
  getJson<LabDevice[]>(`/api/labs/${encodeURIComponent(lab)}/devices`)

export const labDiscover = (lab: string) =>
  postJson<LabDevice[]>(`/api/labs/${encodeURIComponent(lab)}/discover`, {})
```

- [ ] **Step 3: Create `src/stores/labsStore.ts`**

```ts
/** Lab roster + per-lab device view. The selected lab is app-global (shown in the shell
 * header, spec §9.1) and persists across reloads via localStorage. */
import { create } from 'zustand'
import { labDevices, labDiscover, listLabs } from '../api/labs'
import type { LabDevice, LabSummary } from '../types/labs'

const STORAGE_KEY = 'studio.selectedLab'

const message = (e: unknown): string => (e instanceof Error ? e.message : String(e))

interface LabsState {
  labs: LabSummary[] | null
  labsError: string | null
  loadingLabs: boolean
  selected: string | null
  devices: LabDevice[] | null
  devicesError: string | null
  loadingDevices: boolean
  discovering: boolean
  refreshLabs: () => Promise<void>
  selectLab: (name: string | null) => void
  refreshDevices: () => Promise<void>
  rediscover: () => Promise<void>
}

export const useLabsStore = create<LabsState>()((set, get) => ({
  labs: null,
  labsError: null,
  loadingLabs: false,
  selected: localStorage.getItem(STORAGE_KEY),
  devices: null,
  devicesError: null,
  loadingDevices: false,
  discovering: false,

  refreshLabs: async () => {
    set({ loadingLabs: true, labsError: null })
    try {
      set({ labs: await listLabs(), loadingLabs: false })
    } catch (e) {
      set({ labsError: message(e), loadingLabs: false })
    }
  },

  selectLab: (name) => {
    if (name === null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, name)
    set({ selected: name, devices: null, devicesError: null })
    if (name !== null) void get().refreshDevices()
  },

  refreshDevices: async () => {
    const lab = get().selected
    if (lab === null) return
    set({ loadingDevices: true, devicesError: null })
    try {
      const devices = await labDevices(lab)
      if (get().selected !== lab) return
      set({ devices, loadingDevices: false })
    } catch (e) {
      if (get().selected !== lab) return
      set({ devicesError: message(e), loadingDevices: false })
    }
  },

  rediscover: async () => {
    const lab = get().selected
    if (lab === null) return
    set({ discovering: true, devicesError: null })
    try {
      const devices = await labDiscover(lab)
      if (get().selected !== lab) return
      set({ devices, discovering: false })
    } catch (e) {
      if (get().selected !== lab) return
      set({ devicesError: message(e), discovering: false })
    }
  },
}))
```

- [ ] **Step 4: Create `src/devices/DevicesTab.tsx`**

```tsx
import { useEffect } from 'react'
import { useLabsStore } from '../stores/labsStore'

/** Devices tab (spec §9.2): lab picker with online badges, read-only device table, and
 * a confirmed Rediscover that re-enumerates the lab's bus. Device control belongs to
 * experiments, not this tab. Per-device ping is deferred (no §6 endpoint). */
export function DevicesTab() {
  const s = useLabsStore()

  useEffect(() => {
    void useLabsStore.getState().refreshLabs()
    if (useLabsStore.getState().selected !== null) {
      void useLabsStore.getState().refreshDevices()
    }
  }, [])

  const rediscover = () => {
    if (
      window.confirm(
        'Rediscover re-enumerates the serial bus on the lab agent. It takes a few seconds ' +
          'and must not run during an active experiment. Continue?',
      )
    ) {
      void s.rediscover()
    }
  }

  return (
    <div className="flex gap-4">
      <aside className="w-64 shrink-0">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">Labs</h2>
          <button
            onClick={() => void s.refreshLabs()}
            disabled={s.loadingLabs}
            className="text-xs text-slate-400 hover:text-slate-700 disabled:opacity-40"
          >
            {s.loadingLabs ? '…' : '↻ refresh'}
          </button>
        </div>
        {s.labsError && (
          <p className="mb-2 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-700">
            roster unreachable: {s.labsError}
          </p>
        )}
        {s.labs !== null && s.labs.length === 0 && (
          <p className="text-xs text-slate-400">no labs in the roster</p>
        )}
        <ul className="space-y-1">
          {(s.labs ?? []).map((lab) => (
            <li key={lab.name}>
              <button
                onClick={() => s.selectLab(lab.name)}
                className={
                  'flex w-full items-center gap-2 rounded border px-2 py-1.5 text-left text-sm ' +
                  (s.selected === lab.name
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-slate-200 bg-white hover:border-slate-300')
                }
              >
                <span
                  title={lab.online ? 'online' : 'offline'}
                  className={
                    'h-2 w-2 shrink-0 rounded-full ' + (lab.online ? 'bg-emerald-500' : 'bg-slate-300')
                  }
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{lab.name}</span>
                  <span className="block truncate text-xs text-slate-400">
                    {lab.host}:{lab.port}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <section className="min-w-0 flex-1">
        {s.selected === null ? (
          <p className="rounded border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-400">
            Pick a lab to see its devices.
          </p>
        ) : (
          <>
            <div className="mb-2 flex items-center gap-2">
              <h2 className="text-sm font-semibold text-slate-700">Devices — {s.selected}</h2>
              <span className="ml-auto flex gap-1">
                <button
                  onClick={() => void s.refreshDevices()}
                  disabled={s.loadingDevices || s.discovering}
                  className="rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-40"
                >
                  Refresh
                </button>
                <button
                  onClick={rediscover}
                  disabled={s.loadingDevices || s.discovering}
                  className="rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-40"
                >
                  {s.discovering ? 'Rediscovering…' : 'Rediscover'}
                </button>
              </span>
            </div>
            {s.devicesError && (
              <p className="mb-2 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-700">
                {s.devicesError}{' '}
                <button onClick={() => void s.refreshDevices()} className="underline">
                  retry
                </button>
              </p>
            )}
            {s.loadingDevices && <p className="text-xs text-slate-400">loading devices…</p>}
            {s.devices !== null && (
              <table className="w-full border-collapse rounded bg-white text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-xs uppercase text-slate-400">
                    <th className="px-2 py-1.5">id</th>
                    <th className="px-2 py-1.5">type</th>
                    <th className="px-2 py-1.5">port</th>
                    <th className="px-2 py-1.5">connected</th>
                    <th className="px-2 py-1.5">model</th>
                    <th className="px-2 py-1.5">firmware</th>
                  </tr>
                </thead>
                <tbody>
                  {s.devices.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-2 py-4 text-center text-xs text-slate-400">
                        no devices attached
                      </td>
                    </tr>
                  )}
                  {s.devices.map((d) => (
                    <tr key={d.id} className="border-b border-slate-100">
                      <td className="px-2 py-1.5 font-mono text-xs">{d.id}</td>
                      <td className="px-2 py-1.5">{d.type}</td>
                      <td className="px-2 py-1.5 font-mono text-xs">{d.port ?? '—'}</td>
                      <td className="px-2 py-1.5">
                        <span
                          className={
                            'rounded-full px-2 py-0.5 text-xs ' +
                            (d.connected
                              ? 'bg-emerald-100 text-emerald-700'
                              : 'bg-slate-100 text-slate-500')
                          }
                        >
                          {d.connected ? 'connected' : 'disconnected'}
                        </span>
                      </td>
                      <td className="px-2 py-1.5 text-xs">{d.model ?? '—'}</td>
                      <td className="px-2 py-1.5 text-xs">{d.firmware ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </section>
    </div>
  )
}
```

- [ ] **Step 5: Add the lab chip to `src/shell/TabShell.tsx`**

Add a `lab: string | null` prop and render it next to the status line. Change the
component signature and header block to:

```tsx
export function TabShell(props: {
  active: Tab
  onSelect: (tab: Tab) => void
  statusLine: string
  lab: string | null
  children: ReactNode
}) {
  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <header className="border-b border-slate-200 bg-white px-6 py-3">
        <div className="flex items-baseline justify-between">
          <h1 className="text-lg font-semibold">Experiment Studio</h1>
          <span className="flex items-center gap-3">
            <span
              className={
                'rounded-full px-2 py-0.5 text-xs ' +
                (props.lab ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-400')
              }
            >
              {props.lab ? `lab: ${props.lab}` : 'no lab selected'}
            </span>
            <span className="text-xs text-slate-500">{props.statusLine}</span>
          </span>
        </div>
        ...nav unchanged...
      </header>
      <main className="p-6">{props.children}</main>
    </div>
  )
}
```

- [ ] **Step 6: Mount DevicesTab in `src/App.tsx`**

Update App to select Devices as the default tab again, render `<DevicesTab />` for
Devices, and pass the lab chip:

```tsx
import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api/client'
import { describeHealth } from './api/health'
import { TabShell, type Tab } from './shell/TabShell'
import { BuilderTab } from './builder/BuilderTab'
import { DevicesTab } from './devices/DevicesTab'
import { useLabsStore } from './stores/labsStore'

const PLACEHOLDERS: Partial<Record<Tab, string>> = {
  Run: 'Run controls, live chart, and prompts arrive in increments W4-W5.',
  Records: 'Run records arrive in increment W5.',
}

export default function App() {
  const [tab, setTab] = useState<Tab>('Devices')
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
      {(tab === 'Run' || tab === 'Records') && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          {PLACEHOLDERS[tab]}
        </div>
      )}
    </TabShell>
  )
}
```

Note: `BuilderTab` unmounts when switching tabs, but its state lives in the zustand
stores, so the document survives tab switches — verify this in the Task 10 walkthrough.

- [ ] **Step 7: Run all four gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add webapp/frontend/src
git commit -m "feat(studio): devices tab with lab picker, device roster, rediscover"
```

---

### Task 10: Full gates, spec amendments, manual walkthrough (controller-executed)

This task is executed by the controlling session (not a subagent) because it drives the
running app.

**Files:**
- Modify: `docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md`
  (two amendments, mirroring the W2 amendment style)

- [ ] **Step 1: Amend the spec where the engine/API contradicted it**

In §9.3, change the Wait sentence to read:

```
  `into`-stream picker (from declared streams, with inline "new stream"). Wait gets a
  duration field (`"5s"`, `"2min"` grammar — units ms|s|min|h; amended 2026-07-12 during
  W3: the original `"2m"` example was not the engine grammar). Loop gets count / until /
```

In §9.2, change the device-table sentence to note the ping deferral:

```
Lab picker from `/api/labs` (online badges) → device table (id, type, port, connected,
firmware from `identify`) and a global "Rediscover" button (confirm dialog; explains it
re-enumerates the bus). Per-device ping deferred to the v2 backlog (amended 2026-07-12
during W3: §6 defines no ping endpoint and the §6 table is the API contract). Read-only
otherwise — device control belongs to experiments.
```

- [ ] **Step 2: Run the complete frontend + backend gates**

```bash
cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build
cd ../backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy experiment_studio && .venv/bin/python -m ruff check .
git diff main --stat -- ../../src ../../pyproject.toml   # MUST be empty
```

Expected: frontend suite ≥ 40 tests green; backend suite still 47 green (untouched);
no library/root changes.

- [ ] **Step 3: Manual walkthrough (the W3 gate: "manual walkthrough builds a real workflow doc")**

Start the dev stack (backend with a temp data dir + vite dev), then drive the browser
(use the `run` skill / browser tooling; capture screenshots as evidence):

1. **Devices:** open the app → Devices tab shows the lab roster (or an explicit offline
   state if no roster is reachable — both acceptable; the walkthrough continues either way).
2. **Roles:** Builder tab → add roles `feed_pump` (pump) and `od_meter` (densitometer) →
   palette grows both sections with verb chips.
3. **Streams:** add stream `od` with units `AU`.
4. **Build the golden workflow:** drag Serial to the canvas root; drag `feed_pump ·
   dispense` into it, set `volume_ml` = 5; drag Loop after it, set mode until,
   `mean(od, last=3) > 0.6`, pace `30s`; inside the loop drag `od_meter · measure`
   (into `od`) and Wait `5s`. Open the ƒ help popover on the until field — it must list
   `od`, the five stat functions, and the three window forms.
5. **Validation:** chip reads "valid" once complete; transiently shows problems while
   the loop condition is empty (doc-level `workflow` diagnostic in the problems panel)
   and a badge when a required param is missing (block-level).
6. **Undo/redo:** ⌘Z steps backwards through edits; role rename (`feed_pump` →
   `acid_pump` → rename back) rewrites the dispense chip/card in ONE undo step.
7. **Parallel:** drag a Parallel block in, confirm two lanes side by side, `+ lane`
   appends a third, empty lanes show drop hint + remove control. Confirm a container
   cannot be dropped into itself (no highlight). Delete it afterwards.
8. **Save/load/duplicate:** Save → dirty dot clears. Rename + Save as → separate copy.
   Load dialog lists both, search filters, open the original. Duplicate → "<name>
   (copy)" opens. Delete the copies from the load dialog.
9. **Compare with the fixture:** `curl -s localhost:8000/api/experiments | jq` — the
   saved doc's workflow must be structurally identical to
   `webapp/fixtures/valid-od-growth.json` (same block nesting; params may differ where
   the walkthrough diverged).
10. **Tab switch:** flip Devices ↔ Builder — the document persists (zustand store).

Fix anything that fails, re-running the affected gates; then re-verify the specific
walkthrough step.

- [ ] **Step 4: Commit spec amendments + any walkthrough fixes**

```bash
git add docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md
git commit -m "docs(studio): W3 spec amendments — duration grammar example, ping deferral"
```

---

## Execution notes

- Branch: `feat/experiment-studio-3-builder-ui` off current `main` (W2 merged as PR #12).
- Task order is strictly 1 → 10; tasks 5-7 each depend on 4 and on each other's
  BuilderTab edits as written (6 creates it, 7 and 8 edit it).
- CI needs no changes: the existing `webapp-frontend` job (lint + test + build on
  `webapp/**` changes) covers everything; `package-lock.json` changes ride along.
- After the final review: PR to `main`, merge when CI is green.

## Self-review (performed while writing)

- **Spec coverage:** §9.3 palette ✓(T5) canvas/N-lane/collapse/dnd ✓(T6) inspector/
  expression fields/help ✓(T7) toolbar/save/load/duplicate/diagnostics badges/problems
  panel/undo-redo ✓(T4/T6/T8); §4.2 role semantics ✓(T3/T4/T5); §4.3 debounced validate +
  path mapping ✓(T3/T8); §9.2 devices ✓(T9, ping deferred with amendment); §11 frontend
  test list: doc↔canvas mapping ✓, role cascades ✓, placeholder-path resolution ✓,
  expression-help generation ✓ (WS reducer is W5). Fixtures consumed by frontend ✓(T2).
- **Placeholders:** none — every step carries full code or exact commands.
- **Type consistency:** `BlockNode` union fields (`condition`, `inputType`, `gapAfter`,
  `startOffset`, loop `mode`) used consistently across T2 code, T6 canvas, T7 inspector;
  `DragPayload` variants match between T5 chips and T6 onDragEnd; store action names in
  T4 match every component call site in T5-T8; `useTemporal` selector shape matches
  zundo's `TemporalState` (pastStates/futureStates arrays).







