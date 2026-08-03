import { useEffect, useMemo, useRef, useState } from 'react'
import { Col, Progress, Row, Space, Table, Tag, Typography } from 'antd'
import { api, connectAuthedWs } from '../api/client'
import { useAppSettings } from '../api/settings'
import { GaugeCard } from '../components/GaugeCard'
import { StatusCard } from '../components/StatusCard'
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
  const { isModuleEnabled, moduleOpts } = useAppSettings()
  const ov = moduleOpts('overview')
  const [data, setData] = useState<SystemData | null>(null)
  const [series, setSeries] = useState<Point[]>([])
  const [security, setSecurity] = useState<any>(null)
  const [pg, setPg] = useState<any>(null)
  const [docker, setDocker] = useState<any>(null)
  const [network, setNetwork] = useState<any>(null)
  const [disksOverview, setDisksOverview] = useState<any>(null)
  const [sshTunnel, setSshTunnel] = useState<any>(null)
  const [wireguard, setWireguard] = useState<any>(null)
  const [openvpn, setOpenvpn] = useState<any>(null)
  const [nginx, setNginx] = useState<any>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (ov.status_cards !== false) {
      if (isModuleEnabled('fail2ban') || isModuleEnabled('firewall')) {
        void api('/api/security/overview').then(setSecurity).catch(() => null)
      }
      if (isModuleEnabled('postgres')) {
        void api('/api/postgres/status').then(setPg).catch(() => null)
      }
      if (isModuleEnabled('docker')) {
        void api('/api/docker/overview').then(setDocker).catch(() => null)
      }
      if (isModuleEnabled('network')) {
        void api('/api/network/overview').then(setNetwork).catch(() => null)
      }
      if (isModuleEnabled('disks')) {
        void api('/api/disks/overview').then(setDisksOverview).catch(() => null)
      }
      if (isModuleEnabled('ssh_tunnel')) {
        void api('/api/ssh-tunnel/overview').then(setSshTunnel).catch(() => null)
      }
      if (isModuleEnabled('wireguard')) {
        void api('/api/wireguard/overview').then(setWireguard).catch(() => null)
      }
      if (isModuleEnabled('openvpn')) {
        void api('/api/openvpn/overview').then(setOpenvpn).catch(() => null)
      }
      if (isModuleEnabled('nginx')) {
        void api('/api/nginx/overview').then(setNginx).catch(() => null)
      }
    }

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
  }, [ov.live_metrics, ov.status_cards, isModuleEnabled])

  const loadLine = useMemo(() => {
    if (ov.live_metrics === false) return 'Live metrics disabled in settings'
    if (!data) return 'Connecting to WebSocket…'
    return `${data.host.os} · uptime ${formatUptime(data.host.uptime_seconds)} · load ${data.cpu.load_avg['1'].toFixed(2)} / ${data.cpu.load_avg['5'].toFixed(2)} / ${data.cpu.load_avg['15'].toFixed(2)}`
  }, [data, ov.live_metrics])

  const showCards = ov.status_cards !== false
  const cardModules = [
    isModuleEnabled('fail2ban'),
    isModuleEnabled('firewall'),
    isModuleEnabled('docker'),
    isModuleEnabled('network'),
    isModuleEnabled('disks'),
    isModuleEnabled('ssh_tunnel'),
    isModuleEnabled('wireguard'),
    isModuleEnabled('openvpn'),
    isModuleEnabled('nginx'),
    isModuleEnabled('postgres'),
  ].filter(Boolean).length

  const cardSpan = cardModules >= 5 ? 8 : cardModules > 2 ? 6 : 12

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

      {showCards && cardModules > 0 ? (
        <Row gutter={[16, 16]}>
          {isModuleEnabled('fail2ban') ? (
            <Col xs={24} sm={12} lg={cardSpan}>
              <StatusCard
                kind="fail2ban"
                title="Fail2ban"
                ok={!!security?.fail2ban?.installed && !!security?.fail2ban?.active}
                description={
                  security?.fail2ban?.installed
                    ? `${security.fail2ban.active ? 'Active' : 'Stopped'} · jails: ${security.fail2ban.jails_count}`
                    : 'Not installed'
                }
                to="/fail2ban"
              />
            </Col>
          ) : null}
          {isModuleEnabled('firewall') ? (
            <Col xs={24} sm={12} lg={cardSpan}>
              <StatusCard
                kind="firewall"
                title="Firewall"
                ok={!!security?.firewall?.enabled}
                description={
                  security?.firewall
                    ? `${security.firewall.backend} · ${security.firewall.enabled ? 'enabled' : 'disabled'}`
                    : 'Checking…'
                }
                to="/firewall"
              />
            </Col>
          ) : null}
          {isModuleEnabled('docker') ? (
            <Col xs={24} sm={12} lg={cardSpan}>
              <StatusCard
                kind="docker"
                title="Docker"
                ok={!!docker?.available}
                description={
                  !docker
                    ? 'Checking…'
                    : !docker.installed
                      ? 'Not installed'
                      : docker.available
                        ? `${docker.containers_running || 0}/${docker.containers || 0} running · images ${docker.images || 0}`
                        : docker.error || 'Daemon unavailable'
                }
                to="/docker"
              />
            </Col>
          ) : null}
          {isModuleEnabled('network') ? (
            <Col xs={24} sm={12} lg={cardSpan}>
              <StatusCard
                kind="network"
                title="Network"
                ok={!!network?.available}
                description={
                  network?.available
                    ? `listen ${network.listening || 0} · est ${network.established || 0} · sockets ${network.total || 0}`
                    : network?.error || 'Checking…'
                }
                to="/network"
              />
            </Col>
          ) : null}
          {isModuleEnabled('disks') ? (
            <Col xs={24} sm={12} lg={cardSpan}>
              <StatusCard
                kind="disks"
                title="Disks"
                ok={!!disksOverview?.available && (disksOverview?.count || 0) > 0}
                description={
                  disksOverview?.available
                    ? `${disksOverview.count || 0} volume(s) · free ${formatBytes(
                        disksOverview.free_total,
                      )}`
                    : disksOverview?.error || 'Checking…'
                }
                to="/disks"
              />
            </Col>
          ) : null}
          {isModuleEnabled('ssh_tunnel') ? (
            <Col xs={24} sm={12} lg={cardSpan}>
              <StatusCard
                kind="ssh_tunnel"
                title="SSH Tunnel"
                ok={!!sshTunnel?.available}
                description={
                  sshTunnel?.available
                    ? `${sshTunnel.count || 0} user(s) · ${sshTunnel.active_sessions || 0} online · ${sshTunnel.sshd_dropin_managed ? 'sshd OK' : 'sshd drop-in?'}`
                    : sshTunnel?.error || 'Checking…'
                }
                to="/ssh-tunnel"
              />
            </Col>
          ) : null}
          {isModuleEnabled('wireguard') ? (
            <Col xs={24} sm={12} lg={cardSpan}>
              <StatusCard
                kind="wireguard"
                title="WireGuard"
                ok={!!wireguard?.available && !!wireguard?.installed}
                description={
                  wireguard?.available
                    ? wireguard.installed
                      ? `${wireguard.peer_count || 0} peer(s) · ${wireguard.status?.up ? 'up' : 'down'}`
                      : 'Tools not installed'
                    : wireguard?.error || 'Checking…'
                }
                to="/wireguard"
              />
            </Col>
          ) : null}
          {isModuleEnabled('openvpn') ? (
            <Col xs={24} sm={12} lg={cardSpan}>
              <StatusCard
                kind="openvpn"
                title="OpenVPN"
                ok={!!openvpn?.available && !!openvpn?.installed}
                description={
                  openvpn?.available
                    ? openvpn.installed
                      ? `${openvpn.client_count || 0} client(s) · ${openvpn.status?.active ? 'up' : 'down'}`
                      : 'Tools not installed'
                    : openvpn?.error || 'Checking…'
                }
                to="/openvpn"
              />
            </Col>
          ) : null}
          {isModuleEnabled('nginx') ? (
            <Col xs={24} sm={12} lg={cardSpan}>
              <StatusCard
                kind="nginx"
                title="Nginx Edge"
                ok={!!nginx?.available && !!nginx?.installed && !!nginx?.status?.active}
                description={
                  nginx?.available
                    ? nginx.installed
                      ? `${nginx.routes_enabled || 0} route(s) · ${nginx.status?.active ? 'up' : 'down'}`
                      : 'Not installed'
                    : nginx?.error || 'Checking…'
                }
                to="/nginx"
              />
            </Col>
          ) : null}
          {isModuleEnabled('postgres') ? (
            <Col xs={24} sm={12} lg={cardSpan}>
              <StatusCard
                kind="postgres"
                title="PostgreSQL"
                ok={!!pg?.available}
                description={
                  pg?.available
                    ? `v${pg.version} · connections ${pg.connections}/${pg.max_connections}`
                    : pg?.error || 'Unavailable'
                }
                to="/postgres"
              />
            </Col>
          ) : null}
        </Row>
      ) : null}

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
