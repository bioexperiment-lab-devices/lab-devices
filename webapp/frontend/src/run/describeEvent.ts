/** Human-readable one-liners for engine RunEvents (§9.4 event log). One case per kind
 * emitted by the engine (run.py / execute.py / finalize.py); unknown kinds degrade to
 * `kind {json}` so a future engine event never renders blank. */

interface EventLike {
  kind: string
  data: Record<string, unknown>
}

const s = (v: unknown): string => String(v)

export function describeEvent(e: EventLike): string {
  const d = e.data
  switch (e.kind) {
    case 'run_started': return 'run started'
    case 'run_finished': return `run finished: ${s(d.status)}`
    case 'paused': return 'run paused'
    case 'resumed': return 'run resumed'
    case 'abort_requested': return 'abort requested'
    case 'block_started': return 'block started'
    case 'block_finished': return 'block finished'
    case 'block_failed': return `block failed: ${s(d.error)}`
    case 'invariant_violation': return `invariant violation: ${s(d.error)}`
    case 'mode_opened': return `${s(d.device)}: mode ${s(d.verb)} opened`
    case 'mode_closed': return `${s(d.device)}: mode ${s(d.verb)} closed`
    case 'measure_recorded': return `${s(d.stream)} = ${s(d.value)}`
    case 'binding_computed': return `${s(d.name)} = ${s(d.value)}`
    case 'sample_recorded': return `${s(d.stream)} = ${s(d.value)}`
    case 'input_requested': return `operator input requested: '${s(d.name)}'`
    case 'input_bound': return `${s(d.name)} = ${s(d.value)}`
    case 'finalize_started': return 'finalize started'
    case 'finalize_finished': return `finalize finished (${s(d.errors)} errors)`
    case 'block_retried': return `retrying (attempt ${s(d.attempt)}/${s(d.of)}): ${s(d.error)}`
    case 'block_error_tolerated': return `tolerated failure: ${s(d.error)}`
    // Emitted from execute.py's `finally` when an attempt's job is still physically running
    // but got orphaned and the device-wide stop had to fail closed (an open mode would have
    // been killed): the channels stay held so nothing dispatches on top of the stranded job —
    // degraded but safe, same "surfaced, non-fatal" category as block_error_tolerated.
    case 'job_stranded':
      return `${s(d.device)}: job ${s(d.job_id)} stranded, channels ${s(d.channels)} held`
    case 'job_poll_retried':
      return `${s(d.device)}: poll of job ${s(d.job_id)} failed ` +
        `(${s(d.failure)}/${s(d.of)}), still running: ${s(d.error)}`
    case 'job_cancelled': return `${s(d.device)}: job ${s(d.verb)} cancelled`
    case 'teardown_issued': return `${s(d.device)}: teardown ${s(d.verb)} issued`
    case 'sweep_command': return `${s(d.device)}: sweep ${s(d.verb)}`
    case 'finalize_step_failed':
      return `${s(d.device)}: finalize ${s(d.verb)} failed: ${s(d.error)}`
    default: {
      const extra = Object.keys(d).length > 0 ? ` ${JSON.stringify(d)}` : ''
      return `${e.kind}${extra}`
    }
  }
}
