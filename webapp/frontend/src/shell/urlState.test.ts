import { describe, expect, it } from 'vitest'
import { formatHash, parseHash } from './urlState'
import { EMPTY_URL_STATE, type UrlState } from './bootstrap'
import { TABS } from './tabs'

const st = (over: Partial<UrlState> = {}): UrlState => ({ ...EMPTY_URL_STATE, ...over })

// Declared ABOVE the describe blocks that read it. Test bodies run after the module has
// finished evaluating, so a `const` below them would happen to work; but `it.each`'s own
// argument arrays are evaluated during collection, so anything derived from this set at
// registration time would hit the temporal dead zone. Keeping it above removes the trap,
// and deriving it from TABS keeps one source of truth for the tab list.
const TABS_SET = new Set<string>(TABS)

describe('parseHash', () => {
  it.each([
    ['', st()],
    ['#', st()],
    ['#/', st()],
    ['#/builder', st()],
    ['#/run', st({ tab: 'Run' })],
    ['#/labs', st({ tab: 'Labs' })],
    ['#/devices', st({ tab: 'Devices' })],
    ['#/records', st({ tab: 'Records' })],
    ['#/records/rec_99', st({ tab: 'Records', rec: 'rec_99' })],
    ['#/builder?exp=a1b2', st({ exp: 'a1b2' })],
    ['#/builder?exp=a1b2&scope=dose', st({ exp: 'a1b2', scope: 'dose' })],
    [
      '#/builder?exp=a1b2&sel=blocks%5B0%5D.children%5B2%5D',
      st({ exp: 'a1b2', sel: 'blocks[0].children[2]' }),
    ],
  ])('parses %j', (hash, expected) => {
    expect(parseHash(hash)).toEqual(expected)
  })

  // A record id is a path segment, so it is percent-encoded on the way out and must be
  // decoded on the way back in — otherwise an id with any reserved character round-trips
  // into a different id that still looks plausible.
  it('decodes a percent-encoded record id', () => {
    expect(parseHash('#/records/rec%20a%23b')).toEqual(st({ tab: 'Records', rec: 'rec a#b' }))
  })

  // The rec segment qualifies the Records view only. Carrying it under another tab would
  // let formatHash and parseHash disagree about what a Builder URL means.
  it('ignores a stray path segment under a non-Records tab', () => {
    expect(parseHash('#/builder/rec_99')).toEqual(st())
  })

  it('is case-insensitive on the tab slug', () => {
    expect(parseHash('#/RUN').tab).toBe('Run')
  })

  // Regression: the parser splits on the FIRST '?' via `raw.indexOf('?')`, not
  // `raw.split('?', 2)` — the latter's split limit truncates the result array instead of
  // merging the remainder, so it silently discards everything after a second '?'. A
  // hand-edited URL is exactly where a stray extra '?' shows up, and URLSearchParams then
  // treats it as a literal character in the `exp` value rather than a delimiter.
  it('keeps everything after a second "?" in the query instead of discarding it', () => {
    expect(parseHash('#/builder?exp=a1b2?extra=zzz')).toEqual(st({ exp: 'a1b2?extra=zzz' }))
  })

  // Totality: a hand-edited or truncated URL must land on a usable screen, never throw.
  it.each([
    '#/nope',
    '#/BUILDER/x/y/z',
    '#?????',
    '#/builder?exp',
    '#/builder?=&&=',
    '#/records/%',
    '#/builder?sel=%E0%A4%A',
    '#//////',
    'builder?exp=a1b2',
  ])('degrades %j to a usable state without throwing', (hash) => {
    expect(() => parseHash(hash)).not.toThrow()
    expect(TABS_SET.has(parseHash(hash).tab)).toBe(true)
  })
})

describe('formatHash', () => {
  it('omits every absent field', () => {
    expect(formatHash(st())).toBe('#/builder')
  })

  it('puts a record id in the path, not the query', () => {
    expect(formatHash(st({ tab: 'Records', rec: 'rec_99' }))).toBe('#/records/rec_99')
  })

  it('round-trips through parseHash', () => {
    const cases: UrlState[] = [
      st(),
      st({ tab: 'Run' }),
      st({ tab: 'Records', rec: 'rec_99' }),
      // A rec id is a path segment (encodeURIComponent), not a query value
      // (URLSearchParams) — only the latter is covered by the scope/sel '%j' cases below,
      // so a '/' in a rec id needs its own case here.
      st({ tab: 'Records', rec: 'a/b' }),
      st({ exp: 'a1b2' }),
      st({ exp: 'a1b2', scope: 'dose', sel: "groups['dose'].body[1]" }),
    ]
    for (const c of cases) expect(parseHash(formatHash(c))).toEqual(c)
  })

  // Group names may legally contain a space, an apostrophe, or '->' (paths.ts:19-31), which
  // is why URLSearchParams does the encoding and no string is concatenated by hand.
  it.each(['a b', "a'b", 'a->b', 'a&b=c', 'a#b', 'a?b', 'a%b', 'a+b', 'a/b'])(
    'round-trips a group named %j in scope and sel',
    (name) => {
      const s = st({ exp: 'x', scope: name, sel: `groups['${name}'].body[0]` })
      expect(parseHash(formatHash(s))).toEqual(s)
    },
  )

  // The real-browser guarantee behind the 'a#b' case above. `location.hash` is everything
  // from the FIRST '#' onward, so a second raw '#' anywhere in the emitted hash would be
  // handed to parseHash intact but would have already split the URL for anything that reads
  // the fragment by other means. URLSearchParams' urlencoded serializer percent-encodes
  // '#' to %23, and encodeURIComponent does the same for the rec segment, so the sigil is
  // the only '#' the output can ever contain. This test is what keeps that true.
  it.each([
    st({ scope: 'a#b', sel: "groups['a#b'].body[0]" }),
    st({ exp: 'e#1' }),
    st({ tab: 'Records', rec: 'rec#9' }),
  ])('emits no raw "#" past the leading sigil for %j', (s) => {
    const hash = formatHash(s)
    expect(hash.startsWith('#')).toBe(true)
    expect(hash.slice(1)).not.toContain('#')
  })

  it('never emits a raw space, which a URL bar would encode behind our back', () => {
    expect(formatHash(st({ scope: 'a b' }))).not.toContain(' ')
  })
})
