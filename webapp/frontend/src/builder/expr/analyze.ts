/** Client-side draft analysis (spec §3.4): syntax via the parity-pinned parser, plus
 * known-name checks against the ACTIVE scope and two slot heuristics. Types and units
 * deliberately stay server-side — this file must never grow a copy of the lattice. */
import { parseExpression, type Expr } from './parse'

export type ExpectedType = 'bool' | 'number' | 'int' | 'duration' | 'any'

export interface ExprProblem {
  message: string
  pos: number
  /** 0 = no usable span (at-end parse errors). */
  len: number
}

export interface ExprScope {
  streams: string[]
  bindings: string[]
}

function walk(ast: Expr, scope: ExprScope, out: ExprProblem[]): void {
  switch (ast.t) {
    case 'stat':
      if (!scope.streams.includes(ast.stream)) {
        out.push({
          message: `unknown stream '${ast.stream}'`,
          pos: ast.streamPos,
          len: ast.stream.length,
        })
      }
      return
    case 'binding':
      if (!scope.bindings.includes(ast.name)) {
        out.push({ message: `unknown binding '${ast.name}'`, pos: ast.pos, len: ast.name.length })
      }
      return
    case 'unary':
      walk(ast.operand, scope, out)
      return
    case 'binary':
      walk(ast.left, scope, out)
      walk(ast.right, scope, out)
      return
    default:
      return
  }
}

export function analyzeExpression(
  text: string,
  expected: ExpectedType,
  scope: ExprScope,
): ExprProblem[] {
  if (text.trim() === '') return []
  const result = parseExpression(text)
  if (!result.ok) {
    const { message, pos, atEnd } = result.error
    return [{ message, pos, len: atEnd ? 0 : 1 }]
  }
  const problems: ExprProblem[] = []
  walk(result.ast, scope, problems)
  const ast = result.ast
  if (expected === 'duration' && ast.t === 'const' && typeof ast.value === 'number') {
    problems.push({ message: 'durations need a unit — 30s, not 30', pos: 0, len: text.length })
  }
  if (
    expected === 'int' &&
    ast.t === 'const' &&
    typeof ast.value === 'number' &&
    !Number.isInteger(ast.value)
  ) {
    problems.push({ message: 'expected a whole number', pos: 0, len: text.length })
  }
  return problems
}
