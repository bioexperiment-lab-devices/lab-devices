import { describe, expect, it } from 'vitest'
import { classifyJob } from './jobStatus'

describe('classifyJob', () => {
  it('reads a running job with progress', () => {
    expect(classifyJob({ job_id: 'j1', status: 'running', progress: 0.4 })).toEqual({
      phase: 'running',
      progress: 0.4,
      jobId: 'j1',
      done: false,
    })
  })

  it('marks succeeded/failed/cancelled as done', () => {
    expect(classifyJob({ status: 'succeeded' }).done).toBe(true)
    expect(classifyJob({ status: 'failed' }).done).toBe(true)
    expect(classifyJob({ status: 'cancelled' }).done).toBe(true)
  })

  it('unknown shape is unknown+not-done with null progress', () => {
    expect(classifyJob({})).toEqual({ phase: 'unknown', progress: null, jobId: null, done: false })
    expect(classifyJob(null)).toEqual({ phase: 'unknown', progress: null, jobId: null, done: false })
  })

  it('accepts state as an alias for status and id for job_id', () => {
    const c = classifyJob({ id: 'j2', state: 'running' })
    expect(c.jobId).toBe('j2')
    expect(c.phase).toBe('running')
  })
})
