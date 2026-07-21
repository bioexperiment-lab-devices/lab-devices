import { describe, expect, it } from 'vitest'
import { blockSummary, blockSummaryParts, formatParams } from './summary'
import { newPaletteNode } from './tree'
import type { BlockNode } from './tree'

const base = { label: null, gapAfter: null, startOffset: null }

/** One fixture per BlockNode kind (14 total), for tests that must cover every kind rather than
 * pick a handful. `command` uses device `pump1` / verb `dispense` — pinned by the
 * blockSummaryParts subject/verb split test below. The 11 palette kinds that `newPaletteNode`
 * can build come from there; `command`, `measure` and `group_ref` are hand-written because
 * `newPaletteNode` either can't build them (command/measure need a device+verb from the
 * catalog) or would leave them empty in a way that's awkward to assert on (a blank group_ref). */
const ALL_KIND_FIXTURES: BlockNode[] = [
  { uid: 'x', kind: 'command', device: 'pump1', verb: 'dispense', params: { volume_ml: 5 }, ...base },
  { uid: 'x', kind: 'measure', device: 'od_meter', verb: 'measure', into: 'od', params: {}, ...base },
  { uid: 'x', kind: 'group_ref', name: 'service', as: null, args: { tube: 1 }, ...base },
  newPaletteNode('serial'),
  newPaletteNode('parallel'),
  newPaletteNode('branch'),
  newPaletteNode('loop'),
  newPaletteNode('for_each'),
  newPaletteNode('compute'),
  newPaletteNode('record'),
  newPaletteNode('wait'),
  newPaletteNode('operator_input'),
  newPaletteNode('alarm'),
  newPaletteNode('abort'),
]

describe('formatParams', () => {
  it('shows up to two params and an ellipsis beyond', () => {
    expect(formatParams({})).toBe('')
    expect(formatParams({ volume_ml: 5 })).toBe('volume_ml=5')
    expect(formatParams({ a: 1, b: 'cw', c: true })).toBe('a=1, b=cw, …')
  })
})

describe('blockSummary', () => {
  it('describes each block kind', () => {
    const cases: Array<[BlockNode, string]> = [
      [{ uid: 'x', kind: 'command', device: 'feed_pump', verb: 'dispense', params: { volume_ml: 5 }, ...base },
        'feed_pump · dispense (volume_ml=5)'],
      [{ uid: 'x', kind: 'measure', device: 'od_meter', verb: 'measure', into: 'od', params: {}, ...base },
        'od_meter · measure → od'],
      [{ uid: 'x', kind: 'measure', device: 'od_meter', verb: 'measure', into: '', params: {}, ...base },
        'od_meter · measure → ?'],
      [{ uid: 'x', kind: 'wait', duration: '30s', ...base }, 'wait 30s'],
      [{ uid: 'x', kind: 'operator_input', name: 'feed_ml', inputType: 'float', prompt: null, min: null, max: null, choices: null, ...base },
        'input feed_ml (float)'],
      [{ uid: 'x', kind: 'serial', children: [], ...base }, 'Serial · 0'],
      [{ uid: 'x', kind: 'parallel', children: [], ...base }, 'Parallel · 0 lanes'],
      [{ uid: 'x', kind: 'loop', mode: 'count', count: 3, until: '', check: 'after', pace: null, body: [], ...base },
        'Loop ×3'],
      [{ uid: 'x', kind: 'loop', mode: 'until', count: 2, until: 'mean(od, last=3) > 0.6', check: 'after', pace: null, body: [], ...base },
        'Loop until mean(od, last=3) > 0.6'],
      [{ uid: 'x', kind: 'branch', condition: '', then: [], else: null, ...base }, 'If …'],
    ]
    for (const [node, expected] of cases) expect(blockSummary(node)).toBe(expected)
  })

  it('appends a compact marker when retry / on_error: continue is set, otherwise nothing', () => {
    const withRetry: BlockNode = {
      uid: 'x', kind: 'command', device: 'feed_pump', verb: 'stop', params: {}, ...base,
      retry: { attempts: 3 },
    }
    expect(blockSummary(withRetry)).toBe('feed_pump · stop R×3')

    const withOnError: BlockNode = { uid: 'x', kind: 'wait', duration: '1s', ...base, onError: 'continue' }
    expect(blockSummary(withOnError)).toBe('wait 1s ⤳')

    const withBoth: BlockNode = {
      uid: 'x', kind: 'measure', device: 'od_meter', verb: 'measure', into: 'od', params: {}, ...base,
      retry: { attempts: 2 }, onError: 'continue',
    }
    expect(blockSummary(withBoth)).toBe('od_meter · measure → od R×2 ⤳')

    const plain: BlockNode = { uid: 'x', kind: 'wait', duration: '1s', ...base }
    expect(blockSummary(plain)).toBe('wait 1s')
  })

  it('the retry marker never collides with the loop block glyph, even when a loop retries', () => {
    // A retrying loop is the exact case that motivated the marker change (2026-07-14
    // review, Fix 5): `↻ Loop ×3 ↻2` was unreadable — two near-identical arrows.
    const retryingLoop: BlockNode = {
      uid: 'x', kind: 'loop', mode: 'count', count: 3, until: '', check: 'after', pace: null, body: [],
      ...base, retry: { attempts: 2 },
    }
    expect(blockSummary(retryingLoop)).toBe('Loop ×3 R×2')
  })

  it('summarises control blocks', () => {
    expect(blockSummary({ uid: 'u', kind: 'compute', into: 'c', value: 'c * 0.9', ...base })).toBe(
      'c = c * 0.9',
    )
    expect(blockSummary({ uid: 'u', kind: 'record', into: 'c_series', value: 'c', ...base })).toBe(
      'c_series ← c',
    )
    expect(
      blockSummary({ uid: 'u', kind: 'abort', condition: 'estop', message: 'stop', ...base }),
    ).toBe('Abort if estop')
    expect(
      blockSummary({ uid: 'u', kind: 'alarm', condition: 'od > 2', message: 'bad', ...base }),
    ).toBe('Alarm if od > 2')
  })

  it('shows a placeholder for an unfilled control block and keeps the fault marker', () => {
    expect(blockSummary({ uid: 'u', kind: 'compute', into: '', value: '', ...base })).toBe('? = …')
    expect(
      blockSummary({
        uid: 'u',
        kind: 'alarm',
        condition: 'x',
        message: 'm',
        onError: 'continue',
        ...base,
      }),
    ).toBe('Alarm if x ⤳')
  })

  it('summarises repetition blocks', () => {
    expect(
      blockSummary({ uid: 'u', kind: 'for_each', vars: [{ name: 'tube', kind: 'int' }], rows: [{ tube: 1 }, { tube: 2 }, { tube: 3 }], body: [], ...base }),
    ).toBe('For each tube × 3')
    expect(
      blockSummary({ uid: 'u', kind: 'for_each', vars: [{ name: 'tube', kind: 'int' }, { name: 'od', kind: 'stream' }], rows: [{ tube: 1, od: 'od_1' }, { tube: 2, od: 'od_2' }], body: [], ...base }),
    ).toBe('For each tube, od × 2')
    expect(blockSummary({ uid: 'u', kind: 'group_ref', name: 'service', as: null, args: { tube: 1 }, ...base })).toBe(
      'service(tube=1)',
    )
    expect(blockSummary({ uid: 'u', kind: 'group_ref', name: 'wash', as: null, args: {}, ...base })).toBe('wash')
  })
})

/** blockSummary(node) pinned against hand-written expected strings, for all 14 BlockNode
 * kinds plus the two alternate forms that ALL_KIND_FIXTURES can't reach (newPaletteNode
 * always builds `loop` as mode:'count' and `for_each` with a non-null `var`), plus a
 * fault-marker case. This is the real safety net for the parts/join refactor: `blockSummary`
 * IS `blockSummaryParts(node).map(s => s.text).join('')`, so comparing that join back to
 * `blockSummary(node)` — as the previous version of this test did — is tautological and can
 * never catch a broken segment (2026-07-18 review). The expected strings here are literals,
 * derived by hand from reading blockSummaryParts, not computed from it.
 *
 * The last entry pins the fault marker's OWN leading space: `faultMarker` returns `' R×3'`
 * (with the space), not `'R×3'` — losing that space would be an invisible regression since
 * nothing else in the command case supplies a separator before the marker segment. */
const PINNED_SUMMARIES: Array<[BlockNode, string]> = [
  [{ uid: 'x', kind: 'command', device: 'pump1', verb: 'dispense', params: { volume_ml: 5 }, ...base },
    'pump1 · dispense (volume_ml=5)'],
  [{ uid: 'x', kind: 'measure', device: 'od_meter', verb: 'measure', into: 'od', params: {}, ...base },
    'od_meter · measure → od'],
  [{ uid: 'x', kind: 'group_ref', name: 'service', as: null, args: { tube: 1 }, ...base },
    'service(tube=1)'],
  [{ uid: 'x', kind: 'serial', children: [], ...base },
    'Serial · 0'],
  [{ uid: 'x', kind: 'parallel', children: [
      { uid: 'a', kind: 'serial', children: [], ...base },
      { uid: 'b', kind: 'serial', children: [], ...base },
    ], ...base },
    'Parallel · 2 lanes'],
  [{ uid: 'x', kind: 'branch', condition: '', then: [], else: [], ...base },
    'If …'],
  [{ uid: 'x', kind: 'loop', mode: 'count', count: 2, until: '', check: 'after', pace: null, body: [], ...base },
    'Loop ×2'],
  [{ uid: 'x', kind: 'for_each', vars: [{ name: 'tube', kind: 'int' }], rows: [{ tube: 1 }, { tube: 2 }, { tube: 3 }], body: [], ...base },
    'For each tube × 3'],
  [{ uid: 'x', kind: 'compute', into: '', value: '', ...base },
    '? = …'],
  [{ uid: 'x', kind: 'record', into: '', value: '', ...base },
    '? ← …'],
  [{ uid: 'x', kind: 'wait', duration: '1s', ...base },
    'wait 1s'],
  [{ uid: 'x', kind: 'operator_input', name: 'value', inputType: 'float', prompt: null, min: null, max: null, choices: null, ...base },
    'input value (float)'],
  [{ uid: 'x', kind: 'alarm', condition: '', message: '', ...base },
    'Alarm if …'],
  [{ uid: 'x', kind: 'abort', condition: '', message: '', ...base },
    'Abort if …'],
  // Alternate forms newPaletteNode never reaches — the coverage gap noted in review. The
  // multi-var for_each exercises the comma-joined var-name list a single-var palette default
  // never reaches.
  [{ uid: 'x', kind: 'loop', mode: 'until', count: 2, until: 'mean(od, last=3) > 0.6', check: 'after', pace: null, body: [], ...base },
    'Loop until mean(od, last=3) > 0.6'],
  [{ uid: 'x', kind: 'for_each', vars: [{ name: 'tube', kind: 'int' }, { name: 'od', kind: 'stream' }], rows: [{ tube: 1, od: 'od_1' }, { tube: 2, od: 'od_2' }], body: [], ...base },
    'For each tube, od × 2'],
  // Fault marker on a kind that otherwise has no trailing detail segment — pins the marker's
  // own leading space.
  [{ uid: 'x', kind: 'command', device: 'pump1', verb: 'dispense', params: {}, ...base, retry: { attempts: 3 } },
    'pump1 · dispense R×3'],
]

describe('blockSummaryParts', () => {
  // blockSummary feeds the `title` attribute, the drag overlay and WorkflowSnapshot. If the
  // join ever drifts from the string those three silently disagree with the card.
  it('matches hardcoded expected strings for every kind, including alternate forms', () => {
    for (const [node, expected] of PINNED_SUMMARIES) {
      expect(blockSummary(node)).toBe(expected)
    }
  })

  // Every kind that emits a `subject` segment, with the exact text expected under each role.
  //
  // The join test above CANNOT catch a mis-tagged segment, and that is the whole reason this
  // table exists: swapping `measure`'s `seg(node.device, 'subject')` / `seg(node.verb, 'verb')`
  // tags reproduces 'od_meter · measure → od' byte-for-byte and leaves the entire rest of this
  // suite green, while rendering every measure card on the canvas with the device and the verb
  // emphasised the wrong way round (Canvas weights the roles differently, design §3.4). This
  // table was mutation-verified against exactly that swap.
  //
  // Every fixture uses DISTINCT, non-empty subject and verb text on purpose — a fixture whose
  // subject is '' or equal to its verb would make the assertion pass under the swap it exists
  // to catch. The non-vacuity test below enforces that.
  const SUBJECT_VERB_TAGS: Array<{
    node: BlockNode
    subject: string[]
    verb: string[]
  }> = [
    { node: { uid: 'x', kind: 'command', device: 'pump1', verb: 'dispense', params: { volume_ml: 5 }, ...base },
      subject: ['pump1'], verb: ['dispense'] },
    { node: { uid: 'x', kind: 'measure', device: 'od_meter', verb: 'measure', into: 'od', params: {}, ...base },
      subject: ['od_meter'], verb: ['measure'] },
    { node: { uid: 'x', kind: 'operator_input', name: 'feed_ml', inputType: 'float', prompt: null, min: null, max: null, choices: null, ...base },
      subject: ['feed_ml'], verb: ['input'] },
    { node: { uid: 'x', kind: 'compute', into: 'ratio', value: 'od / blank', ...base },
      subject: ['ratio'], verb: [] },
    { node: { uid: 'x', kind: 'record', into: 'od_log', value: 'od', ...base },
      subject: ['od_log'], verb: [] },
    // Schema 2: for_each no longer emits a `subject` segment (its summary is 'For each' +
    // detail only), so it is deliberately absent from this subject-tag table.
    { node: { uid: 'x', kind: 'group_ref', name: 'service', as: null, args: { tube: 1 }, ...base },
      subject: ['service'], verb: [] },
  ]

  const textsWithRole = (node: BlockNode, role: string) =>
    blockSummaryParts(node).filter((p) => p.role === role).map((p) => p.text)

  it('tags subject and verb segments for every kind that emits a subject', () => {
    for (const { node, subject, verb } of SUBJECT_VERB_TAGS) {
      expect(textsWithRole(node, 'subject'), `${node.kind} subject`).toEqual(subject)
      expect(textsWithRole(node, 'verb'), `${node.kind} verb`).toEqual(verb)
    }
  })

  it('covers every subject-emitting kind, with fixtures a tag swap cannot survive', () => {
    // Non-vacuity: each expectation must actually distinguish the two roles.
    for (const { node, subject, verb } of SUBJECT_VERB_TAGS) {
      expect(subject.length, `${node.kind} must emit a subject`).toBeGreaterThan(0)
      expect(subject.some((s) => s === ''), `${node.kind} subject must not be blank`).toBe(false)
      expect(subject.some((s) => verb.includes(s)), `${node.kind} subject must differ from its verb`).toBe(false)
    }
    // Coverage: no kind may emit a subject without appearing in the table above.
    const tabled = new Set(SUBJECT_VERB_TAGS.map((c) => c.node.kind))
    for (const node of ALL_KIND_FIXTURES) {
      if (textsWithRole(node, 'subject').length > 0) expect(tabled).toContain(node.kind)
    }
  })

  it('marks the fault marker as its own segment', () => {
    const node = { ...ALL_KIND_FIXTURES.find((n) => n.kind === 'command')!,
                   onError: 'continue' as const }
    const marker = blockSummaryParts(node).filter((p) => p.role === 'marker')
    expect(marker).toHaveLength(1)
    expect(marker[0].text).toContain('⤳')
  })

  it('emits no marker segment when neither retry nor on_error is set', () => {
    const node = ALL_KIND_FIXTURES.find((n) => n.kind === 'wait')!
    expect(blockSummaryParts(node).filter((p) => p.role === 'marker')).toHaveLength(0)
  })
})
