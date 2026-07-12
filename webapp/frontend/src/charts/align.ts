/** Align N time-series onto one x-array for uPlot: x = sorted union of timestamps,
 * missing points are null (uPlot renders gaps). Pure and chart-lib-agnostic. */

export interface NamedSeries {
  label: string
  t: number[]
  v: number[]
}

export type UPlotData = [number[], ...(number | null)[][]]

export function alignSeries(series: NamedSeries[]): UPlotData {
  const xs = Array.from(new Set(series.flatMap((s) => s.t))).sort((a, b) => a - b)
  const index = new Map(xs.map((x, i) => [x, i]))
  const columns = series.map((s) => {
    const col: (number | null)[] = new Array<number | null>(xs.length).fill(null)
    for (let i = 0; i < s.t.length; i++) col[index.get(s.t[i]) as number] = s.v[i]
    return col
  })
  return [xs, ...columns]
}
