import { describe, expect, it } from 'vitest'
import { shouldDismiss, type DismissContainer } from './useDismissable'

/** Minimal stand-in for a DOM node — vitest runs in node here, so there is no real one. */
const container = (contains: boolean) => ({ contains: () => contains })
const target = {} as never

describe('shouldDismiss', () => {
  it('dismisses on a pointerdown outside the container', () => {
    expect(shouldDismiss({ type: 'pointerdown', target }, container(false))).toBe(true)
  })

  it('ignores a pointerdown inside the container', () => {
    // Clicking the popover's own content must never close it.
    expect(shouldDismiss({ type: 'pointerdown', target }, container(true))).toBe(false)
  })

  it('dismisses on Escape regardless of where focus is', () => {
    expect(shouldDismiss({ type: 'keydown', key: 'Escape', target }, container(true))).toBe(true)
  })

  it('ignores other keys', () => {
    expect(shouldDismiss({ type: 'keydown', key: 'a', target }, container(false))).toBe(false)
  })

  it('does not dismiss when the container is not mounted yet', () => {
    expect(shouldDismiss({ type: 'pointerdown', target }, null)).toBe(false)
  })
})

const containerOf = (members: Set<unknown>): DismissContainer => ({
  contains: (n) => members.has(n),
})

describe('shouldDismiss with a composite container (portal popovers)', () => {
  const inTrigger = {} as Node
  const inPortal = {} as Node
  const outside = {} as Node
  const composite: DismissContainer = {
    contains: (n) =>
      containerOf(new Set([inTrigger])).contains(n) || containerOf(new Set([inPortal])).contains(n),
  }
  it('keeps open for pointerdown inside either part', () => {
    expect(shouldDismiss({ type: 'pointerdown', target: inTrigger }, composite)).toBe(false)
    expect(shouldDismiss({ type: 'pointerdown', target: inPortal }, composite)).toBe(false)
  })
  it('dismisses for pointerdown outside both', () => {
    expect(shouldDismiss({ type: 'pointerdown', target: outside }, composite)).toBe(true)
  })
})
