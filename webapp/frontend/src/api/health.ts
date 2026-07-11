import type { Health } from './client'

export function describeHealth(health: Health | null, error: string | null): string {
  if (error) return `backend unreachable: ${error}`
  if (!health) return 'checking backend…'
  return `backend ok — engine ${health.library}, studio ${health.studio}`
}
