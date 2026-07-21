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
  groupScopeRefs: path.join(repoRoot, 'webapp/fixtures/group-scope-refs.json'),
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

/** Select the first block card whose `textContent` matches `re`, by clicking its drag
 * header (the card's own onClick is what sets selection). Matches raw `textContent`, not
 * the accessible name — the distinction is load-bearing: the `∀` glyph on a `for_each`
 * card is `aria-hidden`, so it appears in `textContent` but is invisible to the accessible
 * name, which is exactly why the `for_each` selector below needed its leading anchor
 * removed (see `inspector-tail-absent` below). */
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
  // Verify the click actually landed — a selector that silently matched nothing (0 elements)
  // or a section that refused to open would otherwise leave every caller's state "clean" with
  // the tail still collapsed, which is the exact vacuous-pass trap this harness exists to catch.
  if ((await header.getAttribute('aria-expanded')) !== 'true') {
    throw new Error(`${title} section did not expand`)
  }
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
    name: 'group-scope-roles-streams',
    description:
      'editing probe_group: the Roles pump block shows top_pump AND the {param_pump} role ' +
      'param under an "In this group" divider (its verb chips draggable), and the opened ' +
      'Streams section shows od_top above the {param_stream}/{local_stream} subsection. The ' +
      'state that makes the new palette subsections non-vacuous for R4/R5 and the ' +
      'truncate-with-title rule.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.groupScopeRefs)
      await selectScope(page, 'probe_group')
      // Select the role-param badge so its draggable verb chips actually mount.
      await page.locator('[id="role-{param_pump}"]').click()
      await page.getByRole('button', { name: 'Streams', exact: true }).click()
      await page.waitForTimeout(200)
      // Assert the new DOM mounted, or the capture would be a vacuous clean pass.
      if ((await page.locator('[id="role-{param_pump}"]').count()) !== 1) {
        throw new Error('the {param_pump} role-param badge did not mount')
      }
    },
  },
  {
    name: 'group-scope-expression',
    description:
      'the expression-help popover while editing probe_group: its Streams list includes ' +
      '{param_stream}/{local_stream} and its Bindings list includes {tube}/{c}. Guards the ' +
      'scope-aware help wiring.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.groupScopeRefs)
      await selectScope(page, 'probe_group')
      await selectBlock(page, /branch on stream param|^\s*If /)
      await page.getByRole('button', { name: 'Expression help' }).first().click()
      await page.waitForTimeout(200)
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
      // Assert both sections actually auto-opened — a section that silently stayed
      // collapsed after the remount would still leave R4 nothing to measure, and no error
      // would surface anywhere else in this harness.
      const timingHeader = page.getByRole('button', { name: /^Timing/ })
      const failureHeader = page.getByRole('button', { name: /^On failure/ })
      if ((await timingHeader.getAttribute('aria-expanded')) !== 'true') {
        throw new Error('Timing did not auto-open after the away-and-back reselect')
      }
      if ((await failureHeader.getAttribute('aria-expanded')) !== 'true') {
        throw new Error('On failure did not auto-open after the away-and-back reselect')
      }
      if ((await page.getByLabel('Gap after').count()) !== 1) {
        throw new Error('Gap after not visible after Timing auto-opened')
      }
      if ((await page.getByLabel('On error').count()) !== 1) {
        throw new Error('On error not visible after On failure auto-opened')
      }
      // The auto-open path is `open = summary !== null` at mount (InspectorSection.tsx) —
      // aria-expanded alone can't distinguish that from a stale click, since both render
      // identically once open. The collapsed-state summary text is the one piece of DOM
      // evidence that the computed summary is genuinely non-null, but InspectorSection only
      // renders it while collapsed — so toggle Timing closed to read it, then back open to
      // leave the captured screenshot showing both sections expanded as described above.
      await timingHeader.click()
      const collapsedName = (await timingHeader.textContent()) ?? ''
      if (!/gap after 30s/.test(collapsedName)) {
        throw new Error(`Timing's collapsed summary did not carry its value: "${collapsedName}"`)
      }
      await timingHeader.click()
      await page.waitForTimeout(150)
      if ((await timingHeader.getAttribute('aria-expanded')) !== 'true') {
        throw new Error('Timing did not reopen after the summary-text check')
      }
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
      // expandSection already throws if its own click didn't land, but assert the fields
      // themselves rendered too — a collapsed section mounts no children at all
      // (InspectorSection.tsx), so this is the concrete proof R4 has rows to measure here.
      if ((await page.getByLabel('Gap after').count()) !== 1) {
        throw new Error('Timing expanded but Gap after is not visible')
      }
      if ((await page.getByLabel('On error').count()) !== 1) {
        throw new Error('On failure expanded but On error is not visible')
      }
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
      // Assert the premise this state depends on: dispense is NOT retry_safe, so ticking
      // the box opens the amber hazard box rather than materialising `retry` directly. If
      // the catalog ever marked dispense retry_safe, this would silently capture a less
      // dense shape (no hazard box) with nothing else to notice.
      if ((await page.getByLabel(/allow repeat/).count()) !== 1) {
        throw new Error(
          'the allow_repeat hazard box did not appear — dispense may no longer be retry-unsafe',
        )
      }
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
      // Assert the stated purpose directly: zero section headers of either kind, not just
      // "no error was thrown while looking for one" — a stray Timing/On failure header
      // here would mean `timingFields`/`failureFields` stopped returning `[]` for for_each.
      if ((await page.getByRole('button', { name: /^Timing/ }).count()) !== 0) {
        throw new Error('for_each rendered a Timing header — expected none')
      }
      if ((await page.getByRole('button', { name: /^On failure/ }).count()) !== 0) {
        throw new Error('for_each rendered an On failure header — expected none')
      }
    },
  },
  {
    name: 'inspector-bool-param-toggle',
    description:
      'a command with a bool param selected — the ONE R4-visible "control beside a button" ' +
      'row in the Inspector. Three rows pair a control with a button: ExpressionInput ' +
      '(textarea + IconButton) and the unknown-param remove row (span + IconButton) are both ' +
      'invisible to R4, which only collects BUTTON/INPUT/SELECT (probe.mjs) — deliberately, ' +
      'since a textarea is height-free and auto-grows, so a rule that flagged it would fire on ' +
      'correct multi-line code. The bool-param branch\'s `<select>` beside its "Use an ' +
      'expression" IconButton is the only one of the three built from collectable tags, so it ' +
      'is the only row this state needs to mount.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.torture)
      // valve_03 · configure carries a bool param (hold_torque), which is what renders
      // the select-plus-expression-toggle row R4 needs. It is not the only such block in
      // this fixture — od_meter_01 · measure (include_raw) and od_meter_02 ·
      // set_thermostat (enabled) are siblings of it in the same top-level `serial`
      // (gen_torture.py's every_catalog_verb()) — but any one of the three renders the
      // same row shape, so this state only needs to mount one.
      await selectBlock(page, /valve_03 · configure/)
      // Assert the row this state exists for actually mounted — a future fixture edit that
      // changes valve_03's params (or drops the bool one) would otherwise leave this state
      // silently measuring whatever row happens to render instead of the one that matters.
      if ((await page.getByRole('button', { name: 'Use an expression' }).count()) !== 1) {
        throw new Error('valve_03 · configure did not render the bool-param expression toggle')
      }
    },
  },
  {
    name: 'group-scope-typed-properties',
    description:
      "the group-scope Inspector with nothing selected: groups.service's typed param table " +
      '(tube:int, od:stream) and locals table (7 bindings/streams with init/units) — the S3 ' +
      'typed editors replacing the S2 read-only <ul> summaries.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.morbidostat)
      await selectScope(page, 'service')
      // The typed editors render one name TextField per declared param/local (placeholder
      // "name"); the S2 shim rendered plain read-only <li> text and had none of these. Pinned
      // to morbidostat's actual counts (2 params + 7 locals) rather than ">0" so a row silently
      // failing to render is caught, not just total absence.
      const nameFields = await page.evaluate(
        () => document.querySelectorAll('input[placeholder="name"]').length,
      )
      if (nameFields !== 9) {
        throw new Error(
          `group scope Inspector rendered ${nameFields} typed name fields, expected 9 (2 params + 7 locals)`,
        )
      }
    },
  },
  {
    name: 'group-ref-kind-aware-args',
    description:
      "a group_ref block ('service(tube={tube}, od={od})') selected: `as` marked required " +
      "(the group declares locals) and one kind-aware arg editor per param — od (stream) " +
      "renders as a StreamIntoPicker for an ORDINARY stream value, but both tube and od here " +
      'hold a `{name}` hole (this group_ref lives inside the tube/od for_each, whose body ' +
      "substitutes its own vars), so ArgField's hole handling must divert both to a mono text " +
      'field showing the hole literally instead of a picker/NumberField that cannot represent ' +
      'it (fix wave finding 1: StreamIntoPicker\'s <select> has no matching <option> for a ' +
      "hole, so it silently displayed the FIRST declared stream — od_1 — instead of {od}).",
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.morbidostat)
      await selectBlock(page, /^service\(tube=/)
      const asRequired = await page.evaluate(() =>
        [...document.querySelectorAll('label')].some(
          (l) => (l.textContent ?? '').includes('As (call-site prefix)') && (l.textContent ?? '').includes('*'),
        ),
      )
      if (!asRequired) {
        throw new Error('`as` was not marked required for a group that declares locals')
      }
      // Both args are holes here, not literals: `tube` (int) must show "{tube}" in a text
      // field (a NumberField cannot hold a string at all) and `od` (stream) must show "{od}"
      // in a text field rather than StreamIntoPicker's <select>, whose options are only real
      // stream names — none of which is "{od}", so the browser would otherwise fall back to
      // silently selecting the first one (finding 1).
      const holeInputValues = await page.evaluate(() =>
        [...document.querySelectorAll('input')].map((i) => i.value),
      )
      if (!holeInputValues.includes('{tube}')) {
        throw new Error("group_ref args did not display the 'tube' (int) arg's hole {tube} in a text field")
      }
      if (!holeInputValues.includes('{od}')) {
        throw new Error("group_ref args did not display the 'od' (stream) arg's hole {od} in a text field")
      }
      // And the od arg must NOT still be showing StreamIntoPicker's select — that's the exact
      // regression this fix removes (a <select> silently landing on od_1 instead).
      const streamPickerStillShown = await page.evaluate(() =>
        [...document.querySelectorAll('select')].some((sel) =>
          [...sel.options].some((o) => o.value === '__new__'),
        ),
      )
      if (streamPickerStillShown) {
        throw new Error("group_ref's 'od' arg still rendered StreamIntoPicker's select despite holding a hole")
      }
    },
  },
  {
    name: 'for-each-role-grid',
    description:
      'the outer for_each (tube:int, meter:role<densitometer>, od:stream) selected: the typed ' +
      'vars editor plus the typed row grid, whose `meter` column is a role <select> filtered ' +
      'to densitometer roles — the case design §9.2 calls out by name.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.morbidostat)
      await selectBlock(page, /^∀For each tube, meter,/)
      const gridPresent = (await page.locator('table').count()) > 0
      if (!gridPresent) {
        throw new Error('for_each Inspector did not render the row grid')
      }
      const roleColumnFiltered = await page.evaluate(() =>
        [...document.querySelectorAll('table select')].some((sel) =>
          [...sel.options].some((o) => o.value === 'od_meter_1'),
        ),
      )
      if (!roleColumnFiltered) {
        throw new Error("for_each grid did not render a role-filtered select for the 'meter' column")
      }
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
