/** Editor tree model: the canvas tree IS the engine AST (settled decision S1), with
 * stable uids for React keys, selection, and diagnostics mapping. All ops are pure and
 * return new trees (zustand/zundo snapshot immutability). */
import type { ParamValue } from '../types/doc'
import type { VerbSpec } from '../types/catalog'

export type InputType = 'int' | 'float' | 'bool' | 'enum'
export type StructureKind = 'serial' | 'parallel' | 'loop' | 'branch' | 'wait' | 'operator_input'

interface NodeBase {
  uid: string
  label: string | null
  gapAfter: string | null
  startOffset: string | null
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
  count: number
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

export type BlockNode =
  | CommandNode
  | MeasureNode
  | OperatorInputNode
  | WaitNode
  | SerialNode
  | ParallelNode
  | LoopNode
  | BranchNode

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

export const newUid = (): string => crypto.randomUUID()

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
    default:
      return []
  }
}

function replaceSlot(node: BlockNode, slot: string, list: BlockNode[]): BlockNode {
  if (node.kind === 'serial' || node.kind === 'parallel') return { ...node, children: list }
  if (node.kind === 'loop') return { ...node, body: list }
  if (node.kind === 'branch') {
    return slot === 'then' ? { ...node, then: list } : { ...node, else: list }
  }
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
        list.splice(clampIndex(at.index, list.length), 0, node)
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

const nodeBase = (): NodeBase => ({ uid: newUid(), label: null, gapAfter: null, startOffset: null })

export function newStructureNode(kind: StructureKind): BlockNode {
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
      return { ...base, kind, mode: 'count', count: 2, until: '', check: 'after', pace: null, body: [] }
    case 'branch':
      return { ...base, kind, condition: '', then: [], else: [] }
    case 'wait':
      return { ...base, kind, duration: '1s' }
    case 'operator_input':
      return { ...base, kind, name: 'value', inputType: 'float', prompt: null, min: null, max: null, choices: null }
  }
}

export function newVerbNode(role: string, verb: string, spec: VerbSpec): BlockNode {
  return spec.kind === 'measure'
    ? { ...nodeBase(), kind: 'measure', device: role, verb, into: '', params: {} }
    : { ...nodeBase(), kind: 'command', device: role, verb, params: {} }
}
