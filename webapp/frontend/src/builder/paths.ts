/** Resolve backend diagnostic paths (engine structural grammar + studio doc-level
 * grammar) onto editor tree uids. Unresolvable paths map to uid null and surface in the
 * problems panel only. */
import type { Diagnostic } from '../types/doc'
import { childSlots, type BlockNode } from './tree'

export interface ResolvedPath {
  uid: string | null
  role: string | null
  param: string | null
}

export interface MappedDiagnostic extends Diagnostic {
  uid: string | null
  role: string | null
  param: string | null
}

const NONE: ResolvedPath = { uid: null, role: null, param: null }

export function resolveDiagnosticPath(tree: BlockNode[], path: string): ResolvedPath {
  const roleMatch = /^roles\['(.+)'\]$/.exec(path)
  if (roleMatch) return { uid: null, role: roleMatch[1], param: null }

  const paramMatch = /^(.*?) param '([^']+)'/.exec(path)
  const structural = paramMatch ? paramMatch[1] : path
  const param = paramMatch ? paramMatch[2] : null

  if (!/^blocks\[\d+\](?:\.(?:children|body|then|else)\[\d+\])*$/.test(structural)) {
    return param ? { ...NONE, param } : NONE
  }
  const tokens = structural.match(/(?:^blocks|\.(?:children|body|then|else))\[\d+\]/g) ?? []
  let node: BlockNode | null = null
  for (const token of tokens) {
    const bracket = token.indexOf('[')
    const slot = token.startsWith('.') ? token.slice(1, bracket) : 'blocks'
    const index = Number(token.slice(bracket + 1, -1))
    let list: BlockNode[] | null
    if (slot === 'blocks') {
      list = tree
    } else if (node) {
      list = childSlots(node).find(([name]) => name === slot)?.[1] ?? null
    } else {
      list = null
    }
    if (!list || index < 0 || index >= list.length) return { ...NONE, param }
    node = list[index]
  }
  return { uid: node?.uid ?? null, role: null, param }
}

export function mapDiagnostics(tree: BlockNode[], diags: Diagnostic[]): MappedDiagnostic[] {
  return diags.map((d) => ({ ...d, ...resolveDiagnosticPath(tree, d.path) }))
}

export function diagnosticsByUid(diags: MappedDiagnostic[]): Map<string, MappedDiagnostic[]> {
  const out = new Map<string, MappedDiagnostic[]>()
  for (const d of diags) {
    if (!d.uid) continue
    const list = out.get(d.uid) ?? []
    list.push(d)
    out.set(d.uid, list)
  }
  return out
}
