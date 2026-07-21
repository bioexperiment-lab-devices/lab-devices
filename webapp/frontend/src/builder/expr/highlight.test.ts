import { describe, expect, it } from 'vitest'
import { highlightSpans } from './highlight'

const flat = (text: string, spans = highlightSpans(text, [])) =>
  spans.map((s) => `${s.cls}:${text.slice(s.start, s.end)}${s.underline ? '~' : ''}`)

describe('highlightSpans', () => {
  it('classifies a full expression and tiles the text exactly', () => {
    const text = "mean(od, last=30s) > 0.6 and mode == 'x'"
    const spans = highlightSpans(text, [])
    expect(spans[0]).toMatchObject({ start: 0, end: 4, cls: 'fn' })
    expect(flat(text, spans)).toEqual([
      'fn:mean',
      'op:(',
      'name:od',
      'op:,',
      'plain: ',
      'name:last',
      'op:=',
      'duration:30s',
      'op:)',
      'plain: ',
      'op:>',
      'plain: ',
      'number:0.6',
      'plain: ',
      'keyword:and',
      'plain: ',
      'name:mode',
      'plain: ',
      'op:==',
      'plain: ',
      "string:'x'",
    ])
    expect(spans[0].start).toBe(0)
    expect(spans[spans.length - 1].end).toBe(text.length)
  })
  it('a stat name NOT followed by ( is a plain name; unknown fn is a name too', () => {
    expect(flat('count > 2')[0]).toBe('name:count')
    expect(flat('median(od)')[0]).toBe('name:median')
  })
  it('marks the un-lexable tail as an underlined error span', () => {
    const text = 'od > §3'
    const spans = highlightSpans(text, [])
    const last = spans[spans.length - 1]
    expect(last).toMatchObject({ start: 5, end: 7, cls: 'error', underline: true })
  })
  it('splits spans at underline boundaries', () => {
    const text = 'mean(ph)'
    const spans = highlightSpans(text, [{ pos: 5, len: 2 }])
    expect(flat(text, spans)).toEqual(['fn:mean', 'op:(', 'name:ph~', 'op:)'])
  })
  it('partial underline splits a token', () => {
    const spans = highlightSpans('abcd', [{ pos: 1, len: 2 }])
    expect(spans.map((s) => [s.start, s.end, s.underline])).toEqual([
      [0, 1, false],
      [1, 3, true],
      [3, 4, false],
    ])
  })
  it('clamps stale out-of-range underlines instead of crashing', () => {
    const spans = highlightSpans('od', [{ pos: 1, len: 10 }])
    expect(spans.map((s) => [s.start, s.end, s.underline])).toEqual([
      [0, 1, false],
      [1, 2, true],
    ])
  })
})
