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
