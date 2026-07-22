/** Shared uPlot wrapper for the live run chart and the record viewer (§9.4, §9.5).
 * x is elapsed seconds; one shared y axis; built-in cursor crosshair + legend
 * (legend click toggles a series). Colors: fixed-order categorical palette. */
import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { alignSeries, type NamedSeries } from './align'
import { dedupeConsecutive, formatElapsed } from '../records/format'
import type { EffectiveTheme } from '../stores/themeSetting'
import { useThemeStore } from '../stores/themeStore'

/** Same hue order both themes; dark steps are brightened to read on the dark card.
 * uPlot takes concrete color strings at construction time, so the component rebuilds
 * on theme change (the `theme` dep below) rather than trying to restyle in place.
 * The one sanctioned hex outside index.css's palette remap — see CLAUDE.md Colour. */
export const CHART_THEMES: Record<
  EffectiveTheme,
  { axis: string; grid: string; series: readonly string[] }
> = {
  light: {
    axis: '#898781',
    grid: '#e1e0d9',
    series: ['#2a78d6', '#1baf7a', '#eda100', '#008300', '#4a3aa7', '#e34948'],
  },
  dark: {
    axis: '#9b99a1',
    grid: '#33333b',
    series: ['#5aa2f0', '#3ec98f', '#f0b429', '#59c159', '#9184e8', '#f0716a'],
  },
}

export interface ChartSeries extends NamedSeries {
  units: string | null
}

export function StreamChart(props: { series: ChartSeries[]; height?: number }) {
  const host = useRef<HTMLDivElement | null>(null)
  const plot = useRef<uPlot | null>(null)
  const height = props.height ?? 260
  const theme = useThemeStore((s) => s.effective)
  const shape = props.series.map((s) => `${s.label}|${s.units ?? ''}`).join(',')

  useEffect(() => {
    const el = host.current
    if (el === null || props.series.length === 0) return
    const { axis: axisStroke, grid, series: palette } = CHART_THEMES[theme]
    const axis = {
      stroke: axisStroke,
      grid: { stroke: grid, width: 1 },
      ticks: { stroke: grid, width: 1 },
    }
    const opts: uPlot.Options = {
      width: Math.max(el.clientWidth, 320),
      height,
      scales: { x: { time: false } },
      axes: [
        { ...axis, values: (_u, ticks) => dedupeConsecutive(ticks.map((t) => formatElapsed(t))) },
        { ...axis },
      ],
      series: [
        { label: 'elapsed', value: (_u, v) => (v === null ? '—' : formatElapsed(v)) },
        ...props.series.map((s, i) => ({
          label: s.units ? `${s.label} (${s.units})` : s.label,
          stroke: palette[i % palette.length],
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
    // recreate only when the series set or theme changes; data updates go through setData below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shape, height, theme])

  useEffect(() => {
    plot.current?.setData(alignSeries(props.series))
  })

  if (props.series.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg border border-slate-200 bg-white text-xs text-hint">
        no samples yet
      </div>
    )
  }
  return <div ref={host} className="rounded-lg border border-slate-200 bg-white p-2" />
}
