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
