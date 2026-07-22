/** The one expression-editing surface (spec 2026-07-21 §3.1): native textarea for input,
 * a color-token overlay BEHIND it for highlighting, an autocomplete popup, the clickable
 * help popover, and 300 ms draft analysis. Commit semantics match TextField: commit on
 * blur/Enter, revert on Escape (popup gets first claim on those keys). All logic lives in
 * ./expr/* as pure functions — this file is only wiring, which is probe territory. */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { SquareFunction } from 'lucide-react'
import { useCatalogStore } from '../stores/catalogStore'
import { useActiveTree, useDocStore } from '../stores/docStore'
import { autoGrowHeight, collapseNewlines } from '../ui/autoGrow'
import { textAreaClass } from '../ui/controls'
import { IconButton } from '../ui/IconButton'
import { useDismissable } from '../ui/useDismissable'
import {
  analyzeExpression,
  type ExpectedType,
  type ExprProblem,
  type ExprScope,
} from './expr/analyze'
import {
  completionsAt,
  insideStatCallArgs,
  type Completion,
  type CompletionSet,
} from './expr/complete'
import { highlightSpans, SPAN_CLASSES, UNDERLINE_CLASS } from './expr/highlight'
import { insertFragment } from './expr/insert'
import { buildExpressionHelp, type ExpressionHelp } from './exprHelp'
import { DURATION_RE } from './params'
import { collectBindings } from './refs'
import { scopeBindingNames, scopeStreamNames, useScopeRefs } from './scopeRefs'

const MAX_LINES = 6
const VALIDATE_DEBOUNCE_MS = 300

export function ExpressionEditor(props: {
  value: string
  onCommit: (v: string) => void
  placeholder?: string
  expected?: ExpectedType
}) {
  const { expected = 'any' } = props
  const streams = useDocStore((s) => s.streams)
  // Workflow-global constants (constants design 2026-07-22) are top-level, not group-scoped —
  // union them into `bindings` unconditionally, unlike `scopeBindingNames(group)` below.
  const constants = useDocStore((s) => s.constants)
  // Bindings must be collected from the ACTIVE scope, not always the main tree (2026-07-16
  // review, Finding 1): a group body is unreachable from `tree` (a `group_ref` node has no
  // `childSlots`), so an expression inside a group — e.g. morbidostat.json's `groups.service`,
  // whose own `compute` blocks feed later expressions in that same body — needs its own
  // group's bindings, not the main workflow's.
  const activeTree = useActiveTree()
  // Scope-aware: inside a group's body the help panel also lists that group's stream params &
  // locals (as {holes}) under Streams, and its value + binding params/locals under Bindings
  // (design 2026-07-21).
  const { group } = useScopeRefs()
  const expression = useCatalogStore((s) => s.catalog?.expression ?? null)
  // Memoized so the analysis effect below doesn't re-fire every render (the unstable-dep
  // trap): streams/activeTree/group are store references that only change on real edits.
  const scope = useMemo<ExprScope>(
    () => ({
      streams: scopeStreamNames(streams, group),
      bindings: Array.from(
        new Set([
          ...collectBindings(activeTree),
          ...scopeBindingNames(group),
          ...Object.keys(constants),
        ]),
      ),
    }),
    [streams, group, activeTree, constants],
  )
  const help = useMemo<ExpressionHelp | null>(
    () => (expression ? buildExpressionHelp(expression, scope.streams, scope.bindings) : null),
    [expression, scope],
  )

  const taRef = useRef<HTMLTextAreaElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  const caretRef = useRef(0)
  const pendingCaretRef = useRef<number | null>(null)
  const [draft, setDraft] = useState(props.value)
  const [problems, setProblems] = useState<ExprProblem[]>([])
  const [popup, setPopup] = useState<{ set: CompletionSet; index: number } | null>(null)
  const [helpOpen, setHelpOpen] = useState(false)
  useEffect(() => setDraft(props.value), [props.value])

  // Auto-grow (AutoGrowTextArea's measurement, verbatim) + overlay scroll sync.
  useLayoutEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    const lineHeight = Number.parseFloat(getComputedStyle(el).lineHeight) || 16
    const { height, overflow } = autoGrowHeight({
      scrollHeight: el.scrollHeight,
      lineHeight,
      maxLines: MAX_LINES,
    })
    el.style.height = `${height}px`
    el.style.overflowY = overflow
    if (overlayRef.current) overlayRef.current.scrollTop = el.scrollTop
  }, [draft])

  // Caret restore after a programmatic insert (help click / completion accept).
  useLayoutEffect(() => {
    const p = pendingCaretRef.current
    if (p === null) return
    pendingCaretRef.current = null
    const el = taRef.current
    if (!el) return
    el.focus()
    el.setSelectionRange(p, p)
  }, [draft])

  // Instant validation (spec §3.4): 300 ms idle, amber, advisory only. A DURATION_RE
  // literal in a duration slot is the spec §3.7 fast-path: valid, no parse.
  useEffect(() => {
    const trimmed = draft.trim()
    if (trimmed === '' || (expected === 'duration' && DURATION_RE.test(trimmed))) {
      setProblems([])
      return
    }
    const timer = setTimeout(
      () => setProblems(analyzeExpression(draft, expected, scope)),
      VALIDATE_DEBOUNCE_MS,
    )
    return () => clearTimeout(timer)
  }, [draft, expected, scope])

  const spans = useMemo(() => highlightSpans(draft, problems), [draft, problems])

  const commit = () => {
    if (draft !== props.value) props.onCommit(draft)
  }

  const applyInsert = (
    fragment: string,
    opts?: { replace?: { start: number; end: number }; caretBack?: number },
  ) => {
    const r = insertFragment(draft, caretRef.current, fragment, opts)
    setDraft(r.text)
    caretRef.current = r.caret
    pendingCaretRef.current = r.caret
    setPopup(null)
  }

  const accept = (item: Completion, replace: { start: number; end: number }) =>
    applyInsert(item.insert, { replace, caretBack: item.caretBack })

  const onName = (name: string) => applyInsert(name)
  const onFn = (name: string) => applyInsert(`${name}()`, { caretBack: 1 })
  const onWindow = (w: { example: string; fragment: string | null }) => {
    if (w.fragment !== null && insideStatCallArgs(draft, caretRef.current)) applyInsert(w.fragment)
    else applyInsert(w.example)
  }

  // The ref wraps BOTH the trigger and the panel: if the trigger sat outside it, clicking
  // it while open would dismiss and immediately re-open (spec §4.2, finding #6).
  const wrapRef = useDismissable(helpOpen, () => setHelpOpen(false))

  return (
    <div ref={wrapRef} className="relative">
      <div className="flex items-start gap-1">
        <div className="relative min-w-0 flex-1">
          <div
            ref={overlayRef}
            aria-hidden
            className={`${textAreaClass({ mono: true })} pointer-events-none absolute inset-0 select-none overflow-hidden whitespace-pre-wrap break-words`}
          >
            {spans.map((s, i) => (
              <span
                key={i}
                className={SPAN_CLASSES[s.cls] + (s.underline ? ' ' + UNDERLINE_CLASS : '')}
              >
                {draft.slice(s.start, s.end)}
              </span>
            ))}
          </div>
          <textarea
            ref={taRef}
            value={draft}
            rows={1}
            placeholder={props.placeholder ?? 'expression'}
            className={`${textAreaClass({ mono: true, ghost: true })} relative resize-none`}
            onChange={(e) => {
              const next = collapseNewlines(e.target.value)
              const caret = e.target.selectionStart ?? next.length
              setDraft(next)
              caretRef.current = caret
              const set = completionsAt(next, caret, scope)
              setPopup(set ? { set, index: 0 } : null)
              if (set) setHelpOpen(false)
            }}
            onSelect={(e) => {
              const caret = e.currentTarget.selectionStart ?? 0
              caretRef.current = caret
              if (popup) {
                const set = completionsAt(draft, caret, scope)
                setPopup(set ? { set, index: 0 } : null)
              }
            }}
            onScroll={() => {
              if (overlayRef.current && taRef.current) {
                overlayRef.current.scrollTop = taRef.current.scrollTop
              }
            }}
            onBlur={() => {
              commit()
              setPopup(null)
            }}
            onKeyDown={(e) => {
              if (popup) {
                const n = popup.set.items.length
                if (e.key === 'ArrowDown') {
                  e.preventDefault()
                  setPopup({ ...popup, index: (popup.index + 1) % n })
                  return
                }
                if (e.key === 'ArrowUp') {
                  e.preventDefault()
                  setPopup({ ...popup, index: (popup.index - 1 + n) % n })
                  return
                }
                if (e.key === 'Enter' || e.key === 'Tab') {
                  e.preventDefault()
                  accept(popup.set.items[popup.index], popup.set.replace)
                  return
                }
                if (e.key === 'Escape') {
                  // First Escape closes the popup; a second one reverts the draft.
                  e.preventDefault()
                  e.stopPropagation()
                  setPopup(null)
                  return
                }
              }
              if (e.key === 'Escape') {
                setDraft(props.value)
                return
              }
              if (e.key === 'Enter') {
                // Single-line semantics: the grammar has no newlines, Enter commits.
                e.preventDefault()
                commit()
                return
              }
              if (e.key === ' ' && e.ctrlKey) {
                e.preventDefault()
                const set = completionsAt(draft, caretRef.current, scope, true)
                if (set) {
                  setPopup({ set, index: 0 })
                  setHelpOpen(false)
                }
              }
            }}
          />
        </div>
        <IconButton
          icon={SquareFunction}
          label="Expression help"
          onClick={() => {
            setHelpOpen(!helpOpen)
            setPopup(null)
          }}
          className="border border-slate-300"
        />
      </div>
      {problems.length > 0 && (
        <div className="mt-0.5">
          {problems.map((p, i) => (
            <p key={i} className="text-[10px] text-amber-700">
              {p.message}
            </p>
          ))}
        </div>
      )}
      {popup && <CompletionPopup popup={popup} onPick={accept} />}
      {helpOpen && help && (
        <HelpPopover help={help} onName={onName} onFn={onFn} onWindow={onWindow} />
      )}
    </div>
  )
}

function CompletionPopup(props: {
  popup: { set: CompletionSet; index: number }
  onPick: (item: Completion, replace: { start: number; end: number }) => void
}) {
  return (
    <ul
      role="listbox"
      aria-label="Completions"
      className="absolute left-0 z-20 mt-1 max-h-48 w-56 overflow-auto rounded border border-slate-300 bg-white py-0.5 text-xs shadow-lg"
    >
      {props.popup.set.items.map((it, i) => (
        <li key={it.kind + it.label} role="option" aria-selected={i === props.popup.index}>
          <button
            type="button"
            className={
              'flex h-6 w-full items-center justify-between gap-2 px-2 text-left ' +
              (i === props.popup.index ? 'bg-blue-100 text-blue-700' : 'hover:bg-slate-100')
            }
            // preventDefault keeps textarea focus, so blur-commit doesn't fire pre-click.
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => props.onPick(it, props.popup.set.replace)}
          >
            <span className="font-mono">{it.label}</span>
            <span className="text-hint">{it.kind}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

/** The documentation surface (spec §3.6): every row inserts at the caret and the popover
 * STAYS open so `mean(` + `od` + `, last=30s` composes in three clicks. */
function HelpPopover(props: {
  help: ExpressionHelp
  onName: (name: string) => void
  onFn: (name: string) => void
  onWindow: (w: { example: string; fragment: string | null }) => void
}) {
  const { help } = props
  // h-6 keeps every clickable row/chip at IconButton's 24px hit-area floor (the probe's
  // tiny-target rule flagged the first cut of these at 16px).
  const rowClass =
    'flex h-6 w-full items-center justify-between gap-2 rounded px-1 text-left hover:bg-slate-100'
  const chipClass = 'inline-flex h-6 items-center rounded px-1 font-mono hover:bg-slate-100'
  const stop = (e: { preventDefault: () => void }) => e.preventDefault()
  return (
    <div className="absolute right-0 z-20 mt-1 w-72 rounded border border-slate-300 bg-white p-2 text-xs shadow-lg">
      <p className="font-semibold text-slate-600">Streams</p>
      <p className="mb-1 font-mono text-caption">
        {help.streams.length > 0
          ? help.streams.map((s) => (
              <button key={s} type="button" title={`Insert ${s}`} className={chipClass} onMouseDown={stop} onClick={() => props.onName(s)}>
                {s}
              </button>
            ))
          : '— none declared —'}
      </p>
      <p className="font-semibold text-slate-600">Bindings</p>
      <p className="mb-1 font-mono text-caption">
        {help.bindings.length > 0
          ? help.bindings.map((b) => (
              <button key={b} type="button" title={`Insert ${b}`} className={chipClass} onMouseDown={stop} onClick={() => props.onName(b)}>
                {b}
              </button>
            ))
          : '— none —'}
      </p>
      <p className="font-semibold text-slate-600">Functions</p>
      <ul className="mb-1">
        {help.functions.map((f) => (
          <li key={f.name}>
            <button type="button" title={`Insert ${f.name}()`} className={rowClass} onMouseDown={stop} onClick={() => props.onFn(f.name)}>
              <span className="font-mono">{f.name}</span>
              <span className="font-mono text-hint">{f.example}</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="font-semibold text-slate-600">Windows</p>
      <ul>
        {help.windowForms.map((w) => (
          <li key={w.label}>
            <button type="button" title={w.fragment ? `Insert ${w.fragment.replace(/^, /, '')}` : `Insert ${w.example}`} className={rowClass} onMouseDown={stop} onClick={() => props.onWindow(w)}>
              <span>{w.label}</span>
              <span className="font-mono text-hint">{w.example}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
