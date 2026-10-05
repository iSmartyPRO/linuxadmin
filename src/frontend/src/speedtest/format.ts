export type RateUnit = 'mbps' | 'mbs'

const UNIT_KEY = 'lnxadmin_speed_unit'

export function loadUnit(): RateUnit {
  return localStorage.getItem(UNIT_KEY) === 'mbs' ? 'mbs' : 'mbps'
}

export function saveUnit(u: RateUnit) {
  localStorage.setItem(UNIT_KEY, u)
}

/** bits/s → number in the chosen display unit (Mbit/s or MB/s). */
export function toUnit(bps: number | null | undefined, unit: RateUnit): number {
  if (bps == null || !Number.isFinite(bps)) return 0
  return unit === 'mbs' ? bps / 8 / 1e6 : bps / 1e6
}

export function unitLabel(unit: RateUnit): string {
  return unit === 'mbs' ? 'MB/s' : 'Mbps'
}

/** Speedtest-style number: 3 significant digits, no trailing noise. */
export function fmtSpeedNum(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (v >= 1000) return Math.round(v).toLocaleString('en-US')
  if (v >= 100) return v.toFixed(0)
  if (v >= 10) return v.toFixed(1)
  return v.toFixed(2)
}

export function fmtSpeed(bps: number | null | undefined, unit: RateUnit): string {
  if (bps == null || !Number.isFinite(bps)) return '—'
  return `${fmtSpeedNum(toUnit(bps, unit))} ${unitLabel(unit)}`
}

/** Auto-scaled bit rate (Kbps → Gbps) for compact labels. */
export function fmtBitsAuto(bps: number | null | undefined): string {
  if (bps == null || !Number.isFinite(bps)) return '—'
  if (bps >= 1e9) return `${(bps / 1e9).toFixed(bps >= 1e10 ? 1 : 2)} Gbps`
  if (bps >= 1e6) return `${fmtSpeedNum(bps / 1e6)} Mbps`
  if (bps >= 1e3) return `${fmtSpeedNum(bps / 1e3)} Kbps`
  return `${Math.round(bps)} bps`
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return '—'
  if (ms >= 100) return ms.toFixed(0)
  if (ms >= 10) return ms.toFixed(1)
  return ms.toFixed(2)
}

export function fmtBytesShort(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`
}

/**
 * Bufferbloat grade from the latency increase under load (similar to the
 * Waveform / DSLReports scale).
 */
export function bloatGrade(idleMs?: number | null, loadedMs?: number | null): { grade: string; color: string } | null {
  if (idleMs == null || loadedMs == null) return null
  const d = Math.max(0, loadedMs - idleMs)
  if (d < 5) return { grade: 'A+', color: '#10b981' }
  if (d < 30) return { grade: 'A', color: '#14b8a6' }
  if (d < 60) return { grade: 'B', color: '#84cc16' }
  if (d < 200) return { grade: 'C', color: '#f59e0b' }
  if (d < 400) return { grade: 'D', color: '#f97316' }
  return { grade: 'F', color: '#ef4444' }
}

/** Gauge scales (Mbps) — piecewise, speedtest.net style. */
export const GAUGE_SCALES: number[][] = [
  [0, 1, 5, 10, 20, 30, 50, 75, 100],
  [0, 5, 10, 50, 100, 250, 500, 750, 1000],
  [0, 100, 500, 1000, 2500, 5000, 7500, 10000],
  [0, 1000, 5000, 10000, 25000, 50000, 75000, 100000],
]

export function pickScale(maxMbps: number): number[] {
  for (const s of GAUGE_SCALES) {
    if (maxMbps <= s[s.length - 1] * 0.92) return s
  }
  return GAUGE_SCALES[GAUGE_SCALES.length - 1]
}

export const PHASE_COLORS = {
  download: { from: '#14b8a6', to: '#22d3ee', solid: '#14b8a6' },
  upload: { from: '#8b5cf6', to: '#ec4899', solid: '#a855f7' },
  ping: { from: '#f59e0b', to: '#fbbf24', solid: '#f59e0b' },
  idle: { from: '#14b8a6', to: '#22d3ee', solid: '#14b8a6' },
} as const

export type PhaseColorKey = keyof typeof PHASE_COLORS
