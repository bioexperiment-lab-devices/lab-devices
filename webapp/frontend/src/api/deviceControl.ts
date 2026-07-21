/** Manual device-control endpoints (webapp design §6): a thin generic command passthrough
 * plus a job-status poll. The catalog (src/devices/catalog.ts) decides which commands are
 * jobs; this module just carries the wire calls. */
import { getJson, postJson } from './client'

export interface CommandResult {
  result: unknown
}

export const runCommand = (
  lab: string,
  id: string,
  cmd: string,
  params: Record<string, unknown> | null,
) =>
  postJson<CommandResult>(
    `/api/labs/${encodeURIComponent(lab)}/devices/${encodeURIComponent(id)}/command`,
    { cmd, params },
  )

export const pollJob = (lab: string, id: string, jobId: string) =>
  getJson<CommandResult>(
    `/api/labs/${encodeURIComponent(lab)}/devices/${encodeURIComponent(id)}/jobs/${encodeURIComponent(jobId)}`,
  )
