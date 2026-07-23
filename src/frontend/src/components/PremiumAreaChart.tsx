import { useId, useMemo } from 'react'
import {
  Area,
  AreaChart,
  Brush,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

export type SeriesDef = {
  key: string
  label: string
  color: string
  /** left = primary axis, right = secondary (e.g. network rates) */
  yAxisId?: 'left' | 'right'
  /** Tooltip / legend value formatter for this series */
  formatValue?: (v: number) => string
}

type Props = {
  data: Array<Record<string, string | number>>
  xKey?: string
  series: SeriesDef[]
  height?: number
  yDomain?: [number | 'auto', number | 'auto']
  yDomainRight?: [number | 'auto', number | 'auto']
  yFormatter?: (v: number) => string
  yFormatterRight?: (v: number) => string
  brush?: boolean
  brushStartIndex?: number
  brushEndIndex?: number
  onBrushChange?: (range: { startIndex?: number; endIndex?: number }) => void
}

export function PremiumAreaChart({
  data,
  xKey = 'time',
  series,
  height = 260,
  yDomain,
  yDomainRight,
  yFormatter,
  yFormatterRight,
  brush = false,
  brushStartIndex,
  brushEndIndex,
  onBrushChange,
}: Props) {
  const uid = useId().replace(/:/g, '')
  const gradients = useMemo(
    () =>
      series.map((s) => ({
        ...s,
        id: `grad-${uid}-${s.key}`,
        yAxisId: s.yAxisId || 'left',
      })),
    [series, uid],
  )
  const hasRight = gradients.some((s) => s.yAxisId === 'right')
  const seriesByKey = useMemo(() => Object.fromEntries(series.map((s) => [s.key, s])), [series])

  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 8, right: hasRight ? 12 : 8, left: 0, bottom: brush ? 8 : 0 }}>
          <defs>
            {gradients.map((s) => (
              <linearGradient key={s.id} id={s.id} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={s.color} stopOpacity={0.38} />
                <stop offset="70%" stopColor={s.color} stopOpacity={0.06} />
                <stop offset="100%" stopColor={s.color} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid strokeDasharray="3 8" vertical={false} />
          <XAxis
            dataKey={xKey}
            tick={{ fill: 'var(--la-muted)', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis
            yAxisId="left"
            domain={yDomain}
            tick={{ fill: 'var(--la-muted)', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={52}
            tickFormatter={yFormatter}
          />
          {hasRight ? (
            <YAxis
              yAxisId="right"
              orientation="right"
              domain={yDomainRight || ['auto', 'auto']}
              tick={{ fill: 'var(--la-muted)', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={72}
              tickFormatter={yFormatterRight}
            />
          ) : null}
          <Tooltip
            contentStyle={{
              background: 'var(--la-panel)',
              border: '1px solid var(--la-panel-border)',
              borderRadius: 12,
              backdropFilter: 'blur(12px)',
              boxShadow: 'var(--la-panel-shadow)',
              fontFamily: 'var(--la-sans)',
            }}
            labelStyle={{ color: 'var(--la-muted)', marginBottom: 4 }}
            itemStyle={{ fontFamily: 'var(--la-mono)', fontSize: 12 }}
            formatter={(value, name, item) => {
              const num = typeof value === 'number' ? value : Number(value)
              const key = String(item?.dataKey ?? '')
              const def = seriesByKey[key]
              if (def?.formatValue && Number.isFinite(num)) {
                return [def.formatValue(num), def.label || String(name)]
              }
              const axisFmt =
                def?.yAxisId === 'right' ? yFormatterRight : yFormatter
              if (axisFmt && Number.isFinite(num)) {
                return [axisFmt(num), def?.label || String(name)]
              }
              if (Number.isFinite(num)) {
                return [String(num), def?.label || String(name)]
              }
              return [String(value ?? '—'), String(name)]
            }}
          />
          {series.length > 1 ? (
            <Legend
              verticalAlign="top"
              align="right"
              iconType="circle"
              wrapperStyle={{ fontSize: 12, paddingBottom: 8 }}
            />
          ) : null}
          {gradients.map((s) => (
            <Area
              key={s.key}
              yAxisId={s.yAxisId}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              strokeWidth={2.2}
              fill={`url(#${s.id})`}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 0 }}
              isAnimationActive={false}
            />
          ))}
          {brush && data.length > 2 ? (
            <Brush
              dataKey={xKey}
              height={28}
              stroke="var(--la-accent)"
              travellerWidth={10}
              startIndex={brushStartIndex}
              endIndex={brushEndIndex}
              onChange={(r) => onBrushChange?.(r as { startIndex?: number; endIndex?: number })}
              tickFormatter={() => ''}
              fill="color-mix(in srgb, var(--la-accent) 8%, transparent)"
            />
          ) : null}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
