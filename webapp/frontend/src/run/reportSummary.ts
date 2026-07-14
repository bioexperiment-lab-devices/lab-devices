import type { RecordReport } from '../types/records'

/** Formats the live-run terminal panel's tolerated-errors line, or null when there are
 * none. A run that dropped samples via on_error: 'continue' still reports status
 * 'completed' — this is what stops it looking identical to a clean run on the LIVE run
 * screen (mirrors RecordViewer.tsx's "N block failure(s) tolerated" panel; design
 * 2026-07-14 §3.4, review Fix 2). */
export function toleratedSummary(report: RecordReport | null): string | null {
  const errors = report?.tolerated_errors ?? []
  if (errors.length === 0) return null
  const list = errors.map((e) => `${e.block_id}: ${e.error}`).join('; ')
  return `${errors.length} block failure(s) tolerated: ${list}`
}
