/** The hash grammar (design §4).
 *
 *   #/builder?exp=a1b2&scope=dose&sel=groups%5B%27dose%27%5D.body%5B1%5D
 *   #/records/rec_99
 *   #/run
 *
 * A hash rather than real paths because vite.config.ts pins `base: './'` so the bundle stays
 * deployable behind the lab-bridge prefix-stripping proxy at /studio/. Under a relative base,
 * a path segment makes the browser request assets from that segment, which 404s into the SPA
 * catch-all and fails on MIME type (design §1.1, C-1).
 *
 * Every query value goes through URLSearchParams and every path segment through
 * encodeURIComponent. Group names may legally contain a space, an apostrophe, '&', '#', '?',
 * '%', '+', '/', or '->' — non-identifier names are reachable via Import, since GROUP_NAME_RE
 * (docStore.ts:40) is enforced only on add/rename and convert.ts loads keys verbatim
 * (paths.ts:19-31). A hand-rolled encoder would silently turn one group name into a different,
 * valid-looking one, and `sel` carries those names inside a `groups['name'].body[i]` path.
 *
 * That encoding boundary is also what makes the hash survive a real browser. `location.hash`
 * is defined as everything from the FIRST '#' onward, so a value carrying a raw '#' would end
 * up inside the fragment the browser hands back — readable here, but the fragment would no
 * longer be the thing that was written, and anything splitting the URL on '#' (a copy-pasted
 * link, a server log, an <a href>) would truncate it. URLSearchParams' urlencoded serializer
 * percent-encodes '#' to %23, and encodeURIComponent likewise, so the leading sigil is the
 * only '#' formatHash can ever emit. urlState.test.ts asserts that directly rather than
 * inferring it from a round trip, which would pass even if a raw '#' leaked through.
 *
 * Parsing is total. A hand-edited or truncated URL lands on a usable screen: an unknown tab
 * slug falls back to the default tab, and a malformed percent-escape (which decodeURIComponent
 * throws on) yields the raw segment rather than an exception.
 */
import { TABS, type Tab } from './tabs'
import { EMPTY_URL_STATE, type UrlState } from './bootstrap'

const SLUG_TO_TAB = new Map<string, Tab>(TABS.map((t) => [t.toLowerCase(), t]))

/** decodeURIComponent throws a URIError on a malformed escape ('%', '%E0%A4%A'). A truncated
 * URL must still land on a usable screen, so the undecoded segment is the fallback. */
function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment)
  } catch {
    return segment
  }
}

export function parseHash(hash: string): UrlState {
  const raw = hash.startsWith('#') ? hash.slice(1) : hash
  // Split on the FIRST '?' and keep everything after it as the query — not `split('?', 2)`,
  // which discards the remainder. formatHash never emits a second raw '?' (it encodes to
  // %3F), but a hand-edited URL can, and dropping half a query silently is worse than
  // letting URLSearchParams decide what the extra token means.
  const mark = raw.indexOf('?')
  const pathPart = mark === -1 ? raw : raw.slice(0, mark)
  const queryPart = mark === -1 ? '' : raw.slice(mark + 1)
  const segments = pathPart.split('/').filter((s) => s !== '')
  const tab = SLUG_TO_TAB.get((segments[0] ?? '').toLowerCase()) ?? EMPTY_URL_STATE.tab

  const params = new URLSearchParams(queryPart)
  const get = (key: string): string | null => {
    const value = params.get(key)
    return value === null || value === '' ? null : value
  }

  const recSegment = segments[1]
  return {
    tab,
    exp: get('exp'),
    // A record id is the thing being viewed rather than a qualifier on a view, so it is a
    // path segment. Only meaningful under /records — carried under any other tab it would
    // make formatHash and parseHash disagree about what the same URL means.
    rec: tab === 'Records' && recSegment !== undefined ? decodeSegment(recSegment) : null,
    scope: get('scope'),
    sel: get('sel'),
  }
}

export function formatHash(s: UrlState): string {
  const path =
    s.tab === 'Records' && s.rec !== null
      ? `/records/${encodeURIComponent(s.rec)}`
      : `/${s.tab.toLowerCase()}`

  const params = new URLSearchParams()
  if (s.exp !== null) params.set('exp', s.exp)
  if (s.scope !== null) params.set('scope', s.scope)
  if (s.sel !== null) params.set('sel', s.sel)
  const query = params.toString()
  return query === '' ? `#${path}` : `#${path}?${query}`
}
