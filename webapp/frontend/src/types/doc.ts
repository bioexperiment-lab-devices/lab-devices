/** Hand-written TS mirrors of doc v1 + engine workflow schema v1 (webapp design §4.1).
 * The block grammar mirrors the engine serializer: one type key per block plus optional
 * block-level keys label/gap_after/start_offset/retry/on_error (2026-07-14 design). */

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

/** for_each is a SPLICING macro: it copies `body` once per item and splices the copies into the
 * ENCLOSING list, so mode is inherited — sole child of a parallel becomes N lanes; inside a
 * serial, an N-step sequence (engine design 2026-07-15 §2). The JSON key is `in`; the node
 * field is `items` (convert.ts translates, as it already does for branch.if <-> condition). */
export interface ForEachBody {
  var?: string
  in: Array<ParamValue | Record<string, ParamValue>>
  body: BlockJson[]
}

export interface GroupJson {
  params?: string[]
  body: BlockJson[]
}

export interface GroupRefBody {
  name: string
  args?: Record<string, ParamValue>
}

/** compute binds a scalar into RunState.bindings; record appends a numeric sample to a
 * DECLARED stream. Both carry a ValueExpr (engine blocks.py:8 — str | int | float | bool),
 * so a bare literal is as legal as an expression string. */
export interface ComputeBody {
  into: string
  value: ParamValue
}

export interface RecordBody {
  into: string
  value: ParamValue
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
  schema_version: number
  metadata?: Record<string, unknown>
  persistence?: Record<string, unknown>
  streams?: Record<string, StreamDeclJson>
  groups?: Record<string, GroupJson>
  defaults?: { retry?: RetryJson }
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
