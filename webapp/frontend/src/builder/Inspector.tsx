import { Plus, SquareFunction, X } from 'lucide-react'
import { useState } from 'react'
import { useCatalogStore } from '../stores/catalogStore'
import { useActiveTree, useDocStore } from '../stores/docStore'
import { AutoGrowTextArea } from '../ui/AutoGrowTextArea'
import { controlClass, inlineButtonClass } from '../ui/controls'
import { IconButton } from '../ui/IconButton'
import type { ParamSpec } from '../types/catalog'
import type { ParamValue, RetryJson } from '../types/doc'
import { failureFields, failureSummary, timingFields, timingSummary } from './inspectorRules'
import { InspectorSection } from './InspectorSection'
import { coerceParamInput, coerceValueInput, paramInputText } from './params'
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
 * This is a COMPILE-AND-RENDER SHIM (S2): it presents both read-only. The real typed editors
 * — a param-decl table and a locals table — land in S3; the store already has setGroupParams/
 * setGroupLocals for them. */
function GroupProperties({ name }: { name: string }) {
  const group = useDocStore((s) => s.groups[name])
  const params = group?.params ?? []
  const locals = group?.locals ?? {}
  const localEntries = Object.entries(locals)
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <h2 className="mb-2 text-sm font-semibold text-slate-700">Group: {name}</h2>
      <h3 className="mt-2 text-xs font-semibold uppercase text-caption">Params</h3>
      {params.length === 0 ? (
        <p className="text-xs text-hint">no params</p>
      ) : (
        <ul className="text-xs text-caption">
          {params.map((p) => (
            <li key={p.name} className="font-mono">
              {p.name}: {p.kind}
              {p.device_type !== undefined ? ` (${p.device_type})` : ''}
            </li>
          ))}
        </ul>
      )}
      <h3 className="mt-2 text-xs font-semibold uppercase text-caption">Locals</h3>
      {localEntries.length === 0 ? (
        <p className="text-xs text-hint">no locals</p>
      ) : (
        <ul className="text-xs text-caption">
          {localEntries.map(([localName, decl]) => (
            <li key={localName} className="font-mono">
              {localName}: {decl.kind}
            </li>
          ))}
        </ul>
      )}
      {/* mt-auto pins these to the bottom of the panel (finding #5a). */}
      <p className="mt-auto pt-2 text-xs text-caption">{group?.body.length ?? 0} top-level blocks.</p>
      <p className="mt-1 text-xs text-caption">Select a block to edit its parameters.</p>
    </div>
  )
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
  const roles = useDocStore((s) => s.roles)
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
  const roles = useDocStore((s) => s.roles)
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
  return (
    <FieldRow label="Into stream" required>
      <StreamIntoPicker value={node.into} onPick={(name) => patchBlock(node.uid, { into: name })} />
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
          <NumberField
            value={node.count}
            integer
            min={1}
            onCommit={(v) => patchBlock(node.uid, { count: v ?? 1 })}
          />
        </FieldRow>
      ) : (
        <>
          <FieldRow label="Until" required>
            <ExpressionInput
              value={node.until}
              onCommit={(v) => patchBlock(node.uid, { until: v })}
              placeholder="mean(od, last=5) > 0.6"
            />
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
          <StreamIntoPicker value={node.into} onPick={(v) => patchBlock(node.uid, { into: v })} />
        </FieldRow>
      )}
      <FieldRow label="Value" required>
        <ExpressionInput
          value={String(node.value)}
          onCommit={(v) => patchBlock(node.uid, { value: coerceValueInput(v) })}
        />
      </FieldRow>
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
 * typed `vars` and one value per `row` (the scalar `var` shorthand is gone). COMPILE-AND-RENDER
 * SHIM (S2): vars and rows are presented read-only; the typed vars-and-rows editor lands in S3. */
function ForEachForm({ node }: { node: ForEachNode }) {
  return (
    <div>
      <h3 className="mt-2 text-xs font-semibold uppercase text-caption">Loop variables</h3>
      {node.vars.length === 0 ? (
        <p className="text-xs text-hint">no vars</p>
      ) : (
        <ul className="text-xs text-caption">
          {node.vars.map((v) => (
            <li key={v.name} className="font-mono">
              {v.name}: {v.kind}
              {v.device_type !== undefined ? ` (${v.device_type})` : ''}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-caption">
        {node.rows.length} row{node.rows.length === 1 ? '' : 's'} · {node.body.length} block
        {node.body.length === 1 ? '' : 's'} in the body — drag onto the canvas to edit; each copy
        is spliced into the list for_each sits in.
      </p>
    </div>
  )
}

/** `args` are keyed by the target group's declared `params` (design §5.2), so arity is right
 * by construction (expand.py:190 `set(args) != set(params)` rejects a mismatch) — switching
 * the picked group resets `args` to exactly that group's param set, carrying over any value
 * already entered under a name the new group also declares. */
function GroupRefForm({ node }: { node: GroupRefNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  const groups = useDocStore((s) => s.groups)
  const groupNames = Object.keys(groups)
  const params = groups[node.name]?.params ?? []

  const setName = (name: string) => {
    const nextParams = groups[name]?.params ?? []
    const args: Record<string, ParamValue> = {}
    for (const p of nextParams) if (node.args[p.name] !== undefined) args[p.name] = node.args[p.name]
    patchBlock(node.uid, { name, args })
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
          declares locals). S3 makes it conditional on the group having locals; here it is
          always shown as a plain optional field. */}
      <FieldRow label="As (call-site prefix)">
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
            <FieldRow key={p.name} label={p.name} required>
              <ExpressionInput
                value={paramInputText(node.args[p.name])}
                onCommit={(v) =>
                  patchBlock(node.uid, { args: { ...node.args, [p.name]: coerceValueInput(v) } })
                }
              />
            </FieldRow>
          ))}
        </>
      )}
    </div>
  )
}
