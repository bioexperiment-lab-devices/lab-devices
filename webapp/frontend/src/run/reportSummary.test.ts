import { describe, expect, it } from 'vitest'
import type { RecordReport } from '../types/records'
import { alarmSummary, toleratedSummary } from './reportSummary'

const baseReport: RecordReport = {
  status: 'completed', error: null, finalize_errors: [], persistence_errors: [],
  diagnostics: [], clock_origin: 0, started_at: '', ended_at: '',
  experiment_name: 'OD growth', lab: 'lab_a', role_mapping: {},
}

describe('toleratedSummary', () => {
  it('is null when there is no report', () => {
    expect(toleratedSummary(null)).toBeNull()
  })

  it('is null when tolerated_errors is absent or empty', () => {
    expect(toleratedSummary(baseReport)).toBeNull()
    expect(toleratedSummary({ ...baseReport, tolerated_errors: [] })).toBeNull()
  })

  it('summarizes count and lists block_id: error for each tolerated failure', () => {
    const report: RecordReport = {
      ...baseReport,
      tolerated_errors: [
        { block_id: 'b1', error: 'timeout' },
        { block_id: 'b2', error: 'device offline' },
      ],
    }
    expect(toleratedSummary(report)).toBe(
      '2 block failure(s) tolerated: b1: timeout; b2: device offline',
    )
  })
})

describe('alarmSummary', () => {
  it('is null when there is no report', () => {
    expect(alarmSummary(null)).toBeNull()
  })

  it('is null when alarms is absent or empty', () => {
    expect(alarmSummary(baseReport)).toBeNull()
    expect(alarmSummary({ ...baseReport, alarms: [] })).toBeNull()
  })

  it('summarizes count and lists block_id: message for each alarm', () => {
    const report: RecordReport = {
      ...baseReport,
      alarms: [
        { block_id: 'blocks[0]', message: 'lost' },
      ],
    }
    expect(alarmSummary(report)).toBe('1 alarm(s): blocks[0]: lost')
  })
})
