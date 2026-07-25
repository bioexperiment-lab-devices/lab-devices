import { chromium } from 'playwright'
const OUT = '/private/tmp/claude-501/-Users-khamit-lab-devices/199327d3-0209-4fb5-9b1f-68f2a7e2b00e/scratchpad'
const DOC = process.argv[2] ?? `${OUT}/demo.json`
const TAG = process.argv[3] ?? 'after'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } })
await page.goto('http://localhost:5173', { waitUntil: 'domcontentloaded' })
await page.getByRole('button', { name: /^1\s*Builder$/ }).click()
await page.getByRole('button', { name: 'Load', exact: true }).waitFor()
await page.setInputFiles('input[type=file]', DOC)
await page.waitForFunction(() => document.querySelectorAll('[id^="block-"]').length > 0, undefined, { timeout: 15000 })
await page.waitForTimeout(900)
await page.screenshot({ path: `${OUT}/demo-${TAG}.png`, clip: { x: 285, y: 90, width: 900, height: 860 } })

const geom = await page.evaluate(() => {
  const round = (n) => Math.round(n * 10) / 10
  const box = (el) => (el ? { top: round(el.getBoundingClientRect().top), h: round(el.getBoundingClientRect().height), w: round(el.getBoundingClientRect().width) } : null)
  // the top-level parallel: lanes 1 (one chip) / 2 (empty) / 3 (tall)
  const lanes = [...document.querySelectorAll('.min-w-48')]
  const alarm = [...document.querySelectorAll('[id^="block-"]')].find((e) => (e.textContent || '').startsWith('Alarm'))
  const hints = [...document.querySelectorAll('div')].filter((d) => d.textContent === 'drop here')
  const addLane = [...document.querySelectorAll('button')].find((b) => b.title === 'Add lane')
  const addElse = [...document.querySelectorAll('button')].find((b) => (b.textContent || '').includes('add else'))
  const wait = [...document.querySelectorAll('[id^="block-"]')].find((e) => (e.textContent || '').startsWith('wait'))
  return {
    firstCard: box(alarm),
    lastCardOfTallLane: box(wait),
    hint0: box(hints[0]),
    addLane: box(addLane),
    addElse: box(addElse),
    laneCount: lanes.length,
  }
})
console.log(JSON.stringify(geom, null, 1))
await browser.close()
