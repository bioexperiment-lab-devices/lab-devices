import type { LabDevice } from '../types/labs'

const TYPE_LABEL: Record<string, string> = {
  pump: 'Pumps',
  valve: 'Valves',
  densitometer: 'Densitometers',
}

const label = (type: string): string => TYPE_LABEL[type] ?? type

/** Left navigation: the device types present in the roster, grouped from `device.type`,
 * each with a count (design §4). */
export function TypeNav(props: {
  devices: LabDevice[]
  selected: string | null
  onSelect: (type: string) => void
}) {
  const counts = new Map<string, number>()
  for (const d of props.devices) counts.set(d.type, (counts.get(d.type) ?? 0) + 1)
  const types = [...counts.keys()]

  if (types.length === 0) {
    return <p className="text-xs text-caption">no devices in this lab</p>
  }

  return (
    <ul className="space-y-1">
      {types.map((type) => (
        <li key={type}>
          <button
            onClick={() => props.onSelect(type)}
            className={
              'flex w-full items-center justify-between rounded border px-2 py-1.5 text-left text-sm ' +
              (props.selected === type
                ? 'border-blue-500 bg-blue-50'
                : 'border-slate-200 bg-white hover:border-slate-300')
            }
          >
            <span className="min-w-0 truncate">{label(type)}</span>
            <span className="shrink-0 text-xs text-caption">{counts.get(type)}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}
