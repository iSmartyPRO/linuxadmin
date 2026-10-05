import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

export type JobSample = Record<string, any> & { kind: string; t: number }

export type JobSnapshot = {
  id: string
  kind: 'internet' | 'iperf_client' | 'iperf_server'
  owner: string
  status: 'starting' | 'running' | 'done' | 'error' | 'stopped'
  phase: string
  params: Record<string, any>
  started_at: number
  finished_at: number | null
  elapsed: number
  result: Record<string, any>
  meta: Record<string, any>
  error: string | null
  samples: JobSample[]
  next: number
  log: string[]
  log_next: number
}

export type JobState = Omit<JobSnapshot, 'samples' | 'log' | 'next' | 'log_next'> & {
  samples: JobSample[]
  log: string[]
}

export const isActive = (s?: { status: string } | null) => !!s && (s.status === 'starting' || s.status === 'running')

/** Poll a speedtest job incrementally (only new samples / log lines). */
export function useJob(jobId: string | null, intervalMs = 400) {
  const [job, setJob] = useState<JobState | null>(null)
  const cursor = useRef({ since: 0, log: 0 })
  const idRef = useRef<string | null>(null)

  useEffect(() => {
    idRef.current = jobId
    cursor.current = { since: 0, log: 0 }
    setJob(null)
    if (!jobId) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const tick = async () => {
      try {
        const snap = await api<JobSnapshot>(
          `/api/speedtest/jobs/${jobId}?since=${cursor.current.since}&log_since=${cursor.current.log}`,
        )
        if (stopped || idRef.current !== jobId) return
        cursor.current = { since: snap.next, log: snap.log_next }
        const { samples, log, next: _n, log_next: _l, ...rest } = snap
        setJob((prev) => ({
          ...rest,
          samples: prev && prev.id === snap.id ? [...prev.samples, ...samples].slice(-6000) : samples,
          log: prev && prev.id === snap.id ? [...prev.log, ...log].slice(-1500) : log,
        }))
        if (isActive(snap)) timer = setTimeout(tick, intervalMs)
      } catch {
        if (!stopped) timer = setTimeout(tick, intervalMs * 3)
      }
    }
    void tick()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
  }, [jobId, intervalMs])

  const stop = useCallback(async () => {
    if (!jobId) return
    await api(`/api/speedtest/jobs/${jobId}/stop`, { method: 'POST', body: '{}' })
  }, [jobId])

  return { job, stop }
}
