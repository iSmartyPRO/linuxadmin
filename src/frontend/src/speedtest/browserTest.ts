/**
 * Browser ↔ panel speed test engine (LibreSpeed / speedtest.net approach):
 * parallel HTTP streams for a fixed time, live sampling, slow-start grace
 * period excluded from the final figure, latency measured idle and under load.
 */
import { api } from '../api/client'

export type BrowserPhase = 'idle' | 'connect' | 'ping' | 'download' | 'upload' | 'done' | 'error' | 'aborted'

export type BrowserTestOptions = {
  streams: number
  duration: number // seconds per direction
  pingCount: number
  download: boolean
  upload: boolean
}

export const DEFAULT_BROWSER_OPTIONS: BrowserTestOptions = {
  streams: 6,
  duration: 10,
  pingCount: 20,
  download: true,
  upload: true,
}

export type BrowserUpdate = {
  phase: BrowserPhase
  /** Smoothed instantaneous rate, bits/s */
  bps?: number
  /** Running average after the grace window, bits/s */
  avgBps?: number
  progress?: number
  latencyMs?: number
  pingMs?: number
  jitterMs?: number
  downloadBps?: number
  uploadBps?: number
  loadedDownMs?: number
  loadedUpMs?: number
  bytes?: number
  error?: string
}

type Ticket = { ticket: string; expires_at: number }

const DL_REQUEST_BYTES = 25 * 1024 * 1024
const UL_REQUEST_BYTES = 4 * 1024 * 1024

let uploadBlob: Blob | null = null
function getUploadBlob(): Blob {
  if (uploadBlob) return uploadBlob
  const buf = new Uint8Array(UL_REQUEST_BYTES)
  for (let off = 0; off < buf.length; off += 65536) {
    crypto.getRandomValues(buf.subarray(off, Math.min(buf.length, off + 65536)))
  }
  uploadBlob = new Blob([buf], { type: 'application/octet-stream' })
  return uploadBlob
}

function median(xs: number[]): number | undefined {
  if (!xs.length) return undefined
  const s = [...xs].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

function jitter(xs: number[]): number | undefined {
  if (xs.length < 2) return undefined
  let sum = 0
  for (let i = 1; i < xs.length; i += 1) sum += Math.abs(xs[i] - xs[i - 1])
  return sum / (xs.length - 1)
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function pingOnce(ticket: string, signal: AbortSignal): Promise<number | null> {
  const url = `/api/speedtest/ping?r=${Math.random().toString(36).slice(2)}`
  const t0 = performance.now()
  try {
    const res = await fetch(url, { headers: { 'X-Speedtest-Ticket': ticket }, cache: 'no-store', signal })
    await res.arrayBuffer()
    const t1 = performance.now()
    if (!res.ok) return null
    // Resource Timing strips JS/event-loop overhead when available.
    const entry = performance.getEntriesByName(new URL(url, location.href).href).pop() as
      | PerformanceResourceTiming
      | undefined
    if (entry && entry.responseStart > 0 && entry.requestStart > 0) {
      const v = entry.responseStart - entry.requestStart
      if (v > 0) return v
    }
    return t1 - t0
  } catch {
    return null
  }
}

export async function runBrowserTest(
  opts: BrowserTestOptions,
  onUpdate: (u: BrowserUpdate) => void,
  signal: AbortSignal,
): Promise<BrowserUpdate> {
  const result: BrowserUpdate = { phase: 'connect' }
  const emit = (u: Partial<BrowserUpdate>) => {
    Object.assign(result, u)
    onUpdate({ ...result })
  }
  try {
    performance.clearResourceTimings()
    performance.setResourceTimingBufferSize?.(1000)
  } catch {
    /* ignore */
  }

  emit({ phase: 'connect' })
  const { ticket } = await api<Ticket>('/api/speedtest/session', { method: 'POST', body: '{}' })

  // ── Ping ─────────────────────────────────────────
  emit({ phase: 'ping' })
  await pingOnce(ticket, signal) // warm up the connection
  const pings: number[] = []
  for (let i = 0; i < opts.pingCount; i += 1) {
    if (signal.aborted) throw new DOMException('aborted', 'AbortError')
    const ms = await pingOnce(ticket, signal)
    if (ms != null) {
      pings.push(ms)
      emit({ latencyMs: ms, pingMs: median(pings), jitterMs: jitter(pings), progress: (i + 1) / opts.pingCount })
    }
    await sleep(40)
  }

  const transfer = async (dir: 'download' | 'upload') => {
    emit({ phase: dir, bps: 0, avgBps: 0, progress: 0 })
    const ctrl = new AbortController()
    const onAbort = () => ctrl.abort()
    signal.addEventListener('abort', onAbort)
    let total = 0
    let running = true
    const xhrs = new Set<XMLHttpRequest>()

    const dlWorker = async () => {
      while (running) {
        try {
          const res = await fetch(`/api/speedtest/download?bytes=${DL_REQUEST_BYTES}&r=${Math.random()}`, {
            headers: { 'X-Speedtest-Ticket': ticket },
            cache: 'no-store',
            signal: ctrl.signal,
          })
          if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
          const reader = res.body.getReader()
          for (;;) {
            const { done, value } = await reader.read()
            if (done) break
            total += value.byteLength
            if (!running) {
              await reader.cancel().catch(() => {})
              break
            }
          }
        } catch (e) {
          if (!running || ctrl.signal.aborted) return
          await sleep(200)
          if (String(e).includes('401')) throw e
        }
      }
    }

    const ulWorker = () =>
      new Promise<void>((resolve) => {
        const blob = getUploadBlob()
        const once = () => {
          if (!running) return resolve()
          const xhr = new XMLHttpRequest()
          xhrs.add(xhr)
          let last = 0
          xhr.upload.onprogress = (ev) => {
            total += ev.loaded - last
            last = ev.loaded
          }
          const next = () => {
            xhrs.delete(xhr)
            if (running) once()
            else resolve()
          }
          xhr.onload = () => {
            total += Math.max(0, blob.size - last)
            last = blob.size
            next()
          }
          xhr.onerror = () => setTimeout(next, 200)
          xhr.onabort = () => {
            xhrs.delete(xhr)
            resolve()
          }
          xhr.open('POST', `/api/speedtest/upload?r=${Math.random()}`, true)
          xhr.setRequestHeader('X-Speedtest-Ticket', ticket)
          xhr.setRequestHeader('Content-Type', 'application/octet-stream')
          xhr.send(blob)
        }
        once()
      })

    // Latency under load
    const loaded: number[] = []
    const pinger = (async () => {
      while (running) {
        await sleep(450)
        if (!running) break
        const ms = await pingOnce(ticket, ctrl.signal)
        if (ms != null && running) {
          loaded.push(ms)
          emit({ latencyMs: ms, [dir === 'download' ? 'loadedDownMs' : 'loadedUpMs']: median(loaded) })
        }
      }
    })()

    const workers: Promise<unknown>[] = []
    for (let i = 0; i < opts.streams; i += 1) {
      workers.push(dir === 'download' ? dlWorker() : ulWorker())
      await sleep(30)
    }

    const started = performance.now()
    const durMs = opts.duration * 1000
    const graceMs = Math.min(1500, durMs * 0.2)
    let graceBytes = 0
    let graceAt = 0
    let lastT = started
    let lastB = 0
    let ema = 0
    while (true) {
      await sleep(150)
      if (signal.aborted) break
      const now = performance.now()
      const el = now - started
      const inst = ((total - lastB) * 8 * 1000) / Math.max(1, now - lastT)
      lastT = now
      lastB = total
      ema = ema === 0 ? inst : ema * 0.7 + inst * 0.3
      if (!graceAt && el >= graceMs) {
        graceAt = el
        graceBytes = total
      }
      const avg =
        graceAt && el > graceAt + 300
          ? ((total - graceBytes) * 8 * 1000) / (el - graceAt)
          : (total * 8 * 1000) / Math.max(1, el)
      emit({ bps: ema, avgBps: avg, progress: Math.min(1, el / durMs), bytes: total })
      if (el >= durMs) break
    }
    running = false
    ctrl.abort()
    xhrs.forEach((x) => x.abort())
    signal.removeEventListener('abort', onAbort)
    await Promise.allSettled([...workers, pinger])
    if (signal.aborted) throw new DOMException('aborted', 'AbortError')
    const final = result.avgBps || 0
    emit(dir === 'download' ? { downloadBps: final } : { uploadBps: final })
  }

  if (opts.download) await transfer('download')
  if (opts.upload) await transfer('upload')
  emit({ phase: 'done', bps: undefined, progress: 1 })
  return { ...result }
}
