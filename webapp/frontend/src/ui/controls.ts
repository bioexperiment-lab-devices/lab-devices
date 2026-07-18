/** The one control-height token (spec §4.1, cause C-A).
 *
 * Before this existed the app had four height scales: IconButton pinned 24px,
 * `inputClass` yielded ~22px, Toolbar's `buttonClass` ~26px, and ad-hoc add-buttons
 * omitted the border and lost 2px more. Any row mixing two of them sat visibly
 * crooked — twelve such sites shipped in 0.8.0.
 *
 * 24px is not arbitrary: it is the hit-area floor IconButton already enforces
 * (see IconButton.tsx), so an icon button beside a text field is now flush by
 * construction rather than by coincidence. Height lives HERE and nowhere else —
 * a consumer that needs a different height is a bug in the consumer.
 */
export const CONTROL_H = 'h-6'

/** Border, background, horizontal padding, text size, and focus ring shared by every
 * text-entry control — the part of the visual contract that does NOT depend on height.
 * `controlClass` (fixed-height inputs/selects) and `textAreaClass` (height-free textareas)
 * both derive from this so the border/focus-ring never drifts between the two families.
 * Not exported: callers want a control class, not this fragment on its own. */
function controlSurfaceClass(opts: { mono?: boolean; invalid?: boolean } = {}): string {
  return (
    'rounded border bg-white px-1.5 text-xs ' +
    'focus:border-blue-400 focus:outline-none ' +
    (opts.invalid ? 'border-red-400 ' : 'border-slate-300 ') +
    (opts.mono ? 'font-mono' : '')
  ).trim()
}

/** Text inputs, textareas' single-line siblings, and selects. */
export function controlClass(opts: { mono?: boolean; invalid?: boolean } = {}): string {
  return `${CONTROL_H} w-full ${controlSurfaceClass(opts)}`.trim()
}

/** Textareas. Shares `controlSurfaceClass` with `controlClass` but deliberately carries no
 * `h-*` class: a textarea's height is driven by its content (see `autoGrow.ts`), never by
 * the fixed single-line token. `py-0.5` replaces the vertical space `CONTROL_H` would have
 * fixed. `fillParent` adds `max-h-full` so a flex parent can bound the growth instead. */
export function textAreaClass(opts: { mono?: boolean; fillParent?: boolean } = {}): string {
  return (
    `w-full py-0.5 ${controlSurfaceClass(opts)} ` + (opts.fillParent ? 'max-h-full' : '')
  ).trim()
}

/** Inline buttons that sit in a row with inputs or other buttons.
 * `subtle` is the dashed "add another" affordance; it keeps the same height. */
export function inlineButtonClass(opts: { subtle?: boolean } = {}): string {
  return (
    `${CONTROL_H} inline-flex shrink-0 items-center justify-center rounded border px-2 text-xs ` +
    'disabled:opacity-40 ' +
    (opts.subtle
      ? 'border-dashed border-slate-300 text-caption hover:border-slate-400 hover:text-slate-700'
      : 'border-slate-300 bg-white hover:bg-slate-100 disabled:hover:bg-white')
  ).trim()
}
