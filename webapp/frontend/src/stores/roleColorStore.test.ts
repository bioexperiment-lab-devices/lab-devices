import { beforeEach, describe, expect, it } from 'vitest'
import { useRoleColorStore } from './roleColorStore'

const store = () => useRoleColorStore.getState()

beforeEach(() => {
  // load() degrades to {} under Node (no localStorage) anyway, but reset explicitly so
  // tests never leak overrides into one another regardless of run order.
  useRoleColorStore.setState({ overrides: {} })
})

describe('roleColorStore', () => {
  it('setColor stores the class string under the key', () => {
    store().setColor('feed_pump', 'bg-blue-100')
    expect(store().overrides.feed_pump).toBe('bg-blue-100')
  })

  it('clearColor stores an explicit null — the key exists, it is not merely absent', () => {
    store().clearColor('feed_pump')
    expect(store().overrides).toHaveProperty('feed_pump')
    expect(store().overrides.feed_pump).toBeNull()
  })

  it('resetColor deletes the key entirely — the key is absent, not set to null', () => {
    store().setColor('feed_pump', 'bg-blue-100')
    store().resetColor('feed_pump')
    expect(store().overrides).not.toHaveProperty('feed_pump')
    expect(Object.keys(store().overrides)).not.toContain('feed_pump')
  })

  it('resetColor on a never-set key is a no-op, not an accidental clearColor', () => {
    store().resetColor('feed_pump')
    expect(store().overrides).not.toHaveProperty('feed_pump')
  })

  it('distinguishes clearColor from resetColor — swapping the two implementations must ' +
    'fail this test', () => {
    store().clearColor('feed_pump')
    // explicit null: key present, value null ("plain white card")
    expect('feed_pump' in store().overrides).toBe(true)
    expect(store().overrides.feed_pump).toBeNull()

    store().resetColor('feed_pump')
    // deleted: key absent ("positional auto-assignment")
    expect('feed_pump' in store().overrides).toBe(false)
  })

  it('setColor and clearColor only touch the given key, leaving others untouched', () => {
    store().setColor('a', 'bg-blue-100')
    store().setColor('b', 'bg-green-100')
    store().clearColor('a')
    expect(store().overrides).toEqual({ a: null, b: 'bg-green-100' })
  })
})
