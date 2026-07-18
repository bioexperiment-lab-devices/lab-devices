# Experiment Studio frontend — project rules

## Icons

- Interactive icons come from **lucide-react** only (`src/ui/icons.tsx` maps block
  kinds; `src/ui/IconButton.tsx` is the only way to render an icon-only action —
  it enforces the ≥24×24px hit area, contrast, and title/aria-label).
- Toolbar-row exception: a button that must visually match adjacent labeled buttons (e.g. the Toolbar's Undo/Redo) may inline a Lucide icon inside the shared button class instead of IconButton, provided it keeps an explicit `aria-label`, a `title`, and a ≥24×24px rendered hit area.
- Brand marks, if ever needed, come from **Simple Icons** (https://simpleicons.org).
- **No raw glyph characters for interactive controls** (no ✕ ⧉ ✎ ▾ ↻ ⭳ buttons).
  Semantic notation stays typographic: `∀` (for_each), `R×N` retry marker, `⤳`
  tolerated-error marker, `×N` loop count, the `●` unsaved dot, ellipses, prose
  dashes.

## Text colors

- Meaning-carrying secondary text uses `text-caption` (slate-600); incidental
  placeholder/empty-state text uses `text-hint` (slate-500). Raw `text-slate-400`
  or lighter on text that carries meaning fails the audit's AA gate — don't
  reintroduce it (docs/ui-audit/2026-07-17.md, finding 1).

## Testing

- vitest runs in node env: pure functions only, no component rendering, no jsdom,
  no @testing-library. DOM wiring is verified by the UI-audit probe harness
  (docs/superpowers/plans/2026-07-17-experiment-studio-ui-audit.md, Task 2).
