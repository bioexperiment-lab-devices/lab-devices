import { useState } from 'react'
import { useCatalogStore } from '../stores/catalogStore'
import { useDocStore } from '../stores/docStore'
import type { ParamSpec } from '../types/catalog'
import type { ParamValue, RetryJson } from '../types/doc'
import { coerceParamInput, coerceValueInput, paramInputText } from './params'
import {
  DurationField,
  ExpressionInput,
  FieldRow,
  NumberField,
  TextAreaField,
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

/** "The current tree" is a selector over `scope`, not a fixed field (design §5.2) — a
 * selected uid can live in a group's body, not just the main tree, once the scope switcher
 * (Canvas.tsx) has a group active. Mirrors Canvas's identical read and docStore's internal
 * `activeList` (not exported; store ops resolve it themselves for writes). */
function useActiveTree(): BlockNode[] {
  const scope = useDocStore((s) => s.scope)
  const tree = useDocStore((s) => s.tree)
  const groups = useDocStore((s) => s.groups)
  return scope === null ? tree : (groups[scope]?.body ?? [])
}

export function Inspector() {
  const selectedUid = useDocStore((s) => s.selectedUid)
  const scope = useDocStore((s) => s.scope)
  const activeTree = useActiveTree()
  const node = selectedUid ? findNode(activeTree, selectedUid) : null
  return (
    <aside className="w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-slate-50 p-3">
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
 * DocProperties. `params` is the ONLY thing that belongs to the group itself rather than to a
 * block inside it (design §5.2): group_ref's args are keyed by this list (expand.py:190), so
 * editing it here, in the scope it declares, is what keeps every call site's arity correct by
 * construction rather than by a second validation pass. */
function GroupProperties({ name }: { name: string }) {
  const group = useDocStore((s) => s.groups[name])
  const setGroupParams = useDocStore((s) => s.setGroupParams)
  const params = group?.params ?? []
  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold text-slate-700">Group: {name}</h2>
      <FieldRow label="Params (one per line)">
        <TextAreaField
          mono
          value={params.join('\n')}
          onCommit={(v) =>
            setGroupParams(
              name,
              v
                .split('\n')
                .map((line) => line.trim())
                .filter((line) => line !== ''),
            )
          }
        />
      </FieldRow>
      <p className="mt-2 text-xs text-slate-400">{group?.body.length ?? 0} top-level blocks.</p>
      <p className="mt-4 text-xs text-slate-400">Select a block to edit its parameters.</p>
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
    <div>
      <h2 className="mb-2 text-sm font-semibold text-slate-700">Experiment</h2>
      <FieldRow label="Description">
        <TextAreaField value={description ?? ''} onCommit={(v) => setDescription(v || null)} />
      </FieldRow>
      <p className="mt-2 text-xs text-slate-400">
        {Object.keys(roles).length} roles · {Object.keys(streams).length} streams ·{' '}
        {tree.length} top-level blocks
      </p>
      <p className="mt-4 text-xs text-slate-400">Select a block to edit its parameters.</p>
    </div>
  )
}

function BlockForm({ node }: { node: BlockNode }) {
  const activeTree = useActiveTree()
  const patchBlock = useDocStore((s) => s.patchBlock)
  const loc = findLocation(activeTree, node.uid)
  const parentKind = loc?.parent?.kind ?? null
  // for_each may not carry gap_after/start_offset at all (expand.py:26 _FOR_EACH_FORBIDDEN) —
  // it is a splice, so there is no single runtime block for either key to attach to.
  const showGapAfter = node.kind !== 'for_each' && (parentKind === null || parentKind === 'serial')
  const showStartOffset = node.kind !== 'for_each' && parentKind === 'parallel'
  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold text-slate-700">{KIND_TITLES[node.kind]}</h2>
      <KindBody node={node} />
      <h3 className="mt-3 border-t border-slate-200 pt-2 text-xs font-semibold uppercase text-slate-400">
        Timing & label
      </h3>
      <FieldRow label="Label">
        <TextField
          value={node.label ?? ''}
          onCommit={(v) => patchBlock(node.uid, { label: v || null })}
          placeholder="optional display name"
        />
      </FieldRow>
      {showGapAfter && (
        <FieldRow label="Gap after">
          <DurationField
            value={node.gapAfter}
            allowEmpty
            onCommit={(v) => patchBlock(node.uid, { gapAfter: v })}
          />
        </FieldRow>
      )}
      {showStartOffset && (
        <FieldRow label="Start offset">
          <DurationField
            value={node.startOffset}
            allowEmpty
            onCommit={(v) => patchBlock(node.uid, { startOffset: v })}
          />
        </FieldRow>
      )}
      {/* abort forbids on_error: "continue" — tolerating a safety stop is a contradiction
          (engine design 2026-07-16 §5.1), so the control is omitted rather than offered and
          rejected. The related rule (an abort may have no tolerant ANCESTOR) is the backend
          validator's; it surfaces as a diagnostic, not as a second frontend opinion.
          for_each forbids on_error outright (expand.py:26) for the same splice reason as
          gap_after/start_offset above — same suppression pattern, different block-level key. */}
      {node.kind !== 'abort' && node.kind !== 'for_each' && (
        <FieldRow label="On error">
          <select
            value={node.onError ?? 'fail'}
            onChange={(e) => patchBlock(node.uid, { onError: e.target.value as 'fail' | 'continue' })}
            className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
          >
            <option value="fail">fail (stop the run)</option>
            <option value="continue">continue (tolerate the failure)</option>
          </select>
        </FieldRow>
      )}
      {(node.kind === 'command' || node.kind === 'measure') && <RetrySection node={node} />}
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
            <p className="rounded border border-dashed border-slate-300 bg-slate-100 p-1.5 text-[11px] text-slate-400">
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
      return <p className="text-xs text-slate-400">{node.children.length} children — drag blocks on the canvas.</p>
    case 'parallel':
      return <p className="text-xs text-slate-400">{node.children.length} lanes — manage lanes on the canvas.</p>
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
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
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
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
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
      {node.kind === 'measure' && <IntoPicker node={node} />}
      {spec ? (
        <ParamFields node={node} specs={spec.params} />
      ) : (
        <p className="text-xs text-amber-600">verb not in catalog — params not editable</p>
      )}
    </div>
  )
}

function IntoPicker({ node }: { node: MeasureNode }) {
  const streams = useDocStore((s) => s.streams)
  const addStream = useDocStore((s) => s.addStream)
  const patchBlock = useDocStore((s) => s.patchBlock)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [units, setUnits] = useState('')
  const [error, setError] = useState<string | null>(null)
  const names = Object.keys(streams)
  const create = () => {
    const err = addStream(name, units || null)
    setError(err)
    if (!err) {
      patchBlock(node.uid, { into: name })
      setAdding(false)
      setName('')
      setUnits('')
    }
  }
  return (
    <FieldRow label="Into stream" required>
      <select
        value={adding ? '__new__' : node.into}
        onChange={(e) => {
          if (e.target.value === '__new__') setAdding(true)
          else {
            setAdding(false)
            patchBlock(node.uid, { into: e.target.value })
          }
        }}
        className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
      >
        {node.into === '' && !adding && <option value="">— pick a stream —</option>}
        {names.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
        <option value="__new__">+ new stream…</option>
      </select>
      {adding && (
        <div className="mt-1 flex items-center gap-1">
          <input
            value={name}
            placeholder="name"
            onChange={(e) => setName(e.target.value)}
            className="w-20 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
          />
          <input
            value={units}
            placeholder="units"
            onChange={(e) => setUnits(e.target.value)}
            className="w-14 rounded border border-slate-300 px-1 py-0.5 text-xs"
          />
          <button onClick={create} className="rounded bg-slate-200 px-2 py-0.5 text-xs hover:bg-slate-300">
            Add
          </button>
        </div>
      )}
      {error && <p className="text-[10px] text-red-600">{error}</p>}
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
      <h3 className="mt-2 text-xs font-semibold uppercase text-slate-400">Params</h3>
      {specs.length === 0 && <p className="text-xs text-slate-400">no params</p>}
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
            <span className="flex-1 truncate font-mono text-xs text-amber-700">
              {paramInputText(node.params[name])}
            </span>
            <button
              title="Remove unknown param"
              onClick={() => setParam(name, undefined)}
              className="text-xs text-slate-400 hover:text-red-600"
            >
              ✕
            </button>
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
      <TextField
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
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
        >
          <option value="">— unset —</option>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
        <button
          type="button"
          title="Use an expression"
          onClick={() => setExprMode(true)}
          className="shrink-0 rounded border border-slate-300 px-1 text-xs text-slate-500 hover:bg-slate-200"
        >
          ƒ
        </button>
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
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
        >
          <option value="int">int</option>
          <option value="float">float</option>
          <option value="bool">bool</option>
          <option value="enum">enum</option>
        </select>
      </FieldRow>
      <FieldRow label="Prompt">
        <TextField
          value={node.prompt ?? ''}
          onCommit={(v) => patchBlock(node.uid, { prompt: v || null })}
          placeholder="shown to the operator"
        />
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
          <TextAreaField
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
              className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
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
          className="rounded border border-dashed border-slate-300 px-2 py-1 text-xs text-slate-500 hover:text-slate-700"
        >
          + add else lane
        </button>
      ) : (
        <button
          disabled={node.else.length > 0}
          title={node.else.length > 0 ? 'Empty the else lane first' : undefined}
          onClick={() => patchBlock(node.uid, { else: null })}
          className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-500 enabled:hover:text-red-600 disabled:opacity-40"
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
  const streams = useDocStore((s) => s.streams)
  const streamNames = Object.keys(streams)
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
        <FieldRow label="Into (stream)" required>
          <select
            value={node.into}
            onChange={(e) => patchBlock(node.uid, { into: e.target.value })}
            className="w-full rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
          >
            <option value="">stream…</option>
            {streamNames.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {streamNames.length === 0 && (
            <p className="mt-1 text-xs text-amber-600">
              No streams declared — add one in the Streams panel.
            </p>
          )}
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
        <TextField
          value={node.message}
          onCommit={(v) => patchBlock(node.uid, { message: v })}
          placeholder={node.kind === 'abort' ? 'why the run must stop' : 'what to flag'}
        />
      </FieldRow>
      <p className="mt-1 text-xs text-slate-400">
        {node.kind === 'abort'
          ? 'True stops the run: devices are swept safe and the run ends "aborted".'
          : 'True flags the run and continues. Fires every time it holds — latch it with a compute if you want it once.'}
      </p>
    </div>
  )
}

/** Fast-feedback mirror of expand.py:95-118 `_envs` (design §5.1): non-empty list; scalars
 * when `var` is set; objects sharing one key set when it is not. This is NOT a second
 * opinion — on ambiguity we still accept the input and let the backend diagnostic speak, so
 * the return is only ever advisory text, never a reason to withhold the patch. */
function forEachItemsWarning(items: unknown[], hasVar: boolean): string | null {
  if (items.length === 0) return "for_each 'in' must be a non-empty list"
  if (hasVar) {
    return items.some((item) => item !== null && typeof item === 'object')
      ? "for_each with 'var' requires scalar items"
      : null
  }
  const keysets = items.map((item) =>
    item !== null && typeof item === 'object' && !Array.isArray(item)
      ? Object.keys(item as Record<string, unknown>).sort().join(',')
      : null,
  )
  if (keysets.some((k) => k === null)) return 'for_each without \'var\' requires object items'
  if (new Set(keysets).size > 1) return 'for_each object items must share one key set'
  return null
}

/** for_each is a SPLICE, not a runtime block (design 2026-07-15 §2/2026-07-16 §5.1): it copies
 * `body` once per item and splices the copies into the enclosing list, so retry/on_error/
 * gap_after/start_offset are omitted here — BlockForm already suppresses all four for this
 * kind (expand.py:26 `_FOR_EACH_FORBIDDEN`), and `label` is the one block-level key left. */
function ForEachForm({ node }: { node: ForEachNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  const itemsText = JSON.stringify(node.items)
  const [itemsError, setItemsError] = useState<string | null>(null)

  const commitItems = (text: string) => {
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      setItemsError('invalid JSON — expected an array, e.g. [1, 2, 3]')
      return
    }
    if (!Array.isArray(parsed)) {
      setItemsError('must be a JSON array')
      return
    }
    setItemsError(forEachItemsWarning(parsed, node.var !== null))
    // Accept regardless of the warning above (fast-feedback mirror, not a gate) — the
    // backend's own for_each validation is authoritative and will speak as a diagnostic.
    patchBlock(node.uid, { items: parsed as ForEachNode['items'] })
  }

  return (
    <div>
      <FieldRow label="Loop variable (var)">
        <TextField
          mono
          value={node.var ?? ''}
          onCommit={(v) => patchBlock(node.uid, { var: v || null })}
          placeholder="unset: items are objects, spread as named holes"
        />
      </FieldRow>
      <FieldRow label="Items (JSON array)" required>
        <TextAreaField mono rows={4} value={itemsText} onCommit={commitItems} />
      </FieldRow>
      {itemsError && <p className="text-[10px] text-amber-600">{itemsError}</p>}
      <p className="mt-2 text-xs text-slate-400">
        {node.body.length} block{node.body.length === 1 ? '' : 's'} in the body — drag onto the
        canvas to edit; each copy is spliced into the list for_each sits in.
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
    for (const p of nextParams) if (node.args[p] !== undefined) args[p] = node.args[p]
    patchBlock(node.uid, { name, args })
  }

  return (
    <div>
      <FieldRow label="Group" required>
        <select
          value={node.name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
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
      {params.length === 0 ? (
        <p className="text-xs text-slate-400">
          {node.name === '' ? 'pick a group above' : 'this group takes no params'}
        </p>
      ) : (
        <>
          <h3 className="mt-2 text-xs font-semibold uppercase text-slate-400">Args</h3>
          {params.map((p) => (
            <FieldRow key={p} label={p} required>
              <ExpressionInput
                value={paramInputText(node.args[p])}
                onCommit={(v) =>
                  patchBlock(node.uid, { args: { ...node.args, [p]: coerceValueInput(v) } })
                }
              />
            </FieldRow>
          ))}
        </>
      )}
    </div>
  )
}
