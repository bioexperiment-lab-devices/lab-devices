/** Doc v1 JSON <-> editor tree. treeToDoc(docToTree(doc)) must round-trip the golden
 * fixture byte-for-byte (deep equality); emission rules mirror the engine serializer:
 * omit empty params, omit null timing keys, `check` only alongside `until`, `else`
 * omitted (not null) when absent. */
import type {
  BlockJson,
  BranchBody,
  CommandBody,
  ExperimentDocJson,
  LoopBody,
  MeasureBody,
  OperatorInputBody,
  StreamDeclJson,
} from '../types/doc'
import { newUid, type BlockNode, type InputType } from './tree'

export interface DocContent {
  name: string
  description: string | null
  roles: Record<string, { type: string }>
  streams: Record<string, { units: string | null }>
  tree: BlockNode[]
}

export class DocConvertError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'DocConvertError'
  }
}

const TIMING_KEYS = new Set(['label', 'gap_after', 'start_offset'])

export function docToTree(doc: ExperimentDocJson): DocContent {
  if (doc.doc_version !== 1) {
    throw new DocConvertError(`unsupported doc_version ${String(doc.doc_version)}`)
  }
  const wf = doc.workflow
  if (wf.schema_version !== 1) {
    throw new DocConvertError(`unsupported workflow schema_version ${String(wf.schema_version)}`)
  }
  if (wf.groups && Object.keys(wf.groups).length > 0) {
    throw new DocConvertError('workflow groups are not supported in the builder (v2 backlog)')
  }
  const streams: DocContent['streams'] = {}
  for (const [name, decl] of Object.entries(wf.streams ?? {})) {
    streams[name] = { units: decl.units ?? null }
  }
  const roles: DocContent['roles'] = {}
  for (const [name, role] of Object.entries(doc.roles)) roles[name] = { type: role.type }
  return {
    name: doc.name,
    description: doc.description ?? null,
    roles,
    streams,
    tree: (wf.blocks ?? []).map(blockToNode),
  }
}

function blockToNode(block: BlockJson): BlockNode {
  const keys = Object.keys(block).filter((k) => !TIMING_KEYS.has(k))
  if (keys.length !== 1) {
    throw new DocConvertError(`block must have exactly one type key, got [${keys.join(', ')}]`)
  }
  const kind = keys[0]
  const base = {
    uid: newUid(),
    label: block.label ?? null,
    gapAfter: block.gap_after ?? null,
    startOffset: block.start_offset ?? null,
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
    default:
      throw new DocConvertError(`unsupported block type '${kind}' in the builder`)
  }
}

export function treeToDoc(content: DocContent): ExperimentDocJson {
  const streams: Record<string, StreamDeclJson> = {}
  for (const [name, s] of Object.entries(content.streams)) streams[name] = { units: s.units }
  const roles: ExperimentDocJson['roles'] = {}
  for (const [name, role] of Object.entries(content.roles)) roles[name] = { type: role.type }
  return {
    doc_version: 1,
    name: content.name,
    description: content.description,
    roles,
    workflow: {
      schema_version: 1,
      metadata: { name: content.name },
      persistence: { default: 'in_memory', format: 'jsonl' },
      streams,
      blocks: content.tree.map(nodeToBlock),
    },
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
  }
  if (node.label !== null) out.label = node.label
  if (node.gapAfter !== null) out.gap_after = node.gapAfter
  if (node.startOffset !== null) out.start_offset = node.startOffset
  return out
}
