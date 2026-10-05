import type { JobSnapshot } from '../../speedtest/useJob'

export type SpeedInfo = {
  hostname: string
  client_ip: string | null
  server_ip: string | null
  tools: {
    iperf3: boolean
    iperf3_path: string | null
    iperf3_version: string | null
    pkg_manager: string | null
  }
  addresses: Array<{ iface: string; ip: string; family: 4 | 6; speed_mbps: number | null; mtu: number | null }>
  congestion: { available: string[]; current: string | null }
  options: Record<string, any>
  can_run: boolean
  jobs: Array<Pick<JobSnapshot, 'id' | 'kind' | 'status' | 'phase' | 'params' | 'started_at' | 'owner'>>
}

export type HistoryItem = {
  id: string
  at: number
  kind: 'browser' | 'internet' | 'iperf'
  target?: string
  by?: string
  ping_ms?: number
  jitter_ms?: number
  download_bps?: number
  upload_bps?: number
  loaded_latency_ms?: number
  protocol?: string
  direction?: string
  parallel?: number
  loss_pct?: number
  retr?: number
  client_ip?: string
  meta?: Record<string, any>
}
