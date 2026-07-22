# Experiment Studio frontend — project rules

## Icons

- Interactive icons come from **lucide-react** only (`src/ui/icons.tsx` maps block
  kinds; `src/ui/IconButton.tsx` is the only way to render an icon-only action —
  it enforces the ≥24×24px hit area, contrast, and title/aria-label).
- Toolbar-row exception: a button that must visually match adjacent labeled buttons (e.g. the Toolbar's Undo/Redo) may inline a Lucide icon inside the shared button class instead of IconButton, provided it keeps an explicit `aria-label`, a `title`, and a ≥24×24px rendered hit area.
- Anchor exception: an icon-only action that must be a link (e.g. a download `<a href>`) uses `iconButtonClass()` from src/ui/IconButton.tsx to get the same hit area/contrast, plus explicit `title` and `aria-label`.
- Brand marks, if ever needed, come from **Simple Icons** (https://simpleicons.org).
- **No raw glyph characters for interactive controls** (no ✕ ⧉ ✎ ▾ ↻ ⭳ buttons).
  Semantic notation stays typographic: `∀` (for_each), `R×N` retry marker, `⤳`
  tolerated-error marker, `×N` loop count, the `●` unsaved dot, ellipses, prose
  dashes.

## Control height

- Every text input, select, and inline button renders at **24px** via `controlClass()` /
  `inlineButtonClass()` from `src/ui/controls.ts`, matching `IconButton`'s hit-area floor.
  Height belongs in that module and nowhere else — a component needing a different height
  is a bug in the component. Four competing height scales shipped in 0.8.0 and left twelve
  visibly crooked rows (docs/superpowers/specs/2026-07-18-experiment-studio-ui-improvements-design.md, cause C-A).
- Textareas are exempt from the fixed height (they are multi-line by definition) but share
  the same border and padding, via `textAreaClass()`.
- A button that must match the height of the row it sits in rather than a text control asks
  for `inlineButtonClass({ stretch: true })` (Canvas's "+ lane"). The option *replaces* the
  height class — do not append `self-stretch` yourself: `align-self` is ignored once a
  cross-size is set, so the button would silently stay 24px.
- **Pass `width` as an option; never concatenate one.** `controlClass({ width: 'w-28' })`,
  not `controlClass() + ' w-28'`. `w-full` and fixed widths are equal-specificity utilities
  in the same `@layer utilities` block, so the cascade is decided by declaration order in the
  compiled stylesheet, not by class-string order — and `w-full` sorts last. An appended width
  therefore loses silently and the control renders full-width. The `width` option *selects*
  the class instead of appending, so only one width class is ever emitted and there is no
  cascade fight to lose.
- The probe's `sibling-height-mismatch` rule (`webapp/frontend/tools/probe.mjs`, R4) is what
  keeps this honest: it flags sibling controls on a shared visual line whose heights disagree
  by more than 1px. Run `npm run capture` against a real doc after touching any control class.

## Colour

- Construct tints, role swatches and state colours are three separate languages and must
  not be mixed. Hue (blue/red/amber/emerald) is reserved for **state**: selection, error,
  warning, valid. Construct identity uses the pale tints in `src/builder/constructTint.ts`;
  device roles use the saturated ramp in `src/builder/roleColors.ts`. Both deliberately
  exclude every reserved family. Adding a canvas colour outside those two modules is how
  the error language stops being readable.
- **Any class baked into a helper is un-overridable by concatenation — for every property,
  not just width.** `cardBorderClass` and friends *select* and return exactly one class per
  property. Never `helperClass() + ' border-blue-500'`: equal-specificity utilities in the
  same `@layer utilities` block are decided by declaration order in the compiled stylesheet,
  not by class-string order. W11 hit this on `width`, W12 hit it on `text` colour, where an
  appended `text-blue-700` lost to a baked-in `text-slate-500` and the highlight never
  rendered while looking perfect in source.
- **Tailwind class names must be complete literals in source.** Tailwind 4 scans source
  text; `` `bg-${family}-500` `` compiles to no CSS at all.
- **Dark theme is a palette remap, not a variant system.** `index.css`'s
  `:root[data-theme='dark']` block redefines every in-use `--color-*` token; components
  keep writing plain palette classes (`bg-white`, `text-red-600`) and MUST NOT use
  `dark:` variants, hex, or arbitrary values — the remap is the only mechanism
  (StreamChart's `CHART_THEMES` is the one sanctioned exception, uPlot needs concrete
  strings). A palette step used by a component but absent from the remap renders at its
  light value in dark mode — the expression editor shipped invisible (measured 1.00:1)
  dark tokens exactly this way. `npm run capture` shoots BOTH themes (probe R5 enforces
  AA on each); that is the enforcement, not eyes. Theme state lives in
  `src/stores/themeStore.ts` (`studio.theme`); `index.html`'s inline script stamps
  `<html data-theme>` pre-paint — its storage-key literal must match
  `THEME_STORAGE_KEY` by hand.
- Hatching (`bg-hatch`, `edge-hatch` in `index.css`) means exactly one thing: *this stands
  for something not shown here*. It has exactly two sanctioned uses — group scope and
  `group_ref`. A third dilutes it to decoration.
- **Text must never sit directly on the hatch.** A striped surface has no single background
  colour, so the probe's R5 scores text against the worst stripe: `text-caption`/slate-600
  clears at 6.15:1 but `text-hint`/slate-500 measures 3.86:1 and fails. Give hint text an
  opaque backing (`bg-white shadow-sm`) whenever a group scope is active, as the empty-tree
  and drop-slot hints do.
- New coloured surfaces are verified with `npm run capture` (R5 `text-contrast`), not by
  eye. Measured on the real app: the five construct tints carry header text at 9.44–17.22:1
  and caption text at 6.91–7.27:1, all clear of the 4.5:1 AA floor
  (`docs/visual-language/after/README.md`).

## Text colors

- Meaning-carrying secondary text uses `text-caption` (slate-600); incidental
  placeholder/empty-state text uses `text-hint` (slate-500). Raw `text-slate-400`
  or lighter on text that carries meaning fails the audit's AA gate — don't
  reintroduce it (docs/ui-audit/2026-07-17.md, finding 1).
- On the tinted canvas (bg-slate-100) use `text-caption` even for incidental
  text — `text-hint` measures under 4.5:1 there.

## Testing

- vitest runs in node env: pure functions only, no component rendering, no jsdom,
  no @testing-library. DOM wiring is verified by the UI-audit probe harness
  (docs/superpowers/plans/2026-07-17-experiment-studio-ui-audit.md, Task 2).
