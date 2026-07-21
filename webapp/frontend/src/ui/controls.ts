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

/** Text inputs, textareas' single-line siblings, and selects.
 *
 * `width` picks the control's width class and defaults to `w-full`. It exists because
 * `w-full` and a narrower width (e.g. `w-28`) are equal-specificity Tailwind utilities in
 * the SAME `@layer utilities` block — whichever is declared later in the compiled
 * stylesheet wins the cascade, regardless of class-string order. `w-full` sorts after every
 * fixed width there, so `controlClass(...) + ' w-28'` silently rendered full-width no matter
 * what came after it in the string. Passing `width` here selects the class instead of
 * appending one, so there is only ever one width class in the output and no cascade fight
 * to lose (see docs' 2026-07-18 control-token sweep, finding C-width). */
export function controlClass(
  opts: { mono?: boolean; invalid?: boolean; width?: string } = {},
): string {
  return `${CONTROL_H} ${opts.width ?? 'w-full'} ${controlSurfaceClass(opts)}`.trim()
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
 * `subtle` is the dashed "add another" affordance; it keeps the same height.
 * `width` has no default (unlike `controlClass`'s) — most inline buttons size to their
 * label, so omitting it emits no width class at all, exactly as before this option
 * existed. Pass it (e.g. `'w-full'` for a full-bleed button below a branch arm) instead of
 * concatenating a width string: same cascade hazard as `controlClass` — see its docstring.
 *
 * `stretch` is the ONE sanctioned exception to the 24px token: a button that must match the
 * height of the flex row it sits in rather than the height of a text control (Canvas's
 * "+ lane", which runs the full height of the lanes beside it). It swaps `CONTROL_H` for
 * `self-stretch` — the two cannot coexist, since `align-self: stretch` is ignored once a
 * cross-size is set. It lives here, not as an appended override at the call site, so the
 * height rule (see frontend/CLAUDE.md) still has exactly one home: a caller that needs a
 * non-24px button asks for it by name, and there is no silent `h-6`/`self-stretch` clash. */
export function inlineButtonClass(
  opts: { subtle?: boolean; danger?: boolean; active?: boolean; width?: string; stretch?: boolean } = {},
): string {
  return (
    `${opts.stretch ? 'self-stretch' : CONTROL_H} ${opts.width ? opts.width + ' ' : ''}` +
    'inline-flex shrink-0 items-center justify-center rounded border px-2 text-xs ' +
    'disabled:opacity-40 ' +
    // Each variant SELECTS a whole border/bg set rather than appending one (the cascade
    // reasoning behind `width`): appending `border-blue-500` onto a baked `border-slate-300`
    // loses to compiled-order, not string-order. `active` is blue (selection state); `danger`
    // is red on hover only (the destructive pattern IconButton uses — red is an error-state
    // colour, not a resting fill).
    (opts.subtle
      ? 'border-dashed border-slate-300 text-caption hover:border-slate-400 hover:text-slate-700'
      : opts.active
        ? 'border-blue-500 bg-blue-50 text-blue-700 hover:bg-blue-100'
        : opts.danger
          ? 'border-slate-300 bg-white hover:border-red-200 hover:bg-red-50 hover:text-red-600 disabled:hover:bg-white'
          : 'border-slate-300 bg-white hover:bg-slate-100 disabled:hover:bg-white')
  ).trim()
}

/** Radio-style badge buttons (the Roles section's role picker). Borderless — they read as
 * selectable chips, not push buttons — but they carry CONTROL_H because they share a
 * visual row with 24px IconButtons (rename/delete), and the probe's
 * sibling-height-mismatch rule holds every such row to ≤1px.
 * `min-w-0 max-w-full` bounds a badge to its row so an inner truncating span can ellipsize
 * a pathological role name instead of widening the palette — ellipsis must live on an inner
 * span because text-overflow does not apply to flex containers. */
export function badgeClass(opts: { active?: boolean } = {}): string {
  return (
    `${CONTROL_H} inline-flex min-w-0 max-w-full items-center rounded px-1.5 font-mono text-xs ` +
    (opts.active ? 'bg-blue-100 text-blue-700' : 'text-slate-700 hover:bg-slate-200')
  ).trim()
}

/** The Inspector's collapsible tail-section header (design 2026-07-18 §3.3).
 *
 * Borderless and left-aligned, so it reads as a section heading rather than a push button —
 * which is what distinguishes it from the body's plain `PARAMS`/`ARGS` sub-labels, whose
 * ambiguity with the old `h3` headers is part of what this increment removes.
 *
 * It exists as its own helper rather than as options bolted onto `inlineButtonClass` because
 * that one bakes `justify-center` and a border: appending `justify-start` would lose the
 * cascade silently (equal specificity, same `@layer utilities`, compiled order decides). One
 * helper, one alignment class, no fight to lose.
 *
 * Carries CONTROL_H: the header shares a column with 24px inputs and selects, and the probe's
 * sibling-height-mismatch rule holds that column to ≤1px. */
export function sectionHeaderClass(): string {
  return (
    `${CONTROL_H} flex w-full items-center justify-start gap-1 rounded px-1 ` +
    'text-xs font-semibold uppercase text-caption hover:bg-slate-100'
  ).trim()
}
