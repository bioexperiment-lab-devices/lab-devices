# Dark Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dark theme for the Studio frontend — System/Light/Dark switch in the header, a CSS-variable palette remap covering all 58 in-use color tokens, theme-aware stream charts, and the capture/probe harness enforcing AA contrast in both themes.

**Architecture:** Tailwind 4 compiles every color utility to `var(--color-*)` defined on `:root, :host`, so the entire dark theme is one `:root[data-theme='dark']` block in `src/index.css` remapping literal OKLCH values — zero component call-site changes. A zustand store (pure logic split into a node-testable module) stamps `data-theme` on `<html>`; an inline script in `index.html` stamps it before first paint. Spec: `docs/superpowers/specs/2026-07-22-dark-theme-design.md`.

**Tech Stack:** React 19, Tailwind 4 (CSS-first), zustand, lucide-react, uPlot, Playwright capture harness, vitest (node env, pure functions only).

## Global Constraints

- Working directory: `/Users/khamit/lab-devices-dark-theme/webapp/frontend` (the `feat/dark-theme` worktree).
- vitest is node-env: tests import pure modules only — never a file that touches `window`, `document`, `localStorage`, or `matchMedia` at module scope.
- Icons: lucide-react via `IconButton` only; `title`+`aria-label` always; no raw glyphs.
- Tailwind class names must be complete literals in source; helpers SELECT one class per property, never append competing utilities.
- Light palette stays byte-identical; dark values are literal OKLCH (no `var()` chains — they go circular under remap).
- Hue stays reserved for state: blue=selection, red=error, amber=warning, emerald=valid.
- Commit after every task; messages end with the Co-Authored-By + Claude-Session trailer.

---

### Task 1: Theme setting logic, store, and no-flash boot

**Files:**
- Create: `src/stores/themeSetting.ts` (pure, node-testable)
- Create: `src/stores/themeSetting.test.ts`
- Create: `src/stores/themeStore.ts` (DOM-touching, NOT imported by tests)
- Modify: `index.html` (inline boot script)

**Interfaces:**
- Produces: `type ThemeSetting = 'system' | 'light' | 'dark'`, `type EffectiveTheme = 'light' | 'dark'`, `THEME_STORAGE_KEY = 'studio.theme'`, `parseThemeSetting(raw: string | null): ThemeSetting`, `resolveTheme(setting: ThemeSetting, systemDark: boolean): EffectiveTheme`, `cycleSetting(s: ThemeSetting): ThemeSetting`, and `useThemeStore` with `{ setting, effective, cycle() }`. Task 2 consumes `useThemeStore` + `cycleSetting`; Task 4 consumes `useThemeStore(s => s.effective)`.

- [ ] **Step 1: Write the failing test**

`src/stores/themeSetting.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  THEME_STORAGE_KEY,
  cycleSetting,
  parseThemeSetting,
  resolveTheme,
} from './themeSetting'

describe('parseThemeSetting', () => {
  it('accepts the three settings', () => {
    expect(parseThemeSetting('system')).toBe('system')
    expect(parseThemeSetting('light')).toBe('light')
    expect(parseThemeSetting('dark')).toBe('dark')
  })
  it('falls back to system on null, junk, and legacy values', () => {
    expect(parseThemeSetting(null)).toBe('system')
    expect(parseThemeSetting('')).toBe('system')
    expect(parseThemeSetting('DARK')).toBe('system')
    expect(parseThemeSetting('auto')).toBe('system')
  })
})

describe('resolveTheme', () => {
  it('explicit settings ignore the system preference', () => {
    expect(resolveTheme('light', true)).toBe('light')
    expect(resolveTheme('dark', false)).toBe('dark')
  })
  it('system follows the media query', () => {
    expect(resolveTheme('system', true)).toBe('dark')
    expect(resolveTheme('system', false)).toBe('light')
  })
})

describe('cycleSetting', () => {
  it('cycles system → light → dark → system', () => {
    expect(cycleSetting('system')).toBe('light')
    expect(cycleSetting('light')).toBe('dark')
    expect(cycleSetting('dark')).toBe('system')
  })
})

it('storage key follows the studio.* convention', () => {
  expect(THEME_STORAGE_KEY).toBe('studio.theme')
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/stores/themeSetting.test.ts`
Expected: FAIL — cannot resolve `./themeSetting`

- [ ] **Step 3: Write the pure module**

`src/stores/themeSetting.ts`:

```ts
/** Pure theme-setting logic, split from themeStore so vitest (node env) can import it —
 * the store itself touches matchMedia/localStorage/document at module scope. */

export type ThemeSetting = 'system' | 'light' | 'dark'
export type EffectiveTheme = 'light' | 'dark'

/** Same `studio.*` namespace as `studio.selectedLab` / `studio.draft.v1`. The inline boot
 * script in index.html reads this key BY LITERAL — keep the two in sync by hand. */
export const THEME_STORAGE_KEY = 'studio.theme'

export function parseThemeSetting(raw: string | null): ThemeSetting {
  return raw === 'light' || raw === 'dark' || raw === 'system' ? raw : 'system'
}

export function resolveTheme(setting: ThemeSetting, systemDark: boolean): EffectiveTheme {
  if (setting === 'system') return systemDark ? 'dark' : 'light'
  return setting
}

export function cycleSetting(s: ThemeSetting): ThemeSetting {
  return s === 'system' ? 'light' : s === 'light' ? 'dark' : 'system'
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- src/stores/themeSetting.test.ts`
Expected: PASS (7 tests)

- [ ] **Step 5: Write the store**

`src/stores/themeStore.ts`:

```ts
/** Theme selection, persisted to localStorage — view state, same family as
 * roleColorStore: never document state, never in the zundo snapshot.
 *
 * The store is the ONLY writer of <html data-theme> after boot (index.html's inline
 * script stamps the same attribute before first paint so the app never flashes light;
 * this module re-applies on init, which is idempotent and also corrects a stale stamp
 * if the OS preference changed between the boot script and module evaluation). */
import { create } from 'zustand'
import {
  THEME_STORAGE_KEY,
  cycleSetting,
  parseThemeSetting,
  resolveTheme,
  type EffectiveTheme,
  type ThemeSetting,
} from './themeSetting'

const media = window.matchMedia('(prefers-color-scheme: dark)')

function apply(theme: EffectiveTheme): void {
  if (theme === 'dark') document.documentElement.dataset.theme = 'dark'
  else delete document.documentElement.dataset.theme
}

function loadSetting(): ThemeSetting {
  try {
    return parseThemeSetting(localStorage.getItem(THEME_STORAGE_KEY))
  } catch {
    // Private-mode / disabled storage: follow the OS for the session.
    return 'system'
  }
}

type ThemeState = {
  setting: ThemeSetting
  effective: EffectiveTheme
  /** System → Light → Dark → System; persists and re-stamps <html>. */
  cycle: () => void
}

export const useThemeStore = create<ThemeState>((set, get) => {
  media.addEventListener('change', (e) => {
    if (get().setting !== 'system') return
    const effective = resolveTheme('system', e.matches)
    apply(effective)
    set({ effective })
  })
  const setting = loadSetting()
  const effective = resolveTheme(setting, media.matches)
  apply(effective)
  return {
    setting,
    effective,
    cycle: () => {
      const next = cycleSetting(get().setting)
      try {
        localStorage.setItem(THEME_STORAGE_KEY, next)
      } catch {
        // Quota or disabled storage — the in-memory setting still drives this session.
      }
      const effective = resolveTheme(next, media.matches)
      apply(effective)
      set({ setting: next, effective })
    },
  }
})
```

- [ ] **Step 6: Add the no-flash boot script to `index.html`**

In `<head>`, after `<title>`:

```html
    <script>
      // Stamp the theme BEFORE first paint — React mounting later is what makes a
      // store-only approach flash light on every dark-mode load. Key literal must
      // match THEME_STORAGE_KEY in src/stores/themeSetting.ts.
      ;(function () {
        var t = null
        try {
          t = localStorage.getItem('studio.theme')
        } catch (e) {}
        if (t === 'dark' || (t !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches))
          document.documentElement.dataset.theme = 'dark'
      })()
    </script>
```

- [ ] **Step 7: Verify full suite, typecheck, lint**

Run: `npm test && npm run typecheck && npm run lint`
Expected: 745+7 tests pass; tsc clean; no NEW lint warnings

- [ ] **Step 8: Commit**

```bash
git add src/stores/themeSetting.ts src/stores/themeSetting.test.ts src/stores/themeStore.ts index.html
git commit -m "feat(studio): theme setting store + no-flash boot stamp"
```

---

### Task 2: ThemeToggle in the TabShell header

**Files:**
- Create: `src/shell/ThemeToggle.tsx`
- Modify: `src/shell/TabShell.tsx` (right-hand span, before the lab pill)

**Interfaces:**
- Consumes: `useThemeStore`, `cycleSetting` (Task 1); `IconButton` from `src/ui/IconButton.tsx`.

- [ ] **Step 1: Write the component**

`src/shell/ThemeToggle.tsx`:

```tsx
import { Monitor, Moon, Sun } from 'lucide-react'
import { cycleSetting, type ThemeSetting } from '../stores/themeSetting'
import { useThemeStore } from '../stores/themeStore'
import { IconButton } from '../ui/IconButton'
import type { LucideIcon } from 'lucide-react'

/** The icon shows the SETTING (Monitor = following the OS), not the effective theme —
 * a Monitor icon that flipped to Moon whenever the OS went dark would read as "you
 * chose dark" when the user chose "follow the system". */
const ICONS: Record<ThemeSetting, LucideIcon> = {
  system: Monitor,
  light: Sun,
  dark: Moon,
}

export function ThemeToggle() {
  const setting = useThemeStore((s) => s.setting)
  const cycle = useThemeStore((s) => s.cycle)
  return (
    <IconButton
      icon={ICONS[setting]}
      label={`Theme: ${setting} — switch to ${cycleSetting(setting)}`}
      onClick={cycle}
    />
  )
}
```

- [ ] **Step 2: Mount it in `TabShell.tsx`**

Import: `import { ThemeToggle } from './ThemeToggle'`. In the right-hand span, first child (before the lab pill), so it sits leftmost of the status cluster:

```tsx
        <span className="ml-auto flex min-w-0 items-center gap-3 self-center py-3">
          <ThemeToggle />
          {labScopedTab(props.active) && (
```

- [ ] **Step 3: Verify**

Run: `npm test && npm run typecheck && npm run lint`
Expected: clean. Then `npm run dev`, load the app: the toggle cycles Monitor→Sun→Moon, `<html data-theme="dark">` appears in devtools on the Moon (and on Monitor with the OS dark), survives reload with no light flash.

- [ ] **Step 4: Commit**

```bash
git add src/shell/ThemeToggle.tsx src/shell/TabShell.tsx
git commit -m "feat(studio): theme toggle in the tab shell header"
```

---

### Task 3: The dark palette remap in `index.css`

**Files:**
- Modify: `src/index.css` (append the dark block; also `color-scheme: light` on `:root`)

**Interfaces:**
- Produces: `:root[data-theme='dark']` remapping exactly the 58 in-use tokens. Tasks 5–6 verify it; no code consumes it by name.

- [ ] **Step 1: Append the dark block**

Append to `src/index.css` (after the existing utilities). Every value below is either a copy of a Tailwind palette step (commented with its source) or an interpolated literal (commented with its intent):

```css
/* ---------------------------------------------------------------------------
 * Dark theme (design 2026-07-22-dark-theme §Architecture).
 *
 * Tailwind 4 compiles every color utility to var(--color-*), so this block IS the
 * dark theme: a remap of exactly the tokens the app uses, stamped on by
 * <html data-theme="dark"> (themeStore + the index.html boot script). Values are
 * LITERAL OKLCH — a var() chain like `--color-slate-100: var(--color-slate-900)`
 * goes circular the moment slate-900 is itself remapped. Sources: permutations of
 * tailwindcss/theme.css steps, noted per line; interpolated values noted as such.
 *
 * Invariants (spec §Mapping strategy): elevation ordering preserved (white = raised
 * card stays lighter than the slate-100 canvas); text tiers keep their hierarchy;
 * state hues keep the family and swap the step (-50 tints → -950 end, -600/-700
 * text → -300/-400); construct tints keep their five hues; role swatches stay
 * saturated; hue stays reserved for state.
 *
 * A token used by a component but MISSING here renders at its light value on dark
 * ground — `npm run capture` (both themes) is the enforcement, not eyes.
 * ------------------------------------------------------------------------- */
:root {
  color-scheme: light;
}
:root[data-theme='dark'] {
  color-scheme: dark;

  /* Surfaces & neutral text. Light-mode meaning in brackets. */
  --color-white: oklch(27.9% 0.041 260.031); /* [cards] slate-800 */
  --color-slate-50: oklch(24.5% 0.041 262); /* [subtle fill] interpolated 800↔900 */
  --color-slate-100: oklch(20.8% 0.042 265.755); /* [canvas] slate-900 */
  --color-slate-200: oklch(33% 0.042 261); /* [hover fill/dividers] interpolated 700↔800 */
  --color-slate-300: oklch(37.2% 0.044 257.287); /* [borders] slate-700 */
  --color-slate-400: oklch(55.4% 0.046 257.417); /* [muted icons] slate-500 */
  --color-slate-500: oklch(70.4% 0.04 256.788); /* [text-hint] slate-400 */
  --color-slate-600: oklch(76% 0.035 257); /* [text-caption] interpolated 300↔400 */
  --color-slate-700: oklch(86.9% 0.022 252.894); /* [strong text] slate-300 */
  --color-slate-900: oklch(96.8% 0.007 247.896); /* [primary text] slate-100 */

  /* State: error (red) */
  --color-red-50: oklch(25.8% 0.092 26.042); /* red-950 */
  --color-red-100: oklch(30% 0.105 26); /* interpolated 900↔950 */
  --color-red-200: oklch(39.6% 0.141 25.723); /* red-900 */
  --color-red-400: oklch(70.4% 0.191 22.216); /* unchanged — reads on dark */
  --color-red-500: oklch(63.7% 0.237 25.331); /* unchanged */
  --color-red-600: oklch(70.4% 0.191 22.216); /* red-400 */
  --color-red-700: oklch(80.8% 0.114 19.571); /* red-300 */

  /* State: warning (amber) */
  --color-amber-50: oklch(27.9% 0.077 45.635); /* amber-950 */
  --color-amber-100: oklch(32% 0.09 46); /* interpolated 900↔950 */
  --color-amber-200: oklch(41.4% 0.112 45.904); /* amber-900 */
  --color-amber-300: oklch(47.3% 0.137 46.201); /* amber-800 */
  --color-amber-400: oklch(82.8% 0.189 84.429); /* unchanged — reads on dark */
  --color-amber-600: oklch(82.8% 0.189 84.429); /* amber-400 */
  --color-amber-700: oklch(87.9% 0.169 91.605); /* amber-300 */
  --color-amber-800: oklch(92.4% 0.12 95.746); /* amber-200 */
  --color-amber-900: oklch(96.2% 0.059 95.617); /* amber-100 */

  /* State: selection/info (blue) */
  --color-blue-50: oklch(28.2% 0.091 267.935); /* blue-950 */
  --color-blue-100: oklch(33% 0.115 266); /* interpolated 900↔950 */
  --color-blue-200: oklch(37.9% 0.146 265.522); /* blue-900 */
  --color-blue-300: oklch(42.4% 0.199 265.638); /* blue-800 */
  --color-blue-400: oklch(70.7% 0.165 254.624); /* unchanged — focus ring */
  --color-blue-500: oklch(62.3% 0.214 259.815); /* unchanged — selection border */
  --color-blue-600: oklch(70.7% 0.165 254.624); /* blue-400 — primary buttons */
  --color-blue-700: oklch(80.9% 0.105 251.813); /* blue-300 */
  --color-blue-800: oklch(88.2% 0.059 254.128); /* blue-200 */

  /* State: valid (emerald + the one green tint) */
  --color-emerald-100: oklch(26.2% 0.051 172.552); /* emerald-950 */
  --color-emerald-500: oklch(69.6% 0.17 162.48); /* unchanged */
  --color-emerald-700: oklch(84.5% 0.143 164.978); /* emerald-300 */
  --color-green-100: oklch(26.6% 0.065 152.934); /* green-950 */

  /* Construct tints (constructTint.ts): -50 headers → -950, -200 borders → -800 */
  --color-teal-50: oklch(27.7% 0.046 192.524); /* teal-950 */
  --color-teal-200: oklch(43.7% 0.078 188.216); /* teal-800 */
  --color-violet-50: oklch(28.3% 0.141 291.089); /* violet-950 */
  --color-violet-100: oklch(33% 0.16 292); /* interpolated 900↔950 */
  --color-violet-200: oklch(43.2% 0.232 292.759); /* violet-800 */
  --color-fuchsia-50: oklch(29.3% 0.136 325.661); /* fuchsia-950 */
  --color-fuchsia-200: oklch(45.2% 0.211 324.591); /* fuchsia-800 */
  --color-lime-50: oklch(27.4% 0.072 132.109); /* lime-950 */
  --color-lime-200: oklch(45.3% 0.124 130.933); /* lime-800 */

  /* Construct/role text accents */
  --color-teal-700: oklch(85.5% 0.138 181.071); /* teal-300 */
  --color-violet-700: oklch(81.1% 0.111 293.571); /* violet-300 */

  /* Role swatches (roleColors.ts) — saturated mid-steps read on dark; unchanged. */
  --color-teal-500: oklch(70.4% 0.14 182.503);
  --color-violet-500: oklch(60.6% 0.25 292.717);
  --color-fuchsia-500: oklch(66.7% 0.295 322.15);
  --color-lime-600: oklch(64.8% 0.2 131.684);
  --color-cyan-600: oklch(60.9% 0.126 221.723);
  --color-purple-500: oklch(62.7% 0.265 303.9);
  --color-pink-500: oklch(65.6% 0.241 354.308);
  --color-stone-500: oklch(55.3% 0.013 58.071);

  /* --color-black intentionally NOT remapped: only use is dialog backdrops
   * (backdrop:bg-black/30), correct in both themes. */
}

/* uPlot's zoom-selection box is a baked rgba(0,0,0,.07) — invisible on dark. */
:root[data-theme='dark'] .u-select {
  background: rgba(255, 255, 255, 0.14);
}
```

- [ ] **Step 2: Sanity-check in the browser**

Run: `npm run dev` (backend not required for a visual spot check of the Builder with a local example). Toggle dark: canvas near-black, cards raised dark, construct tints keep their hues, error/warning chips read. Native selects/scrollbars render dark (color-scheme).

- [ ] **Step 3: Verify suite still clean**

Run: `npm test && npm run typecheck && npm run lint`
Expected: clean (no TS/test surface touched — this step is a regression tripwire).

- [ ] **Step 4: Commit**

```bash
git add src/index.css
git commit -m "feat(studio): dark palette remap — 58 tokens under data-theme=dark"
```

---

### Task 4: Theme-aware StreamChart

**Files:**
- Modify: `src/charts/StreamChart.tsx`

**Interfaces:**
- Consumes: `useThemeStore(s => s.effective)` (Task 1).
- Produces: `CHART_THEMES: Record<EffectiveTheme, { axis, grid, series }>` replacing `SERIES_COLORS`/`AXIS` (no external consumers — verified by grep).

- [ ] **Step 1: Rewrite the color constants and wire the theme**

Replace lines 10–22 (`SERIES_COLORS` + `AXIS`) with:

```tsx
import { useThemeStore } from '../stores/themeStore'
import type { EffectiveTheme } from '../stores/themeSetting'

/** Same hue order both themes; dark steps are brightened to read on the dark card.
 * uPlot takes concrete color strings at construction time, so the component rebuilds
 * on theme change (the `theme` dep below) rather than trying to restyle in place. */
export const CHART_THEMES: Record<
  EffectiveTheme,
  { axis: string; grid: string; series: readonly string[] }
> = {
  light: {
    axis: '#898781',
    grid: '#e1e0d9',
    series: ['#2a78d6', '#1baf7a', '#eda100', '#008300', '#4a3aa7', '#e34948'],
  },
  dark: {
    axis: '#9b99a1',
    grid: '#33333b',
    series: ['#5aa2f0', '#3ec98f', '#f0b429', '#59c159', '#9184e8', '#f0716a'],
  },
}
```

In the component: `const theme = useThemeStore((s) => s.effective)`, then inside the effect
`const { axis, grid, series } = CHART_THEMES[theme]`, axes use
`{ stroke: axis, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 } }`,
series stroke `series[i % series.length]`, and the recreate-effect dep array becomes
`[shape, height, theme]` (data updates still flow through the second effect's `setData`).

- [ ] **Step 2: Verify**

Run: `npm test && npm run typecheck && npm run lint`
Expected: clean. In the dev app with a record open (or a run streaming), toggling the theme rebuilds the chart with dark axes/grid and brightened series; legend text inherits the page's dark text color.

- [ ] **Step 3: Commit**

```bash
git add src/charts/StreamChart.tsx
git commit -m "feat(studio): theme-aware stream chart palettes"
```

---

### Task 5: Capture harness shoots both themes

**Files:**
- Modify: `tools/capture.mjs`

**Interfaces:**
- Produces: `--theme light|dark|both` flag (default `both`); screenshots under `<out>/<theme>/<state>@<viewport>.png`; each `probe.json` entry gains a `theme` field.

- [ ] **Step 1: Add the flag and theme loop**

After the `baseUrl` line:

```js
const themeArg = arg('theme', 'both')
const THEMES = themeArg === 'both' ? ['light', 'dark'] : [themeArg]
if (!THEMES.every((t) => t === 'light' || t === 'dark')) {
  console.error(`--theme must be light, dark, or both; got "${themeArg}"`)
  process.exit(1)
}
```

Wrap the main loop (currently `for (const vp of VIEWPORTS) { for (const state of states) {`) in an outer `for (const theme of THEMES) {`, and inside the loop:

```js
for (const theme of THEMES) {
  await mkdir(path.join(outDir, theme), { recursive: true })
  for (const vp of VIEWPORTS) {
    for (const state of states) {
      const context = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
      })
      // Through the app's OWN mechanism (the index.html boot script reads this key),
      // not a direct data-theme stamp — so every capture also exercises the no-flash
      // boot path, and a broken boot script fails loudly here.
      await context.addInitScript((t) => {
        try {
          localStorage.setItem('studio.theme', t)
        } catch {}
      }, theme)
      const page = await context.newPage()
      page.on('dialog', (d) => void d.accept())
      const id = `${theme}/${state.name}@${vp.name}`
      try {
        await state.setup(page)
        // A dark capture whose page silently stayed light would probe the LIGHT theme
        // under a dark label — the vacuous-pass trap again. Assert the stamp took.
        const stamped = await page.evaluate(() => document.documentElement.dataset.theme)
        if (theme === 'dark' && stamped !== 'dark') {
          throw new Error('dark capture but <html data-theme> is not "dark"')
        }
        if (theme === 'light' && stamped === 'dark') {
          throw new Error('light capture but <html data-theme> is "dark"')
        }
```

The body (probeRules, metrics, screenshot) is unchanged except: `report.push({ theme, state: state.name, viewport: vp.name, violations, metrics })` (and the error branch gains `theme` too), and the screenshot path is `path.join(outDir, `${id}.png`)` which now lands in the per-theme subdir. Close the extra brace at the loop end.

- [ ] **Step 2: Verify against the running dev server (light only, fast smoke)**

Run: `node tools/capture.mjs --out capture-out/smoke --theme light`
Expected: identical behavior to before the change (same states, `light/` prefix on ids), 0 setup failures.

- [ ] **Step 3: Commit**

```bash
git add tools/capture.mjs
git commit -m "feat(studio): capture harness shoots light+dark, asserts the stamp took"
```

---

### Task 6: Full both-theme capture; iterate palette until the probe is clean

**Files:**
- Modify: `src/index.css` (only if the probe flags dark values)

- [ ] **Step 1: Start backend + dev server** (per `tools/README.md`; backend on :8000, `npm run dev` on :5173 — the worktree has no `.venv`, so run the backend with the primary checkout's venv against this worktree's sources, or `uv venv && uv pip install -e .` in the worktree backend)

- [ ] **Step 2: Run the full capture**

Run: `node tools/capture.mjs --out capture-out/dark-theme`
Expected: every state × 3 viewports × 2 themes; read `capture-out/dark-theme/probe.json`.

- [ ] **Step 3: Fix any dark-side violations by adjusting `index.css` values only** (raise an L, drop a chroma — never touch component classes; the light palette is frozen). Re-run capture until **0 violations in both themes** (or only violations already present on `main`'s light run — compare with a `--theme light` run from the primary checkout if in doubt).

- [ ] **Step 4: Eyeball the dark screenshots** for non-contrast defects the probe cannot see: elevation reading correctly, construct hues distinguishable, hatch visible, chart legible.

- [ ] **Step 5: Commit any palette adjustments**

```bash
git add src/index.css
git commit -m "fix(studio): dark palette adjustments from the probe run"
```

---

### Task 7: Documentation

**Files:**
- Modify: `CLAUDE.md` (frontend one — the Colour section)

- [ ] **Step 1: Add the dark-theme rule to the Colour section**

```markdown
- **Dark theme is a palette remap, not a variant system.** `index.css`'s
  `:root[data-theme='dark']` block redefines every in-use `--color-*` token; components
  keep writing plain palette classes (`bg-white`, `text-red-600`) and MUST NOT use
  `dark:` variants, hex, or arbitrary values — the remap is the only mechanism
  (StreamChart's `CHART_THEMES` is the one sanctioned exception, uPlot needs concrete
  strings). A palette step used by a component but absent from the remap renders at its
  light value in dark mode; `npm run capture` shoots BOTH themes (probe R5 enforces AA
  on each), which is the enforcement. Theme state lives in `src/stores/themeStore.ts`
  (`studio.theme`); `index.html`'s inline script stamps `<html data-theme>` pre-paint.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(studio): dark-theme colour rules"
```

---

### Task 8: Ship

- [ ] **Step 1: Full local gate**

Run: `npm test && npm run typecheck && npm run lint && npm run build`
Expected: all clean.

- [ ] **Step 2: Browser sweep (Claude-in-Chrome)** — every tab (Builder, Run, Records, Labs, Devices) and every meaningful state (selection, error/warning chips, group scope + hatch, expanded group_ref, run log, stream charts, dialogs/pickers, drag states, Devices command forms, Labs roster) in dark AND light against the dev server. Fix + commit anything found (palette values in `index.css` only).

- [ ] **Step 3: Push, PR, CI, merge**

```bash
git push -u origin feat/dark-theme
gh pr create --title "feat(studio): dark theme" --body "..."
gh pr checks --watch
gh pr merge --squash
```

- [ ] **Step 4: Clean up the worktree** (after merge): `git worktree remove ../lab-devices-dark-theme` and delete the branch.
