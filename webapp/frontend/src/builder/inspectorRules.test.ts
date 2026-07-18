import { describe, expect, it } from 'vitest'
import {
  failureFields,
  failureSummary,
  gapAfterEligible,
  timingFields,
  timingSummary,
} from './inspectorRules'
import type { BlockNode } from './tree'
import type { RetryJson } from '../types/doc'

describe('gapAfterEligible', () => {
  it('is true wherever the engine honors gap_after (execute.py:451 shared runner)', () => {
    expect(gapAfterEligible('wait', null)).toBe(true) // top level
    expect(gapAfterEligible('wait', 'serial')).toBe(true)
    expect(gapAfterEligible('abort', 'loop')).toBe(true) // audit F5: loop body child
    expect(gapAfterEligible('wait', 'branch')).toBe(true) // audit F5: then/else child
    expect(gapAfterEligible('wait', 'for_each')).toBe(true) // expand.py: "put it on the body blocks"
  })
  it('is false where the engine rejects or ignores it', () => {
    expect(gapAfterEligible('for_each', null)).toBe(false) // validate.py rejects on the block itself
    expect(gapAfterEligible('for_each', 'serial')).toBe(false)
    expect(gapAfterEligible('wait', 'parallel')).toBe(false) // lanes have no "next"
  })
})

describe('timingFields', () => {
  it('offers gap after wherever the shared runner honors it', () => {
    expect(timingFields('wait', null)).toEqual(['gapAfter'])
    expect(timingFields('wait', 'serial')).toEqual(['gapAfter'])
    expect(timingFields('command', 'loop')).toEqual(['gapAfter'])
  })
  it('offers start offset only to a child of a parallel, which has no next-in-list', () => {
    expect(timingFields('wait', 'parallel')).toEqual(['startOffset'])
    expect(timingFields('serial', 'parallel')).toEqual(['startOffset'])
  })
  it('offers nothing for for_each, a splice with no runtime block to carry the keys', () => {
    // expand.py:26 _FOR_EACH_FORBIDDEN — an empty list means the section does not render.
    expect(timingFields('for_each', null)).toEqual([])
    expect(timingFields('for_each', 'parallel')).toEqual([])
  })
})

describe('failureFields', () => {
  it('offers on error plus retry to the two device-touching kinds', () => {
    expect(failureFields('command')).toEqual(['onError', 'retry'])
    expect(failureFields('measure')).toEqual(['onError', 'retry'])
  })
  it('offers on error alone to every other kind that can tolerate a failure', () => {
    expect(failureFields('wait')).toEqual(['onError'])
    expect(failureFields('alarm')).toEqual(['onError'])
    expect(failureFields('parallel')).toEqual(['onError'])
    // group_ref is NOT restricted — only for_each appears in _FOR_EACH_FORBIDDEN.
    expect(failureFields('group_ref')).toEqual(['onError'])
  })
  it('offers nothing to abort or for_each, so neither renders the section', () => {
    // abort: tolerating a safety stop is a contradiction (engine design 2026-07-16 §5.1).
    expect(failureFields('abort')).toEqual([])
    // for_each: expand.py:26 forbids retry and on_error along with the timing keys.
    expect(failureFields('for_each')).toEqual([])
  })
})

/** Minimal NodeBase-shaped fixture. The parameter is spelled out field by field rather than
 * as `Partial<BlockNode>`: BlockNode is a union, and both `Partial` and `Pick` distribute
 * over unions, so the derived type would admit a `kind: 'wait'` carrying a Command's payload.
 * These tests exercise only the block-level keys every kind shares, so the explicit shape is
 * both safer and clearer. The cast is confined to this one boundary. */
const node = (over: {
  kind: BlockNode['kind']
  gapAfter?: string | null
  startOffset?: string | null
  onError?: 'fail' | 'continue'
  retry?: RetryJson
}): BlockNode =>
  ({ uid: 'u1', label: null, gapAfter: null, startOffset: null, ...over }) as BlockNode

describe('timingSummary', () => {
  it('is null when nothing is set, which is what keeps the section collapsed', () => {
    expect(timingSummary(node({ kind: 'wait' }), null)).toBeNull()
  })
  it('names each set value so a collapsed section still shows what it holds', () => {
    expect(timingSummary(node({ kind: 'wait', gapAfter: '30s' }), null)).toBe('gap after 30s')
    expect(timingSummary(node({ kind: 'wait', startOffset: '5min' }), 'parallel')).toBe('start +5min')
    expect(
      timingSummary(node({ kind: 'wait', gapAfter: '30s', startOffset: '5min' }), 'parallel'),
    ).toBe('start +5min')
  })
  it('ignores a value whose field this section does not render', () => {
    // gapAfter survives in the doc when a block is moved into a parallel lane, but the
    // section has no control for it there — advertising it would point at nothing.
    expect(timingSummary(node({ kind: 'wait', gapAfter: '30s' }), 'parallel')).toBeNull()
    // Mirror case: startOffset is eligible only under a parallel, so a value left on a
    // block that has since moved to top level must not be advertised either.
    expect(timingSummary(node({ kind: 'wait', startOffset: '5min' }), null)).toBeNull()
  })
})

describe('failureSummary', () => {
  it('is null at the engine default (on_error: fail, no retry)', () => {
    expect(failureSummary(node({ kind: 'command' }))).toBeNull()
    expect(failureSummary(node({ kind: 'command', onError: 'fail' }))).toBeNull()
  })
  it('reports a tolerated failure and the retry count', () => {
    expect(failureSummary(node({ kind: 'command', onError: 'continue' }))).toBe('continue')
    expect(failureSummary(node({ kind: 'command', retry: { attempts: 3 } }))).toBe('retry ×3')
    expect(
      failureSummary(node({ kind: 'command', onError: 'continue', retry: { attempts: 3 } })),
    ).toBe('continue, retry ×3')
  })
  it('ignores a retry left on a kind that does not render the control', () => {
    expect(failureSummary(node({ kind: 'wait', retry: { attempts: 3 } }))).toBeNull()
  })
})
