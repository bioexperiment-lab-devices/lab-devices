/** Rules run inside the page via page.evaluate(). Keep this a single pure function with no
 * imports — it is serialised into the browser. */
export function probeRules() {
  const out = []
  const cssPath = (el) => {
    const parts = []
    for (let n = el; n && n.nodeType === 1 && parts.length < 4; n = n.parentElement) {
      parts.unshift(
        n.tagName.toLowerCase() +
          (n.className ? '.' + String(n.className).trim().split(/\s+/).join('.') : ''),
      )
    }
    return parts.join(' > ')
  }

  // R1 — clipped overflow: content wider than its box under a non-scrolling overflow.
  //
  // The exclusion is load-bearing, not a convenience. Tailwind's `truncate` compiles to
  // `overflow:hidden; white-space:nowrap; text-overflow:ellipsis`, so EVERY actively
  // ellipsizing element satisfies the naive condition by construction — the app has 16 of
  // them. Without this guard the rule can never return empty, goes permanently red, and
  // gets ignored, which is worse than not having it. Deliberate single-line ellipsis is
  // R2's business (it checks the text is still reachable via `title`), not R1's.
  // Second exclusion, same reasoning as the first and found the same way — by running the
  // probe against the real app rather than by argument. Chromium's UA stylesheet reports
  // `overflow-x: clip` for <input>/<textarea>, but a native text control SCROLLS its own
  // value: measured on the Inspector's Label field holding a 138-char morbidostat label,
  // setting scrollLeft moved it 0 -> 325, so the text is reachable by caret or drag. Every
  // Inspector text field holding a long value would otherwise be a standing R1 hit, which
  // is the permanently-red failure mode described above. Excluded by natively-scrolling
  // control, not by tag name: a <select> is NOT excluded, because a too-long option really
  // is unreachable.
  const NON_TEXT_INPUTS = ['checkbox', 'radio', 'range', 'color', 'button', 'submit', 'reset', 'image', 'file']
  for (const el of document.querySelectorAll('*')) {
    const s = getComputedStyle(el)
    const ellipsized = s.whiteSpace === 'nowrap' && s.textOverflow === 'ellipsis'
    if (ellipsized) continue
    const nativeTextControl =
      el.tagName === 'TEXTAREA' ||
      (el.tagName === 'INPUT' && !NON_TEXT_INPUTS.includes(el.type))
    if (nativeTextControl) continue
    if ((s.overflowX === 'hidden' || s.overflowX === 'clip') && el.scrollWidth > el.clientWidth + 1) {
      out.push({
        rule: 'clipped-overflow',
        selector: cssPath(el),
        detail: `${el.scrollWidth} > ${el.clientWidth}`,
      })
    }
  }

  // R2 — truncate without title: an ellipsised label with no hover text is unreadable.
  for (const el of document.querySelectorAll('*')) {
    if (
      getComputedStyle(el).textOverflow === 'ellipsis' &&
      el.scrollWidth > el.clientWidth + 1 &&
      !el.title
    ) {
      out.push({
        rule: 'truncate-without-title',
        selector: cssPath(el),
        detail: el.textContent?.slice(0, 40) ?? '',
      })
    }
  }

  // R3 — tiny target: interactive controls below the 24px hit-area floor.
  for (const el of document.querySelectorAll('button, a[href], input, select, textarea')) {
    const r = el.getBoundingClientRect()
    if (r.width > 0 && (r.height < 23.5 || r.width < 23.5) && el.tagName === 'BUTTON') {
      out.push({
        rule: 'tiny-target',
        selector: cssPath(el),
        detail: `${Math.round(r.width)}x${Math.round(r.height)}`,
      })
    }
  }

  // R4 — sibling controls disagree about height. THIS IS THE NEW RULE (spec §5): the audit
  // had no rule for it, which is why all twelve C-sites shipped in 0.8.0.
  //
  // No `align-items: stretch` skip. An earlier version had one, commented "stretch makes
  // heights agree by definition" — false whenever a child sets an explicit height, which is
  // exactly what this codebase's control token does (`CONTROL_H = 'h-6'`, src/ui/controls.ts):
  // per the flexbox spec, `stretch` only inflates a flex item whose cross-size is `auto`; an
  // item with an explicit height keeps it. Measured in Chromium: two children with explicit
  // 24px/28px heights under `align-items: stretch` render at 24/28 (mismatch preserved, spread
  // 4px); two children with NO explicit height under the same `align-items: stretch` render
  // identically (spread 0px). So dropping the skip and relying solely on the >1px threshold
  // below catches the real defect (explicit-height mismatch survives stretch) without flagging
  // genuine stretch equalization (auto-height children truly render at equal heights) — no
  // false positive, no re-introduced blind spot.
  //
  // Controls are gathered by descending into plain (non-flex) wrapper divs — a control one
  // level deeper than `row.children` (e.g. the Toolbar's button grouping, or a chip wrapped in
  // its own div) was invisible to a direct-children-only scan. Descent stops at any element
  // that is itself a flex row: that element gets its own pass through this same loop, so
  // descending into it here would double-count it and could wrongly compare controls that
  // belong to an independently-laid-out nested row.
  //
  // Gathered controls are then clustered by vertical overlap into visual lines before
  // comparing heights, so a `flex-wrap` container that wraps into multiple lines only compares
  // controls that actually share a rendered row — two controls on different wrapped lines can
  // have wildly different heights without it being a mismatch of anything.
  const rowControls = (row) => {
    const found = []
    const walk = (el) => {
      for (const child of el.children) {
        if (['BUTTON', 'INPUT', 'SELECT'].includes(child.tagName)) {
          found.push(child)
          continue
        }
        const cs = getComputedStyle(child)
        const isNestedRow = cs.display === 'flex' && !cs.flexDirection.startsWith('column')
        if (!isNestedRow) walk(child) // a nested flex row is inspected in its own iteration
      }
    }
    walk(row)
    return found
  }
  for (const row of document.querySelectorAll('*')) {
    const s = getComputedStyle(row)
    if (s.display !== 'flex' || s.flexDirection.startsWith('column')) continue
    const controls = rowControls(row)
    if (controls.length < 2) continue
    const withRect = controls
      .map((c) => ({ c, r: c.getBoundingClientRect() }))
      .filter((x) => x.r.height > 0)
      .sort((a, b) => a.r.top - b.r.top)
    const lines = []
    for (const item of withRect) {
      const line = lines.find((l) => item.r.top < l.bottom && item.r.bottom > l.top)
      if (line) {
        line.items.push(item)
        line.top = Math.min(line.top, item.r.top)
        line.bottom = Math.max(line.bottom, item.r.bottom)
      } else {
        lines.push({ items: [item], top: item.r.top, bottom: item.r.bottom })
      }
    }
    for (const line of lines) {
      if (line.items.length < 2) continue
      const hs = line.items.map((x) => x.r.height)
      const spread = Math.max(...hs) - Math.min(...hs)
      if (spread > 1) {
        out.push({
          rule: 'sibling-height-mismatch',
          selector: cssPath(row),
          detail: `spread ${spread.toFixed(1)}px`,
        })
      }
    }
  }

  // R5 — text below the WCAG AA contrast floor. Added for the canvas visual language: five
  // construct-keyed container tints, a depth zebra alternating slate-50/slate-100, eight
  // saturated role swatches and two hatch utilities all put NEW coloured surface under text,
  // and nothing in this harness was measuring it.
  //
  // Colour is read back as PIXELS, not parsed as a string, and that is not a style choice.
  // Tailwind 4 emits `oklch()`/`oklab()` for every palette colour except white and black
  // (which stay hex), so an `rgb(...)`-only regex misses nearly every real colour in this app.
  // Its failure mode is not silence, it is INVERSION: an earlier scratchpad version of this
  // rule scored the colours it could not parse as black/white and so reported confident
  // ratio-1.00 "white on white" violations on the brand buttons while staying completely
  // silent on the genuinely faint slate text it existed to find. The obvious workaround fails
  // too — Chromium round-trips oklch through `ctx.fillStyle` VERBATIM (measured: assigning
  // "oklch(0.984 0.014 180.72)" reads the same string back, not an rgb() form), so the usual
  // canvas-normalisation trick silently returns the input. Painting the colour and reading the
  // bytes back is what actually resolves it: that same teal-50 reads back as [240, 253, 250].
  const cvs = document.createElement('canvas')
  cvs.width = 1
  cvs.height = 1
  const ctx = cvs.getContext('2d', { willReadFrequently: true })
  const rgbaCache = new Map() // every element walks its ancestors; the same few colours recur
  const toRGBA = (css) => {
    if (rgbaCache.has(css)) return rgbaCache.get(css)
    // Assigning an invalid value to fillStyle leaves it at its previous value rather than
    // throwing, so "did this parse?" is answered by assigning it after two DIFFERENT
    // sentinels: a real colour lands on the same value both times, a non-colour keeps
    // whichever sentinel preceded it. Needed because the gradient stops below are pulled
    // out of a computed string by regex and can hand this function a non-colour token.
    ctx.fillStyle = '#000000'
    ctx.fillStyle = css
    const afterBlack = ctx.fillStyle
    ctx.fillStyle = '#ffffff'
    ctx.fillStyle = css
    const afterWhite = ctx.fillStyle
    let v = null
    if (afterBlack === afterWhite) {
      ctx.clearRect(0, 0, 1, 1)
      ctx.fillStyle = css
      ctx.fillRect(0, 0, 1, 1)
      const d = ctx.getImageData(0, 0, 1, 1).data
      v = [d[0], d[1], d[2], d[3] / 255]
    }
    rgbaCache.set(css, v)
    return v
  }
  const over = (fg, bg) => [0, 1, 2].map((i) => fg[i] * fg[3] + bg[i] * (1 - fg[3]))
  const relLum = (c) => {
    const f = (v) => {
      const x = v / 255
      return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4)
    }
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])
  }
  const contrast = (a, b) => {
    const [x, y] = [relLum(a), relLum(b)]
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
  }

  // Effective background = the ancestor chain composited, walked OUTWARD until a fully opaque
  // layer is reached and then painted back inward over the page's white canvas. The walk is
  // the whole point: in this app the text element is almost never the coloured one. Every
  // construct tint and every zebra stripe is set on a container, and the label inside it is a
  // transparent <span>, so a check that read only the element's own `background-color` would
  // score all of them against white and miss exactly the surfaces this rule was added for.
  // Partial alpha is composited rather than rounded to opaque, so a translucent layer
  // contributes only its real share.
  //
  // HATCHED / STRIPED SURFACES (`bg-hatch`, `edge-hatch` in src/index.css) — the decision:
  // a striped background has NO single background colour, so there is no honest scalar to
  // compare against. This rule therefore evaluates the text against the base composite AND
  // against every opaque colour stop in the background-image (each composited over that base)
  // and keeps the WORST ratio. That is deliberately conservative: it treats a stripe that in
  // reality covers 1px in 6 as if it covered the glyph completely. The alternative — scoring
  // the base only — is a false negative dressed up as a pass, which is the failure mode that
  // matters here, since the stripe is by construction the darker colour and so always the
  // side the text is closest to. The conservatism was checked against the real palette before
  // being adopted: the sanctioned pairing (`text-caption`/slate-600 over the slate-200 hatch
  // stripe) measures 6.15:1 and so still clears AA at full assumed coverage, i.e. this does
  // NOT make the two hatched surfaces permanently red. `text-hint`/slate-500 over that same
  // stripe measures 3.86:1 and does fire, which is a true finding and matches the standing
  // instruction in src/index.css to verify hatch contrast with the probe rather than by eye.
  //
  // A `url()` background is unknowable from colour tokens alone (it could be any image), so
  // such an element is skipped outright rather than scored against its base and reported as a
  // pass it has not earned. This app currently has none.
  const COLOR_TOKEN = /(?:oklch|oklab|rgba?|hsla?|lab|lch|color)\([^()]*\)|#[0-9a-f]{3,8}/gi
  const effectiveBg = (el) => {
    const layers = []
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const s = getComputedStyle(n)
      const c = toRGBA(s.backgroundColor) ?? [0, 0, 0, 0]
      layers.push({ color: c, image: s.backgroundImage })
      if (c[3] >= 0.999) break // opaque: nothing above it can show through
    }
    let base = [255, 255, 255] // the page canvas sits under everything
    const stripes = []
    for (let i = layers.length - 1; i >= 0; i--) {
      base = over(layers[i].color, base)
      const img = layers[i].image
      if (!img || img === 'none') continue
      if (img.includes('url(')) return null
      for (const tok of img.match(COLOR_TOKEN) ?? []) {
        const c = toRGBA(tok)
        if (c && c[3] > 0) stripes.push(c)
      }
    }
    return [base, ...stripes.map((s) => over(s, base))]
  }

  for (const el of document.querySelectorAll('*')) {
    // Only elements that render text THEMSELVES. Scoring an ancestor as well would report the
    // same run of text once per level of nesting it happens to sit under.
    const text = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent)
      .join('')
      .trim()
    if (!text) continue
    // WCAG 1.4.3 explicitly exempts inactive controls, and this app fades them with
    // `disabled:opacity-40` (src/ui/controls.ts, src/ui/IconButton.tsx). Without this skip
    // every disabled button becomes a standing hit for something that is not a defect — the
    // permanently-red failure mode R1's comments describe.
    if (el.closest('[disabled]')) continue
    const s = getComputedStyle(el)
    if (s.visibility === 'hidden') continue
    const r = el.getBoundingClientRect()
    if (r.width < 1 || r.height < 1) continue
    const fg = toRGBA(s.color)
    if (!fg) continue
    // `opacity` genuinely reduces contrast, so it is folded into the text's alpha rather than
    // ignored. Slightly conservative by construction: opacity fades an element's own
    // background along with its text, and only the text is faded here, so a faded-subtree
    // ratio is reported a little lower than it truly renders. It errs toward reporting.
    let alpha = fg[3]
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      alpha *= Number(getComputedStyle(n).opacity)
    }
    if (alpha < 0.05) continue // effectively invisible; an absent glyph is not a contrast bug
    const candidates = effectiveBg(el)
    if (!candidates) continue
    const worst = Math.min(
      ...candidates.map((c) => contrast(over([fg[0], fg[1], fg[2], alpha], c), c)),
    )
    // WCAG AA: 3:1 for large text (>=24px, or >=18.66px when bold), 4.5:1 otherwise.
    const size = parseFloat(s.fontSize)
    const large = size >= 24 || (size >= 18.66 && Number(s.fontWeight) >= 700)
    const floor = large ? 3 : 4.5
    if (worst + 0.005 < floor) {
      out.push({
        rule: 'text-contrast',
        selector: cssPath(el),
        detail: `${worst.toFixed(2)}:1 < ${floor}:1 "${text.slice(0, 30)}"`,
      })
    }
  }

  return out
}
