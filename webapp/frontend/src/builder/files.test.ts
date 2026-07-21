import { describe, expect, it } from 'vitest'
import type { ExperimentDocJson } from '../types/doc'
import { DocFileError, exportFilename, parseDocFile, serializeDoc } from './files'

const doc = (): ExperimentDocJson => ({
  doc_version: 1,
  name: 'OD growth curve',
  description: null,
  workflow: { schema_version: 2, roles: { feed_pump: { type: 'pump' } }, blocks: [] },
})

describe('exportFilename', () => {
  it('slugs runs of disallowed characters', () => {
    expect(exportFilename('OD growth curve')).toBe('OD_growth_curve.json')
  })

  it('keeps the characters the backend sanitizer keeps', () => {
    expect(exportFilename('morbidostat-demo_speed.v2')).toBe('morbidostat-demo_speed.v2.json')
  })

  it('strips path separators so an export cannot escape the download directory', () => {
    expect(exportFilename('../../etc/passwd')).toBe('etc_passwd.json')
  })

  it('falls back when nothing survives sanitizing', () => {
    expect(exportFilename('')).toBe('experiment.json')
    expect(exportFilename('...')).toBe('experiment.json')
    expect(exportFilename('Морбидостат')).toBe('experiment.json')
  })
})

describe('serializeDoc', () => {
  it('is 2-space indented with a trailing newline', () => {
    const text = serializeDoc(doc())
    expect(text.startsWith('{\n  "doc_version": 1,\n')).toBe(true)
    expect(text.endsWith('}\n')).toBe(true)
  })

  it('preserves the examples/*.json key order', () => {
    expect(Object.keys(JSON.parse(serializeDoc(doc())) as object)).toEqual([
      'doc_version',
      'name',
      'description',
      'workflow',
    ])
  })
})

describe('parseDocFile', () => {
  it('rejects non-JSON with a typed error', () => {
    expect(() => parseDocFile('not json at all')).toThrow(DocFileError)
    expect(() => parseDocFile('')).toThrow(DocFileError)
  })

  it('round-trips a doc through serialize (§8, client half)', () => {
    expect(parseDocFile(serializeDoc(doc()))).toEqual(doc())
  })
})
