import { useEffect, useMemo, useRef, useState } from 'react'
import { Col, Progress, Row, Space, Table, Tag, Typography } from 'antd'
import { connectAuthedWs } from '../api/client'
import { useAppSettings } from '../api/settings'
import { GaugeCard } from '../components/GaugeCard'
import { OsInfoCard, type OsHostInfo } from '../components/OsInfoCard'
import { Panel } from '../components/Panel'
import { PageHeader } from '../components/PageHeader'
import { PremiumAreaChart } from '../components/PremiumAreaChart'
import { formatBytes, formatNetworkRate, formatRateTick, formatUptime } from '../utils/format'

type SystemData = {
  host: OsHostInfo & { hostname: string; uptime_seconds: number }
  cpu: {
    percent: number
    per_cpu: number[]
    count_logical?: number
    count_physical?: number
    load_avg: { '1': number; '5': number; '15': number }
  }
  memory: { percent: number; used: number; total: number }
  swap: { percent: number; used: number; total: number }
  disks: Array<{ mountpoint: string; percent: number; used: number; total: number }>
  network: {
    bytes_sent_rate: number
    bytes_recv_rate: number
    interfaces: Array<{ name: string; bytes_sent_rate: number; bytes_recv_rate: number }>
  }
  processes: Array<{
    pid: number
    name: string
    username?: string
    cpu_percent: number
    memory_percent: number
  }>
  temperatures: Array<{ label: string; current: number }>
}

type Point = { time: string; cpu: number; mem: number; netIn: number; netOut: number }

export function DashboardPage() {
  const { moduleOpts } = useAppSettings()
  const ov = moduleOpts('overview')
  const [data, setData] = useState<SystemData | null>(null)
  const [series, setSeries] = useState<Point[]>([])
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (ov.live_metrics === false) return

    const ws = connectAuthedWs('/ws/metrics')
    wsRef.current = ws
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'auth_ok') return
        if (msg.type === 'system' && msg.data) {
          const d = msg.data as SystemData
          setData(d)
          const point: Point = {
            time: new Date().toLocaleTimeString(),
            cpu: d.cpu?.percent ?? 0,
            mem: d.memory?.percent ?? 0,
            netIn: d.network?.bytes_recv_rate ?? 0,
            netOut: d.network?.bytes_sent_rate ?? 0,
          }
          setSeries((prev) => [...prev.slice(-59), point])
        }
      } catch {
        /* ignore */
      }
    }
    return () => ws.close()
  }, [ov.live_metrics])

  const loadLine = useMemo(() => {
    if (ov.live_metrics === false) return 'Live metrics disabled in settings'
    if (!data) return 'Connecting to WebSocket…'
    return `${data.host.os} · uptime ${formatUptime(data.host.uptime_seconds)} · load ${data.cpu.load_avg['1'].toFixed(2)} / ${data.cpu.load_avg['5'].toFixed(2)} / ${data.cpu.load_avg['15'].toFixed(2)}`
  }, [data, ov.live_metrics])

  return (
    <div className="la-page">
      <PageHeader
        docsKey="overview"
        title={data?.host.hostname || 'Overview'}
        subtitle={loadLine}
        live={!!data && ov.live_metrics !== false}
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={24}>
          <OsInfoCard
            host={data?.host}
            cpuLogical={data?.cpu.count_logical}
            cpuPhysical={data?.cpu.count_physical}
          />
        </Col>
      </Row>

      {ov.gauges !== false ? (
        <Row gutter={[16, 16]}>
          <Col xs={12} md={6}>
            <GaugeCard
              title="CPU"
              percent={data?.cpu.percent}
              subtitle={`${data?.cpu.per_cpu?.length || 0} cores`}
            />
          </Col>
          <Col xs={12} md={6}>
            <GaugeCard
              title="RAM"
              percent={data?.memory.percent}
              subtitle={
                data
                  ? `${formatBytes(data.memory.used)} / ${formatBytes(data.memory.total)}`
                  : undefined
              }
            />
          </Col>
          <Col xs={12} md={6}>
            <GaugeCard
              title="Swap"
              percent={data?.swap.percent}
              subtitle={
                data ? `${formatBytes(data.swap.used)} / ${formatBytes(data.swap.total)}` : undefined
              }
            />
          </Col>
          <Col xs={12} md={6}>
            <GaugeCard
              title="Disk /"
              percent={data?.disks?.find((d) => d.mountpoint === '/')?.percent}
              subtitle={
                data
                  ? `↓ ${formatNetworkRate(data.network.bytes_recv_rate)} ↑ ${formatNetworkRate(data.network.bytes_sent_rate)}`
                  : undefined
              }
            />
          </Col>
        </Row>
      ) : null}

      {ov.charts !== false ? (
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Panel title="CPU / RAM">
              <PremiumAreaChart
                data={series}
                series={[
                  { key: 'cpu', label: 'CPU %', color: '#0d9488' },
                  { key: 'mem', label: 'RAM %', color: '#0284c7' },
                ]}
                yDomain={[0, 100]}
                height={250}
              />
            </Panel>
          </Col>
          <Col xs={24} lg={12}>
            <Panel title="Network (RX / TX)">
              <PremiumAreaChart
                data={series}
                series={[
                  {
                    key: 'netIn',
                    label: 'RX',
                    color: '#059669',
                    formatValue: formatNetworkRate,
                  },
                  {
                    key: 'netOut',
                    label: 'TX',
                    color: '#d97706',
                    formatValue: formatNetworkRate,
                  },
                ]}
                height={250}
                yFormatter={formatRateTick}
              />
            </Panel>
          </Col>
        </Row>
      ) : null}

      {ov.disks !== false || ov.processes !== false ? (
        <Row gutter={[16, 16]}>
          {ov.disks !== false ? (
            <Col xs={24} md={ov.processes !== false ? 12 : 24}>
              <Panel title="Disks">
                {(data?.disks || []).map((d) => (
                  <div key={d.mountpoint} style={{ marginBottom: 14 }}>
                    <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                      <span className="mono" style={{ fontWeight: 600 }}>
                        {d.mountpoint}
                      </span>
                      <span className="mono" style={{ color: 'var(--la-muted)', fontSize: 12 }}>
                        {formatBytes(d.used)} / {formatBytes(d.total)}
                      </span>
                    </Space>
                    <Progress
                      percent={d.percent}
                      size="small"
                      showInfo={false}
                      strokeColor={d.percent > 90 ? 'var(--la-danger)' : 'var(--la-accent)'}
                      railColor="color-mix(in srgb, var(--la-muted) 16%, transparent)"
                      style={{ marginTop: 6 }}
                    />
                  </div>
                ))}
                {ov.temperatures !== false && data?.temperatures?.length ? (
                  <>
                    <Typography.Text
                      type="secondary"
                      style={{
                        display: 'block',
                        marginTop: 8,
                        marginBottom: 10,
                        fontSize: 12,
                        fontWeight: 700,
                        letterSpacing: '0.04em',
                        textTransform: 'uppercase',
                      }}
                    >
                      Temperatures
                    </Typography.Text>
                    <Space wrap>
                      {data.temperatures.map((t, i) => (
                        <Tag key={`${t.label}-${i}`} className="mono">
                          {t.label}: {t.current.toFixed(1)}°C
                        </Tag>
                      ))}
                    </Space>
                  </>
                ) : null}
              </Panel>
            </Col>
          ) : null}
          {ov.processes !== false ? (
            <Col xs={24} md={ov.disks !== false ? 12 : 24}>
              <Panel title="Top processes" padded={false} bodyStyle={{ padding: '8px 8px 12px' }}>
                <Table
                  size="small"
                  rowKey="pid"
                  pagination={false}
                  dataSource={data?.processes || []}
                  columns={[
                    {
                      title: 'PID',
                      dataIndex: 'pid',
                      width: 70,
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    { title: 'Name', dataIndex: 'name', ellipsis: true },
                    {
                      title: 'CPU %',
                      dataIndex: 'cpu_percent',
                      width: 80,
                      render: (v) => <span className="mono">{v?.toFixed?.(1)}</span>,
                    },
                    {
                      title: 'RAM %',
                      dataIndex: 'memory_percent',
                      width: 80,
                      render: (v) => <span className="mono">{v?.toFixed?.(1)}</span>,
                    },
                  ]}
                />
              </Panel>
            </Col>
          ) : null}
        </Row>
      ) : null}
    </div>
  )
}
