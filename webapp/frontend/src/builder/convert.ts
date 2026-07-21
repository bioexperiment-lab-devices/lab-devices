/** Doc v1 JSON <-> editor tree. treeToDoc(docToTree(doc)) must round-trip the golden
 * fixture byte-for-byte; emission rules mirror the engine serializer:
 * omit empty params, omit null timing keys, `check` only alongside `until`, `else`
 * omitted (not null) when absent, `on_error` omitted unless it is 'continue'. `groups`
 * omitted entirely when empty; a for_each carries typed `vars` and its JSON key `in` maps
 * to the node field `rows` (typed rows; the v1 scalar `var` shorthand is gone); a group_ref's
 * `as` is omitted when null and `args` when empty (typed-params design 2026-07-20 §3-4,
 * `serialize.py`; roles now live in `workflow.roles`, not the doc envelope, §5). */
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
  LocalDeclJson,
  LoopBody,
  MeasureBody,
  OperatorInputBody,
  ParamDeclJson,
  RecordBody,
  RoleDeclJson,
  StreamDeclJson,
  WorkflowJson,
} from '../types/doc'
import { newUid, type BlockNode, type InputType } from './tree'

/** The editor form of a group: typed params, named locals, and a body of editor nodes
 * (schema 2, typed-group-parameters design §9.2). Exported so the store and paths.ts key
 * their `groups` field on the same shape. */
export type GroupDef = { params: ParamDeclJson[]; locals: Record<string, LocalDeclJson>; body: BlockNode[] }

export interface DocContent {
  name: string
  description: string | null
  // Flat editor field; emitted UNDER workflow.roles (schema 2 moved roles inside the
  // workflow). Kept flat here — the store's selectContent/snapshotOf/partialize all read
  // `content.roles`, and treeToDoc places it under `workflow.roles`.
  roles: Record<string, RoleDeclJson>
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
  // Carried opaquely for the same reason as persistence/defaults above: the builder has no
  // UI for workflow.metadata beyond the doc name (mirrored into metadata.name on save), but
  // a hand-authored `author` or `description` is real authorial content — destroying it on
  // save would silently erase a document's authorship and its entire scientific description.
  metadata?: WorkflowJson['metadata']
  // Reusable group bodies invoked via group_ref (design §2.2/§5). Optional, like persistence/
  // defaults above, for the same structural reason: docStore.ts's store now has a full
  // authoring API for groups (addGroup/renameGroup/removeGroup/setGroupParams/setGroupLocals/
  // setScope) and treats `groups` as a required field there, like `tree` — this type just
  // stays permissive for any DocContent built directly by a caller that predates this field.
  // docToTree always populates it.
  groups?: Record<string, GroupDef>
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
  if (wf.schema_version !== 3) {
    throw new DocConvertError(`unsupported workflow schema_version ${String(wf.schema_version)}`)
  }
  const groups: NonNullable<DocContent['groups']> = {}
  for (const [name, g] of Object.entries(wf.groups ?? {})) {
    groups[name] = {
      params: (g.params ?? []).map((p) => ({ ...p })),
      locals: { ...(g.locals ?? {}) },
      body: (g.body ?? []).map(blockToNode),
    }
  }
  const streams: DocContent['streams'] = {}
  for (const [name, decl] of Object.entries(wf.streams ?? {})) {
    streams[name] = {
      // The engine spells "no unit" as the literal string "unitless" (units.py
      // _UNITLESS_TEXTS); the Studio spells it as a blank field instead, converting at this
      // one boundary. Only the exact spelling "unitless" maps to blank — "" and "1" are other
      // engine-recognized unitless spellings, but they must round-trip verbatim, not collapse
      // into this one, or a doc that spells it "" would silently re-save as "unitless".
      units: decl.units === 'unitless' ? null : (decl.units ?? null),
      ...(decl.persistence !== undefined ? { persistence: decl.persistence } : {}),
    }
  }
  // Roles live under the workflow now (schema 2); a role may carry an optional direct device
  // binding, which must survive the round trip.
  const roles: DocContent['roles'] = {}
  for (const [name, role] of Object.entries(wf.roles ?? {})) {
    roles[name] = role.device !== undefined ? { type: role.type, device: role.device } : { type: role.type }
  }
  return {
    name: doc.name,
    description: doc.description ?? null,
    roles,
    streams,
    tree: (wf.blocks ?? []).map(blockToNode),
    groups,
    ...(wf.metadata !== undefined ? { metadata: wf.metadata } : {}),
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
      return { ...base, kind, into: b.into, value: b.value, as: b.as ?? null }
    }
    case 'record': {
      const b = block.record as RecordBody
      return { ...base, kind, into: b.into, value: b.value, as: b.as ?? null }
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
      // Splice macro (design §2.1): JSON key `in`, node field `rows` — doc.ts states the
      // translation, the same role this function already plays for branch.if <-> condition.
      // Schema 2: typed `vars`, one value per row. body is a real child slot (tree.ts
      // childSlots), so it recurses like loop.body.
      const b = block.for_each as ForEachBody
      return { ...base, kind, vars: (b.vars ?? []).map((v) => ({ ...v })), rows: (b.in ?? []).map((r) => ({ ...r })), body: (b.body ?? []).map(blockToNode) }
    }
    case 'group_ref': {
      // Parametrized group reference (design §2.2). args is data carried on the node, not a
      // child slot — the referenced group's body lives in DocContent.groups, not here. Schema
      // 2 adds `as`, the call-site prefix that namespaces a group's locals.
      const b = block.group_ref as GroupRefBody
      return { ...base, kind, name: b.name, as: b.as ?? null, args: { ...(b.args ?? {}) } }
    }
    default:
      throw new DocConvertError(`unsupported block type '${kind}' in the builder`)
  }
}

export function treeToDoc(content: DocContent): ExperimentDocJson {
  const streams: Record<string, StreamDeclJson> = {}
  for (const [name, s] of Object.entries(content.streams)) {
    streams[name] = {
      // Mirror of the docToTree boundary above: a blank field (null) serializes back to the
      // engine's literal "unitless" spelling; any other value (including "" or "1") passes
      // through unchanged.
      units: s.units ?? 'unitless',
      ...(s.persistence !== undefined ? { persistence: s.persistence } : {}),
    }
  }
  // Roles are emitted under workflow.roles now (schema 2), NOT the envelope; an optional
  // direct device binding rides along.
  const roles: Record<string, RoleDeclJson> = {}
  for (const [name, role] of Object.entries(content.roles)) {
    roles[name] = role.device !== undefined ? { type: role.type, device: role.device } : { type: role.type }
  }
  const groupEntries = Object.entries(content.groups ?? {})
  let groups: Record<string, GroupJson> | undefined
  if (groupEntries.length > 0) {
    groups = {}
    for (const [name, g] of groupEntries) {
      groups[name] = {
        ...(g.params.length > 0 ? { params: g.params.map((p) => ({ ...p })) } : {}),
        ...(Object.keys(g.locals).length > 0 ? { locals: g.locals } : {}),
        body: g.body.map(nodeToBlock),
      }
    }
  }
  // Key order mirrors workflow_to_dict: schema_version, metadata, persistence, defaults,
  // roles, streams, groups, blocks — all conditional sections omitted when empty. defaults,
  // roles and groups are spread into the literal at their canonical position rather than
  // assigned afterward — an object-literal-plus-post-assignment cannot land a conditional key
  // ahead of keys that must appear unconditionally after it.
  const workflow: WorkflowJson = {
    schema_version: 3,
    // content.name stays authoritative for metadata.name (the builder edits the doc name,
    // which is mirrored here) — re-assigning an existing key via spread keeps its original
    // position, so a carried-in metadata.author/description keeps its place after name.
    metadata: { ...content.metadata, name: content.name },
    // Preserve a custom persistence setting if the doc carried one in; only fall back to
    // the builder's historical default when none was present (2026-07-14 review, Fix 1).
    persistence: content.persistence ?? { default: 'in_memory', format: 'jsonl' },
    ...(content.defaults !== undefined ? { defaults: content.defaults } : {}),
    // roles omitted entirely when empty (engine workflow_to_dict), so a role-less doc keeps a
    // minimal workflow.
    ...(Object.keys(roles).length > 0 ? { roles } : {}),
    streams,
    // groups omitted entirely when empty (serialize.py:445 `if w.groups:`), so a group-less
    // doc round-trips byte-identically to today.
    ...(groups !== undefined ? { groups } : {}),
    blocks: content.tree.map(nodeToBlock),
  }
  return {
    doc_version: 1,
    name: content.name,
    description: content.description,
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
        // Canonicalize: a numeric-string count (typed into the expression editor) emits as
        // a JSON number, so literal counts keep one spelling across save/load round-trips.
        const c = node.count
        body.count = typeof c === 'string' && /^\d+$/.test(c.trim()) ? Number(c.trim()) : c
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
      out.compute = { into: node.into, value: node.value, ...(node.as != null ? { as: node.as } : {}) }
      break
    case 'record':
      out.record = { into: node.into, value: node.value, ...(node.as != null ? { as: node.as } : {}) }
      break
    case 'abort':
      out.abort = { if: node.condition, message: node.message }
      break
    case 'alarm':
      out.alarm = { if: node.condition, message: node.message }
      break
    case 'for_each': {
      // Mirrors serialize.py _dump_body's ForEach arm: vars, then in (rows), then body, in
      // that order (design §5/§9.2).
      const body: ForEachBody = {
        vars: node.vars.map((v) => ({ ...v })),
        in: node.rows.map((r) => ({ ...r })),
        body: node.body.map(nodeToBlock),
      }
      out.for_each = body
      break
    }
    case 'group_ref': {
      // Mirrors serialize.py _dump_body's GroupRef arm: name always, then `as` when set, then
      // args when non-empty.
      const body: GroupRefBody = { name: node.name }
      if (node.as !== null) body.as = node.as
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
