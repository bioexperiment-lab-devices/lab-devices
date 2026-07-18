/**
 * Capture harness: drives the running Studio across the states behind the audit
 * screenshots, at three viewports, writing a PNG per state/viewport plus a single
 * `probe.json` holding every violation the probe found.
 *
 * PREREQUISITE: the dev server is already running (`npm run dev`, which proxies /api to
 * the backend on :8000). This script does NOT start it — see tools/README.md.
 *
 *   node tools/capture.mjs --out ../../../.tmp/capture
 *   node tools/capture.mjs --out /tmp/shots --url http://localhost:5174
 */
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { probeRules } from './probe.mjs'

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`)
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback
}

const outDir = path.resolve(arg('out', 'capture-out'))
const baseUrl = arg('url', 'http://localhost:5173')

const repoRoot = fileURLToPath(new URL('../../../', import.meta.url))
const FIXTURES = {
  morbidostat: path.join(repoRoot, 'examples/morbidostat.json'),
  torture: path.join(repoRoot, 'webapp/fixtures/ui-audit-torture.json'),
}

const VIEWPORTS = [
  { name: '1024x720', width: 1024, height: 720 },
  { name: '1440x900', width: 1440, height: 900 },
  { name: '1920x1080', width: 1920, height: 1080 },
]

/** Click the Builder tab and wait for the toolbar to exist. */
async function gotoBuilder(page) {
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: /^1\s*Builder$/ }).click()
  await page.getByRole('button', { name: 'Load', exact: true }).waitFor()
}

/** Import a doc through the Toolbar's hidden file input — server-backed, and independent
 * of whatever happens to be saved in the backend already. */
async function importDoc(page, file) {
  await page.setInputFiles('input[type=file]', file)
  await page.waitForFunction(
    () => document.querySelectorAll('[id^="block-"]').length > 0,
    undefined,
    { timeout: 15_000 },
  )
  await page.waitForTimeout(400) // let validation settle so the chip is not mid-flight
}

/** Select the first block card whose one-line summary matches `re`, by clicking its
 * drag header (the card's own onClick is what sets selection). */
async function selectBlock(page, re) {
  const uid = await page.evaluate((src) => {
    const rx = new RegExp(src)
    for (const el of document.querySelectorAll('[id^="block-"]')) {
      const header = el.firstElementChild
      if (header && rx.test(header.textContent ?? '')) return el.id
    }
    return null
  }, re.source)
  if (!uid) throw new Error(`no block matching ${re}`)
  // Attribute selector, not `#id` — the uids are generated and need no CSS escaping here,
  // and `CSS.escape` is a browser global that does not exist in Node.
  await page.locator(`[id="${uid}"] > div`).first().click({ position: { x: 120, y: 10 } })
  await page.waitForTimeout(200)
  return uid
}

/** Switch the Canvas to a named group. Every `branch` in morbidostat.json lives inside
 * `groups.service`, which the main tree cannot reach — a `group_ref` node has no
 * childSlots — so the branch states must switch scope first. */
async function selectScope(page, group) {
  await scopeSelect(page).selectOption(group)
  await page.waitForTimeout(300)
}

/** The ScopeSwitcher's <select>, identified by its fixed "Main workflow" option — the
 * Roles and Streams panels also render <select>s and an "Add" button, so neither
 * `select` nor `getByRole('button', {name: 'Add'})` is unique on this page. */
const scopeSelect = (page) => page.locator('select:has(option:text-is("Main workflow"))')
/** The ScopeSwitcher row itself, so "New group…"/"Add" resolve inside it. */
const scopeRow = (page) => scopeSelect(page).locator('xpath=..')

/** A block whose DIRECT parent is `parallel` — the only position where `timingFields`
 * (inspectorRules.ts) offers `Start offset` instead of `Gap after`. Settled on lane 1 of
 * ui-audit-torture.json's top-level 8-lane `parallel` (blocks[5]): every lane there is a
 * `serial`, and W13 makes a `serial` lane render AS the lane itself (Canvas.tsx `Lane`) —
 * its handle row's accessible text is `lane 1` (from the lane index), immediately followed
 * by the block's own quoted label (also "lane 1" in this fixture, coincidentally), so the
 * DOM text is `lane 1"lane 1"`. Confirmed empirically against the running app: selecting
 * this block and opening Timing shows exactly one `Start offset` field and zero `Gap
 * after` fields — see the `inspector-tail-start-offset` state below, which asserts this
 * rather than trusting the selector. */
const PARALLEL_CHILD = /^lane 1\b/

/** Expand a collapsed Inspector tail section by title. The accessible name gains the
 * collapsed-state summary once a value is set (`Timing · gap after 30s`), so anchor the
 * match at the start rather than using an exact name. */
async function expandSection(page, title) {
  const header = page.getByRole('button', { name: new RegExp(`^${title}`) })
  if ((await header.getAttribute('aria-expanded')) === 'false') await header.click()
  await page.waitForTimeout(150)
}

const states = [
  {
    name: 'builder-morbidostat',
    description: 'morbidostat example loaded, nothing selected',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.morbidostat)
    },
  },
  {
    name: 'branch-selected',
    description: 'a branch block selected, Inspector showing its condition',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.morbidostat)
      await selectScope(page, 'service')
      await selectBlock(page, /^\s*If /)
    },
  },
  {
    name: 'inspector-operator-input',
    description: 'Inspector on an operator-input block',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.morbidostat)
      await selectBlock(page, /input .+ \(/)
    },
  },
  {
    name: 'expression-popover',
    description: 'the expression-help popover open over the Inspector',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.morbidostat)
      await selectScope(page, 'service')
      await selectBlock(page, /^\s*If /)
      await page.getByRole('button', { name: 'Expression help' }).first().click()
      await page.waitForTimeout(200)
    },
  },
  {
    name: 'builder-torture',
    description: 'the boundary-stress fixture — long names, deep nesting, many lanes',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.torture)
    },
  },
  {
    name: 'scope-switcher-long-group',
    description:
      'a group whose name is far longer than any fixture ships — the ScopeSwitcher <select> ' +
      'sizes itself to its longest option, so this is what would widen the canvas if anything does. ' +
      'Also opens the Palette\'s Groups section so the declared group\'s draggable-chip row ' +
      '(Palette.tsx GroupsPanel) actually mounts — otherwise R4 (sibling-height-mismatch) has ' +
      'nothing to measure on those rows, since the section renders `defaultOpen={false}`.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.torture)
      const row = scopeRow(page)
      await row.getByRole('button', { name: /New group/ }).click()
      await row.getByPlaceholder('group name').fill('group_' + 'g'.repeat(80))
      await row.getByRole('button', { name: 'Add', exact: true }).click()
      await page.waitForTimeout(400)
      await page.getByRole('button', { name: 'Groups', exact: true }).click()
      await page.waitForTimeout(200)
    },
  },
  {
    name: 'inspector-tail-autoopen',
    description:
      'both tail sections auto-opened by non-default values. Sets the values, then selects ' +
      'AWAY and back so BlockForm remounts and the auto-open path (summary !== null) is what ' +
      'opens them — not the clicks that set them.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.torture)
      await selectBlock(page, /^\s*wait /)
      await expandSection(page, 'Timing')
      await page.getByLabel('Gap after').fill('30s')
      await page.getByLabel('Gap after').press('Enter')
      await expandSection(page, 'On failure')
      await page.getByLabel('On error').selectOption('continue')
      await page.waitForTimeout(200)
      await selectBlock(page, /^\s*Abort if /) // away…
      await selectBlock(page, /^\s*wait /) // …and back: remount, auto-open
    },
  },
  {
    name: 'inspector-tail-expanded',
    description:
      'a block at all defaults with both tail sections manually expanded — the collapsed ' +
      'default would leave R4 (sibling-height-mismatch) nothing to measure on these rows, ' +
      'which is exactly how W12 shipped a vacuously clean probe run.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.torture)
      await selectBlock(page, /^\s*Alarm if /)
      await expandSection(page, 'Timing')
      await expandSection(page, 'On failure')
    },
  },
  {
    name: 'inspector-retry-hazard',
    description:
      'the densest mixed-control rows in the panel: the amber allow_repeat hazard box open ' +
      'under On failure, for a verb the catalog does not report as retry_safe.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.morbidostat)
      // pump.dispense takes a RELATIVE volume_ml, so the engine registry leaves it
      // retry_safe = False — retrying after a partial dispense double-doses the culture.
      // It lives in groups.service, which the main tree cannot reach.
      await selectScope(page, 'service')
      await selectBlock(page, / · dispense/)
      await expandSection(page, 'On failure')
      await page.getByLabel('retry on failure').check()
      await page.waitForTimeout(200)
    },
  },
  {
    name: 'inspector-tail-start-offset',
    description:
      'a block sitting in a parallel lane, whose Timing section offers Start offset INSTEAD of ' +
      'Gap after (a lane has no next-in-list). The only state that renders that control, and ' +
      'the one field the Task 4 browser check never exercised.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.torture)
      await selectBlock(page, PARALLEL_CHILD)
      await expandSection(page, 'Timing')
      // Assert PARALLEL_CHILD really is a parallel's direct child, not just trust the
      // selector — a `Gap after` field here would mean the block picked has a `serial`
      // or other non-parallel parent, and every row below would measure the wrong shape.
      if ((await page.getByLabel('Start offset').count()) !== 1) {
        throw new Error('PARALLEL_CHILD did not render Start offset — not a parallel lane child')
      }
      if ((await page.getByLabel('Gap after').count()) !== 0) {
        throw new Error('PARALLEL_CHILD rendered Gap after — not a parallel lane child')
      }
    },
  },
  {
    name: 'inspector-tail-absent',
    description:
      'a for_each block, which renders NO tail at all (expand.py:26 forbids all four ' +
      'block-level keys on a splice). Guards the empty-section path against a regression ' +
      'that renders an empty bordered box.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.torture)
      // No leading `\s*` anchor: for_each is the one kind with no Lucide icon (icons.tsx
      // BLOCK_ICONS.for_each is null) — KindIcon renders a literal `∀` text glyph instead,
      // which lands in the card header's textContent BEFORE blockSummary's text. Anchoring
      // at the very start (as the other selectBlock regexes do) never matches; confirmed
      // empirically against the running app.
      await selectBlock(page, /For each /)
    },
  },
]

const browser = await chromium.launch()
await mkdir(outDir, { recursive: true })
const report = []
let failures = 0

for (const vp of VIEWPORTS) {
  for (const state of states) {
    const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } })
    const page = await context.newPage()
    // Import over a dirty doc pops a confirm(); always take the destructive branch.
    page.on('dialog', (d) => void d.accept())
    const id = `${state.name}@${vp.name}`
    try {
      await state.setup(page)
      const violations = await page.evaluate(probeRules)
      // Not a rule (the probe has exactly four), but the number the layout work is judged
      // on: does the document, or the Canvas's single scroller, exceed the viewport?
      const metrics = await page.evaluate(() => {
        const doc = document.documentElement
        // Select the canvas BY IDENTITY, not by "first element that happens to scroll
        // horizontally". A document-order scan reports the left palette instead whenever the
        // palette also overflows — measured on the torture fixture, where it logged the
        // palette's 590>255 while the canvas was really 4008>1294. Any element whose
        // overflow-y is auto also computes overflow-x to auto (per CSS overflow coercion),
        // so scrolling side panels match the naive predicate by construction.
        const canvas = document.querySelector('.overflow-auto.bg-slate-100')
        const overflowsX = (e) =>
          e && getComputedStyle(e).overflowX === 'auto' && e.scrollWidth > e.clientWidth + 1
        return {
          viewportWidth: window.innerWidth,
          documentScrollWidth: doc.scrollWidth,
          pageOverflowsViewport: doc.scrollWidth > window.innerWidth + 1,
          canvasScrollerOverflow: overflowsX(canvas)
            ? { scrollWidth: canvas.scrollWidth, clientWidth: canvas.clientWidth }
            : null,
          // Every horizontally-scrolling box, so a second scroller reappearing (the F11
          // regression this work exists to prevent) is visible in the evidence rather than
          // hidden behind whichever one sorted first.
          horizontalScrollers: [...document.querySelectorAll('*')]
            .filter(overflowsX)
            .map((e) => ({
              selector: String(e.className).trim().split(/\s+/).slice(0, 6).join('.'),
              scrollWidth: e.scrollWidth,
              clientWidth: e.clientWidth,
            })),
        }
      })
      await page.screenshot({ path: path.join(outDir, `${id}.png`), fullPage: false })
      report.push({ state: state.name, viewport: vp.name, violations, metrics })
      const tally = violations.reduce((a, v) => ({ ...a, [v.rule]: (a[v.rule] ?? 0) + 1 }), {})
      const overflow = metrics.pageOverflowsViewport
        ? ` PAGE-OVERFLOW ${metrics.documentScrollWidth}>${metrics.viewportWidth}`
        : ''
      console.log(
        `${id}: ${violations.length === 0 ? 'clean' : JSON.stringify(tally)}${overflow}`,
      )
    } catch (e) {
      failures += 1
      report.push({ state: state.name, viewport: vp.name, error: String(e) })
      console.error(`${id}: ERROR ${e}`)
    }
    await context.close()
  }
}

await browser.close()
await writeFile(path.join(outDir, 'probe.json'), JSON.stringify(report, null, 2) + '\n')

const total = report.reduce((n, r) => n + (r.violations?.length ?? 0), 0)
console.log(`\nwrote ${report.length} screenshots + probe.json to ${outDir}`)
console.log(`${total} violation(s) across ${report.length} state/viewport combinations`)
if (failures > 0) {
  console.error(`${failures} state(s) failed to set up`)
  process.exit(1)
}
