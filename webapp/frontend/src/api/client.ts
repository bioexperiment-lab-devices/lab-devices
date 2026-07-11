export interface Health {
  status: string
  library: string
  studio: string
}

export async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(path)
  if (!resp.ok) throw new Error(`${path}: HTTP ${resp.status}`)
  return (await resp.json()) as T
}

export const getHealth = () => getJson<Health>('/api/health')
