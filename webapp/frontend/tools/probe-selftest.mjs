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
const expected = [
  'clipped-overflow',
  'sibling-height-mismatch',
  'tiny-target',
  'truncate-without-title',
]

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
const overfired = expected.filter((r) => counts[r] !== 1)
if (overfired.length) {
  console.error(
    `FAIL — expected exactly one hit per rule, got ${JSON.stringify(counts)} (traps firing?)`,
  )
  process.exit(1)
}
console.log('PASS — probe found exactly the planted set:', JSON.stringify(counts))
