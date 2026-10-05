import type { ReactNode } from 'react'
import { Tooltip } from 'antd'
import { PHASE_COLORS, type PhaseColorKey } from '../../speedtest/format'

/** Big circular start button with breathing rings (speedtest.net style). */
export function GoButton({
  onClick,
  disabled,
  label = 'GO',
  hint,
}: {
  onClick: () => void
  disabled?: boolean
  label?: string
  hint?: string
}) {
  return (
    <div className="stg-go-wrap">
      <button type="button" className="stg-go" onClick={onClick} disabled={disabled} aria-label="Start speed test">
        <span className="stg-go-ring" />
        <span className="stg-go-ring stg-go-ring-2" />
        <span className="stg-go-ring stg-go-ring-3" />
        <span className="stg-go-face">{label}</span>
      </button>
      {hint ? <div className="stg-go-hint">{hint}</div> : null}
    </div>
  )
}

export function MetricTile({
  icon,
  label,
  value,
  unit,
  sub,
  color,
  active,
  done,
  tooltip,
}: {
  icon: ReactNode
  label: string
  value: ReactNode
  unit?: string
  sub?: ReactNode
  color: string
  active?: boolean
  done?: boolean
  tooltip?: string
}) {
  const tile = (
    <div
      className={`stg-tile${active ? ' is-active' : ''}${done ? ' is-done' : ''}`}
      style={{ ['--tile-color' as string]: color }}
    >
      <div className="stg-tile-head">
        <span className="stg-tile-icon">{icon}</span>
        <span className="stg-tile-label">{label}</span>
      </div>
      <div className="stg-tile-value">
        <span>{value}</span>
        {unit ? <small>{unit}</small> : null}
      </div>
      {sub ? <div className="stg-tile-sub">{sub}</div> : null}
    </div>
  )
  return tooltip ? <Tooltip title={tooltip}>{tile}</Tooltip> : tile
}

export function PhaseStepper({ steps, current }: { steps: Array<{ key: string; label: string }>; current: string }) {
  const idx = steps.findIndex((s) => s.key === current)
  return (
    <div className="stg-steps">
      {steps.map((s, i) => (
        <div key={s.key} className={`stg-step${i < idx ? ' is-done' : ''}${i === idx ? ' is-current' : ''}`}>
          <span className="stg-step-dot" />
          <span>{s.label}</span>
        </div>
      ))}
    </div>
  )
}

export function ProgressBar({ value, phase }: { value: number; phase: PhaseColorKey }) {
  const c = PHASE_COLORS[phase]
  return (
    <div className="stg-progress">
      <div
        className="stg-progress-bar"
        style={{ width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`, background: `linear-gradient(90deg, ${c.from}, ${c.to})` }}
      />
    </div>
  )
}

export function GradeBadge({ grade, color, title }: { grade: string; color: string; title?: string }) {
  return (
    <Tooltip title={title}>
      <span className="stg-grade" style={{ color, borderColor: color, background: `color-mix(in srgb, ${color} 12%, transparent)` }}>
        {grade}
      </span>
    </Tooltip>
  )
}

/** Horizontal per-stream bars (iperf3 parallel streams). */
export function StreamBars({ streams, max, color }: { streams: Array<{ id: string; bps: number; retr?: number | null }>; max: number; color: string }) {
  if (!streams.length) return null
  return (
    <div className="stg-streams">
      {streams.map((s) => (
        <div key={s.id} className="stg-stream">
          <span className="mono stg-stream-id">#{s.id}</span>
          <div className="stg-stream-track">
            <div
              className="stg-stream-fill"
              style={{ width: `${Math.min(100, (s.bps / Math.max(1, max)) * 100)}%`, background: color }}
            />
          </div>
          <span className="mono stg-stream-val">{(s.bps / 1e6).toFixed(s.bps >= 1e8 ? 0 : 1)} Mbps</span>
        </div>
      ))}
    </div>
  )
}
