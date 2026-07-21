/** Insert-at-caret shared by autocomplete acceptance and the clickable help popover
 * (spec §3.6). Pads a space only where the insert would otherwise glue two identifier
 * tokens together. */
const IDENT_CHAR = /[A-Za-z0-9_]/

export interface InsertOptions {
  replace?: { start: number; end: number }
  /** Move the caret back N chars from the end of the inserted fragment (before any
   * trailing pad space) — e.g. 1 places it inside `name()`. */
  caretBack?: number
}

export function insertFragment(
  text: string,
  caret: number,
  fragment: string,
  opts: InsertOptions = {},
): { text: string; caret: number } {
  const start = opts.replace?.start ?? caret
  const end = opts.replace?.end ?? caret
  let lead = ''
  let tail = ''
  if (start > 0 && IDENT_CHAR.test(text[start - 1]) && IDENT_CHAR.test(fragment[0])) lead = ' '
  if (
    end < text.length &&
    IDENT_CHAR.test(text[end]) &&
    IDENT_CHAR.test(fragment[fragment.length - 1])
  ) {
    tail = ' '
  }
  const newText = text.slice(0, start) + lead + fragment + tail + text.slice(end)
  return { text: newText, caret: start + lead.length + fragment.length - (opts.caretBack ?? 0) }
}
