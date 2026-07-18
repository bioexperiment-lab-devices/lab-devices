import { describe, expect, it } from 'vitest'
import { failureFields, gapAfterEligible, timingFields } from './inspectorRules'

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
