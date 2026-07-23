/**
 * Parse fail2ban-style duration to seconds.
 * Accepts: 600, -1, 10m, 1h, 2d, 1w, 1.5h
 */
export function parseFail2banDuration(raw: string | number | null | undefined): number | null {
  if (raw == null || raw === '') return null
  const s = String(raw).trim().replace(/\s+/g, '')
  if (!s) return null
  if (/^-?\d+$/.test(s)) return Number(s)
  const m = s.match(/^(-?\d+(?:\.\d+)?)([smhdwSMHDW])?$/)
  if (!m) return null
  const n = Number(m[1])
  if (!Number.isFinite(n)) return null
  if (n < 0) return -1
  const u = (m[2] || 's').toLowerCase()
  const mult: Record<string, number> = {
    s: 1,
    m: 60,
    h: 3600,
    d: 86400,
    w: 604800,
  }
  return Math.round(n * (mult[u] ?? 1))
}

function pluralEn(n: number, one: string, many: string): string {
  return Math.floor(Math.abs(n)) === 1 ? one : many
}

function fmtNum(n: number): string {
  return n.toLocaleString('en-US', { maximumFractionDigits: n >= 10 ? 1 : 2 })
}

/**
 * Live calculator hint under bantime/findtime fields.
 * 600 → "10 minutes · 0.17 hours · 600 sec"
 * 86400 → "1 day · 24 hours · 1,440 minutes · 86,400 sec"
 */
export function formatFail2banDurationHint(
  raw: string | number | null | undefined,
): string | null {
  const sec = parseFail2banDuration(raw)
  if (sec == null) return null
  if (sec < 0) return 'permanent — no expiration'

  const chunks: string[] = []

  // Canonical breakdown (days / hours / minutes / seconds)
  let rem = sec
  const days = Math.floor(rem / 86400)
  rem %= 86400
  const hours = Math.floor(rem / 3600)
  rem %= 3600
  const minutes = Math.floor(rem / 60)
  const seconds = rem % 60
  const broken: string[] = []
  if (days) broken.push(`${days} ${pluralEn(days, 'day', 'days')}`)
  if (hours) broken.push(`${hours} ${pluralEn(hours, 'hour', 'hours')}`)
  if (minutes) broken.push(`${minutes} ${pluralEn(minutes, 'minute', 'minutes')}`)
  if (seconds || !broken.length) {
    broken.push(`${seconds} ${pluralEn(seconds, 'second', 'seconds')}`)
  }
  chunks.push(broken.join(' '))

  // Totals in larger units (skip if already identical to breakdown)
  const unitWord = (n: number, one: string, many: string) =>
    Number.isInteger(n) ? pluralEn(n, one, many) : many

  const totals: string[] = []
  if (sec >= 86400) {
    const d = sec / 86400
    if (!(days === d && !hours && !minutes && !seconds)) {
      totals.push(`${fmtNum(d)} ${unitWord(d, 'day', 'days')}`)
    }
  }
  if (sec >= 3600) {
    const h = sec / 3600
    if (!(days === 0 && hours === h && !minutes && !seconds)) {
      totals.push(`${fmtNum(h)} ${unitWord(h, 'hour', 'hours')}`)
    }
  }
  if (sec >= 60) {
    const m = sec / 60
    if (!(days === 0 && hours === 0 && minutes === m && !seconds)) {
      totals.push(`${fmtNum(m)} ${unitWord(m, 'minute', 'minutes')}`)
    }
  }
  // Skip redundant "30 sec" when breakdown is already only seconds
  if (!(days === 0 && hours === 0 && minutes === 0)) {
    totals.push(`${sec.toLocaleString('en-US')} sec`)
  }

  return [...chunks, ...totals].join('  ·  ')
}
