import { describe, expect, it } from 'vitest'
import { describeHealth } from './health'

describe('describeHealth', () => {
  it('reports checking while loading', () => {
    expect(describeHealth(null, null)).toBe('checking backend…')
  })
  it('prefers the error when present', () => {
    expect(describeHealth(null, 'boom')).toBe('backend unreachable: boom')
  })
  it('formats versions when healthy', () => {
    expect(
      describeHealth({ status: 'ok', library: '0.1.1', studio: '0.1.0' }, null),
    ).toBe('backend ok — engine 0.1.1, studio 0.1.0')
  })
})
