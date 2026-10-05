import { useEffect, useId, useRef, useState } from 'react'
import { fmtSpeedNum, PHASE_COLORS, type PhaseColorKey } from '../../speedtest/format'

type Props = {
  /** Target value in display units (Mbps or MB/s) */
  value: number | null
  scale: number[]
  unit: string
  phase: PhaseColorKey
  label?: string
  sublabel?: string
  active?: boolean
  size?: number
}

const START = 135 // degrees, 0 = 3 o'clock, clockwise
const SWEEP = 270

function valueToFrac(v: number, scale: number[]): number {
  if (v <= scale[0]) return 0
  const segs = scale.length - 1
  for (let i = 0; i < segs; i += 1) {
    const a = scale[i]
    const b = scale[i + 1]
    if (v <= b) return (i + (v - a) / (b - a)) / segs
  }
  return 1
}

function polar(cx: number, cy: number, r: number, deg: number) {
  const rad = (deg * Math.PI) / 180
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) }
}

function arcPath(cx: number, cy: number, r: number, from: number, to: number) {
  const a = polar(cx, cy, r, from)
  const b = polar(cx, cy, r, to)
  const large = to - from > 180 ? 1 : 0
  return `M ${a.x} ${a.y} A ${r} ${r} 0 ${large} 1 ${b.x} ${b.y}`
}

/** Smoothly animates toward the target value (critically damped follow). */
function useAnimatedValue(target: number) {
  const [v, setV] = useState(target)
  const cur = useRef(target)
  const tgt = useRef(target)
  tgt.current = target
  useEffect(() => {
    let raf = 0
    let last = performance.now()
    const step = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000)
      last = now
      const diff = tgt.current - cur.current
      if (Math.abs(diff) > Math.max(0.001, Math.abs(tgt.current) * 0.0005)) {
        cur.current += diff * (1 - Math.exp(-dt * 7))
        setV(cur.current)
      }
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [])
  return v
}

export function SpeedGauge({ value, scale, unit, phase, label, sublabel, active, size = 420 }: Props) {
  const uid = useId().replace(/:/g, '')
  const shown = useAnimatedValue(value ?? 0)
  const frac = valueToFrac(Math.max(0, shown), scale)
  const colors = PHASE_COLORS[phase]
  const cx = 200
  const cy = 200
  const r = 158
  const angle = START + frac * SWEEP
  const needle = polar(cx, cy, r - 30, angle)
  const left = polar(cx, cy, 9, angle - 90)
  const right = polar(cx, cy, 9, angle + 90)

  return (
    <div className={`stg-gauge${active ? ' is-active' : ''}`} style={{ width: '100%', maxWidth: size }}>
      <svg viewBox="0 0 400 360" width="100%" role="img" aria-label={`${fmtSpeedNum(value ?? 0)} ${unit}`}>
        <defs>
          <linearGradient id={`g-${uid}`} x1="0%" y1="100%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={colors.from} />
            <stop offset="100%" stopColor={colors.to} />
          </linearGradient>
          <radialGradient id={`hub-${uid}`} cx="50%" cy="40%" r="60%">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.95" />
            <stop offset="100%" stopColor={colors.to} stopOpacity="0.9" />
          </radialGradient>
          <linearGradient id={`needle-${uid}`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor={colors.from} stopOpacity="0.15" />
            <stop offset="100%" stopColor={colors.to} />
          </linearGradient>
          <filter id={`glow-${uid}`} x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="7" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Outer hairline ring */}
        <path d={arcPath(cx, cy, r + 22, START, START + SWEEP)} className="stg-hairline" fill="none" />
        {/* Track */}
        <path d={arcPath(cx, cy, r, START, START + SWEEP)} className="stg-track" fill="none" strokeWidth={20} strokeLinecap="round" />
        {/* Active arc */}
        {frac > 0.001 ? (
          <path
            d={arcPath(cx, cy, r, START, START + Math.max(0.5, frac * SWEEP))}
            fill="none"
            stroke={`url(#g-${uid})`}
            strokeWidth={20}
            strokeLinecap="round"
            filter={`url(#glow-${uid})`}
          />
        ) : null}

        {/* Ticks + labels */}
        {scale.map((mark, i) => {
          const a = START + (i / (scale.length - 1)) * SWEEP
          const p1 = polar(cx, cy, r - 18, a)
          const p2 = polar(cx, cy, r - 26, a)
          const lp = polar(cx, cy, r - 46, a)
          const reached = frac >= i / (scale.length - 1) - 1e-6 && frac > 0
          return (
            <g key={mark}>
              <line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} className="stg-tick" />
              <text
                x={lp.x}
                y={lp.y}
                textAnchor="middle"
                dominantBaseline="middle"
                className={`stg-mark${reached ? ' is-reached' : ''}`}
              >
                {mark >= 1000 ? `${mark / 1000}k` : mark}
              </text>
            </g>
          )
        })}
        {Array.from({ length: (scale.length - 1) * 4 + 1 }).map((_, i) => {
          if (i % 4 === 0) return null
          const a = START + (i / ((scale.length - 1) * 4)) * SWEEP
          const p1 = polar(cx, cy, r - 18, a)
          const p2 = polar(cx, cy, r - 22, a)
          return <line key={`m${i}`} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} className="stg-tick-minor" />
        })}

        {/* Needle */}
        <polygon
          points={`${left.x},${left.y} ${needle.x},${needle.y} ${right.x},${right.y}`}
          fill={`url(#needle-${uid})`}
          className="stg-needle"
        />
        <circle cx={cx} cy={cy} r={15} fill={`url(#hub-${uid})`} className="stg-hub" />
        <circle cx={cx} cy={cy} r={5} className="stg-hub-dot" />

        {/* Readout */}
        <text x={cx} y={300} textAnchor="middle" className="stg-value">
          {value == null ? '—' : fmtSpeedNum(Math.max(0, shown))}
        </text>
        <text x={cx} y={330} textAnchor="middle" className="stg-unit">
          {unit}
        </text>
      </svg>
      {label || sublabel ? (
        <div className="stg-caption">
          {label ? (
            <span className="stg-caption-label" style={{ color: colors.solid }}>
              {label}
            </span>
          ) : null}
          {sublabel ? <span className="stg-caption-sub">{sublabel}</span> : null}
        </div>
      ) : null}
    </div>
  )
}
