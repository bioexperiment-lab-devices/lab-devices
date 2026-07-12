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
