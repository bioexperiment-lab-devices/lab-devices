/** GET /api/labs and /api/labs/{lab}/devices payloads (webapp design §6). */

export interface LabSummary {
  name: string
  host: string
  port: number
  online: boolean
}

export interface LabDevice {
  id: string
  type: string
  port: string | null
  connected: boolean | null
  model: string | null
  firmware: string | null
  name: string | null
}
