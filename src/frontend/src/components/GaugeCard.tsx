import { pctColor } from '../utils/format'
import { Panel } from './Panel'

type Props = {
  title: string
  percent?: number | null
  subtitle?: string
}

export function GaugeCard({ title, percent, subtitle }: Props) {
  const value = Math.min(100, Math.max(0, percent ?? 0))
  const color = pctColor(value)
  const r = 52
  const c = 2 * Math.PI * r
  const dash = (value / 100) * c
  const gradId = `gauge-${title.replace(/[^a-zA-Z0-9_-]/g, '')}`

  return (
    <Panel
      padded={false}
      style={{ height: '100%' }}
      bodyStyle={{ padding: '18px 16px 16px', textAlign: 'center' }}
    >
      <div className="la-panel-title" style={{ marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ position: 'relative', width: 140, height: 140, margin: '0 auto' }}>
        <svg width="140" height="140" viewBox="0 0 140 140">
          <defs>
            <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor={color} stopOpacity="1" />
              <stop offset="100%" stopColor={color} stopOpacity="0.55" />
            </linearGradient>
          </defs>
          <circle
            cx="70"
            cy="70"
            r={r}
            fill="none"
            stroke="color-mix(in srgb, var(--la-muted) 18%, transparent)"
            strokeWidth="10"
          />
          <circle
            cx="70"
            cy="70"
            r={r}
            fill="none"
            stroke={`url(#${gradId})`}
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={`${dash} ${c - dash}`}
            transform="rotate(-90 70 70)"
            style={{ transition: 'stroke-dasharray 0.6s ease' }}
          />
        </svg>
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'grid',
            placeItems: 'center',
          }}
        >
          <div className="mono" style={{ fontSize: 26, fontWeight: 600, letterSpacing: '-0.04em' }}>
            {percent == null ? '—' : value.toFixed(1)}
            {percent == null ? null : (
              <span style={{ fontSize: 12, color: 'var(--la-muted)', marginLeft: 2 }}>%</span>
            )}
          </div>
        </div>
      </div>
      {subtitle ? (
        <div className="mono" style={{ marginTop: 4, fontSize: 12, color: 'var(--la-muted)' }}>
          {subtitle}
        </div>
      ) : null}
    </Panel>
  )
}
