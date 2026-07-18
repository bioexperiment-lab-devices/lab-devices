import { chromium } from 'playwright'
import { fileURLToPath } from 'node:url'
import { probeRules } from './probe.mjs'

const url = fileURLToPath(new URL('./probe-selftest.html', import.meta.url))
const browser = await chromium.launch()
const page = await browser.newPage()
await page.goto(`file://${url}`)
const found = await page.evaluate(probeRules)
await browser.close()

const rules = [...new Set(found.map((v) => v.rule))].sort()
// Exactly one plant per rule, EXCEPT sibling-height-mismatch, which carries three
// deliberately: the original center-aligned mismatch (R4), plus two added to close blind
// spots found in review — R4b (an align-items:stretch row whose children set explicit,
// mismatched heights: stretch does not override an explicit height, so this survives
// stretch and a rule that skipped all stretch rows could never see it) and R4c (a control
// nested one level below row.children inside a plain grouping div, invisible to a
// direct-children-only scan). This is a deliberate, documented count, not a loosened
// assertion — the "exactly N" check below still fails on any drift.
// text-contrast carries two plants: R5a (faint text on the depth zebra, reached only by
// walking up to a tinted ancestor) and R5b (the same text over the hatch, reached only by
// considering background-image colour stops). They fail for different reasons, so one cannot
// stand in for the other.
const expectedCounts = {
  'clipped-overflow': 1,
  'sibling-height-mismatch': 3,
  'text-contrast': 2,
  'tiny-target': 1,
  'truncate-without-title': 1,
}
const expected = Object.keys(expectedCounts).sort()

// An untested probe reporting zero violations is indistinguishable from a working app, and
// is MORE dangerous than no probe. It must be proven to find planted bugs before its
// silence means anything.
const missing = expected.filter((r) => !rules.includes(r))
if (missing.length) {
  console.error(`FAIL — probe missed planted violations: ${missing.join(', ')}`)
  process.exit(1)
}
const counts = Object.fromEntries(
  expected.map((r) => [r, found.filter((v) => v.rule === r).length]),
)
const overfired = expected.filter((r) => counts[r] !== expectedCounts[r])
if (overfired.length) {
  console.error(
    `FAIL — expected ${JSON.stringify(expectedCounts)} hits per rule, got ${JSON.stringify(counts)} (traps firing?)`,
  )
  process.exit(1)
}
console.log('PASS — probe found exactly the planted set:', JSON.stringify(counts))
