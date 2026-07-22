import { useState } from 'react'
import { X } from 'lucide-react'
import { useDocStore } from '../stores/docStore'
import { ExpressionEditor } from './ExpressionEditor'
import { controlClass, inlineButtonClass } from '../ui/controls'
import { IconButton } from '../ui/IconButton'
import type { ParamValue } from '../types/doc'

function coerceConstantValue(text: string): ParamValue {
  const s = text.trim()
  if (/^-?\d+$/.test(s)) return Number(s)
  if (/^-?\d+\.\d+$/.test(s)) return Number(s)
  if (s === 'true') return true
  if (s === 'false') return false
  return s
}

const valueText = (v: ParamValue): string =>
  typeof v === 'number' || typeof v === 'boolean' ? String(v) : v

function TypeBadge({ name }: { name: string }) {
  const t = useDocStore((s) => s.bindingTypes[name])
  if (!t) return null
  const showUnit = t.unit !== 'unitless' && (t.base === 'int' || t.base === 'number')
  return (
    <span
      className="shrink-0 rounded bg-slate-100 px-1 text-xs text-caption"
      title={showUnit ? `${t.base} in ${t.unit}` : t.base}
    >
      {t.base}
      {showUnit && <span className="text-hint">{`<${t.unit}>`}</span>}
    </span>
  )
}

/** Workflow-global, write-once constants (constants design 2026-07-22). Name is a fixed
 * label — there is no rename action in docStore (no ref-rewrite cascade to thread), so this
 * panel never offers one. Value is a `ParamValue`: coerced on commit from the editor's raw
 * text (bare int/decimal → number, true/false → bool, else left as a string/expression) and
 * rendered back via `valueText` for numbers/bools. */
export function ConstantsPanel() {
  const constants = useDocStore((s) => s.constants)
  const addConstant = useDocStore((s) => s.addConstant)
  const setConstantValue = useDocStore((s) => s.setConstantValue)
  const setConstantUnit = useDocStore((s) => s.setConstantUnit)
  const removeConstant = useDocStore((s) => s.removeConstant)
  const [newName, setNewName] = useState('')
  const [newValue, setNewValue] = useState('')
  const [newUnit, setNewUnit] = useState('')
  const [error, setError] = useState<string | null>(null)

  const add = (): void => {
    if (!newName.trim()) return
    const nm = newName.trim()
    const err = addConstant(nm, coerceConstantValue(newValue))
    setError(err)
    if (!err) {
      if (newUnit.trim()) setConstantUnit(nm, newUnit.trim())
      setNewName('')
      setNewValue('')
      setNewUnit('')
    }
  }

  return (
    <div className="space-y-1">
      {Object.keys(constants).length === 0 && (
        <p className="px-1 text-xs text-hint">
          No constants yet — declare a reusable value below.
        </p>
      )}
      <ul className="space-y-1">
        {/* Stacked layout (#8/#9): the 256px palette can't fit name + expression + unit + badge +
            delete on one row without starving the expression editor to one character. Name row,
            then a full-width editor, then unit + type badge — the same shape as the create form. */}
        {Object.entries(constants).map(([name, decl]) => (
          <li key={name} className="space-y-1 border-b border-slate-200 pb-1 text-sm">
            <div className="flex items-center gap-1">
              <span className="min-w-0 flex-1 truncate font-mono text-caption" title={name}>
                {name}
              </span>
              <IconButton
                icon={X}
                label="Delete constant"
                destructive
                onClick={() => setError(removeConstant(name))}
              />
            </div>
            <ExpressionEditor
              value={valueText(decl.value)}
              expected="any"
              placeholder="value or expression"
              onCommit={(t) => setConstantValue(name, coerceConstantValue(t))}
            />
            <div className="flex items-center gap-1">
              <input
                value={decl.as ?? ''}
                placeholder="unit"
                onChange={(e) => setConstantUnit(name, e.target.value || null)}
                className={controlClass({ width: 'w-20' })}
              />
              <TypeBadge name={name} />
            </div>
          </li>
        ))}
      </ul>
      {/* Create form mirrors the stacked edit rows: name + Add, a full-width expression editor for
          the value, then a unit field (#8). ExpressionEditor commits on blur/Enter into newValue;
          pressing Add (or Enter in the name/unit input) creates the constant. */}
      <div className="space-y-1">
        <div className="flex items-center gap-1">
          <input
            value={newName}
            placeholder="name"
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && add()}
            className={controlClass({ mono: true, width: 'w-full' })}
          />
          <button onClick={add} className={inlineButtonClass()}>
            Add
          </button>
        </div>
        <ExpressionEditor
          value={newValue}
          expected="any"
          placeholder="value or expression"
          onCommit={(t) => setNewValue(t)}
        />
        <input
          value={newUnit}
          placeholder="unit"
          onChange={(e) => setNewUnit(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          className={controlClass({ width: 'w-20' })}
        />
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
