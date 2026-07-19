/** The in-progress document draft (design §6).
 *
 * Two layers (design §6.2, fork 6): sessionStorage is authoritative and per-tab, so two tabs
 * can never clobber each other's unsaved work; localStorage is a best-effort mirror read only
 * when the session copy is absent — a genuinely new tab or a new browser session.
 *
 * Parsing is total: every failure degrades to "no draft", i.e. a normal cold start. Corrupt
 * storage must never be able to take the Studio down. Same contract as parseOverrides in
 * builder/roleColorStorage.ts.
 */
import type { DocContent } from '../builder/convert'

export const DRAFT_STORAGE_KEY = 'studio.draft.v1'

export interface DraftView {
  scope: string | null
  selectedUid: string | null
  collapsed: Record<string, boolean>
}

export interface Draft {
  v: 1
  serverId: string | null
  // Stored, not recomputed: selectDirty (docStore.ts:153) compares live content against this
  // string, so a restored draft without it would read as clean and the unsaved dot would lie.
  savedSnapshot: string
  // The EDITOR form, not ExperimentDocJson: the wire form would round-trip through docToTree
  // on restore and remint every uid (convert.ts:108), invalidating view.selectedUid and every
  // key in view.collapsed.
  content: DocContent
  view: DraftView
  updatedAt: number
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

const nullableString = (v: unknown): v is string | null => v === null || typeof v === 'string'

function parseView(v: unknown): DraftView | null {
  if (!isRecord(v)) return null
  if (!nullableString(v.scope) || !nullableString(v.selectedUid)) return null
  const collapsed: Record<string, boolean> = {}
  // A missing or malformed collapsed map degrades to "nothing collapsed" rather than
  // rejecting the whole draft: losing the document to recover a display preference would be
  // a far worse trade than the one it is protecting against.
  if (isRecord(v.collapsed)) {
    for (const [key, value] of Object.entries(v.collapsed)) {
      if (typeof value === 'boolean') collapsed[key] = value
    }
  }
  return { scope: v.scope, selectedUid: v.selectedUid, collapsed }
}

export function parseDraft(raw: string | null): Draft | null {
  if (raw === null || raw === '') return null
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  if (!isRecord(parsed)) return null
  if (parsed.v !== 1) return null
  if (!nullableString(parsed.serverId)) return null
  if (typeof parsed.savedSnapshot !== 'string') return null
  if (!isRecord(parsed.content)) return null
  if (typeof parsed.updatedAt !== 'number') return null
  const view = parseView(parsed.view)
  if (view === null) return null
  return {
    v: 1,
    serverId: parsed.serverId,
    savedSnapshot: parsed.savedSnapshot,
    // Trusted as DocContent after the shape check above. A deep validation here would
    // duplicate convert.ts's grammar; the executor's docToTree/loadDoc path is what actually
    // has to survive a malformed tree, and it already reports DocConvertError.
    content: parsed.content as unknown as DocContent,
    view,
    updatedAt: parsed.updatedAt,
  }
}

export function serializeDraft(d: Draft): string {
  return JSON.stringify(d)
}

// A present-but-corrupt session slot is not the same as an absent one: a null session copy
// means this tab has never saved and it is fair to reach for the cross-session mirror, but a
// non-null, unparseable one means this tab *does* have its own copy and something damaged it
// in place. Falling through to the mirror in that case would silently present a different
// (older) snapshot as this tab's own authoritative work via the restore notice — so a
// non-null sessionRaw is decisive on its own, even when it fails to parse.
export function resolveDraft(sessionRaw: string | null, localRaw: string | null): Draft | null {
  if (sessionRaw !== null) return parseDraft(sessionRaw)
  return parseDraft(localRaw)
}

/* ---- storage edge (design §6.2) -------------------------------------------------------
 * Untested by design: neither Storage API exists in the node vitest environment
 * (webapp/frontend/CLAUDE.md). Everything decidable lives in parseDraft/resolveDraft above.
 */

const session = (): Storage | null => {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

const local = (): Storage | null => {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

const readKey = (s: Storage | null): string | null => {
  if (s === null) return null
  try {
    return s.getItem(DRAFT_STORAGE_KEY)
  } catch {
    return null
  }
}

/** Session first (this tab's own work), then the cross-session mirror. */
export function readDraft(): Draft | null {
  return resolveDraft(readKey(session()), readKey(local()))
}

export function writeDraft(d: Draft): void {
  const raw = serializeDraft(d)
  try {
    session()?.setItem(DRAFT_STORAGE_KEY, raw)
  } catch {
    // Quota or disabled storage. The app stays fully functional without a draft; a failed
    // write is not an error state worth surfacing mid-keystroke.
  }
  try {
    local()?.setItem(DRAFT_STORAGE_KEY, raw)
  } catch {
    // Mirror is best-effort by definition — the session copy above is authoritative.
  }
}

export function clearDraft(): void {
  try {
    session()?.removeItem(DRAFT_STORAGE_KEY)
  } catch {
    /* nothing to recover: the draft is already unreachable */
  }
  try {
    local()?.removeItem(DRAFT_STORAGE_KEY)
  } catch {
    /* as above */
  }
}
