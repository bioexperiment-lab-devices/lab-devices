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
