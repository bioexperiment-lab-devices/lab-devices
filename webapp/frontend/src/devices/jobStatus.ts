/** Lenient reader over the raw agent job dict (design §8): the manual tab polls
 * GET …/jobs/{id} and needs the phase, progress, and terminality without assuming an
 * exact field set. Mirrors the library's tolerant models. */

export type JobPhase = 'running' | 'succeeded' | 'failed' | 'cancelled' | 'unknown'

export interface JobClass {
  phase: JobPhase
  progress: number | null
  jobId: string | null
  done: boolean
}

const TERMINAL: JobPhase[] = ['succeeded', 'failed', 'cancelled']

export function classifyJob(result: unknown): JobClass {
  const r = (result ?? {}) as Record<string, unknown>
  const rawStatus =
    typeof r.status === 'string' ? r.status : typeof r.state === 'string' ? r.state : null
  const phase: JobPhase =
    rawStatus === 'running' || rawStatus === 'pending'
      ? 'running'
      : rawStatus === 'succeeded' || rawStatus === 'ok' || rawStatus === 'done'
        ? 'succeeded'
        : rawStatus === 'failed' || rawStatus === 'error'
          ? 'failed'
          : rawStatus === 'cancelled' || rawStatus === 'canceled'
            ? 'cancelled'
            : 'unknown'
  const progress = typeof r.progress === 'number' ? r.progress : null
  const jobId =
    typeof r.job_id === 'string' ? r.job_id : typeof r.id === 'string' ? r.id : null
  return { phase, progress, jobId, done: TERMINAL.includes(phase) }
}
