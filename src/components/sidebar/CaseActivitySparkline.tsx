import { memo, useMemo } from 'react'
import { Line, LineChart, XAxis, YAxis } from 'recharts'
import type { CaseActivitySeries } from '../../lib/types'

const W = 168
const H = 28
const STROKE_NEUTRAL = '#94a3b8'
const STROKE_ALERT = '#ef4444'
const STROKE_WIDTH = 1.5

function mergeSegmentRuns(values: number[], threshold: number): { red: boolean; from: number; to: number }[] {
  const n = values.length
  if (n === 0) return []
  if (n === 1) return [{ red: values[0] > threshold, from: 0, to: 0 }]
  const edgeRed: boolean[] = []
  for (let k = 0; k < n - 1; k++) {
    edgeRed.push(Math.max(values[k], values[k + 1]) > threshold)
  }
  const runs: { red: boolean; from: number; to: number }[] = []
  let i = 0
  while (i < edgeRed.length) {
    const red = edgeRed[i]
    let j = i
    while (j + 1 < edgeRed.length && edgeRed[j + 1] === red) j++
    runs.push({ red, from: i, to: j + 1 })
    i = j + 1
  }
  return runs
}

export const CaseActivitySparkline = memo(function CaseActivitySparkline({
  series,
}: {
  series: CaseActivitySeries | undefined
}) {
  const { chartData, runs, yMin, yMax } = useMemo(() => {
    const values = series?.values?.length ? series.values : Array.from({ length: 24 }, () => 0)
    const threshold = series?.threshold ?? 0
    const runsIn = mergeSegmentRuns(values, threshold)
    const rows = values.map((v, t) => {
      const row: Record<string, number | null> = { t }
      runsIn.forEach((seg, si) => {
        row[`s${si}`] = t >= seg.from && t <= seg.to ? v : null
      })
      return row
    })
    const mn = Math.min(...values)
    const mx = Math.max(...values)
    const span = mx - mn
    const pad = span > 0 ? span * 0.1 : Math.max(Math.abs(mx), 1) * 0.05 || 1
    return {
      chartData: rows,
      runs: runsIn,
      yMin: mn - pad,
      yMax: mx + pad,
    }
  }, [series?.values, series?.threshold])

  return (
    <div className="pointer-events-none -mx-0.5 h-7 w-full max-w-[10.5rem] shrink-0 select-none self-stretch overflow-visible" aria-hidden>
      <LineChart width={W} height={H} data={chartData} margin={{ top: 3, right: 2, bottom: 2, left: 2 }}>
        <XAxis dataKey="t" type="number" domain={[0, 23]} hide />
        <YAxis hide domain={[yMin, yMax]} />
        {runs.map((seg, si) => (
          <Line
            key={si}
            type="linear"
            dataKey={`s${si}`}
            stroke={seg.red ? STROKE_ALERT : STROKE_NEUTRAL}
            strokeWidth={STROKE_WIDTH}
            dot={false}
            isAnimationActive={false}
            connectNulls={false}
          />
        ))}
      </LineChart>
    </div>
  )
})
