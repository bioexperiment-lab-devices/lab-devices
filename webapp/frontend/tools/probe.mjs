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
  for (const row of document.querySelectorAll('*')) {
    const s = getComputedStyle(row)
    if (s.display !== 'flex' || s.flexDirection.startsWith('column')) continue
    if (s.alignItems === 'stretch') continue // stretch makes heights agree by definition
    const controls = Array.from(row.children).filter((c) =>
      ['BUTTON', 'INPUT', 'SELECT'].includes(c.tagName),
    )
    if (controls.length < 2) continue
    const hs = controls.map((c) => c.getBoundingClientRect().height).filter((h) => h > 0)
    if (hs.length < 2) continue
    const spread = Math.max(...hs) - Math.min(...hs)
    if (spread > 1) {
      out.push({
        rule: 'sibling-height-mismatch',
        selector: cssPath(row),
        detail: `spread ${spread.toFixed(1)}px`,
      })
    }
  }

  return out
}
