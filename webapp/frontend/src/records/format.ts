/** Record/run time formatting. Statuses use the reserved status palette semantics
 * (good/serious/etc) via Tailwind classes; a chip never carries color alone — the
 * status word is always printed. */

export function formatWhen(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const rest = s % 60
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m ${String(rest).padStart(2, '0')}s`
  if (m > 0) return `${m}m ${rest}s`
  return `${rest}s`
}

export function formatDuration(startedIso: string, endedIso: string | null): string {
  if (endedIso === null) return '—'
  const start = new Date(startedIso).getTime()
  const end = new Date(endedIso).getTime()
  if (Number.isNaN(start) || Number.isNaN(end)) return '—'
  return formatElapsed((end - start) / 1000)
}

export const STATUS_STYLES: Record<string, string> = {
  running: 'bg-blue-100 text-blue-700',
  paused: 'bg-slate-200 text-slate-600',
  completed: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-red-100 text-red-700',
  aborted: 'bg-amber-100 text-amber-700',
  cancelled: 'bg-slate-200 text-slate-600',
  interrupted: 'bg-violet-100 text-violet-700',
}
