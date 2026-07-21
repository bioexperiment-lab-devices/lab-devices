/** Hand-written TS mirrors of doc v1 envelope + engine workflow schema v2 (webapp design §4.1;
 * typed-params design 2026-07-20). The block grammar mirrors the engine serializer: one type key
 * per block plus optional block-level keys label/gap_after/start_offset/retry/on_error. Group
 * params/for_each vars are typed decls; groups carry locals; roles live in `workflow.roles`. */

export type ParamValue = number | string | boolean

// mirrors engine ParamKind (workflow.py). Keep this the single source on the FE.
export type ParamKind = 'int' | 'number' | 'bool' | 'string' | 'role' | 'stream' | 'binding'
export const VALUE_KINDS = ['int', 'number', 'bool', 'string'] as const
export const REFERENCE_KINDS = ['role', 'stream', 'binding'] as const

export interface ParamDeclJson {
  name: string
  kind: ParamKind
  device_type?: string // required iff kind === 'role', forbidden otherwise
}

export interface LocalDeclJson {
  kind: 'stream' | 'binding'
  init?: string // constant expr; binding-kind only
  units?: string // stream-kind only
  persistence?: string // stream-kind only
}

export interface RoleDeclJson {
  type: string
  device?: string // optional direct binding
}

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
  /** An int literal or, since schema v3 (engine #58), an int-typed expression string. */
  count?: number | string
  until?: string
  check?: string // 'before' | 'after'
  pace?: string
}

export interface BranchBody {
  if: string
  then: BlockJson[]
  else?: BlockJson[]
}

/** for_each is a SPLICING macro: it copies `body` once per item and splices the copies into the
 * ENCLOSING list, so mode is inherited — sole child of a parallel becomes N lanes; inside a
 * serial, an N-step sequence (engine design 2026-07-15 §2). Schema 2 (typed-group-parameters
 * design §9.2): the scalar `var` shorthand is REMOVED — every for_each declares typed `vars`
 * and a list of `in` rows, one value per var. The JSON key is `in`; the node field is `rows`
 * (convert.ts translates, as it already does for branch.if <-> condition). */
export interface ForEachBody {
  vars: ParamDeclJson[]
  in: Array<Record<string, ParamValue>>
  body: BlockJson[]
}

export interface GroupJson {
  params?: ParamDeclJson[]
  locals?: Record<string, LocalDeclJson>
  body: BlockJson[]
}

export interface GroupRefBody {
  name: string
  as?: string // required when the group declares locals
  args?: Record<string, ParamValue> // one per declared param
}

/** compute binds a scalar into RunState.bindings; record appends a numeric sample to a
 * DECLARED stream. Both carry a ValueExpr (engine blocks.py:8 — str | int | float | bool),
 * so a bare literal is as legal as an expression string. */
export interface ComputeBody {
  into: string
  value: ParamValue
  as?: string | null // unit cast for the bound value (type-system design 2026-07-21 §6)
}

export interface RecordBody {
  into: string
  value: ParamValue
  as?: string | null // unit cast; must match the target stream's unit
}

/** abort raises AbortSignalError (run status 'aborted'); alarm flags and continues. Both
 * require a non-empty message (engine design 2026-07-16 §2.1/§2.2). */
export interface AbortBody {
  if: string
  message: string
}

export interface AlarmBody {
  if: string
  message: string
}

/** command/measure only (2026-07-14 §2.1). attempts is TOTAL tries, not retries-after-the-
 * first. allow_repeat is the explicit opt-in required to retry a non-idempotent verb. */
export interface RetryJson {
  attempts: number
  backoff?: string
  allow_repeat?: boolean
}

export interface BlockJson {
  label?: string
  gap_after?: string
  start_offset?: string
  retry?: RetryJson
  on_error?: 'fail' | 'continue'
  command?: CommandBody
  measure?: MeasureBody
  operator_input?: OperatorInputBody
  wait?: WaitBody
  serial?: SerialBody
  parallel?: ParallelBody
  loop?: LoopBody
  branch?: BranchBody
  for_each?: ForEachBody
  group_ref?: GroupRefBody
  compute?: ComputeBody
  record?: RecordBody
  abort?: AbortBody
  alarm?: AlarmBody
}

export interface StreamDeclJson {
  units?: string | null
  persistence?: string | null
}

export interface WorkflowJson {
  schema_version: number // now 3 (statically typed, unit-checked; design 2026-07-21)
  metadata?: Record<string, unknown>
  persistence?: Record<string, unknown>
  roles?: Record<string, RoleDeclJson> // roles LIVE HERE now (schema 2)
  streams?: Record<string, StreamDeclJson>
  groups?: Record<string, GroupJson>
  defaults?: { retry?: RetryJson }
  blocks: BlockJson[]
}

// ExperimentDocJson LOSES `roles` (schema 2): roles moved inside the workflow.
export interface ExperimentDocJson {
  doc_version: number
  name: string
  description: string | null
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
