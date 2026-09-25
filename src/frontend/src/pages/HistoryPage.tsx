import { useEffect, useMemo, useState } from 'react'
import { Button, DatePicker, Select, Slider, Space, Table, Tabs, Tag, Typography } from 'antd'
import { HolderOutlined, PlusOutlined, CloseOutlined } from '@ant-design/icons'
import { Reorder, useDragControls } from 'framer-motion'
import dayjs, { type Dayjs } from 'dayjs'
import { api } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { PremiumAreaChart, type SeriesDef } from '../components/PremiumAreaChart'
import { useAppSettings } from '../api/settings'
import { formatBytes, formatDuration, formatNetworkRate, formatRate, formatRateTick } from '../utils/format'
import { tablePagination } from '../utils/tablePagination'

const { RangePicker } = DatePicker

type Row = {
  recorded_at: string
  cpu_percent: number
  memory_percent: number
  swap_percent: number
  load_1: number
  load_5: number
  load_15: number
  disk_percent: number
  net_bytes_sent_rate: number
  net_bytes_recv_rate: number
}

type SshSnapshotRow = {
  recorded_at: string
  active_count: number
  users_connected: number
  bytes_sent_total?: number | null
  bytes_recv_total?: number | null
  bytes_sent_rate_total?: number | null
  bytes_recv_rate_total?: number | null
}

type SshConnRow = {
  id: number
  session_key: string
  username: string
  remote_ip?: string
  remote_port?: number
  remote?: string
  pid?: number
  status: string
  started_at: string
  ended_at?: string | null
  duration_seconds?: number | null
  forwards_count?: number
  forwards?: Array<{ peer?: string; host?: string; port?: number }>
  bytes_sent?: number | null
  bytes_recv?: number | null
  bytes_sent_rate?: number | null
  bytes_recv_rate?: number | null
}

type WgSnapshotRow = {
  recorded_at: string
  online_count: number
  peer_count: number
}

type WgConnRow = {
  id: number
  session_key: string
  peer_name: string
  vpn_address?: string | null
  remote_ip?: string | null
  remote_port?: number | null
  remote?: string | null
  status: string
  started_at: string
  ended_at?: string | null
  duration_seconds?: number | null
  transfer_rx?: number | null
  transfer_tx?: number | null
}

type MetricDef = {
  value: string
  label: string
  color: string
  /** percent | load | rate */
  scale: 'percent' | 'load' | 'rate'
}

const METRICS: MetricDef[] = [
  { value: 'cpu_percent', label: 'CPU %', color: '#0d9488', scale: 'percent' },
  { value: 'memory_percent', label: 'RAM %', color: '#0284c7', scale: 'percent' },
  { value: 'swap_percent', label: 'Swap %', color: '#6366f1', scale: 'percent' },
  { value: 'disk_percent', label: 'Disk / %', color: '#d97706', scale: 'percent' },
  { value: 'load_1', label: 'Load 1', color: '#7c3aed', scale: 'load' },
  { value: 'load_5', label: 'Load 5', color: '#a855f7', scale: 'load' },
  { value: 'load_15', label: 'Load 15', color: '#c084fc', scale: 'load' },
  { value: 'net_bytes_recv_rate', label: 'Network RX', color: '#059669', scale: 'rate' },
  { value: 'net_bytes_sent_rate', label: 'Network TX', color: '#ea580c', scale: 'rate' },
]

const METRIC_MAP = Object.fromEntries(METRICS.map((m) => [m.value, m])) as Record<string, MetricDef>

const PRESETS: Array<{ label: string; hours: number }> = [
  { label: '1h', hours: 1 },
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  { label: '7d', hours: 24 * 7 },
]

function MetricChip({
  id,
  onRemove,
}: {
  id: string
  onRemove: () => void
}) {
  const controls = useDragControls()
  const meta = METRIC_MAP[id]
  if (!meta) return null
  return (
    <Reorder.Item
      value={id}
      dragListener={false}
      dragControls={controls}
      style={{ listStyle: 'none' }}
      whileDrag={{ scale: 1.04, zIndex: 10 }}
    >
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          padding: '6px 10px',
          borderRadius: 999,
          border: '1px solid var(--la-panel-border)',
          background: 'var(--la-panel)',
          boxShadow: 'var(--la-panel-shadow)',
          cursor: 'grab',
          userSelect: 'none',
        }}
      >
        <HolderOutlined
          onPointerDown={(e) => controls.start(e)}
          style={{ color: 'var(--la-muted)', touchAction: 'none' }}
        />
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: 99,
            background: meta.color,
            flexShrink: 0,
          }}
        />
        <span style={{ fontSize: 13, fontWeight: 600 }}>{meta.label}</span>
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${meta.label}`}
          style={{
            border: 'none',
            background: 'transparent',
            padding: 0,
            marginLeft: 2,
            cursor: 'pointer',
            color: 'var(--la-muted)',
            display: 'inline-flex',
          }}
        >
          <CloseOutlined style={{ fontSize: 10 }} />
        </button>
      </div>
    </Reorder.Item>
  )
}

function SystemHistoryTab({ range }: { range: [Dayjs, Dayjs] }) {
  const [selected, setSelected] = useState<string[]>(['cpu_percent', 'memory_percent'])
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(false)
  const [windowIdx, setWindowIdx] = useState<[number, number]>([0, 0])

  useEffect(() => {
    const from = range[0].toISOString()
    const to = range[1].toISOString()
    setLoading(true)
    void api<Row[]>(
      `/api/history/metrics?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&limit=5000`,
    )
      .then((data) => {
        setRows(data)
        const end = Math.max(0, data.length - 1)
        if (data.length <= 40) {
          setWindowIdx([0, end])
        } else {
          const start = Math.max(0, end - Math.floor(data.length * 0.35))
          setWindowIdx([start, end])
        }
      })
      .catch(() => {
        setRows([])
        setWindowIdx([0, 0])
      })
      .finally(() => setLoading(false))
  }, [range])

  const availableToAdd = METRICS.filter((m) => !selected.includes(m.value))

  const chartData = useMemo(() => {
    return rows.map((r) => {
      const point: Record<string, string | number> = {
        time: dayjs(r.recorded_at).format('DD.MM HH:mm:ss'),
        ts: dayjs(r.recorded_at).valueOf(),
      }
      for (const key of selected) {
        point[key] = Number((r as any)[key] ?? 0)
      }
      return point
    })
  }, [rows, selected])

  const series: SeriesDef[] = useMemo(
    () =>
      selected
        .map((key) => METRIC_MAP[key])
        .filter(Boolean)
        .map((m) => ({
          key: m.value,
          label: m.label,
          color: m.color,
          yAxisId: m.scale === 'rate' ? 'right' : 'left',
          formatValue:
            m.scale === 'rate'
              ? formatNetworkRate
              : m.scale === 'percent'
                ? (v: number) => `${v.toFixed(1)} %`
                : (v: number) => v.toFixed(2),
        })),
    [selected],
  )

  const hasPercentOrLoad = series.some((s) => {
    const m = METRIC_MAP[s.key]
    return m?.scale === 'percent' || m?.scale === 'load'
  })
  const hasRate = series.some((s) => METRIC_MAP[s.key]?.scale === 'rate')
  const onlyPercent = series.length > 0 && series.every((s) => METRIC_MAP[s.key]?.scale === 'percent')

  const [wStart, wEnd] = windowIdx
  const safeEnd = Math.min(wEnd, Math.max(0, chartData.length - 1))
  const safeStart = Math.min(wStart, safeEnd)

  const windowLabel = useMemo(() => {
    if (!rows.length) return 'no data'
    const a = dayjs(rows[safeStart]?.recorded_at)
    const b = dayjs(rows[safeEnd]?.recorded_at)
    return `${a.format('DD.MM HH:mm')} → ${b.format('DD.MM HH:mm')}`
  }, [rows, safeStart, safeEnd])

  const addMetric = (value: string) => {
    if (!value || selected.includes(value)) return
    setSelected((prev) => [...prev, value])
  }

  const removeMetric = (value: string) => {
    setSelected((prev) => (prev.length <= 1 ? prev : prev.filter((x) => x !== value)))
  }

  return (
    <>
      <Panel title="Metrics on chart">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
          <Reorder.Group
            axis="x"
            values={selected}
            onReorder={setSelected}
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 8,
              margin: 0,
              padding: 0,
              listStyle: 'none',
            }}
          >
            {selected.map((id) => (
              <MetricChip key={id} id={id} onRemove={() => removeMetric(id)} />
            ))}
          </Reorder.Group>

          {availableToAdd.length ? (
            <Select
              placeholder={
                <span>
                  <PlusOutlined /> Add metric
                </span>
              }
              style={{ minWidth: 200 }}
              options={availableToAdd.map((m) => ({ value: m.value, label: m.label }))}
              value={null as unknown as string}
              onChange={addMetric}
              allowClear={false}
            />
          ) : null}
        </div>
        <Typography.Text type="secondary" style={{ display: 'block', marginTop: 10, fontSize: 12 }}>
          Drag ⋮⋮ to reorder lines. Network RX/TX uses the right axis (B/s · Mbit/s).
        </Typography.Text>
      </Panel>

      <Panel
        title="Chart"
        style={{ marginTop: 16 }}
        extra={
          <Typography.Text type="secondary" className="mono" style={{ fontSize: 12 }}>
            {loading ? 'loading…' : `${rows.length} points · window ${windowLabel}`}
          </Typography.Text>
        }
      >
        {chartData.length && series.length ? (
          <PremiumAreaChart
            data={chartData}
            series={series}
            height={420}
            brush
            brushStartIndex={safeStart}
            brushEndIndex={safeEnd}
            onBrushChange={(r) => {
              if (r.startIndex == null || r.endIndex == null) return
              setWindowIdx([r.startIndex, r.endIndex])
            }}
            yDomain={onlyPercent ? [0, 100] : hasPercentOrLoad ? ['auto', 'auto'] : ['auto', 'auto']}
            yDomainRight={hasRate ? ['auto', 'auto'] : undefined}
            yFormatter={(v) =>
              onlyPercent || hasPercentOrLoad
                ? Number.isFinite(v)
                  ? v >= 10
                    ? v.toFixed(0)
                    : v.toFixed(1)
                  : ''
                : String(v)
            }
            yFormatterRight={formatRateTick}
          />
        ) : (
          <Typography.Text type="secondary">No data for the selected period</Typography.Text>
        )}

        {rows.length > 2 ? (
          <div style={{ marginTop: 20, paddingInline: 8 }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                marginBottom: 8,
                fontSize: 12,
                color: 'var(--la-muted)',
              }}
            >
              <span className="mono">{dayjs(rows[0].recorded_at).format('DD.MM HH:mm')}</span>
              <span>Time navigation (drag edges or the middle)</span>
              <span className="mono">
                {dayjs(rows[rows.length - 1].recorded_at).format('DD.MM HH:mm')}
              </span>
            </div>
            <Slider
              range
              min={0}
              max={Math.max(0, rows.length - 1)}
              value={[safeStart, safeEnd]}
              tooltip={{
                formatter: (v) => {
                  const i = Number(v ?? 0)
                  const row = rows[i]
                  return row ? dayjs(row.recorded_at).format('DD.MM HH:mm:ss') : ''
                },
              }}
              onChange={(v) => {
                if (Array.isArray(v) && v.length === 2) {
                  const a = Math.min(v[0], v[1])
                  const b = Math.max(v[0], v[1])
                  setWindowIdx([a, b])
                }
              }}
            />
            <Space wrap style={{ marginTop: 4 }}>
              <Button
                size="small"
                onClick={() => {
                  const span = Math.max(1, safeEnd - safeStart)
                  const start = Math.max(0, safeStart - span)
                  setWindowIdx([start, start + span])
                }}
              >
                ← Earlier
              </Button>
              <Button
                size="small"
                onClick={() => {
                  const span = Math.max(1, safeEnd - safeStart)
                  const end = Math.min(rows.length - 1, safeEnd + span)
                  setWindowIdx([end - span, end])
                }}
              >
                Later →
              </Button>
              <Button size="small" onClick={() => setWindowIdx([0, rows.length - 1])}>
                Full range
              </Button>
              <Button
                size="small"
                onClick={() => {
                  const end = rows.length - 1
                  const start = Math.max(0, end - Math.floor(rows.length * 0.25))
                  setWindowIdx([start, end])
                }}
              >
                Last 25%
              </Button>
            </Space>
          </div>
        ) : null}
      </Panel>
    </>
  )
}

function SshTunnelHistoryTab({ range }: { range: [Dayjs, Dayjs] }) {
  const [snapshots, setSnapshots] = useState<SshSnapshotRow[]>([])
  const [conns, setConns] = useState<SshConnRow[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)

  useEffect(() => {
    const from = range[0].toISOString()
    const to = range[1].toISOString()
    setLoading(true)
    const statusQ = statusFilter ? `&status=${encodeURIComponent(statusFilter)}` : ''
    void Promise.all([
      api<SshSnapshotRow[]>(
        `/api/history/ssh-tunnel?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&limit=5000`,
      ).catch(() => [] as SshSnapshotRow[]),
      api<SshConnRow[]>(
        `/api/history/ssh-tunnel/connections?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&limit=1000${statusQ}`,
      ).catch(() => [] as SshConnRow[]),
    ])
      .then(([snap, events]) => {
        setSnapshots(snap)
        setConns(events)
      })
      .finally(() => setLoading(false))
  }, [range, statusFilter])

  const chartData = useMemo(
    () =>
      snapshots.map((r) => ({
        time: dayjs(r.recorded_at).format('DD.MM HH:mm:ss'),
        ts: dayjs(r.recorded_at).valueOf(),
        active_count: Number(r.active_count ?? 0),
        users_connected: Number(r.users_connected ?? 0),
        bytes_recv_rate_total: Number(r.bytes_recv_rate_total ?? 0),
        bytes_sent_rate_total: Number(r.bytes_sent_rate_total ?? 0),
      })),
    [snapshots],
  )

  const series: SeriesDef[] = [
    {
      key: 'active_count',
      label: 'Active sessions',
      color: '#0d9488',
      formatValue: (v) => String(Math.round(v)),
    },
    {
      key: 'users_connected',
      label: 'Unique users',
      color: '#0284c7',
      formatValue: (v) => String(Math.round(v)),
    },
  ]

  const trafficSeries: SeriesDef[] = [
    {
      key: 'bytes_recv_rate_total',
      label: 'Tunnel RX',
      color: '#059669',
      formatValue: (v) => formatNetworkRate(v),
    },
    {
      key: 'bytes_sent_rate_total',
      label: 'Tunnel TX',
      color: '#ea580c',
      formatValue: (v) => formatNetworkRate(v),
    },
  ]

  const hasTraffic = chartData.some(
    (r) => r.bytes_recv_rate_total > 0 || r.bytes_sent_rate_total > 0,
  )

  return (
    <>
      <Panel
        title="Tunnel activity"
        extra={
          <Typography.Text type="secondary" className="mono" style={{ fontSize: 12 }}>
            {loading ? 'loading…' : `${snapshots.length} points`}
          </Typography.Text>
        }
      >
        {chartData.length ? (
          <PremiumAreaChart data={chartData} series={series} height={280} brush />
        ) : (
          <Typography.Text type="secondary">
            No snapshots for this period. Enable “Write connection history” for SSH Tunnel in Settings.
          </Typography.Text>
        )}
      </Panel>

      {chartData.length && hasTraffic ? (
        <Panel
          title="Tunnel network load"
          style={{ marginTop: 16 }}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              aggregate RX/TX of active tunnel sessions
            </Typography.Text>
          }
        >
          <PremiumAreaChart
            data={chartData}
            series={trafficSeries}
            height={240}
            brush
            yFormatter={formatRateTick}
          />
        </Panel>
      ) : null}

      <Panel
        title="Connection log"
        style={{ marginTop: 16 }}
        extra={
          <Select
            allowClear
            placeholder="Status"
            style={{ width: 140 }}
            value={statusFilter}
            onChange={(v) => setStatusFilter(v)}
            options={[
              { value: 'active', label: 'active' },
              { value: 'closed', label: 'closed' },
            ]}
          />
        }
      >
        <Table
          size="small"
          rowKey="id"
          loading={loading}
          dataSource={conns}
          pagination={tablePagination(25)}
          locale={{ emptyText: 'No connection records for this period' }}
          columns={[
            {
              title: 'Status',
              dataIndex: 'status',
              width: 100,
              render: (v: string) => (
                <Tag color={v === 'active' ? 'success' : 'default'}>{v}</Tag>
              ),
            },
            {
              title: 'User',
              dataIndex: 'username',
              render: (v: string) => <span className="mono">{v}</span>,
            },
            {
              title: 'Client',
              dataIndex: 'remote',
              render: (_: unknown, r: SshConnRow) => (
                <span className="mono">{r.remote || r.remote_ip || '—'}</span>
              ),
            },
            {
              title: 'Start',
              dataIndex: 'started_at',
              render: (v: string) => (
                <span className="mono" style={{ fontSize: 12 }}>
                  {dayjs(v).format('DD.MM.YYYY HH:mm:ss')}
                </span>
              ),
            },
            {
              title: 'End',
              dataIndex: 'ended_at',
              render: (v?: string | null) =>
                v ? (
                  <span className="mono" style={{ fontSize: 12 }}>
                    {dayjs(v).format('DD.MM.YYYY HH:mm:ss')}
                  </span>
                ) : (
                  '—'
                ),
            },
            {
              title: 'Duration',
              dataIndex: 'duration_seconds',
              render: (v: number | null | undefined, r: SshConnRow) => {
                if (r.status === 'active' && r.started_at) {
                  return (
                    <span className="mono">
                      {formatDuration(dayjs().diff(dayjs(r.started_at), 'second'))}
                    </span>
                  )
                }
                return <span className="mono">{formatDuration(v)}</span>
              },
            },
            {
              title: 'Traffic',
              key: 'traffic',
              width: 170,
              render: (_: unknown, r: SshConnRow) => (
                <div className="mono" style={{ fontSize: 12, lineHeight: 1.45 }}>
                  <div>
                    ↓ {formatBytes(r.bytes_recv)}
                    {r.status === 'active' && r.bytes_recv_rate != null
                      ? ` · ${formatRate(r.bytes_recv_rate)}`
                      : ''}
                  </div>
                  <div>
                    ↑ {formatBytes(r.bytes_sent)}
                    {r.status === 'active' && r.bytes_sent_rate != null
                      ? ` · ${formatRate(r.bytes_sent_rate)}`
                      : ''}
                  </div>
                </div>
              ),
            },
            {
              title: 'Forwards',
              dataIndex: 'forwards_count',
              width: 90,
              render: (v?: number) => v ?? 0,
            },
            {
              title: 'PID',
              dataIndex: 'pid',
              width: 80,
              render: (v?: number) => (v != null ? <span className="mono">{v}</span> : '—'),
            },
          ]}
        />
      </Panel>
    </>
  )
}

function WireGuardHistoryTab({ range }: { range: [Dayjs, Dayjs] }) {
  const [snapshots, setSnapshots] = useState<WgSnapshotRow[]>([])
  const [conns, setConns] = useState<WgConnRow[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)

  useEffect(() => {
    const from = range[0].toISOString()
    const to = range[1].toISOString()
    setLoading(true)
    const statusQ = statusFilter ? `&status=${encodeURIComponent(statusFilter)}` : ''
    void Promise.all([
      api<WgSnapshotRow[]>(
        `/api/history/wireguard?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&limit=5000`,
      ).catch(() => [] as WgSnapshotRow[]),
      api<WgConnRow[]>(
        `/api/history/wireguard/connections?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&limit=1000${statusQ}`,
      ).catch(() => [] as WgConnRow[]),
    ])
      .then(([snap, events]) => {
        setSnapshots(snap)
        setConns(events)
      })
      .finally(() => setLoading(false))
  }, [range, statusFilter])

  const chartData = useMemo(
    () =>
      snapshots.map((r) => ({
        time: dayjs(r.recorded_at).format('DD.MM HH:mm:ss'),
        ts: dayjs(r.recorded_at).valueOf(),
        online_count: Number(r.online_count ?? 0),
        peer_count: Number(r.peer_count ?? 0),
      })),
    [snapshots],
  )

  const series: SeriesDef[] = [
    {
      key: 'online_count',
      label: 'Online peers',
      color: '#0d9488',
      formatValue: (v) => String(Math.round(v)),
    },
    {
      key: 'peer_count',
      label: 'Configured peers',
      color: '#0284c7',
      formatValue: (v) => String(Math.round(v)),
    },
  ]

  return (
    <>
      <Panel
        title="Online peers"
        extra={
          <Typography.Text type="secondary" className="mono" style={{ fontSize: 12 }}>
            {loading ? 'loading…' : `${snapshots.length} points`}
          </Typography.Text>
        }
      >
        {chartData.length ? (
          <PremiumAreaChart data={chartData} series={series} height={280} brush />
        ) : (
          <Typography.Text type="secondary">
            No snapshots for this period. Enable “Write connection history” for WireGuard in Settings.
          </Typography.Text>
        )}
      </Panel>

      <Panel
        title="Connection log"
        style={{ marginTop: 16 }}
        extra={
          <Select
            allowClear
            placeholder="Status"
            style={{ width: 140 }}
            value={statusFilter}
            onChange={(v) => setStatusFilter(v)}
            options={[
              { value: 'active', label: 'active' },
              { value: 'closed', label: 'closed' },
            ]}
          />
        }
      >
        <Table
          size="small"
          rowKey="id"
          loading={loading}
          dataSource={conns}
          pagination={tablePagination(25)}
          locale={{ emptyText: 'No connection records for this period' }}
          columns={[
            {
              title: 'Status',
              dataIndex: 'status',
              width: 100,
              render: (v: string) => (
                <Tag color={v === 'active' ? 'success' : 'default'}>{v}</Tag>
              ),
            },
            {
              title: 'Peer',
              dataIndex: 'peer_name',
              render: (v: string) => <span className="mono">{v}</span>,
            },
            {
              title: 'VPN IP',
              dataIndex: 'vpn_address',
              render: (v?: string | null) => <span className="mono">{v || '—'}</span>,
            },
            {
              title: 'Endpoint',
              dataIndex: 'remote',
              render: (_: unknown, r: WgConnRow) => (
                <span className="mono">{r.remote || r.remote_ip || '—'}</span>
              ),
            },
            {
              title: 'Start',
              dataIndex: 'started_at',
              render: (v: string) => (
                <span className="mono" style={{ fontSize: 12 }}>
                  {dayjs(v).format('DD.MM.YYYY HH:mm:ss')}
                </span>
              ),
            },
            {
              title: 'End',
              dataIndex: 'ended_at',
              render: (v?: string | null) =>
                v ? (
                  <span className="mono" style={{ fontSize: 12 }}>
                    {dayjs(v).format('DD.MM.YYYY HH:mm:ss')}
                  </span>
                ) : (
                  '—'
                ),
            },
            {
              title: 'Duration',
              dataIndex: 'duration_seconds',
              width: 110,
              render: (v?: number | null) =>
                v != null ? <span className="mono">{formatDuration(v)}</span> : '—',
            },
            {
              title: 'Transfer',
              key: 'transfer',
              width: 180,
              render: (_: unknown, r: WgConnRow) => (
                <span className="mono" style={{ fontSize: 12 }}>
                  ↓ {formatBytes(r.transfer_rx)} · ↑ {formatBytes(r.transfer_tx)}
                </span>
              ),
            },
          ]}
        />
      </Panel>
    </>
  )
}

export function HistoryPage() {
  const { isModuleEnabled } = useAppSettings()
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(6, 'hour'), dayjs()])
  const showSsh = isModuleEnabled('ssh_tunnel')
  const showWg = isModuleEnabled('wireguard')

  return (
    <div className="la-page">
      <PageHeader
        docsKey="history"
        title="History"
        subtitle="System metrics, SSH Tunnel and WireGuard connection logs for the selected period."
        extra={
          <Space wrap>
            {PRESETS.map((p) => (
              <Button
                key={p.label}
                size="small"
                onClick={() => setRange([dayjs().subtract(p.hours, 'hour'), dayjs()])}
              >
                {p.label}
              </Button>
            ))}
            <RangePicker
              showTime
              value={range}
              onChange={(v) => {
                if (v?.[0] && v?.[1]) setRange([v[0], v[1]])
              }}
            />
          </Space>
        }
      />

      <Tabs
        defaultActiveKey="system"
        items={[
          {
            key: 'system',
            label: 'System',
            children: <SystemHistoryTab range={range} />,
          },
          ...(showSsh
            ? [
                {
                  key: 'ssh',
                  label: 'SSH Tunnel',
                  children: <SshTunnelHistoryTab range={range} />,
                },
              ]
            : []),
          ...(showWg
            ? [
                {
                  key: 'wireguard',
                  label: 'WireGuard',
                  children: <WireGuardHistoryTab range={range} />,
                },
              ]
            : []),
        ]}
      />
    </div>
  )
}
