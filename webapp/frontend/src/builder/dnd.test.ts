import { describe, expect, it } from 'vitest'
import { blockDraggableId, parseSlotDroppableId, slotDroppableId } from './dnd'

describe('slot droppable ids', () => {
  it('round-trips root and container slots', () => {
    const root = { parentUid: null, slot: 'blocks', index: 3 }
    expect(parseSlotDroppableId(slotDroppableId(root))).toEqual(root)
    const nested = { parentUid: 'abc-123', slot: 'children', index: 0 }
    expect(parseSlotDroppableId(slotDroppableId(nested))).toEqual(nested)
  })

  it('rejects non-slot ids', () => {
    expect(parseSlotDroppableId(blockDraggableId('abc'))).toBeNull()
    expect(parseSlotDroppableId('junk')).toBeNull()
  })
})
