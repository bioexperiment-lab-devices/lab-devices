import { describe, expect, it } from 'vitest'
import {
  CONSTRUCT_CHROME,
  cardBorderClass,
  headerFillClass,
  interiorFillClass,
  isFlowKind,
} from './constructTint'

describe('isFlowKind', () => {
  it('accepts exactly the five container kinds', () => {
    for (const k of ['serial', 'parallel', 'branch', 'loop', 'for_each'] as const) {
      expect(isFlowKind(k)).toBe(true)
    }
    for (const k of ['command', 'measure', 'wait', 'operator_input', 'compute',
                     'record', 'abort', 'alarm', 'group_ref'] as const) {
      expect(isFlowKind(k)).toBe(false)
    }
  })
})

describe('CONSTRUCT_CHROME', () => {
  // Loop and for_each were byte-identical before this increment; they are the pair
  // most confused at depth, so their hues must be maximally distant, not merely distinct.
  it('gives every construct a distinct border and header', () => {
    const borders = Object.values(CONSTRUCT_CHROME).map((c) => c.border)
    const headers = Object.values(CONSTRUCT_CHROME).map((c) => c.header)
    expect(new Set(borders).size).toBe(5)
    expect(new Set(headers).size).toBe(5)
  })

  // Reserved-hue exclusion (spec §2.1): blue=selection, red=error, amber=warning,
  // emerald=valid. A tint drawn from those families would collide with state.
  it('avoids every reserved state hue', () => {
    const reserved = ['blue', 'indigo', 'sky', 'red', 'rose', 'amber', 'orange',
                      'yellow', 'emerald', 'green']
    for (const { border, header } of Object.values(CONSTRUCT_CHROME)) {
      for (const family of reserved) {
        expect(border).not.toContain(`-${family}-`)
        expect(header).not.toContain(`-${family}-`)
      }
    }
  })
})

describe('cardBorderClass', () => {
  it('emits exactly one border class', () => {
    const cls = cardBorderClass({ kind: 'loop', selected: false })
    expect(cls.split(/\s+/).filter((c) => c.startsWith('border-'))).toHaveLength(1)
  })

  it('gives leaves the neutral card border', () => {
    expect(cardBorderClass({ kind: 'command', selected: false })).toBe('border-slate-300')
  })

  it('gives containers their construct border', () => {
    expect(cardBorderClass({ kind: 'loop', selected: false })).toBe('border-fuchsia-200')
    expect(cardBorderClass({ kind: 'for_each', selected: false })).toBe('border-lime-200')
  })

  // Selection must SELECT the blue border, not append it: an appended class would be an
  // equal-specificity sibling of the construct border and the cascade would decide by
  // stylesheet order, not by intent (W12's text-colour trap, generalised).
  it('selection replaces the construct border for every kind', () => {
    for (const k of ['serial', 'parallel', 'branch', 'loop', 'for_each', 'command'] as const) {
      expect(cardBorderClass({ kind: k, selected: true })).toBe('border-blue-500')
    }
  })
})

describe('headerFillClass', () => {
  it('tints container headers and leaves leaves untinted', () => {
    expect(headerFillClass('branch')).toBe('bg-violet-50')
    expect(headerFillClass('command')).toBe('')
  })
})

describe('interiorFillClass', () => {
  // The ramp excludes bg-white on purpose: leaf cards are white, so a white interior
  // would leave a card visible only by its 1px border at every other level.
  it('alternates between the two slate steps and never emits white', () => {
    expect(interiorFillClass(1)).toBe('bg-slate-50')
    expect(interiorFillClass(2)).toBe('bg-slate-100')
    expect(interiorFillClass(3)).toBe('bg-slate-50')
    expect(interiorFillClass(4)).toBe('bg-slate-100')
    for (let d = 1; d <= 12; d++) expect(interiorFillClass(d)).not.toBe('bg-white')
  })
})
