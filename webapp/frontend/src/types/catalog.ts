/** GET /api/catalog payload (webapp design §4.4): thin serialization of the engine's
 * verb_catalog() and expression_functions(). */

export type ParamKind = 'number' | 'int' | 'string' | 'bool'

export interface ParamSpec {
  name: string
  type: ParamKind
  required: boolean
  // Present when the param is a closed enum: the device accepts exactly these spellings.
  values?: string[]
  // UI-seed hints (webapp design): the Builder seeds `default` and labels the empty option
  // from `on_omit`. Absent when the param has no canonical default / no special omit meaning.
  default?: string | number | boolean
  on_omit?: 'default' | 'unchanged'
}

export interface VerbSpec {
  kind: 'command' | 'measure'
  params: ParamSpec[]
  result_field: string | null
  // False = re-issuing this verb is not idempotent (e.g. pump.dispense's relative volume_ml);
  // the UI must not let a retry be set without an explicit allow_repeat opt-in.
  retry_safe: boolean
}

export interface ExpressionInfo {
  functions: string[]
  windows: string[]
}

export interface Catalog {
  device_types: Record<string, Record<string, VerbSpec>>
  expression: ExpressionInfo
}
