import { describe, expect, it } from 'vitest'
import { BLOCK_SECTIONS } from './paletteSections'
import { newPaletteNode, type PaletteKind } from './tree'

/** Every kind `newPaletteNode` can construct. Hand-maintained: TypeScript cannot enumerate a
 * union at runtime. Adding a member to `PaletteKind` means adding it here AND to a section —
 * which is exactly the decision this suite exists to force. */
const ALL_KINDS: PaletteKind[] = [
  'serial', 'parallel', 'branch', 'loop', 'for_each',
  'compute', 'record',
  'wait', 'operator_input',
  'alarm', 'abort',
  'group_ref',
]

const listed = (): PaletteKind[] => BLOCK_SECTIONS.flatMap((s) => s.items.map((i) => i.kind))

describe('palette block sections', () => {
  it('covers every palette kind except group_ref', () => {
    expect([...listed()].sort()).toEqual(ALL_KINDS.filter((k) => k !== 'group_ref').sort())
  })

  it('never lists a kind in two sections', () => {
    const kinds = listed()
    expect(new Set(kinds).size).toBe(kinds.length)
  })

  it('keeps group_ref out of the block sections', () => {
    expect(listed()).not.toContain('group_ref')
  })

  it('groups loop and for_each together', () => {
    const section = (k: PaletteKind) => BLOCK_SECTIONS.find((s) => s.items.some((i) => i.kind === k))?.title
    expect(section('loop')).toBe('Flow')
    expect(section('for_each')).toBe('Flow')
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
