/** Binary byte units (1024-based), common for disk/RAM/network UI. */
const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'] as const
const BIT_RATE_UNITS = ['bit/s', 'Kbit/s', 'Mbit/s', 'Gbit/s', 'Tbit/s'] as const

function pickScaled(abs: number, base: number, units: readonly string[]) {
  let v = abs
  let i = 0
  while (v >= base && i < units.length - 1) {
    v /= base
    i += 1
  }
  return { v, unit: units[i], index: i }
}

function formatScaled(n: number, base: number, units: readonly string[], digits?: number): string {
  const sign = n < 0 ? '-' : ''
  const { v, unit, index } = pickScaled(Math.abs(n), base, units)
  const d =
    digits != null
      ? digits
      : v >= 100 || index === 0
        ? 0
        : v >= 10
          ? 1
          : 2
  const num = d === 0 ? Math.round(v).toString() : v.toFixed(d)
  return `${sign}${num} ${unit}`
}

/** Bytes: 1.5 KB, 12 MB, … */
export function formatBytes(n?: number | null, digits?: number): string {
  if (n == null || Number.isNaN(n)) return '—'
  return formatScaled(n, 1024, BYTE_UNITS, digits)
}

/** Byte throughput: B/s, KB/s, MB/s, … (input: bytes per second). */
export function formatRate(n?: number | null, digits?: number): string {
  if (n == null || Number.isNaN(n)) return '—'
  const s = formatBytes(n, digits)
  if (s === '—') return s
  // "12.5 MB" → "12.5 MB/s"; "512 B" → "512 B/s"
  return `${s}/s`
}

/**
 * Bit throughput from bytes/s: bit/s, Kbit/s, Mbit/s, …
 * Useful alongside byte rates for network (1 MB/s ≈ 8 Mbit/s).
 */
export function formatBitRate(bytesPerSec?: number | null, digits?: number): string {
  if (bytesPerSec == null || Number.isNaN(bytesPerSec)) return '—'
  return formatScaled(bytesPerSec * 8, 1000, BIT_RATE_UNITS, digits)
}

/** Tooltip-friendly: "1.2 MB/s · 9.8 Mbit/s" */
export function formatNetworkRate(bytesPerSec?: number | null): string {
  if (bytesPerSec == null || Number.isNaN(bytesPerSec)) return '—'
  return `${formatRate(bytesPerSec)} · ${formatBitRate(bytesPerSec)}`
}

/** Compact axis tick for rates (bytes/s). */
export function formatRateTick(n?: number | null): string {
  if (n == null || Number.isNaN(n)) return ''
  if (Math.abs(n) < 0.5) return '0'
  return formatRate(n, Math.abs(n) >= 1024 * 1024 ? 1 : 0)
}

export function formatUptime(seconds?: number | null): string {
  if (seconds == null) return '—'
  const s = Math.floor(seconds)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  const parts = []
  if (d) parts.push(`${d}d`)
  if (h || d) parts.push(`${h}h`)
  parts.push(`${m}m`)
  return parts.join(' ')
}

/** Human duration for sessions: `45 s`, `12 m 3 s`, `2 h 15 m`, `1d 3h`. */
export function formatDuration(sec?: number | null): string {
  if (sec == null || !Number.isFinite(sec)) return '—'
  const s = Math.max(0, Math.floor(sec))
  if (s < 60) return `${s} s`
  if (s < 3600) return `${Math.floor(s / 60)} m ${s % 60} s`
  if (s < 86400) {
    const h = Math.floor(s / 3600)
    const m = Math.floor((s % 3600) / 60)
    return `${h} h ${m} m`
  }
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  return `${d}d ${h}h`
}

export function pctColor(pct?: number | null): string {
  if (pct == null) return '#94a3b8'
  if (pct >= 90) return '#e11d48'
  if (pct >= 75) return '#d97706'
  return '#0d9488'
}
