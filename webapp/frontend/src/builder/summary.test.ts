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

  it('appends a compact marker when retry / on_error: continue is set, otherwise nothing', () => {
    const withRetry: BlockNode = {
      uid: 'x', kind: 'command', device: 'feed_pump', verb: 'stop', params: {}, ...base,
      retry: { attempts: 3 },
    }
    expect(blockSummary(withRetry)).toBe('▸ feed_pump · stop R×3')

    const withOnError: BlockNode = { uid: 'x', kind: 'wait', duration: '1s', ...base, onError: 'continue' }
    expect(blockSummary(withOnError)).toBe('⏱ wait 1s ⤳')

    const withBoth: BlockNode = {
      uid: 'x', kind: 'measure', device: 'od_meter', verb: 'measure', into: 'od', params: {}, ...base,
      retry: { attempts: 2 }, onError: 'continue',
    }
    expect(blockSummary(withBoth)).toBe('◉ od_meter · measure → od R×2 ⤳')

    const plain: BlockNode = { uid: 'x', kind: 'wait', duration: '1s', ...base }
    expect(blockSummary(plain)).toBe('⏱ wait 1s')
  })

  it('the retry marker never collides with the loop block glyph, even when a loop retries', () => {
    // A retrying loop is the exact case that motivated the marker change (2026-07-14
    // review, Fix 5): `↻ Loop ×3 ↻2` was unreadable — two near-identical arrows.
    const retryingLoop: BlockNode = {
      uid: 'x', kind: 'loop', mode: 'count', count: 3, until: '', check: 'after', pace: null, body: [],
      ...base, retry: { attempts: 2 },
    }
    expect(blockSummary(retryingLoop)).toBe('↻ Loop ×3 R×2')
  })
})
