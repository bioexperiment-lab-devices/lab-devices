import { describe, expect, it } from 'vitest'
import { describeEvent } from './describeEvent'

const d = (kind: string, data: Record<string, unknown> = {}) => describeEvent({ kind, data })

describe('describeEvent', () => {
  it('covers run lifecycle', () => {
    expect(d('run_started')).toBe('run started')
    expect(d('run_finished', { status: 'completed' })).toBe('run finished: completed')
    expect(d('paused')).toBe('run paused')
    expect(d('resumed')).toBe('run resumed')
    expect(d('abort_requested')).toBe('abort requested')
  })
  it('covers block execution', () => {
    expect(d('block_started')).toBe('block started')
    expect(d('block_finished')).toBe('block finished')
    expect(d('block_failed', { error: 'boom' })).toBe('block failed: boom')
    expect(d('invariant_violation', { error: 'busy' })).toBe('invariant violation: busy')
    expect(d('mode_opened', { device: 'thermostat_1', verb: 'hold' })).toBe('thermostat_1: mode hold opened')
    expect(d('mode_closed', { device: 'thermostat_1', verb: 'hold' })).toBe('thermostat_1: mode hold closed')
    expect(d('measure_recorded', { stream: 'od', value: 0.5321 })).toBe('od = 0.5321')
    expect(d('input_requested', { name: 'target' })).toBe("operator input requested: 'target'")
    expect(d('input_bound', { name: 'target', value: 5 })).toBe('target = 5')
  })
  it('covers fault tolerance', () => {
    expect(d('block_retried', { attempt: 1, of: 3, error: 'flaky' }))
      .toBe('retrying (attempt 1/3): flaky')
    // A failed poll is not a failed job: the operator must be able to see that the job kept
    // running and was never re-dispatched.
    expect(d('job_poll_retried', {
      device: 'densitometer_1', job_id: 'j-1', failure: 1, of: 5, error: 'unreachable',
    })).toBe('densitometer_1: poll of job j-1 failed (1/5), still running: unreachable')
    // A run that dropped 40 samples must not look identical to a clean one: this is the
    // event-log side of that guarantee (RunReport.tolerated_errors is the record-level side).
    expect(d('block_error_tolerated', { error: 'no response' }))
      .toBe('tolerated failure: no response')
  })
  it('covers the finalizer', () => {
    expect(d('finalize_started')).toBe('finalize started')
    expect(d('finalize_finished', { errors: 0 })).toBe('finalize finished (0 errors)')
    expect(d('job_cancelled', { device: 'pump_1', verb: 'dispense' })).toBe('pump_1: job dispense cancelled')
    expect(d('teardown_issued', { device: 'pump_1', verb: 'stop' })).toBe('pump_1: teardown stop issued')
    expect(d('sweep_command', { device: 'pump_1', verb: 'stop' })).toBe('pump_1: sweep stop')
    expect(d('finalize_step_failed', { device: 'pump_1', verb: 'stop', error: 'timeout' }))
      .toBe('pump_1: finalize stop failed: timeout')
  })
  it('falls back to kind + data for unknown kinds', () => {
    expect(d('mystery', { a: 1 })).toBe('mystery {"a":1}')
    expect(d('mystery')).toBe('mystery')
  })
})
