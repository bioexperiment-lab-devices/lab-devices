import { describe, expect, it } from 'vitest'
import { gapAfterEligible } from './inspectorRules'

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
