import type { ExperimentDocJson } from '../types/doc'
import { DocConvertError, docToTree } from '../builder/convert'
import { blockSummary } from '../builder/summary'
import type { BlockNode } from '../builder/tree'
import { KindIcon } from '../ui/icons'

function NodeCard(props: { node: BlockNode }) {
  const { node } = props
  const timing = [
    node.gapAfter !== null ? `gap ${node.gapAfter}` : null,
    node.startOffset !== null ? `offset ${node.startOffset}` : null,
  ].filter(Boolean).join(' · ')
  return (
    <div className="rounded border border-slate-200 bg-white px-2 py-1">
      <p className="flex items-center gap-1 text-xs">
        <KindIcon kind={node.kind} />
        <span>
          {blockSummary(node)}
          {node.label !== null && <span className="ml-1 text-caption">“{node.label}”</span>}
          {timing && <span className="ml-1 text-[10px] text-caption">{timing}</span>}
        </span>
      </p>
      {node.kind === 'serial' && <NodeList items={node.children} />}
      {node.kind === 'parallel' && (
        <div className="mt-1 flex gap-2 overflow-x-auto">
          {node.children.map((lane) => (
            <div key={lane.uid} className="min-w-40 flex-1 rounded border border-dashed border-slate-200 p-1">
              <NodeCard node={lane} />
            </div>
          ))}
        </div>
      )}
      {node.kind === 'loop' && <NodeList items={node.body} />}
      {node.kind === 'branch' && (
        <div className="mt-1 flex gap-2 overflow-x-auto">
          <div className="min-w-40 flex-1 rounded border border-dashed border-slate-200 p-1">
            <p className="text-[10px] text-caption">then</p>
            <NodeList items={node.then} />
          </div>
          {node.else !== null && (
            <div className="min-w-40 flex-1 rounded border border-dashed border-slate-200 p-1">
              <p className="text-[10px] text-caption">else</p>
              <NodeList items={node.else} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function NodeList(props: { items: BlockNode[] }) {
  if (props.items.length === 0) return <p className="mt-1 text-[10px] text-hint">empty</p>
  return (
    <div className="mt-1 space-y-1 pl-2">
      {props.items.map((n) => (
        <NodeCard key={n.uid} node={n} />
      ))}
    </div>
  )
}

export function WorkflowSnapshot(props: { doc: ExperimentDocJson | null }) {
  if (props.doc === null) {
    return <p className="text-xs text-hint">no workflow snapshot in this record</p>
  }
  try {
    const { tree } = docToTree(props.doc)
    return (
      <div className="space-y-1">
        {tree.map((n) => (
          <NodeCard key={n.uid} node={n} />
        ))}
      </div>
    )
  } catch (e) {
    const msg = e instanceof DocConvertError ? e.message : String(e)
    return <p className="text-xs text-amber-700">cannot render the snapshot: {msg}</p>
  }
}
