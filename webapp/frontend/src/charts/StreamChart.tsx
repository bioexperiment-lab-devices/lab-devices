/** Shared uPlot wrapper for the live run chart and the record viewer (§9.4, §9.5).
 * x is elapsed seconds; one shared y axis; built-in cursor crosshair + legend
 * (legend click toggles a series). Colors: fixed-order categorical palette. */
import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { alignSeries, type NamedSeries } from './align'
import { formatElapsed } from '../records/format'

export const SERIES_COLORS = [
  '#2a78d6', '#1baf7a', '#eda100', '#008300', '#4a3aa7', '#e34948',
] as const

export interface ChartSeries extends NamedSeries {
  units: string | null
}

const AXIS = {
  stroke: '#898781',
  grid: { stroke: '#e1e0d9', width: 1 },
  ticks: { stroke: '#e1e0d9', width: 1 },
} as const

export function StreamChart(props: { series: ChartSeries[]; height?: number }) {
  const host = useRef<HTMLDivElement | null>(null)
  const plot = useRef<uPlot | null>(null)
  const height = props.height ?? 260
  const shape = props.series.map((s) => `${s.label}|${s.units ?? ''}`).join(',')

  useEffect(() => {
    const el = host.current
    if (el === null || props.series.length === 0) return
    const opts: uPlot.Options = {
      width: Math.max(el.clientWidth, 320),
      height,
      scales: { x: { time: false } },
      axes: [
        { ...AXIS, values: (_u, ticks) => ticks.map((t) => formatElapsed(t)) },
        { ...AXIS },
      ],
      series: [
        { label: 'elapsed', value: (_u, v) => (v === null ? '—' : formatElapsed(v)) },
        ...props.series.map((s, i) => ({
          label: s.units ? `${s.label} (${s.units})` : s.label,
          stroke: SERIES_COLORS[i % SERIES_COLORS.length],
          width: 2,
          points: { show: false },
        })),
      ],
    }
    const u = new uPlot(opts, alignSeries(props.series), el)
    plot.current = u
    const onResize = () => u.setSize({ width: Math.max(el.clientWidth, 320), height })
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      u.destroy()
      plot.current = null
    }
    // recreate only when the series set changes; data updates go through setData below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shape, height])

  useEffect(() => {
    plot.current?.setData(alignSeries(props.series))
  })

  if (props.series.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg border border-slate-200 bg-white text-xs text-slate-400">
        no samples yet
      </div>
    )
  }
  return <div ref={host} className="rounded-lg border border-slate-200 bg-white p-2" />
}
