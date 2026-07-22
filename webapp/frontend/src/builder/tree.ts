/** Editor tree model: the canvas tree IS the engine AST (settled decision S1), with
 * stable uids for React keys, selection, and diagnostics mapping. All ops are pure and
 * return new trees (zustand/zundo snapshot immutability). */
import type { ParamValue, RetryJson, ParamDeclJson } from '../types/doc'
import type { VerbSpec } from '../types/catalog'
import { seedParams } from './paramDefaults'

export type InputType = 'int' | 'float' | 'bool' | 'enum'
/** Blocks that hold a body and decide what runs, in what order, and how many times. This is
 * exactly the set with child slots (`childSlots` below), so the palette's Flow section and the
 * drop affordance coincide (design 2026-07-18 §3). */
export type FlowKind = 'serial' | 'parallel' | 'branch' | 'loop' | 'for_each'
/** Leaf blocks that write run state rather than acting on a device (Increment 6). */
export type DataKind = 'compute' | 'record'
/** Leaf blocks that hold the run until the clock or the operator releases it. */
export type PauseKind = 'wait' | 'operator_input'
/** Leaf blocks that change the run's fate (Increment 8): alarm flags and continues, abort stops. */
export type SafetyKind = 'alarm' | 'abort'
/** Every kind `newPaletteNode` can construct. None of Data/Pause/Safety takes `retry` — retry is
 * command/measure only (design 2026-07-14 §2.1). `group_ref` is in the union but has no section
 * of its own: it is dragged from the Groups panel (design 2026-07-18 §6). */
export type PaletteKind = FlowKind | DataKind | PauseKind | SafetyKind | 'group_ref'

interface NodeBase {
  uid: string
  label: string | null
  gapAfter: string | null
  startOffset: string | null
  // retry is command/measure only in the engine (2026-07-14 §2.1); on_error is legal on every
  // block type (§2.2). Both live on NodeBase since it is the one shape every BlockNode extends.
  retry?: RetryJson
  onError?: 'fail' | 'continue'
}

export interface CommandNode extends NodeBase {
  kind: 'command'
  device: string
  verb: string
  params: Record<string, ParamValue>
}

export interface MeasureNode extends NodeBase {
  kind: 'measure'
  device: string
  verb: string
  into: string
  params: Record<string, ParamValue>
}

export interface OperatorInputNode extends NodeBase {
  kind: 'operator_input'
  name: string
  inputType: InputType
  prompt: string | null
  min: number | null
  max: number | null
  choices: string[] | null
}

export interface WaitNode extends NodeBase {
  kind: 'wait'
  duration: string
}

export interface SerialNode extends NodeBase {
  kind: 'serial'
  children: BlockNode[]
}

export interface ParallelNode extends NodeBase {
  kind: 'parallel'
  children: BlockNode[]
}

export interface LoopNode extends NodeBase {
  kind: 'loop'
  mode: 'count' | 'until'
  /** number = literal; string = int-typed expression (schema v3, engine #58). */
  count: number | string
  until: string
  check: 'before' | 'after'
  pace: string | null
  body: BlockNode[]
}

export interface BranchNode extends NodeBase {
  kind: 'branch'
  condition: string
  then: BlockNode[]
  else: BlockNode[] | null
}

export interface ForEachNode extends NodeBase {
  kind: 'for_each'
  vars: ParamDeclJson[]
  rows: Array<Record<string, ParamValue>>
  body: BlockNode[]
}

export interface GroupRefNode extends NodeBase {
  kind: 'group_ref'
  name: string
  as: string | null
  args: Record<string, ParamValue>
}

export interface ComputeNode extends NodeBase {
  kind: 'compute'
  into: string
  value: ParamValue
  as?: string | null // unit cast, carried opaquely (no builder UI yet; design 2026-07-21 §6)
}

export interface RecordNode extends NodeBase {
  kind: 'record'
  into: string
  value: ParamValue
  as?: string | null // unit cast, carried opaquely
}

/** `condition` mirrors BranchNode.condition: the JSON key is `if` (a reserved word), and
 * convert.ts is the single place that translates. */
export interface AbortNode extends NodeBase {
  kind: 'abort'
  condition: string
  message: string
}

export interface AlarmNode extends NodeBase {
  kind: 'alarm'
  condition: string
  message: string
}

export type BlockNode =
  | CommandNode
  | MeasureNode
  | OperatorInputNode
  | WaitNode
  | SerialNode
  | ParallelNode
  | LoopNode
  | BranchNode
  | ForEachNode
  | GroupRefNode
  | ComputeNode
  | RecordNode
  | AbortNode
  | AlarmNode

export type BlockKind = BlockNode['kind']

export interface SlotRef {
  parentUid: string | null
  slot: string
  index: number
}

export interface ParentInfo {
  parent: BlockNode | null
  slot: string
  index: number
}

export const newUid = (): string =>
  typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `uid-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`

export function childSlots(node: BlockNode): Array<[string, BlockNode[]]> {
  switch (node.kind) {
    case 'serial':
    case 'parallel':
      return [['children', node.children]]
    case 'loop':
      return [['body', node.body]]
    case 'branch':
      return node.else === null
        ? [['then', node.then]]
        : [
            ['then', node.then],
            ['else', node.else],
          ]
    case 'for_each':
      return [['body', node.body]]
    default:
      return []
  }
}

export function replaceSlot(node: BlockNode, slot: string, list: BlockNode[]): BlockNode {
  if (node.kind === 'serial' || node.kind === 'parallel') return { ...node, children: list }
  if (node.kind === 'loop') return { ...node, body: list }
  if (node.kind === 'branch') {
    return slot === 'then' ? { ...node, then: list } : { ...node, else: list }
  }
  if (node.kind === 'for_each') return { ...node, body: list }
  throw new Error(`${node.kind} has no child slot ${slot}`)
}

export function visitNodes(tree: BlockNode[], fn: (node: BlockNode) => void): void {
  for (const node of tree) {
    fn(node)
    for (const [, children] of childSlots(node)) visitNodes(children, fn)
  }
}

export function findNode(tree: BlockNode[], uid: string): BlockNode | null {
  for (const node of tree) {
    if (node.uid === uid) return node
    for (const [, children] of childSlots(node)) {
      const found = findNode(children, uid)
      if (found) return found
    }
  }
  return null
}

export function containsUid(node: BlockNode, uid: string): boolean {
  if (node.uid === uid) return true
  return childSlots(node).some(([, children]) => children.some((c) => containsUid(c, uid)))
}

export function findLocation(tree: BlockNode[], uid: string): ParentInfo | null {
  const inList = (list: BlockNode[], parent: BlockNode | null, slot: string): ParentInfo | null => {
    for (let i = 0; i < list.length; i++) {
      if (list[i].uid === uid) return { parent, slot, index: i }
      for (const [childSlot, children] of childSlots(list[i])) {
        const found = inList(children, list[i], childSlot)
        if (found) return found
      }
    }
    return null
  }
  return inList(tree, null, 'blocks')
}

const clampIndex = (index: number, length: number): number =>
  Math.max(0, Math.min(index, length))

/** A parallel's `children` ARE its lanes, and every lane authored through the UI is a
 * serial container (spec 2026-07-18 §3.4) — so anything landing on a parallel's
 * `children` slot that isn't already a serial gets wrapped in a fresh plain one. Living
 * here (not in onDragEnd) means insertNode/moveNode/duplicateNode all share the one code
 * path, each store action stays a single zundo snapshot, and duplicating a legacy
 * bare-block lane normalizes the copy for free. Imported docs are untouched: docToTree
 * builds children directly and never calls this. */
export function wrapAsLane(node: BlockNode): BlockNode {
  if (node.kind === 'serial') return node
  return { uid: newUid(), label: null, gapAfter: null, startOffset: null, kind: 'serial', children: [node] }
}

export function insertNode(tree: BlockNode[], node: BlockNode, at: SlotRef): BlockNode[] {
  if (at.parentUid === null) {
    const out = [...tree]
    out.splice(clampIndex(at.index, out.length), 0, node)
    return out
  }
  let inserted = false
  const walkNode = (n: BlockNode): BlockNode => {
    let out = n
    for (const [slot, children] of childSlots(n)) {
      let list = children.map(walkNode)
      if (n.uid === at.parentUid && slot === at.slot) {
        const toInsert = n.kind === 'parallel' && slot === 'children' ? wrapAsLane(node) : node
        list.splice(clampIndex(at.index, list.length), 0, toInsert)
        inserted = true
      }
      out = replaceSlot(out, slot, list)
    }
    return out
  }
  const next = tree.map(walkNode)
  return inserted ? next : tree
}

export function removeNode(tree: BlockNode[], uid: string): [BlockNode[], BlockNode | null] {
  let removed: BlockNode | null = null
  const walkNode = (node: BlockNode): BlockNode => {
    let out = node
    for (const [slot, children] of childSlots(node)) {
      out = replaceSlot(out, slot, walkList(children))
    }
    return out
  }
  const walkList = (list: BlockNode[]): BlockNode[] => {
    const kept: BlockNode[] = []
    for (const node of list) {
      if (node.uid === uid) removed = node
      else kept.push(walkNode(node))
    }
    return kept
  }
  const next = walkList(tree)
  return removed ? [next, removed] : [tree, null]
}

export function canDrop(tree: BlockNode[], dragUid: string, at: SlotRef): boolean {
  const dragged = findNode(tree, dragUid)
  if (!dragged) return false
  if (at.parentUid === null) return true
  const target = findNode(tree, at.parentUid)
  if (target === null) return false
  if (!childSlots(target).some(([name]) => name === at.slot)) return false
  return !containsUid(dragged, at.parentUid)
}

export function moveNode(tree: BlockNode[], uid: string, to: SlotRef): BlockNode[] {
  if (!canDrop(tree, uid, to)) return tree
  const from = findLocation(tree, uid)
  if (!from) return tree
  let index = to.index
  const sameList = (from.parent?.uid ?? null) === to.parentUid && from.slot === to.slot
  if (sameList && from.index < to.index) index -= 1
  const [without, node] = removeNode(tree, uid)
  if (!node) return tree
  return insertNode(without, node, { parentUid: to.parentUid, slot: to.slot, index })
}

export function withFreshUids(node: BlockNode): BlockNode {
  let out: BlockNode = { ...node, uid: newUid() }
  for (const [slot, children] of childSlots(out)) {
    out = replaceSlot(out, slot, children.map(withFreshUids))
  }
  return out
}

export function duplicateNode(tree: BlockNode[], uid: string): [BlockNode[], string | null] {
  const loc = findLocation(tree, uid)
  const node = findNode(tree, uid)
  if (!loc || !node) return [tree, null]
  const clone = withFreshUids(node)
  const at: SlotRef = { parentUid: loc.parent?.uid ?? null, slot: loc.slot, index: loc.index + 1 }
  return [insertNode(tree, clone, at), clone.uid]
}

export function updateNode(tree: BlockNode[], uid: string, patch: object): BlockNode[] {
  const walkNode = (node: BlockNode): BlockNode => {
    let out = node.uid === uid ? ({ ...node, ...patch } as BlockNode) : node
    for (const [slot, children] of childSlots(out)) {
      out = replaceSlot(out, slot, children.map(walkNode))
    }
    return out
  }
  return tree.map(walkNode)
}

/** allow_repeat is the author's acknowledgement of a *specific verb's* hazard (retry-safety
 * design 2026-07-14 §2.1) — it must not silently carry over onto a different verb the
 * author never saw the hazard box for (2026-07-14 review, I3). The Inspector calls this
 * whenever a command/measure block's verb changes; clearing allow_repeat alone is enough:
 * RetrySection's `locked` is derived from `!retrySafe && !allowRepeat`, so for a
 * non-retry_safe verb this re-locks attempts/backoff and re-opens the hazard checkbox
 * unticked, forcing the author back through the acknowledgement for the verb that now runs.
 *
 * The device (Role) picker deliberately does NOT get the same treatment: it only ever
 * offers roles of the SAME catalog device type as the current one, so switching device can
 * never change the (roleType, verb) pair retry_safe is keyed on — the hazard the author
 * acknowledged is still the hazard of the verb that runs. */
export function retryAfterVerbChange(retry: RetryJson | undefined): RetryJson | undefined {
  if (retry === undefined) return undefined
  return { ...retry, allow_repeat: undefined }
}

const nodeBase = (): NodeBase => ({ uid: newUid(), label: null, gapAfter: null, startOffset: null })

export function newPaletteNode(kind: PaletteKind): BlockNode {
  const base = nodeBase()
  switch (kind) {
    case 'serial':
      return { ...base, kind, children: [] }
    case 'parallel':
      // Parallelism should be immediately visible (S1): start with two empty lanes.
      return {
        ...base,
        kind,
        children: [
          { ...nodeBase(), kind: 'serial', children: [] },
          { ...nodeBase(), kind: 'serial', children: [] },
        ],
      }
    case 'loop':
      return { ...base, kind, mode: 'count', count: '', until: '', check: 'after', pace: null, body: [] }
    case 'branch':
      return { ...base, kind, condition: '', then: [], else: [] }
    case 'wait':
      return { ...base, kind, duration: '' }
    case 'operator_input':
      return { ...base, kind, name: '', inputType: 'float', prompt: null, min: null, max: null, choices: null }
    case 'compute':
    case 'record':
      return { ...base, kind, into: '', value: '' }
    case 'abort':
    case 'alarm':
      return { ...base, kind, condition: '', message: '' }
    case 'for_each':
      // Seeded empty like branch/compute: a fabricated example (tube / 1,2,3) read as real
      // data. An empty `in` is still a load error (expand.py:99), so the block is
      // invalid-until-filled — which Save permits and ProblemsPanel reports, same as an
      // empty branch condition.
      return { ...base, kind, vars: [], rows: [], body: [] }
    case 'group_ref':
      return { ...base, kind, name: '', as: null, args: {} }
  }
}

/** A `group_ref` pre-filled with the group being called. `newPaletteNode` takes a kind and
 * nothing else, so the Groups panel's per-group chips (design 2026-07-18 §6) get their own
 * constructor rather than pushing a group-shaped optional parameter through every unrelated
 * `newPaletteNode` call. `args` is left empty for the Inspector to fill, exactly as a blank
 * `Group ref` behaved before. */
export function newGroupRefNode(name: string): BlockNode {
  return { ...nodeBase(), kind: 'group_ref', name, as: null, args: {} }
}

export function newVerbNode(role: string, verb: string, spec: VerbSpec): BlockNode {
  const params = seedParams(spec.params)
  return spec.kind === 'measure'
    ? { ...nodeBase(), kind: 'measure', device: role, verb, into: '', params }
    : { ...nodeBase(), kind: 'command', device: role, verb, params }
}
