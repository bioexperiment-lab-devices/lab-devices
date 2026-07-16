/** Doc v1 JSON <-> editor tree. treeToDoc(docToTree(doc)) must round-trip the golden
 * fixture byte-for-byte (deep equality); emission rules mirror the engine serializer:
 * omit empty params, omit null timing keys, `check` only alongside `until`, `else`
 * omitted (not null) when absent, `on_error` omitted unless it is 'continue'. `groups`
 * omitted entirely when empty; a for_each's `var` omitted when null, its JSON key `in` maps
 * to the node field `items`; a group_ref's `args` omitted when empty (repetition design
 * 2026-07-15 §5 `serialize.py:288-347`; W9 removes the `groups`/`for_each`/`group_ref`
 * hard-reject this file carried since Increment 7 §9/§10). */
import type {
  AbortBody,
  AlarmBody,
  BlockJson,
  BranchBody,
  CommandBody,
  ComputeBody,
  ExperimentDocJson,
  ForEachBody,
  GroupJson,
  GroupRefBody,
  LoopBody,
  MeasureBody,
  OperatorInputBody,
  RecordBody,
  StreamDeclJson,
  WorkflowJson,
} from '../types/doc'
import { newUid, type BlockNode, type InputType } from './tree'

export interface DocContent {
  name: string
  description: string | null
  roles: Record<string, { type: string }>
  // persistence is per-stream override support (2026-07-14 review, I2) — the builder has no
  // UI for it (StreamsPanel.tsx), but a stream declared `persistence: "disk"` under an
  // `in_memory` workflow default must survive Save, or its samples are silently never
  // written to disk at all.
  streams: Record<string, { units: string | null; persistence?: string | null }>
  tree: BlockNode[]
  // Carried opaquely — the builder has no UI for either, but it must not destroy them on
  // save (2026-07-14 review, Fix 1): a hand-authored workflow.defaults.retry is a
  // documented, supported policy, and a custom persistence setting is a real run knob.
  persistence?: WorkflowJson['persistence']
  defaults?: WorkflowJson['defaults']
  // Reusable group bodies invoked via group_ref (design §2.2/§5). Optional, like persistence/
  // defaults above: the builder has no authoring UI or store scope for groups yet (that lands
  // in a later W9 task), so a DocContent built directly by a caller that predates this field
  // (docStore.ts's emptyContent/selectContent) simply omits it. docToTree always populates it.
  groups?: Record<string, { params: string[]; body: BlockNode[] }>
}

export class DocConvertError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'DocConvertError'
  }
}

const BLOCK_KEYS = new Set(['label', 'gap_after', 'start_offset', 'retry', 'on_error'])

export function docToTree(doc: ExperimentDocJson): DocContent {
  if (doc.doc_version !== 1) {
    throw new DocConvertError(`unsupported doc_version ${String(doc.doc_version)}`)
  }
  const wf = doc.workflow
  if (wf.schema_version !== 1) {
    throw new DocConvertError(`unsupported workflow schema_version ${String(wf.schema_version)}`)
  }
  const groups: NonNullable<DocContent['groups']> = {}
  for (const [name, g] of Object.entries(wf.groups ?? {})) {
    groups[name] = { params: g.params ?? [], body: (g.body ?? []).map(blockToNode) }
  }
  const streams: DocContent['streams'] = {}
  for (const [name, decl] of Object.entries(wf.streams ?? {})) {
    streams[name] = {
      units: decl.units ?? null,
      ...(decl.persistence !== undefined ? { persistence: decl.persistence } : {}),
    }
  }
  const roles: DocContent['roles'] = {}
  for (const [name, role] of Object.entries(doc.roles)) roles[name] = { type: role.type }
  return {
    name: doc.name,
    description: doc.description ?? null,
    roles,
    streams,
    tree: (wf.blocks ?? []).map(blockToNode),
    groups,
    ...(wf.persistence !== undefined ? { persistence: wf.persistence } : {}),
    ...(wf.defaults !== undefined ? { defaults: wf.defaults } : {}),
  }
}

function blockToNode(block: BlockJson): BlockNode {
  const keys = Object.keys(block).filter((k) => !BLOCK_KEYS.has(k))
  if (keys.length !== 1) {
    throw new DocConvertError(`block must have exactly one type key, got [${keys.join(', ')}]`)
  }
  const kind = keys[0]
  const base = {
    uid: newUid(),
    label: block.label ?? null,
    gapAfter: block.gap_after ?? null,
    startOffset: block.start_offset ?? null,
    ...(block.retry !== undefined ? { retry: block.retry } : {}),
    ...(block.on_error !== undefined ? { onError: block.on_error } : {}),
  }
  switch (kind) {
    case 'command': {
      const b = block.command as CommandBody
      return { ...base, kind, device: b.device, verb: b.verb, params: { ...(b.params ?? {}) } }
    }
    case 'measure': {
      const b = block.measure as MeasureBody
      return {
        ...base,
        kind,
        device: b.device,
        verb: b.verb ?? 'measure',
        into: b.into ?? '',
        params: { ...(b.params ?? {}) },
      }
    }
    case 'operator_input': {
      const b = block.operator_input as OperatorInputBody
      return {
        ...base,
        kind,
        name: b.name,
        inputType: b.type as InputType,
        prompt: b.prompt ?? null,
        min: b.min ?? null,
        max: b.max ?? null,
        choices: b.choices ? [...b.choices] : null,
      }
    }
    case 'wait':
      return { ...base, kind, duration: block.wait?.duration ?? '' }
    case 'serial':
      return { ...base, kind, children: (block.serial?.children ?? []).map(blockToNode) }
    case 'parallel':
      return { ...base, kind, children: (block.parallel?.children ?? []).map(blockToNode) }
    case 'loop': {
      const b = block.loop as LoopBody
      return {
        ...base,
        kind,
        mode: b.until != null ? 'until' : 'count',
        count: b.count ?? 2,
        until: b.until ?? '',
        check: b.check === 'before' ? 'before' : 'after',
        pace: b.pace ?? null,
        body: (b.body ?? []).map(blockToNode),
      }
    }
    case 'branch': {
      const b = block.branch as BranchBody
      return {
        ...base,
        kind,
        condition: b.if,
        then: (b.then ?? []).map(blockToNode),
        else: b.else !== undefined ? b.else.map(blockToNode) : null,
      }
    }
    case 'compute': {
      const b = block.compute as ComputeBody
      return { ...base, kind, into: b.into, value: b.value }
    }
    case 'record': {
      const b = block.record as RecordBody
      return { ...base, kind, into: b.into, value: b.value }
    }
    case 'abort': {
      const b = block.abort as AbortBody
      return { ...base, kind, condition: b.if, message: b.message }
    }
    case 'alarm': {
      const b = block.alarm as AlarmBody
      return { ...base, kind, condition: b.if, message: b.message }
    }
    case 'for_each': {
      // Splice macro (design §2.1): JSON key `in`, node field `items` — doc.ts:55-63 states the
      // translation, the same role this function already plays for branch.if <-> condition.
      // body is a real child slot (tree.ts childSlots), so it recurses like loop.body.
      const b = block.for_each as ForEachBody
      return { ...base, kind, var: b.var ?? null, items: [...b.in], body: (b.body ?? []).map(blockToNode) }
    }
    case 'group_ref': {
      // Parametrized group reference (design §2.2). args is data carried on the node, not a
      // child slot — the referenced group's body lives in DocContent.groups, not here.
      const b = block.group_ref as GroupRefBody
      return { ...base, kind, name: b.name, args: { ...(b.args ?? {}) } }
    }
    default:
      throw new DocConvertError(`unsupported block type '${kind}' in the builder`)
  }
}

export function treeToDoc(content: DocContent): ExperimentDocJson {
  const streams: Record<string, StreamDeclJson> = {}
  for (const [name, s] of Object.entries(content.streams)) {
    streams[name] = {
      units: s.units,
      ...(s.persistence !== undefined ? { persistence: s.persistence } : {}),
    }
  }
  const roles: ExperimentDocJson['roles'] = {}
  for (const [name, role] of Object.entries(content.roles)) roles[name] = { type: role.type }
  const workflow: WorkflowJson = {
    schema_version: 1,
    metadata: { name: content.name },
    // Preserve a custom persistence setting if the doc carried one in; only fall back to
    // the builder's historical default when none was present (2026-07-14 review, Fix 1).
    persistence: content.persistence ?? { default: 'in_memory', format: 'jsonl' },
    streams,
    blocks: content.tree.map(nodeToBlock),
  }
  if (content.defaults !== undefined) workflow.defaults = content.defaults
  // groups omitted entirely when empty (serialize.py:445 `if w.groups:`), so a group-less doc
  // round-trips byte-identically to today. Assigned last (not spread into the literal above)
  // so a doc built with `blocks` already present emits `groups` after `blocks`, matching the
  // fixtures' own key order (see convert.test.ts's `doc()` helper: `blocks` is a base key,
  // `groups` is spread in afterward, so it lands after `blocks` in the JSON the tests pin).
  const groupEntries = Object.entries(content.groups ?? {})
  if (groupEntries.length > 0) {
    const groups: Record<string, GroupJson> = {}
    for (const [name, g] of groupEntries) {
      groups[name] = {
        ...(g.params.length > 0 ? { params: [...g.params] } : {}),
        body: g.body.map(nodeToBlock),
      }
    }
    workflow.groups = groups
  }
  return {
    doc_version: 1,
    name: content.name,
    description: content.description,
    roles,
    workflow,
  }
}

export function nodeToBlock(node: BlockNode): BlockJson {
  const out: BlockJson = {}
  switch (node.kind) {
    case 'command': {
      const body: CommandBody = { device: node.device, verb: node.verb }
      if (Object.keys(node.params).length > 0) body.params = { ...node.params }
      out.command = body
      break
    }
    case 'measure': {
      const body: MeasureBody = { device: node.device, verb: node.verb, into: node.into }
      if (Object.keys(node.params).length > 0) body.params = { ...node.params }
      out.measure = body
      break
    }
    case 'operator_input': {
      const body: OperatorInputBody = { name: node.name, type: node.inputType }
      if (node.prompt !== null) body.prompt = node.prompt
      if (node.min !== null) body.min = node.min
      if (node.max !== null) body.max = node.max
      if (node.choices !== null) body.choices = [...node.choices]
      out.operator_input = body
      break
    }
    case 'wait':
      out.wait = { duration: node.duration }
      break
    case 'serial':
      out.serial = { children: node.children.map(nodeToBlock) }
      break
    case 'parallel':
      out.parallel = { children: node.children.map(nodeToBlock) }
      break
    case 'loop': {
      const body: LoopBody = { body: node.body.map(nodeToBlock) }
      if (node.mode === 'count') {
        body.count = node.count
      } else {
        body.until = node.until
        body.check = node.check
      }
      if (node.pace !== null) body.pace = node.pace
      out.loop = body
      break
    }
    case 'branch': {
      const body: BranchBody = { if: node.condition, then: node.then.map(nodeToBlock) }
      if (node.else !== null) body.else = node.else.map(nodeToBlock)
      out.branch = body
      break
    }
    case 'compute':
      out.compute = { into: node.into, value: node.value }
      break
    case 'record':
      out.record = { into: node.into, value: node.value }
      break
    case 'abort':
      out.abort = { if: node.condition, message: node.message }
      break
    case 'alarm':
      out.alarm = { if: node.condition, message: node.message }
      break
    case 'for_each': {
      // Mirrors serialize.py _dump_body's ForEach arm: var emitted only when set, then in,
      // then body, in that order (design §5) — the conditional spread controls the key order.
      const body: ForEachBody = {
        ...(node.var !== null ? { var: node.var } : {}),
        in: [...node.items],
        body: node.body.map(nodeToBlock),
      }
      out.for_each = body
      break
    }
    case 'group_ref': {
      // Mirrors serialize.py _dump_body's GroupRef arm: name always, args only when non-empty.
      const body: GroupRefBody = { name: node.name }
      if (Object.keys(node.args).length > 0) body.args = { ...node.args }
      out.group_ref = body
      break
    }
    default: {
      // Exhaustiveness guard: a BlockNode kind with no arm here would emit a block with
      // zero type keys, which the engine rejects at serialize.py:279 blaming the document
      // rather than the builder. Keep this a compile error instead (design §6).
      const unreachable: never = node
      throw new DocConvertError(`unserializable block node ${JSON.stringify(unreachable)}`)
    }
  }
  if (node.label !== null) out.label = node.label
  if (node.gapAfter !== null) out.gap_after = node.gapAfter
  if (node.startOffset !== null) out.start_offset = node.startOffset
  if (node.retry !== undefined) out.retry = node.retry
  // Mirrors block_to_dict: on_error is only emitted when it is 'continue' — a default-'fail'
  // block round-trips to a dict with no on_error key at all.
  if (node.onError === 'continue') out.on_error = node.onError
  return out
}
