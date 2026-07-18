import { describe, expect, it } from 'vitest'
import { TABS } from '../shell/tabs'
import { useNavStore } from './navStore'

describe('navStore', () => {
  it('lands on Builder, which needs no lab', () => {
    expect(useNavStore.getState().tab).toBe('Builder')
  })

  it('lands on whichever tab is first in the bar', () => {
    expect(useNavStore.getState().tab).toBe(TABS[0])
  })
})
