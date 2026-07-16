/**
 * Export/import of experiment docs as files (design 2026-07-16 §6).
 *
 * The file IS the bare ExperimentDoc, byte-compatible with examples/*.json.
 * Everything here except triggerDownload is pure and tested in node — the DOM
 * call is deliberately the only untested line, per this app's test convention.
 */
import type { ExperimentDocJson } from '../types/doc'

/** Bad JSON in an imported file. Shape is the server's job, not ours (§6.1). */
export class DocFileError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'DocFileError'
  }
}

/** Mirrors the backend's proven record-download sanitizer (api/records.py:78). */
export function exportFilename(name: string): string {
  const stem = name
    .replace(/[^A-Za-z0-9._-]+/g, '_')
    .replace(/^[._]+|[._]+$/g, '')
  return `${stem || 'experiment'}.json`
}

/** The exported file body: 2-space indent, trailing newline, key order as given (§3). */
export const serializeDoc = (doc: ExperimentDocJson): string =>
  `${JSON.stringify(doc, null, 2)}\n`

/** Parse only. The server's Pydantic model is the single source of truth for shape. */
export function parseDocFile(text: string): ExperimentDocJson {
  try {
    return JSON.parse(text) as ExperimentDocJson
  } catch (e) {
    throw new DocFileError(
      `not a JSON file: ${e instanceof Error ? e.message : String(e)}`
    )
  }
}

/** Browser glue. No branching, no decisions — untested by convention (§6.1). */
export function triggerDownload(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
