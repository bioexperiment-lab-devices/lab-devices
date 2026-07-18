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
    name: 'group-scope-deep',
    description:
      "the torture fixture's `deep_group`, whose body nests serial>branch>parallel>loop>serial. " +
      'This is the state that makes the depth zebra and the group-scope hatch non-vacuous AT THE ' +
      'SAME TIME. Measured on the running app: 7 rendered container levels with both zebra ' +
      'classes present (bg-slate-50 x7, bg-slate-100 x14) and bg-hatch mounted x1. Without a ' +
      'group-scope state carrying real nesting, interiorFillClass() would only ever be observed ' +
      'at depth 1 and `interiorFillClass(2)` would be reported clean by a rule that never saw it — ' +
      'W12 shipped exactly that defect, a rule reporting clean on rows that never mounted.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.torture)
      await selectScope(page, 'deep_group')
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
]

const SETUP_HELP =
  'Start the dev server from the checkout you mean to measure, on a port of its own, and ' +
  'pass it explicitly:\n' +
  '  npx vite --port 5179 --strictPort   # in THIS checkout\n' +
  '  node tools/capture.mjs --url http://localhost:5179 --out <dir>\n' +
  'Capturing against the wrong build reports clean states about code that is not there.'

/** Staleness guard — run BEFORE anything is captured.
 *
 * `--url` is just a port, and a Vite left running by a DIFFERENT CHECKOUT answers on it
 * exactly as convincingly as the right one. Measured during this increment: a stale server on
 * :5173 was serving the main checkout while the work sat in a worktree. Capturing against it
 * would have reported 21 clean states about code containing none of this increment — a silent
 * pass, the worst possible outcome for a harness whose entire job is to catch regressions.
 *
 * So the harness proves the server is the right build instead of assuming it: load the torture
 * fixture (whose main scope contains a `parallel` and a `loop`) and require the construct
 * tints to actually be in the DOM. Any build predating the canvas visual language renders
 * those containers untinted and fails here, loudly, before a single screenshot is written.
 */
async function assertServerServesThisCheckout(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  page.on('dialog', (d) => void d.accept())
  let tinted = 0
  try {
    await gotoBuilder(page)
    await importDoc(page, FIXTURES.torture)
    tinted = await page.evaluate(
      () => document.querySelectorAll('.bg-teal-50, .bg-fuchsia-50').length,
    )
  } catch (e) {
    // A wrong build does not necessarily reach the tint check — it may not present a Builder
    // tab, or may not import a fixture, at all. Any preflight failure is reported as the setup
    // problem it is, rather than as a bare Playwright timeout the reader has to interpret.
    throw new Error(
      `SETUP ERROR — could not drive the app at ${baseUrl} far enough to verify it.\n` +
        `Underlying failure: ${e}\n` +
        `Is something else listening on that port, or is the server not running?\n${SETUP_HELP}`,
    )
  } finally {
    await context.close()
  }
  if (tinted === 0) {
    throw new Error(
      `SETUP ERROR — stale or wrong dev server at ${baseUrl}.\n` +
        'The torture fixture loaded, but its parallel/loop containers rendered with NO ' +
        'construct tint (0 elements matching .bg-teal-50 / .bg-fuchsia-50). That markup ' +
        'predates the canvas visual language, so this port is almost certainly serving a ' +
        `DIFFERENT CHECKOUT.\n${SETUP_HELP}`,
    )
  }
}

const browser = await chromium.launch()
await assertServerServesThisCheckout(browser)
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
      // Not a rule (the probe has exactly five), but the number the layout work is judged
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
