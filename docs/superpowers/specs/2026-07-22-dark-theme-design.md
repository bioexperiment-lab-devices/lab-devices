# Dark theme for Experiment Studio — design

Date: 2026-07-22
Status: approved (brainstorm settled all four forks on the recommended option)

## Goal

Add a dark theme to the Studio frontend covering every tab (Builder, Run, Records,
Labs, Devices), the construct-tint / role-swatch / state-hue color language, and the
uPlot stream charts — switchable System / Light / Dark, persisted, with dark-mode
contrast enforced by the existing capture/probe harness in both themes permanently.

## Settled forks

| Fork | Decision |
|---|---|
| Implementation | Palette remap via CSS variables (no per-call-site changes) |
| Switching | Three-way System / Light / Dark, localStorage-persisted, header toggle |
| Verification | capture/probe runs both themes + one-time full browser sweep |
| Scope | Everything including charts, one increment |

## Architecture: a shadow palette, not a rewrite

Tailwind 4 compiles every color utility to a CSS variable reference
(`.bg-slate-100 { background-color: var(--color-slate-100) }`) with the palette
defined on `:root, :host`. The dark theme is therefore **one block in
`src/index.css`**:

```css
:root[data-theme='dark'] {
  color-scheme: dark;
  --color-white: oklch(/* raised dark surface */);
  --color-slate-100: oklch(/* near-black canvas */);
  /* … every token in use … */
}
```

- `:root[data-theme='dark']` (0,2,0) beats Tailwind's `:root, :host` (0,1,0), and
  the block lives outside any `@layer`, so it wins over the layered theme
  regardless of order.
- Values are **literal OKLCH values**, not `var()` chains — a chain like
  `--color-slate-100: var(--color-slate-900)` goes circular the moment slate-900
  is itself remapped. Values are permutations of Tailwind's own palette (copied
  from `node_modules/tailwindcss/theme.css`), adjusted only where the probe
  demands it.
- **Exactly the tokens in use are remapped** — 58 today, measured from the
  compiled CSS: amber-50/100/200/300/400/600/700/800/900, black,
  blue-50/100/200/300/400/500/600/700/800, cyan-600, emerald-100/500/700,
  fuchsia-50/200/500, green-100, lime-50/200/600, pink-500, purple-500,
  red-50/100/200/400/500/600/700, slate-50/100/200/300/400/500/600/700/900,
  stone-500, teal-50/200/500/700, violet-50/100/200/500/700, white.
  A token added later and not remapped shows up as a light color on dark ground —
  caught by the probe and the R5 contrast rule, not by eye.
- `color-scheme: dark` makes native controls (selects, checkboxes, scrollbars)
  follow; the light root keeps `color-scheme: light`.

### Mapping strategy (invariants, not a frozen table)

The exact values are iterated against the probe during implementation; these
invariants are the contract:

1. **Elevation ordering is preserved.** In light mode cards (`white`) sit lighter
   than the canvas (`slate-100`); in dark mode cards sit *lighter* than the
   canvas too (raised = lighter): `white` → dark raised surface (~slate-800
   region), `slate-50` between, `slate-100` → near-black backdrop, `slate-200/300`
   → dark borders/dividers that still read against both.
2. **Text ramps flip while keeping their meaning tiers.** `slate-900` (primary) →
   near-white; `text-caption`/slate-600 and `text-hint`/slate-500 land wherever
   ≥4.5:1 holds on every surface they sit on — the probe decides, not eyeballs.
3. **State hues keep the family, swap the step.** Pale `-50/-100` tint
   backgrounds (red-50, amber-50, blue-50…) → deep dark tints (the `-950`-ish end
   of the same family); strong `-600/-700` text on light → lighter `-300/-400`
   steps that clear AA on the dark tints; borders move from `-200/-300` to
   `-700/-800`.
4. **Construct tints keep their five hues** (slate/teal/violet/fuchsia/lime) at
   dark-tint depth so construct identity survives the flip; the saturation gap to
   role swatches is preserved.
5. **Role swatches stay saturated** (`-500/-600`) — they already sit on both
   light and dark grounds today; brightened only if the probe or sweep flags
   them.
6. **Hue stays reserved for state** — the dark palette must not blur the
   blue=selection / red=error / amber=warning / emerald=valid language.

Shadows (`shadow-sm/lg/xl`, 11 uses) keep their defaults initially — dark-on-dark
shadows are subtle but harmless; revisit only if the visual sweep flags floating
surfaces that read as flat.

The hatch utilities in `index.css` already reference `var(--color-slate-200/300)`
and theme automatically. The "text never sits directly on the hatch" rule carries
over: the opaque backing (`bg-white shadow-sm`) remaps to the raised surface and
keeps working.

## Theme state and toggle

New `src/stores/themeStore.ts` (zustand + localStorage, mirroring
`roleColorStore`'s persistence pattern):

- Setting: `'system' | 'light' | 'dark'`, persisted under a `studio.` -prefixed
  key consistent with existing storage keys.
- Effective theme: the setting, or `matchMedia('(prefers-color-scheme: dark)')`
  when `system`, with a change listener so an OS flip retints a running app.
- Application: stamps `data-theme="dark"` on `document.documentElement` (absence
  = light). Components never read the DOM attribute; anything needing the
  effective theme (StreamChart) subscribes to the store.
- localStorage unavailable or value unrecognized → `system`.

**No-flash boot:** a tiny framework-free inline script in `index.html` reads the
stored setting + `matchMedia` and stamps `data-theme` before first paint.

**Toggle:** one `IconButton` (lucide `Monitor` / `Sun` / `Moon` reflecting the
current setting) in the TabShell header's right-hand span, cycling
System → Light → Dark. `title`/`aria-label` announce both current mode and what a
click does, per the icon rules in `webapp/frontend/CLAUDE.md`.

## Charts

`StreamChart.tsx`'s hardcoded hex (axis stroke, grid, ticks + 6 series colors)
becomes two explicit named sets — light (today's values) and dark (same hue
order, brightened for dark ground; axis/grid flip to dark greys). The component
subscribes to the effective theme and rebuilds the uPlot instance on change
(uPlot options are construction-time). uPlot's bundled CSS is checked for baked
light colors (legend, cursor) and overridden in `index.css` under the dark root
if needed.

## Verification

1. **Probe both themes, forever:** `tools/capture.mjs` captures every
   state × viewport in light AND dark (stamping the theme before interaction),
   writing to `light/` and `dark/` subtrees of the output dir, with `probe.json`
   covering both. R5 `text-contrast` measures rendered pixels, so it enforces AA
   in dark with no rule changes. A `--theme light|dark|both` flag defaults to
   `both`.
2. **Browser sweep, once, post-implementation:** every tab and every meaningful
   state (selection, error/warning chips, group scope + hatch, expanded
   group_ref, run log live+record, stream charts, modals/pickers, drag states,
   Devices command forms, Labs roster) checked visually in dark and light via
   the Claude-in-Chrome extension against the dev server.
3. **vitest:** pure resolution logic of the theme store (setting × system
   preference → effective theme; persistence round-trip; bad stored value →
   system). No DOM/component tests, per the project's node-env-only rule.

## Documentation

`webapp/frontend/CLAUDE.md` Colour section gains a short dark-theme rule: the
`index.css` remap is the *only* dark-mode mechanism — components keep using
palette classes; no `dark:` variants; no hex or arbitrary values outside
`constructTint.ts`, `roleColors.ts`, and StreamChart's theme sets; a new palette
step must be added to the remap block (the probe's dark run is the enforcement).

## Out of scope

- Per-experiment or per-record theming; print styles.
- Re-tuning the light palette (it stays byte-identical).
- Chart series-color user configuration.
