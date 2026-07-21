import { Plus, SquareFunction, X } from 'lucide-react'
import { useState } from 'react'
import { useCatalogStore } from '../stores/catalogStore'
import { useActiveTree, useDocStore } from '../stores/docStore'
import { AutoGrowTextArea } from '../ui/AutoGrowTextArea'
import { controlClass, inlineButtonClass } from '../ui/controls'
import { IconButton } from '../ui/IconButton'
import type { ParamSpec } from '../types/catalog'
import type { LocalDeclJson, ParamDeclJson, ParamKind, ParamValue, RetryJson } from '../types/doc'
import { REFERENCE_KINDS, VALUE_KINDS } from '../types/doc'
import { argEditorFor, asRequired, defaultArgValue, emptyRow, isHole, rolesOfType } from './groupArgs'
import {
  claimedFieldSuffixes,
  failureFields,
  failureSummary,
  timingFields,
  timingSummary,
} from './inspectorRules'
import { ExpressionEditor } from './ExpressionEditor'
import { fieldDiagnostics, unclaimedDiagnostics } from './paths'
import { InspectorSection } from './InspectorSection'
import { coerceParamInput, coerceValueInput, paramInputText } from './params'
import { useScopeRefs } from './scopeRefs'
import { StreamIntoPicker } from './StreamIntoPicker'
import {
  DurationField,
  ExpressionInput,
  FieldRow,
  NumberField,
  TextField,
} from './fields'
import {
  findLocation,
  findNode,
  retryAfterVerbChange,
  type AbortNode,
  type AlarmNode,
  type BlockNode,
  type BranchNode,
  type CommandNode,
  type ComputeNode,
  type ForEachNode,
  type GroupRefNode,
  type InputType,
  type LoopNode,
  type MeasureNode,
  type OperatorInputNode,
  type RecordNode,
  type WaitNode,
} from './tree'

/** Sentinel maxLines value for fields paired with fillParent. When set, the
 * autoGrowHeight line-cap branch is intentionally unreachable — the parent's
 * max-h-full height constraint is the true bound, not the line count. Prevents
 * future maintainers from "helpfully" shrinking this value and reintroducing
 * dead panel space. */
const UNCAPPED_LINES = 200

const KIND_TITLES: Record<BlockNode['kind'], string> = {
  command: 'Command',
  measure: 'Measure',
  operator_input: 'Operator input',
  wait: 'Wait',
  serial: 'Serial',
  parallel: 'Parallel',
  loop: 'Loop',
  branch: 'Branch',
  compute: 'Compute',
  record: 'Record',
  abort: 'Abort',
  alarm: 'Alarm',
  for_each: 'For each',
  group_ref: 'Group ref',
}

export function Inspector() {
  const selectedUid = useDocStore((s) => s.selectedUid)
  const scope = useDocStore((s) => s.scope)
  const activeTree = useActiveTree()
  const node = selectedUid ? findNode(activeTree, selectedUid) : null
  return (
    <aside className="flex w-80 shrink-0 flex-col overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-3">
      {node ? (
        <BlockForm key={node.uid} node={node} />
      ) : scope === null ? (
        <DocProperties />
      ) : (
        <GroupProperties key={scope} name={scope} />
      )}
    </aside>
  )
}

/** Shown when a group scope is active and no block is selected — the group-level analogue of
 * DocProperties. Schema 2: a group declares typed `params` and named `locals` (design §9.2).
 * The typed param-decl table writes through `setGroupParams`; the locals table through
 * `setGroupLocals` — `ForEachForm`'s "Loop variables" editor below shares `ParamDeclListEditor`
 * with this one's "Params", since a for_each `var` and a group `param` are the same declaration
 * shape (design §4/§2.1). */
function GroupProperties({ name }: { name: string }) {
  const group = useDocStore((s) => s.groups[name])
  const setGroupParams = useDocStore((s) => s.setGroupParams)
  const setGroupLocals = useDocStore((s) => s.setGroupLocals)
  const params = group?.params ?? []
  const locals = group?.locals ?? {}
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <h2 className="mb-2 text-sm font-semibold text-slate-700">Group: {name}</h2>
      <h3 className="mt-2 text-xs font-semibold uppercase text-caption">Params</h3>
      <ParamDeclListEditor
        decls={params}
        addLabel="add param"
        onAdd={() => {
          // A fresh, non-colliding name rather than a blank row: an empty-named row is
          // indistinguishable from nothing having been added until the author notices the
          // placeholder, and ForEachForm's "add variable" (same shared component) already
          // seeds a fresh name for the identical reason.
          let n = 1
          while (params.some((p) => p.name === `param${n}`)) n++
          setGroupParams(name, [...params, { name: `param${n}`, kind: 'string' }])
        }}
        onRemove={(i) => setGroupParams(name, params.filter((_, idx) => idx !== i))}
        onPatch={(i, patch) =>
          setGroupParams(
            name,
            params.map((d, idx) => (idx === i ? { ...d, ...patch } : d)),
          )
        }
      />
      <h3 className="mt-2 text-xs font-semibold uppercase text-caption">Locals</h3>
      <LocalDeclListEditor locals={locals} onChange={(next) => setGroupLocals(name, next)} />
      {/* mt-auto pins these to the bottom of the panel (finding #5a). */}
      <p className="mt-auto pt-2 text-xs text-caption">{group?.body.length ?? 0} top-level blocks.</p>
      <p className="mt-1 text-xs text-caption">Select a block to edit its parameters.</p>
    </div>
  )
}

const PARAM_KIND_OPTIONS: readonly ParamKind[] = [...VALUE_KINDS, ...REFERENCE_KINDS]

/** One row per declared param/var: name, kind, and (role-kind only) device_type — the shape
 * `ParamDeclJson` describes (design §2.1). Shared by `GroupProperties`' "Params" and
 * `ForEachForm`'s "Loop variables": both edit a `ParamDeclJson[]` and differ only in what an
 * edit does to the REST of the document (a group has no rows to remap; for_each does), so that
 * divergence lives in the three callbacks the caller supplies, not in this component. Follows
 * the row-of-controls shape already used by `ParamFields`' unknown-param row and
 * `StreamIntoPicker`'s inline "+ new stream" form (flex row, `gap-1`, an `IconButton` to
 * remove) rather than inventing a new list-editor idiom. */
function ParamDeclListEditor({
  decls,
  addLabel,
  onAdd,
  onRemove,
  onPatch,
}: {
  decls: ParamDeclJson[]
  addLabel: string
  onAdd: () => void
  onRemove: (i: number) => void
  onPatch: (i: number, patch: Partial<ParamDeclJson>) => void
}) {
  const catalog = useCatalogStore((s) => s.catalog)
  const deviceTypes = catalog ? Object.keys(catalog.device_types) : []
  const setKind = (i: number, kind: ParamKind) =>
    onPatch(i, kind === 'role' ? { kind, device_type: deviceTypes[0] ?? '' } : { kind, device_type: undefined })
  return (
    <div>
      {decls.length === 0 && <p className="text-xs text-hint">none declared</p>}
      {/* Index keys, not name keys: two rows can share an in-progress (possibly empty) name
          while being typed, exactly like ProblemsPanel's diagnostic rows (Canvas.tsx has no
          reordering here, so index identity is stable across edits). */}
      {decls.map((d, i) => (
        <div key={i} className="mb-1 flex items-center gap-1">
          <div className="min-w-0 flex-1">
            <TextField mono value={d.name} onCommit={(v) => onPatch(i, { name: v })} placeholder="name" />
          </div>
          <select
            aria-label={`${d.name || 'param ' + (i + 1)} kind`}
            value={d.kind}
            onChange={(e) => setKind(i, e.target.value as ParamKind)}
            className={controlClass({ width: 'w-24' })}
          >
            {PARAM_KIND_OPTIONS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          {d.kind === 'role' && (
            <select
              aria-label={`${d.name || 'param ' + (i + 1)} device type`}
              value={d.device_type ?? ''}
              onChange={(e) => onPatch(i, { device_type: e.target.value })}
              className={controlClass({ width: 'w-28' })}
            >
              {deviceTypes.length === 0 && <option value="">— no device types —</option>}
              {deviceTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          )}
          <IconButton
            icon={X}
            label={`Remove ${d.name || 'param ' + (i + 1)}`}
            destructive
            onClick={() => onRemove(i)}
          />
        </div>
      ))}
      <button onClick={onAdd} className={inlineButtonClass({ subtle: true, width: 'w-full' })}>
        <Plus size={12} aria-hidden className="mr-0.5" />
        {addLabel}
      </button>
    </div>
  )
}

/** Group locals (design §2.2): named, not positional, so unlike `ParamDeclListEditor` this
 * edits a `Record<string, LocalDeclJson>` keyed by the local's own name — renaming a row
 * rebuilds the record so the edited key lands in the same position the old one held. Only
 * `stream`/`binding` kinds are legal here (§2.2), so the kind control is a plain two-option
 * select rather than reusing `PARAM_KIND_OPTIONS`. */
function LocalDeclListEditor({
  locals,
  onChange,
}: {
  locals: Record<string, LocalDeclJson>
  onChange: (next: Record<string, LocalDeclJson>) => void
}) {
  const entries = Object.entries(locals)
  const withEntries = (map: (k: string, v: LocalDeclJson, i: number) => [string, LocalDeclJson]) =>
    onChange(Object.fromEntries(entries.map(([k, v], i) => map(k, v, i))))
  const rename = (i: number, newName: string) => withEntries((k, v, idx) => [idx === i ? newName : k, v])
  const patchAt = (i: number, patch: Partial<LocalDeclJson>) =>
    withEntries((k, v, idx) => [k, idx === i ? { ...v, ...patch } : v])
  const setKind = (i: number, kind: LocalDeclJson['kind']) =>
    patchAt(i, kind === 'stream' ? { kind, init: undefined } : { kind, units: undefined, persistence: undefined })
  const remove = (i: number) => onChange(Object.fromEntries(entries.filter((_, idx) => idx !== i)))
  const add = () => {
    let n = 1
    while (`local${n}` in locals) n++
    onChange({ ...locals, [`local${n}`]: { kind: 'binding' } })
  }
  return (
    <div>
      {entries.length === 0 && <p className="text-xs text-hint">no locals</p>}
      {entries.map(([localName, decl], i) => (
        <div key={i} className="mb-1 flex items-center gap-1">
          <div className="min-w-0 flex-1">
            <TextField mono value={localName} onCommit={(v) => rename(i, v)} placeholder="name" />
          </div>
          <select
            aria-label={`${localName || 'local ' + (i + 1)} kind`}
            value={decl.kind}
            onChange={(e) => setKind(i, e.target.value as LocalDeclJson['kind'])}
            className={controlClass({ width: 'w-20' })}
          >
            <option value="binding">binding</option>
            <option value="stream">stream</option>
          </select>
          <div className="min-w-0 flex-1">
            {decl.kind === 'binding' ? (
              <TextField
                mono
                value={decl.init ?? ''}
                onCommit={(v) => patchAt(i, { init: v || undefined })}
                placeholder="init (optional, constant expr)"
              />
            ) : (
              <TextField
                value={decl.units ?? ''}
                onCommit={(v) => patchAt(i, { units: v || undefined })}
                placeholder="units (optional)"
              />
            )}
          </div>
          <IconButton
            icon={X}
            label={`Remove ${localName || 'local ' + (i + 1)}`}
            destructive
            onClick={() => remove(i)}
          />
        </div>
      ))}
      <button onClick={add} className={inlineButtonClass({ subtle: true, width: 'w-full' })}>
        <Plus size={12} aria-hidden className="mr-0.5" />
        add local
      </button>
    </div>
  )
}

/** One kind-aware value field for a declared param, via `argEditorFor` (groupArgs.ts). Shared
 * by `GroupRefForm`'s per-param args and `ForEachForm`'s per-row cells — both bind a
 * `ParamValue` to a declared `ParamDeclJson`, differing only in what happens to the value on
 * commit. role/stream reuse the same pickers `ActionForm`'s Role select (~line 395) and
 * `StreamIntoPicker` already provide; bool mirrors `ParamInput`'s unset/true/false select.
 *
 * Every one of these kinds can ALSO legitimately be a `{name}` hole — an enclosing `for_each`
 * threading its own typed var into a group_ref arg (design §3.1's typed substitution;
 * morbidostat.json's `service(tube={tube}, od={od})` is exactly this), not a malformed value.
 * `exprMode` is this component's `ƒ` escape hatch — mirrors `ParamInput`'s own
 * `typeof value === 'string'`-seeded toggle below — so a fresh int/bool/role/stream arg can
 * originate a hole, not just display one already saved. role/stream additionally use `isHole`
 * (groupArgs.ts) to tell "a hole" apart from "an ordinary name their own picker already lists":
 * unlike int/bool (where any string IS the hole, since a real int/bool value is never a
 * string), a role/stream value is a string in the common case too, so the picker must stay the
 * default and only a genuine `{name}` hole should divert to the text fallback — else a plain
 * `"od_1"` selection would permanently render as a text box instead of the picker. */
function ArgField({
  param,
  value,
  onCommit,
}: {
  param: ParamDeclJson
  value: ParamValue | undefined
  onCommit: (v: ParamValue | undefined) => void
}) {
  // Scope-aware so a nested group_ref/for_each role arg can pick a {hole} from the enclosing
  // group's role params, not only a top-level role (design 2026-07-21).
  const { roles } = useScopeRefs()
  const editor = argEditorFor(param.kind)
  // Seeded like ParamInput's own exprMode: an arg that already holds a hole starts in
  // expression mode with no click needed. Sticky per mount thereafter (same as ParamInput —
  // no "back to picker" affordance once toggled, by the same reasoning: a value that was
  // deliberately turned into an expression stays editable as one). role/stream must seed on
  // `isHole`, NOT on `typeof value === 'string'`: unlike int/bool (a real value is never a
  // string, so any string IS the hole), a role/stream value is a string in the ordinary
  // picked-name case too — seeding on bare stringness would permanently strand every
  // already-saved role/stream arg in text mode, picker never shown again.
  const [exprMode, setExprMode] = useState(() =>
    editor === 'role' || editor === 'stream' ? isHole(value) : typeof value === 'string',
  )
  const exprToggle = (
    <IconButton
      icon={SquareFunction}
      label="Use an expression"
      onClick={() => setExprMode(true)}
      className="border border-slate-300"
    />
  )
  switch (editor) {
    case 'role': {
      const names = rolesOfType(roles, param.device_type)
      const current = typeof value === 'string' ? value : ''
      if (isHole(current) || exprMode) {
        return (
          <TextField
            mono
            value={current}
            onCommit={(v) => onCommit(v || undefined)}
            placeholder={`{${param.name}}`}
          />
        )
      }
      return (
        <div className="flex items-center gap-1">
          <select
            value={current}
            onChange={(e) => onCommit(e.target.value || undefined)}
            className={controlClass()}
          >
            {current === '' && <option value="">— pick a role —</option>}
            {current !== '' && !names.includes(current) && (
              <option value={current}>{current} (unknown)</option>
            )}
            {names.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          {exprToggle}
        </div>
      )
    }
    case 'stream': {
      const current = typeof value === 'string' ? value : ''
      // Finding 1 (S3 regression vs S2): StreamIntoPicker's <select> only offers real
      // stream names as <option>s, so a hole like "{od}" matches none of them and the
      // browser silently falls back to displaying the FIRST stream instead — not a blank,
      // an actively WRONG selection. Diverting to the text fallback here (not inside
      // StreamIntoPicker, which is shared with the Measure block and out of scope) fixes
      // the display without touching that shared component.
      if (isHole(current) || exprMode) {
        return (
          <TextField
            mono
            value={current}
            onCommit={(v) => onCommit(v || undefined)}
            placeholder={`{${param.name}}`}
          />
        )
      }
      return (
        <div className="flex items-center gap-1">
          <StreamIntoPicker value={current} onPick={(v) => onCommit(v)} />
          {exprToggle}
        </div>
      )
    }
    case 'integer':
    case 'number':
      // A STRING here is a hole bound to an enclosing loop's own typed var (e.g. `{tube}`
      // in a group_ref nested inside that var's for_each) rather than a literal number.
      // NumberField can only hold a real JS number, so feeding it a hole string would
      // render it blank and hide an already-saved value; fall back to a plain text field
      // instead, the same way ParamInput falls back to ExpressionInput whenever a bool
      // param's current value is a string (below). `exprMode` extends this so a FRESH
      // arg (currently a real number, or unset) can also be switched into hole entry —
      // `paramInputText` carries the current numeric value over as a starting point
      // instead of blanking it when the toggle is clicked.
      return typeof value === 'string' || exprMode ? (
        <TextField
          mono
          value={typeof value === 'string' ? value : paramInputText(value)}
          onCommit={(v) => onCommit(coerceParamInput(v, param.kind as 'int' | 'number'))}
          placeholder={`{${param.name}}`}
        />
      ) : (
        <div className="flex items-center gap-1">
          <NumberField
            value={typeof value === 'number' ? value : null}
            integer={editor === 'integer'}
            onCommit={(v) => onCommit(v ?? undefined)}
          />
          {exprToggle}
        </div>
      )
    case 'bool': {
      // Same string-hole fallback as integer/number above, plus the same exprMode escape
      // hatch to originate one from a fresh unset/true/false select.
      if (typeof value === 'string' || exprMode) {
        return (
          <TextField
            mono
            value={typeof value === 'string' ? value : paramInputText(value)}
            onCommit={(v) => onCommit(coerceParamInput(v, 'bool'))}
            placeholder={`{${param.name}}`}
          />
        )
      }
      const current = value === true ? 'true' : value === false ? 'false' : ''
      return (
        <div className="flex items-center gap-1">
          <select
            value={current}
            onChange={(e) => {
              const v = e.target.value
              onCommit(v === '' ? undefined : v === 'true')
            }}
            className={controlClass()}
          >
            <option value="">— unset —</option>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
          {exprToggle}
        </div>
      )
    }
    case 'text':
      // Already free text regardless of hole/literal — string/binding kinds may embed a
      // hole inside a longer literal (design §3), unlike the other kinds above, so there
      // is no separate "picker" mode to escape from and no toggle needed.
      return (
        <TextField
          value={typeof value === 'string' ? value : paramInputText(value)}
          onCommit={(v) => onCommit(v || undefined)}
        />
      )
  }
}

function DocProperties() {
  const description = useDocStore((s) => s.description)
  const setDescription = useDocStore((s) => s.setDescription)
  const roles = useDocStore((s) => s.roles)
  const streams = useDocStore((s) => s.streams)
  const tree = useDocStore((s) => s.tree)
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <h2 className="mb-2 text-sm font-semibold text-slate-700">Experiment</h2>
      <FieldRow label="Description" grow>
        <AutoGrowTextArea
          fillParent
          maxLines={UNCAPPED_LINES}
          value={description ?? ''}
          onCommit={(v) => setDescription(v || null)}
          placeholder="what this experiment does"
        />
      </FieldRow>
      {/* mt-auto pins these to the bottom of the panel (finding #5a): the description
          above grows into the free space instead of leaving 800px of dead panel. */}
      <p className="mt-auto pt-2 text-xs text-caption">
        {Object.keys(roles).length} roles · {Object.keys(streams).length} streams ·{' '}
        {tree.length} top-level blocks
      </p>
      <p className="mt-1 text-xs text-caption">Select a block to edit its parameters.</p>
    </div>
  )
}

/** Server-confirmed diagnostics for one field (spec §3.5): red = the engine rejected what
 * is SAVED, distinct from the editor's amber draft problems. */
function FieldDiags({ uid, fields }: { uid: string; fields: string[] }) {
  const diagnostics = useDocStore((s) => s.diagnostics)
  const matches = fieldDiagnostics(diagnostics, uid, fields)
  return (
    <>
      {matches.map((d, i) => (
        <p key={i} className="mt-0.5 text-[10px] text-red-600">
          {d.message}
        </p>
      ))}
    </>
  )
}

/** Block diagnostics no rendered field claims — shown once under the form header, so a
 * suffix the Inspector doesn't know still surfaces here and not only on the canvas. */
function NodeDiagStrip({ node }: { node: BlockNode }) {
  const diagnostics = useDocStore((s) => s.diagnostics)
  const rest = unclaimedDiagnostics(diagnostics, node.uid, claimedFieldSuffixes(node.kind))
  if (rest.length === 0) return null
  return (
    <div className="mb-1">
      {rest.map((d, i) => (
        <p key={i} className="text-[10px] text-red-600">
          {d.message}
        </p>
      ))}
    </div>
  )
}

function BlockForm({ node }: { node: BlockNode }) {
  const activeTree = useActiveTree()
  const patchBlock = useDocStore((s) => s.patchBlock)
  const loc = findLocation(activeTree, node.uid)
  const parentKind = loc?.parent?.kind ?? null
  // An empty list means the section does not render at all (design §3.3): `for_each` gets
  // no tail whatsoever (expand.py:26 forbids all four keys on a splice) and `abort` gets no
  // "On failure" (tolerating a safety stop is a contradiction, engine design 2026-07-16
  // §5.1). Both absences state the engine's rule better than a disabled control would.
  const timing = timingFields(node.kind, parentKind)
  const failure = failureFields(node.kind)
  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold text-slate-700">{KIND_TITLES[node.kind]}</h2>
      <NodeDiagStrip node={node} />
      {/* Label is the one field that means the same thing for all fourteen kinds, so it
          leads every form. The h2 keeps naming the kind, so nothing about kind legibility
          regresses (design §3.1). */}
      <FieldRow label="Label">
        <TextField
          value={node.label ?? ''}
          onCommit={(v) => patchBlock(node.uid, { label: v || null })}
          placeholder="optional display name"
        />
      </FieldRow>
      <KindBody node={node} />
      {timing.length > 0 && (
        <InspectorSection title="Timing" summary={timingSummary(node, parentKind)}>
          {timing.includes('gapAfter') && (
            <FieldRow label="Gap after">
              <DurationField
                value={node.gapAfter}
                allowEmpty
                onCommit={(v) => patchBlock(node.uid, { gapAfter: v })}
              />
            </FieldRow>
          )}
          {timing.includes('startOffset') && (
            <FieldRow label="Start offset">
              <DurationField
                value={node.startOffset}
                allowEmpty
                onCommit={(v) => patchBlock(node.uid, { startOffset: v })}
              />
            </FieldRow>
          )}
        </InspectorSection>
      )}
      {failure.length > 0 && (
        <InspectorSection title="On failure" summary={failureSummary(node)}>
          {failure.includes('onError') && (
            <FieldRow label="On error">
              <select
                value={node.onError ?? 'fail'}
                onChange={(e) =>
                  patchBlock(node.uid, { onError: e.target.value as 'fail' | 'continue' })
                }
                className={controlClass()}
              >
                <option value="fail">fail (stop the run)</option>
                <option value="continue">continue (tolerate the failure)</option>
              </select>
            </FieldRow>
          )}
          {/* Both conditions are load-bearing. `failure.includes('retry')` keeps
              FAILURE_POLICY the single authority on whether retry is offered at all — without
              it, adding 'retry' to another kind's policy would make failureSummary advertise a
              sub-form that never renders, silently and with no compile error. The kind check is
              what lets TypeScript narrow node to Command/Measure, so RetrySection needs no cast. */}
          {failure.includes('retry') && (node.kind === 'command' || node.kind === 'measure') && (
            <RetrySection node={node} />
          )}
        </InspectorSection>
      )}
    </div>
  )
}

/** retry is command/measure only (design 2026-07-14 §2.1); `attempts` is TOTAL tries,
 * including the first, and the UI labels it that way to avoid an off-by-one surprise.
 * For a verb the catalog reports as not retry_safe (e.g. pump.dispense's relative
 * volume_ml — retrying after a partial dispense double-doses the culture), the
 * attempts/backoff controls stay hidden behind an explicit allow_repeat opt-in so the
 * hazard can't be set silently.
 *
 * Tightened 2026-07-14 (review Fix 4): for an unsafe verb, ticking "retry on failure"
 * must not *write* `retry` to the doc yet either — that would leave a savable doc the
 * engine's `_check_retry` validator rejects (retry without allow_repeat on a non-safe
 * verb). `pending` holds the checkbox visually checked and the hazard box open without
 * materialising `node.retry` until "allow repeat" is ticked. */
function RetrySection({ node }: { node: CommandNode | MeasureNode }) {
  const { roles } = useScopeRefs()
  const patchBlock = useDocStore((s) => s.patchBlock)
  const catalog = useCatalogStore((s) => s.catalog)
  const roleType = roles[node.device]?.type
  const verbs = roleType ? (catalog?.device_types[roleType] ?? {}) : {}
  const spec = verbs[node.verb]
  // Conservative default mirrors the engine registry's Trait.retry_safe = False default:
  // an unrecognized verb is treated as unsafe until the catalog says otherwise.
  const retrySafe = spec?.retry_safe ?? false
  const retry = node.retry
  const allowRepeat = retry?.allow_repeat ?? false
  const locked = !retrySafe && !allowRepeat
  const [pending, setPending] = useState(false)
  const open = retry !== undefined || pending

  const setRetry = (patch: Partial<RetryJson>) => {
    if (!retry) return
    patchBlock(node.uid, { retry: { ...retry, ...patch } })
  }

  const toggleRetry = (checked: boolean) => {
    if (!checked) {
      setPending(false)
      patchBlock(node.uid, { retry: undefined })
    } else if (retrySafe) {
      patchBlock(node.uid, { retry: { attempts: 2 } })
    } else {
      // Unsafe verb: show the hazard box but do not materialise retry until acknowledged.
      setPending(true)
    }
  }

  const acceptHazard = (checked: boolean) => {
    if (checked) {
      setPending(false)
      patchBlock(node.uid, { retry: { attempts: 2, ...retry, allow_repeat: true } })
    } else {
      setRetry({ allow_repeat: undefined })
    }
  }

  return (
    <div className="mt-2">
      <FieldRow label="Retry">
        <label className="flex items-center gap-1 text-xs">
          <input type="checkbox" checked={open} onChange={(e) => toggleRetry(e.target.checked)} />
          retry on failure
        </label>
      </FieldRow>
      {open && (
        <div className="ml-1 border-l-2 border-slate-200 pl-2">
          {!retrySafe && (
            <div className="mb-1 rounded border border-amber-300 bg-amber-50 p-1.5 text-[11px] text-amber-800">
              <p>
                '{node.verb}' is not idempotent — a retry may repeat it. Check "allow repeat" to
                accept that risk before setting attempts/backoff.
              </p>
              <label className="mt-1 flex items-center gap-1 font-semibold">
                <input
                  type="checkbox"
                  checked={allowRepeat}
                  onChange={(e) => acceptHazard(e.target.checked)}
                />
                allow repeat (allow_repeat)
              </label>
            </div>
          )}
          {locked ? (
            // text-caption, not text-hint: this box's own bg-slate-100 is a tinted surface
            // (same shade as the canvas depth zebra), and text-hint/slate-500 measures
            // 4.35:1 there — under the 4.5:1 AA floor (probe R5, frontend/CLAUDE.md
            // "Colour"/"Text colors"). slate-600 clears at ~6.9:1 on this background.
            <p className="rounded border border-dashed border-slate-300 bg-slate-100 p-1.5 text-[11px] text-caption">
              attempts/backoff are hidden until "allow repeat" is checked above
            </p>
          ) : retry !== undefined ? (
            <>
              <FieldRow label="Attempts (total tries, including the first)" required>
                <NumberField
                  value={retry.attempts}
                  integer
                  min={1}
                  onCommit={(v) => setRetry({ attempts: v ?? 1 })}
                />
              </FieldRow>
              <FieldRow label="Backoff (pause before each retry)">
                <DurationField
                  value={retry.backoff ?? null}
                  allowEmpty
                  onCommit={(v) => setRetry({ backoff: v ?? undefined })}
                />
              </FieldRow>
            </>
          ) : null}
        </div>
      )}
    </div>
  )
}

function KindBody({ node }: { node: BlockNode }) {
  switch (node.kind) {
    case 'command':
    case 'measure':
      return <ActionForm node={node} />
    case 'wait':
      return <WaitForm node={node} />
    case 'operator_input':
      return <OperatorInputForm node={node} />
    case 'loop':
      return <LoopForm node={node} />
    case 'branch':
      return <BranchForm node={node} />
    case 'compute':
    case 'record':
      return <ValueForm node={node} />
    case 'abort':
    case 'alarm':
      return <ConditionForm node={node} />
    case 'for_each':
      return <ForEachForm node={node} />
    case 'group_ref':
      return <GroupRefForm node={node} />
    case 'serial':
      return <p className="text-xs text-caption">{node.children.length} children — drag blocks on the canvas.</p>
    case 'parallel':
      return <p className="text-xs text-caption">{node.children.length} lanes — manage lanes on the canvas.</p>
  }
}

function ActionForm({ node }: { node: CommandNode | MeasureNode }) {
  // Scope-aware roles: inside a group's body the Role dropdown offers that group's role params
  // ({param_pump}), so a dropped role-param block resolves its type/verbs and never shows the
  // "unknown role" banner for a valid reference (design 2026-07-21).
  const { roles } = useScopeRefs()
  const patchBlock = useDocStore((s) => s.patchBlock)
  const catalog = useCatalogStore((s) => s.catalog)
  const roleType = roles[node.device]?.type
  const verbs = roleType ? (catalog?.device_types[roleType] ?? {}) : {}
  const sameKindVerbs = Object.entries(verbs).filter(
    ([, spec]) => (spec.kind === 'measure') === (node.kind === 'measure'),
  )
  const sameTypeRoles = Object.entries(roles)
    .filter(([, def]) => def.type === roleType)
    .map(([name]) => name)
  const spec = verbs[node.verb]
  return (
    <div>
      {roleType === undefined && (
        <p className="mb-1 text-xs text-red-600">unknown role '{node.device}'</p>
      )}
      <FieldRow label="Role">
        <select
          value={node.device}
          onChange={(e) => patchBlock(node.uid, { device: e.target.value })}
          className={controlClass()}
        >
          {!sameTypeRoles.includes(node.device) && <option value={node.device}>{node.device}</option>}
          {sameTypeRoles.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </FieldRow>
      <FieldRow label="Verb">
        <select
          value={node.verb}
          onChange={(e) =>
            patchBlock(node.uid, { verb: e.target.value, retry: retryAfterVerbChange(node.retry) })
          }
          className={controlClass()}
        >
          {sameKindVerbs.every(([v]) => v !== node.verb) && (
            <option value={node.verb}>{node.verb}</option>
          )}
          {sameKindVerbs.map(([verb]) => (
            <option key={verb} value={verb}>
              {verb}
            </option>
          ))}
        </select>
      </FieldRow>
      {spec ? (
        <ParamFields node={node} specs={spec.params} />
      ) : (
        <p className="text-xs text-amber-700">verb not in catalog — params not editable</p>
      )}
      {/* Result destination last: configure the action, then say where its value goes.
          It used to sit above the params, splitting a verb from its own arguments. */}
      {node.kind === 'measure' && <IntoPicker node={node} />}
    </div>
  )
}

function IntoPicker({ node }: { node: MeasureNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  const { streamHoles } = useScopeRefs()
  return (
    <FieldRow label="Into stream" required>
      <StreamIntoPicker
        value={node.into}
        onPick={(name) => patchBlock(node.uid, { into: name })}
        extraOptions={streamHoles}
      />
    </FieldRow>
  )
}

function ParamFields({ node, specs }: { node: CommandNode | MeasureNode; specs: ParamSpec[] }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  const setParam = (name: string, value: ParamValue | undefined) => {
    const params = { ...node.params }
    if (value === undefined) delete params[name]
    else params[name] = value
    patchBlock(node.uid, { params })
  }
  const known = new Set(specs.map((s) => s.name))
  const unknown = Object.keys(node.params).filter((k) => !known.has(k))
  return (
    <div>
      <h3 className="mt-2 text-xs font-semibold uppercase text-caption">Params</h3>
      {specs.length === 0 && <p className="text-xs text-hint">no params</p>}
      {specs.map((spec) => (
        <FieldRow key={spec.name} label={`${spec.name} (${spec.type})`} required={spec.required}>
          <ParamInput
            spec={spec}
            value={node.params[spec.name]}
            onCommit={(v) => setParam(spec.name, v)}
          />
          {/* Both quote spellings: validate.py writes the name via !r, which flips to
              double quotes when the name itself contains an apostrophe. */}
          <FieldDiags uid={node.uid} fields={[`param '${spec.name}'`, `param "${spec.name}"`]} />
        </FieldRow>
      ))}
      {unknown.map((name) => (
        <FieldRow key={name} label={`${name} (unknown)`}>
          <div className="flex items-center gap-1">
            <span className="flex h-6 flex-1 items-center truncate font-mono text-xs text-amber-700">
              {paramInputText(node.params[name])}
            </span>
            <IconButton
              icon={X}
              label="Remove unknown param"
              destructive
              onClick={() => setParam(name, undefined)}
            />
          </div>
        </FieldRow>
      ))}
    </div>
  )
}

function ParamInput(props: {
  spec: ParamSpec
  value: ParamValue | undefined
  onCommit: (v: ParamValue | undefined) => void
}) {
  const { spec, value, onCommit } = props
  const [exprMode, setExprMode] = useState(typeof value === 'string')
  if (spec.type === 'string') {
    return (
      <AutoGrowTextArea
        value={typeof value === 'string' ? value : paramInputText(value)}
        onCommit={(t) => onCommit(coerceParamInput(t, 'string'))}
        placeholder={spec.required ? 'required' : 'optional'}
      />
    )
  }
  if (spec.type === 'bool' && !exprMode && typeof value !== 'string') {
    const current = value === true ? 'true' : value === false ? 'false' : ''
    return (
      <div className="flex items-center gap-1">
        <select
          value={current}
          onChange={(e) => {
            const v = e.target.value
            onCommit(v === '' ? undefined : v === 'true')
          }}
          className={controlClass()}
        >
          <option value="">— unset —</option>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
        <IconButton
          icon={SquareFunction}
          label="Use an expression"
          onClick={() => setExprMode(true)}
          className="border border-slate-300"
        />
      </div>
    )
  }
  return (
    <ExpressionInput
      value={paramInputText(value)}
      onCommit={(t) => onCommit(coerceParamInput(t, spec.type))}
      placeholder={spec.required ? 'required' : 'optional'}
    />
  )
}

function WaitForm({ node }: { node: WaitNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  return (
    <FieldRow label="Duration" required>
      <DurationField value={node.duration} onCommit={(v) => patchBlock(node.uid, { duration: v ?? '' })} />
    </FieldRow>
  )
}

function OperatorInputForm({ node }: { node: OperatorInputNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  const numeric = node.inputType === 'int' || node.inputType === 'float'
  const setType = (t: InputType) => {
    const patch: Partial<OperatorInputNode> = { inputType: t }
    if (t !== 'enum') patch.choices = null
    if (t === 'enum' || t === 'bool') {
      patch.min = null
      patch.max = null
    }
    patchBlock(node.uid, patch)
  }
  return (
    <div>
      <FieldRow label="Binding name" required>
        <TextField
          mono
          value={node.name}
          onCommit={(v) => patchBlock(node.uid, { name: v })}
          placeholder="identifier, e.g. feed_ml"
        />
      </FieldRow>
      <FieldRow label="Type" required>
        <select
          value={node.inputType}
          onChange={(e) => setType(e.target.value as InputType)}
          className={controlClass()}
        >
          <option value="int">int</option>
          <option value="float">float</option>
          <option value="bool">bool</option>
          <option value="enum">enum</option>
        </select>
      </FieldRow>
      {numeric && (
        <>
          <FieldRow label="Min">
            <NumberField
              value={node.min}
              integer={node.inputType === 'int'}
              onCommit={(v) => patchBlock(node.uid, { min: v })}
            />
          </FieldRow>
          <FieldRow label="Max">
            <NumberField
              value={node.max}
              integer={node.inputType === 'int'}
              onCommit={(v) => patchBlock(node.uid, { max: v })}
            />
          </FieldRow>
        </>
      )}
      {node.inputType === 'enum' && (
        <FieldRow label="Choices (one per line)" required>
          {/* Auto-grows like GroupProperties' "Params (one per line)" — same field shape, so
              the same behaviour. A fixed 3 rows turned an enum with 20 choices into a
              scroller. Capped by AutoGrowTextArea's default 12 lines rather than
              UNCAPPED_LINES: Params sits in a `grow` FieldRow whose `fillParent` bounds it
              against the panel, and this row has no such bound to fall back on. */}
          <AutoGrowTextArea
            mono
            value={(node.choices ?? []).join('\n')}
            onCommit={(v) =>
              patchBlock(node.uid, {
                choices: v
                  .split('\n')
                  .map((line) => line.trim())
                  .filter((line) => line !== ''),
              })
            }
          />
        </FieldRow>
      )}
      {/* Last: the type and its constraints define what the operator may enter, so they
          belong together; the prompt is the operator-facing prose describing the result. */}
      <FieldRow label="Prompt">
        <AutoGrowTextArea
          value={node.prompt ?? ''}
          onCommit={(v) => patchBlock(node.uid, { prompt: v || null })}
          placeholder="shown to the operator"
        />
      </FieldRow>
    </div>
  )
}

function LoopForm({ node }: { node: LoopNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  return (
    <div>
      <FieldRow label="Repeat" required>
        <div className="flex gap-3 text-xs">
          <label className="flex items-center gap-1">
            <input
              type="radio"
              checked={node.mode === 'count'}
              onChange={() => patchBlock(node.uid, { mode: 'count' })}
            />
            count
          </label>
          <label className="flex items-center gap-1">
            <input
              type="radio"
              checked={node.mode === 'until'}
              onChange={() => patchBlock(node.uid, { mode: 'until' })}
            />
            until
          </label>
        </div>
      </FieldRow>
      {node.mode === 'count' ? (
        <FieldRow label="Count" required>
          <ExpressionEditor
            value={typeof node.count === 'number' ? String(node.count) : node.count}
            expected="int"
            placeholder="3, or an expression"
            onCommit={(t) => {
              const trimmed = t.trim()
              patchBlock(node.uid, {
                count: trimmed === '' ? 1 : /^\d+$/.test(trimmed) ? Number(trimmed) : trimmed,
              })
            }}
          />
          <FieldDiags uid={node.uid} fields={['loop count']} />
        </FieldRow>
      ) : (
        <>
          <FieldRow label="Until" required>
            <ExpressionInput
              value={node.until}
              onCommit={(v) => patchBlock(node.uid, { until: v })}
              placeholder="mean(od, last=5) > 0.6"
            />
            <FieldDiags uid={node.uid} fields={['loop until']} />
          </FieldRow>
          <FieldRow label="Check condition">
            <select
              value={node.check}
              onChange={(e) => patchBlock(node.uid, { check: e.target.value as 'before' | 'after' })}
              className={controlClass()}
            >
              <option value="after">after each pass</option>
              <option value="before">before each pass</option>
            </select>
          </FieldRow>
        </>
      )}
      <FieldRow label="Pace (min. loop period)">
        <DurationField value={node.pace} allowEmpty onCommit={(v) => patchBlock(node.uid, { pace: v })} />
      </FieldRow>
    </div>
  )
}

function BranchForm({ node }: { node: BranchNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  return (
    <div>
      <FieldRow label="If" required>
        <ExpressionInput
          value={node.condition}
          onCommit={(v) => patchBlock(node.uid, { condition: v })}
          placeholder="last(od) > 0.5"
        />
        <FieldDiags uid={node.uid} fields={['branch if']} />
      </FieldRow>
      {node.else === null ? (
        <button
          onClick={() => patchBlock(node.uid, { else: [] })}
          className={inlineButtonClass({ subtle: true, width: 'w-full' })}
        >
          <Plus size={12} aria-hidden className="mr-0.5" />add else lane
        </button>
      ) : (
        <button
          disabled={node.else.length > 0}
          title={node.else.length > 0 ? 'Empty the else lane first' : undefined}
          onClick={() => patchBlock(node.uid, { else: null })}
          className={inlineButtonClass({ width: 'w-full' }) + ' enabled:hover:text-red-600'}
        >
          remove else lane
        </button>
      )}
    </div>
  )
}

/** compute writes a binding; record appends to a DECLARED stream — hence the picker rather
 * than a text field: an undeclared name is a validation error the author would otherwise
 * only meet at save time. */
function ValueForm({ node }: { node: ComputeNode | RecordNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  const { streamHoles } = useScopeRefs()
  return (
    <div>
      {node.kind === 'compute' ? (
        <FieldRow label="Into (binding)" required>
          <TextField
            mono
            value={node.into}
            onCommit={(v) => patchBlock(node.uid, { into: v })}
            placeholder="c_1"
          />
        </FieldRow>
      ) : (
        <FieldRow label="Into stream" required>
          <StreamIntoPicker
            value={node.into}
            onPick={(v) => patchBlock(node.uid, { into: v })}
            extraOptions={streamHoles}
          />
        </FieldRow>
      )}
      <FieldRow label="Value" required>
        <ExpressionInput
          value={String(node.value)}
          onCommit={(v) => patchBlock(node.uid, { value: coerceValueInput(v) })}
        />
        <FieldDiags
          uid={node.uid}
          fields={[node.kind === 'compute' ? 'compute value' : 'record value']}
        />
      </FieldRow>
      <InspectorSection title="Units" summary={node.as ? `as ${node.as}` : null}>
        <FieldRow label="Cast (as)">
          <TextField
            mono
            value={node.as ?? ''}
            onCommit={(v) => patchBlock(node.uid, { as: v.trim() || null })}
            placeholder={node.kind === 'record' ? "the stream's unit" : 'e.g. per_hour'}
          />
        </FieldRow>
      </InspectorSection>
    </div>
  )
}

function ConditionForm({ node }: { node: AbortNode | AlarmNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  return (
    <div>
      <FieldRow label="If" required>
        <ExpressionInput
          value={node.condition}
          onCommit={(v) => patchBlock(node.uid, { condition: v })}
          placeholder="contaminated_1"
        />
        <FieldDiags uid={node.uid} fields={[node.kind === 'abort' ? 'abort if' : 'alarm if']} />
      </FieldRow>
      <FieldRow label="Message" required>
        <AutoGrowTextArea
          value={node.message}
          onCommit={(v) => patchBlock(node.uid, { message: v })}
          placeholder={node.kind === 'abort' ? 'why the run must stop' : 'what to flag'}
        />
      </FieldRow>
      <p className="mt-1 text-xs text-caption">
        {node.kind === 'abort'
          ? 'True stops the run: devices are swept safe and the run ends "aborted".'
          : 'True flags the run and continues. Fires every time it holds — latch it with a compute if you want it once.'}
      </p>
    </div>
  )
}

/** for_each is a SPLICE, not a runtime block (design 2026-07-15 §2/2026-07-16 §5.1): it copies
 * `body` once per row and splices the copies into the enclosing list. Schema 2: it declares
 * typed `vars` and one typed value per `row` (the scalar `var` shorthand is gone). The vars
 * editor reuses `ParamDeclListEditor` (also used by `GroupProperties`' "Params"); editing a
 * var's name or kind here additionally remaps/re-seeds every row (design §9.2 — "Studio render
 * `in` as a grid... a typed value field per column"), which is the one place this form's write
 * path diverges from a plain params editor, so that remapping lives in the three callbacks
 * below rather than inside the shared component. */
function ForEachForm({ node }: { node: ForEachNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)

  const addVar = () => {
    let n = 1
    while (node.vars.some((v) => v.name === `var${n}`)) n++
    const added: ParamDeclJson = { name: `var${n}`, kind: 'string' }
    const vars = [...node.vars, added]
    const rows = node.rows.map((r) => ({ ...r, [added.name]: defaultArgValue(added.kind) }))
    patchBlock(node.uid, { vars, rows })
  }

  const removeVar = (i: number) => {
    const removed = node.vars[i]
    const vars = node.vars.filter((_, idx) => idx !== i)
    const rows = node.rows.map((r) => {
      const next = { ...r }
      delete next[removed.name]
      return next
    })
    patchBlock(node.uid, { vars, rows })
  }

  const patchVar = (i: number, patch: Partial<ParamDeclJson>) => {
    const old = node.vars[i]
    const next = { ...old, ...patch }
    const vars = node.vars.map((v, idx) => (idx === i ? next : v))
    const nameChanged = next.name !== old.name
    const kindChanged = next.kind !== old.kind
    const rows =
      !nameChanged && !kindChanged
        ? node.rows
        : node.rows.map((r) => {
            const row = { ...r }
            const cellValue = kindChanged ? defaultArgValue(next.kind) : row[old.name]
            if (nameChanged) delete row[old.name]
            row[next.name] = cellValue
            return row
          })
    patchBlock(node.uid, { vars, rows })
  }

  const addRow = () => patchBlock(node.uid, { rows: [...node.rows, emptyRow(node.vars)] })
  const removeRow = (i: number) => patchBlock(node.uid, { rows: node.rows.filter((_, idx) => idx !== i) })
  const setCell = (i: number, param: ParamDeclJson, value: ParamValue | undefined) => {
    const cell = value ?? defaultArgValue(param.kind)
    patchBlock(node.uid, { rows: node.rows.map((r, idx) => (idx === i ? { ...r, [param.name]: cell } : r)) })
  }

  return (
    <div>
      <h3 className="mt-2 text-xs font-semibold uppercase text-caption">Loop variables</h3>
      <ParamDeclListEditor
        decls={node.vars}
        addLabel="add variable"
        onAdd={addVar}
        onRemove={removeVar}
        onPatch={patchVar}
      />
      <h3 className="mt-2 text-xs font-semibold uppercase text-caption">Rows</h3>
      {node.vars.length === 0 ? (
        <p className="text-xs text-hint">declare a variable above to add rows</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr>
                {node.vars.map((v) => (
                  <th
                    key={v.name}
                    className="border-b border-slate-200 px-1 py-0.5 text-left font-mono font-normal text-caption"
                  >
                    {v.name}
                  </th>
                ))}
                <th className="w-6 border-b border-slate-200" />
              </tr>
            </thead>
            <tbody>
              {node.rows.map((row, i) => (
                <tr key={i}>
                  {node.vars.map((v) => (
                    <td key={v.name} className="px-1 py-0.5">
                      <ArgField param={v} value={row[v.name]} onCommit={(val) => setCell(i, v, val)} />
                    </td>
                  ))}
                  <td className="px-1 py-0.5">
                    <IconButton icon={X} label={`Remove row ${i + 1}`} destructive onClick={() => removeRow(i)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <button
        onClick={addRow}
        disabled={node.vars.length === 0}
        className={inlineButtonClass({ subtle: true, width: 'w-full' }) + ' mt-1'}
      >
        <Plus size={12} aria-hidden className="mr-0.5" />
        add row
      </button>
      <p className="mt-2 text-xs text-caption">
        {node.body.length} block{node.body.length === 1 ? '' : 's'} in the body — drag onto the canvas to
        edit; each copy is spliced into the list for_each sits in.
      </p>
    </div>
  )
}

/** `args` are keyed by the target group's declared `params` (design §5.2), so arity is right
 * by construction (expand.py:190 `set(args) != set(params)` rejects a mismatch) — switching
 * the picked group resets `args` to exactly that group's param set, carrying over any value
 * already entered under a name the new group also declares. Each arg gets a KIND-AWARE editor
 * via `ArgField`/`argEditorFor` (design §9.2) instead of one free-text `ExpressionInput` for
 * every kind; `as` becomes visibly required exactly when `asRequired` says the target group
 * declares locals (design §6). */
function GroupRefForm({ node }: { node: GroupRefNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  const groups = useDocStore((s) => s.groups)
  const groupNames = Object.keys(groups)
  const group = groups[node.name]
  const params = group?.params ?? []

  const setName = (name: string) => {
    const nextParams = groups[name]?.params ?? []
    const args: Record<string, ParamValue> = {}
    for (const p of nextParams) if (node.args[p.name] !== undefined) args[p.name] = node.args[p.name]
    patchBlock(node.uid, { name, args })
  }

  const setArg = (paramName: string, value: ParamValue | undefined) => {
    const args = { ...node.args }
    if (value === undefined) delete args[paramName]
    else args[paramName] = value
    patchBlock(node.uid, { args })
  }

  return (
    <div>
      <FieldRow label="Group" required>
        <select
          value={node.name}
          onChange={(e) => setName(e.target.value)}
          className={controlClass()}
        >
          {node.name === '' && <option value="">— pick a group —</option>}
          {node.name !== '' && !groupNames.includes(node.name) && (
            <option value={node.name}>{node.name} (unknown)</option>
          )}
          {groupNames.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
      </FieldRow>
      {/* `as` namespaces the group's locals per call site (schema 2, required when the group
          declares locals — design §6). */}
      <FieldRow label="As (call-site prefix)" required={asRequired(group)}>
        <TextField
          mono
          value={node.as ?? ''}
          onCommit={(v) => patchBlock(node.uid, { as: v || null })}
          placeholder="tube_{tube}"
        />
      </FieldRow>
      {params.length === 0 ? (
        <p className="text-xs text-caption">
          {node.name === '' ? 'pick a group above' : 'this group takes no params'}
        </p>
      ) : (
        <>
          <h3 className="mt-2 text-xs font-semibold uppercase text-caption">Args</h3>
          {params.map((p) => (
            <FieldRow
              key={p.name}
              label={`${p.name} (${p.kind}${p.device_type !== undefined ? ' · ' + p.device_type : ''})`}
              required
            >
              <ArgField param={p} value={node.args[p.name]} onCommit={(v) => setArg(p.name, v)} />
            </FieldRow>
          ))}
        </>
      )}
    </div>
  )
}
