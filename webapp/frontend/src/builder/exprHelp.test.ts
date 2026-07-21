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
    expect(help.windowForms.map((w) => w.fragment)).toEqual([null, ', last=5', ', last=30s'])
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
