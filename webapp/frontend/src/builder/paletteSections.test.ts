import { describe, expect, it } from 'vitest'
import { BLOCK_SECTIONS } from './paletteSections'
import { newPaletteNode, type PaletteKind } from './tree'

/** The complete kind→section mapping this suite exists to guard. `Record<Exclude<PaletteKind,
 * 'group_ref'>, string>` makes TypeScript itself force this table to stay exhaustive as
 * `PaletteKind` changes: add, rename, or remove a kind in tree.ts and this literal fails to
 * compile until the table is updated to match — a hand-maintained array cannot do that, only
 * catch a mismatch at test-run time. This also supplies the "every kind except group_ref" list
 * the coverage test below needs, replacing what used to be a separately hand-maintained
 * ALL_KINDS array; keeping both would have been two registries asserting the same fact. */
const EXPECTED_SECTION: Record<Exclude<PaletteKind, 'group_ref'>, string> = {
  serial: 'Flow',
  parallel: 'Flow',
  branch: 'Flow',
  loop: 'Flow',
  for_each: 'Flow',
  compute: 'Data',
  record: 'Data',
  wait: 'Pause',
  operator_input: 'Pause',
  alarm: 'Safety',
  abort: 'Safety',
}

const listed = (): PaletteKind[] => BLOCK_SECTIONS.flatMap((s) => s.items.map((i) => i.kind))

const sectionOf = (k: PaletteKind): string | undefined =>
  BLOCK_SECTIONS.find((s) => s.items.some((i) => i.kind === k))?.title

describe('palette block sections', () => {
  it('covers every palette kind except group_ref', () => {
    expect([...listed()].sort()).toEqual(Object.keys(EXPECTED_SECTION).sort())
  })

  it('never lists a kind in two sections', () => {
    const kinds = listed()
    expect(new Set(kinds).size).toBe(kinds.length)
  })

  it('keeps group_ref out of the block sections', () => {
    expect(listed()).not.toContain('group_ref')
  })

  // Subsumed mechanically by 'assigns every kind to its expected section' below, but kept as
  // its own named test: loop and for_each were the specific pair split across Control and
  // Repeat whose drift motivated this whole re-cut into Flow/Data/Pause/Safety. A test that
  // names that defect is worth more than the duplication costs.
  it('groups loop and for_each together', () => {
    expect(sectionOf('loop')).toBe('Flow')
    expect(sectionOf('for_each')).toBe('Flow')
  })

  it('assigns every kind to its expected section', () => {
    for (const [kind, section] of Object.entries(EXPECTED_SECTION)) {
      expect(sectionOf(kind as PaletteKind)).toBe(section)
    }
  })

  it('gives every chip a non-empty title and a constructible kind', () => {
    for (const s of BLOCK_SECTIONS) {
      expect(s.title).not.toBe('')
      for (const item of s.items) {
        expect(item.title).not.toBe('')
        expect(newPaletteNode(item.kind).kind).toBe(item.kind)
      }
    }
  })
})
