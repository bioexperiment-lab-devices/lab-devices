/** Read-only derivations for the Bindings palette panel (design 2026-07-21). Pure so they are
 * node-env unit-testable; the panel component subscribes to the store and calls these. A binding
 * is written by operator_input/compute and read by any expression; type+unit comes from the
 * backend (this file never re-implements the lattice — analyze.ts:1-3). */
import type { BindingTypeJson } from '../types/doc'
import type { GroupDef } from './convert'
import { collectBindings } from './refs'
import { hole, scopeBindingNames } from './scopeRefs'
import { parseExpression, type Expr } from './expr/parse'
import { visitNodes, type BlockNode } from './tree'

export type WriterKind = 'operator_input' | 'compute'
export interface WriterRef {
  kind: WriterKind
  uid: string
  label: string | null
}
export interface ReaderRef {
  uid: string
  label: string | null
  field: string
}
export interface BindingRow {
  name: string
  type: BindingTypeJson | null
  writers: WriterRef[]
  readers: ReaderRef[]
  /** Set only when the name has NO writer block: a group binding param/local (no canvas block
   * to jump to). null otherwise. */
  decl: 'param' | 'local' | null
}

/** Which block(s) write each binding. operator_input.name / compute.into; a name may have
 * several compute writers, all kept in document order. */
export function collectBindingWriters(tree: BlockNode[]): Record<string, WriterRef[]> {
  const out: Record<string, WriterRef[]> = {}
  visitNodes(tree, (node) => {
    const name =
      node.kind === 'operator_input' ? node.name : node.kind === 'compute' ? node.into : null
    if (name === null || name === '') return
    ;(out[name] ??= []).push({ kind: node.kind as WriterKind, uid: node.uid, label: node.label })
  })
  return out
}

function collectBindingNodeNames(ast: Expr, out: Set<string>): void {
  switch (ast.t) {
    case 'binding':
      out.add(ast.name)
      return
    case 'unary':
      collectBindingNodeNames(ast.operand, out)
      return
    case 'binary':
      collectBindingNodeNames(ast.left, out)
      collectBindingNodeNames(ast.right, out)
      return
    default:
      return
  }
}

/** Which of `names` a single expression references. Bare names come from the parser; {hole}
 * names (group-body templates the tokenizer cannot lex) are matched as exact delimited
 * substrings. Only names in `names` are returned, so stream holes never masquerade as bindings. */
export function bindingReferences(text: string, names: ReadonlySet<string>): string[] {
  const found = new Set<string>()
  const res = parseExpression(text)
  if (res.ok) {
    const bare = new Set<string>()
    collectBindingNodeNames(res.ast, bare)
    for (const n of bare) if (names.has(n)) found.add(n)
  }
  for (const n of names) {
    if (n.startsWith('{') && n.endsWith('}') && text.includes(n)) found.add(n)
  }
  return [...found]
}

/** Every expression-bearing text field on a node that can reference a binding. gap_after /
 * start_offset are out of scope for v1. */
function exprFields(node: BlockNode): Array<[string, string]> {
  const out: Array<[string, string]> = []
  const push = (field: string, v: unknown): void => {
    if (typeof v === 'string' && v.trim() !== '') out.push([field, v])
  }
  switch (node.kind) {
    case 'compute':
    case 'record':
      push('value', node.value)
      break
    case 'branch':
      push('condition', node.condition)
      break
    case 'wait':
      push('duration', node.duration)
      break
    case 'loop':
      push('count', node.count)
      push('until', node.until)
      push('pace', node.pace)
      break
    case 'abort':
    case 'alarm':
      push('condition', node.condition)
      break
    case 'command':
    case 'measure':
      for (const [k, v] of Object.entries(node.params)) push(`params.${k}`, v)
      break
    default:
      break
  }
  return out
}

/** Which block(s) read each of `names`, across every expression-bearing field. */
export function collectBindingReaders(
  tree: BlockNode[],
  names: ReadonlySet<string>,
): Record<string, ReaderRef[]> {
  const out: Record<string, ReaderRef[]> = {}
  visitNodes(tree, (node) => {
    for (const [field, text] of exprFields(node)) {
      for (const name of bindingReferences(text, names)) {
        ;(out[name] ??= []).push({ uid: node.uid, label: node.label, field })
      }
    }
  })
  return out
}

/** {hole} name -> whether it is a binding PARAM or a binding LOCAL of the group. Tags
 * declared-but-unwritten bindings. Empty at the workflow scope. */
export function groupBindingDeclKinds(group: GroupDef | null): Record<string, 'param' | 'local'> {
  const out: Record<string, 'param' | 'local'> = {}
  if (group === null) return out
  for (const p of group.params) {
    if (p.kind !== 'role' && p.kind !== 'stream') out[hole(p.name)] = 'param'
  }
  for (const [name, l] of Object.entries(group.locals)) {
    if (l.kind === 'binding') out[hole(name)] = 'local'
  }
  return out
}

/** The active scope's bindings, merged for the panel — exactly the set the expression editor
 * offers: collectBindings(tree) then the group's binding params/locals ({holes}), in that order.
 * Type comes from `bindingTypes` by exact name (concrete root bindings match; {holes} do not, so
 * they show no type). `decl` is set only when a name has no writer block. */
export function bindingIndex(
  tree: BlockNode[],
  group: GroupDef | null,
  bindingTypes: Record<string, BindingTypeJson>,
): BindingRow[] {
  const writers = collectBindingWriters(tree)
  const declKind = groupBindingDeclKinds(group)
  const order: string[] = []
  const seen = new Set<string>()
  for (const n of [...collectBindings(tree), ...scopeBindingNames(group)]) {
    if (!seen.has(n)) {
      seen.add(n)
      order.push(n)
    }
  }
  const names = new Set(order)
  const readers = collectBindingReaders(tree, names)
  return order.map((name) => {
    const w = writers[name] ?? []
    return {
      name,
      type: bindingTypes[name] ?? null,
      writers: w,
      readers: readers[name] ?? [],
      decl: w.length === 0 ? (declKind[name] ?? null) : null,
    }
  })
}

/** How many expression-bearing fields in `tree` reference the bare name `name`. Used by the
 * constants delete-refusal check — constants live in the binding namespace and are cited inside
 * expression strings, not structural node fields (constants design §7). */
export function countBindingRefs(tree: BlockNode[], name: string): number {
  const names = new Set([name])
  let count = 0
  visitNodes(tree, (node) => {
    for (const [, text] of exprFields(node)) {
      if (bindingReferences(text, names).length > 0) count++
    }
  })
  return count
}
