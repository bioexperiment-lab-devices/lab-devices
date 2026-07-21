import { describe, expect, it } from 'vitest'
import { labScopedTab, TABS } from './tabs'

describe('TABS', () => {
  // Builder first is the whole point: a workflow is authored and validated with no lab in
  // mind, so authoring — not lab selection — is the first thing a user sees.
  it('orders the tabs Builder, Labs, Devices, Run, Records', () => {
    expect([...TABS]).toEqual(['Builder', 'Labs', 'Devices', 'Run', 'Records'])
  })
})

describe('labScopedTab', () => {
  it('marks Run, and only Run, as lab-scoped', () => {
    expect(TABS.filter((t) => labScopedTab(t))).toEqual(['Run'])
  })

  it('does not mark Builder — the builder never reads lab state', () => {
    expect(labScopedTab('Builder')).toBe(false)
  })

  // Records lists every record regardless of lab and already shows a per-row lab column
  // (RecordsTable.tsx), so a global lab pill there would assert a filter that does not exist.
  it('does not mark Records — the records table is not filtered by lab', () => {
    expect(labScopedTab('Records')).toBe(false)
  })
})
