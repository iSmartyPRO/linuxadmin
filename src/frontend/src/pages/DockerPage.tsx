import { useCallback, useEffect, useState, type ReactNode } from 'react'
import {
  Alert,
  Button,
  Col,
  Descriptions,
  Progress,
  Row,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import { useAppSettings } from '../api/settings'
import { GaugeCard } from '../components/GaugeCard'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { tablePagination } from '../utils/tablePagination'
import { formatBytes, pctColor } from '../utils/format'

type ContainerRow = {
  id: string
  id_full?: string
  names?: string
  image?: string
  status?: string
  state?: string
  ports?: string
  created?: string
  size?: string
  size_rw_bytes?: number | null
  size_virtual_bytes?: number | null
  cpu_percent?: number | null
  mem_percent?: number | null
  mem_usage?: string | null
  mem_used_bytes?: number | null
  mem_limit_bytes?: number | null
  net_io?: string | null
  net_rx_bytes?: number | null
  net_tx_bytes?: number | null
  block_io?: string | null
  block_read_bytes?: number | null
  block_write_bytes?: number | null
  pids?: number | null
}

type StatsRow = {
  id: string
  name?: string
  cpu_percent?: number | null
  cpu_percent_raw?: string | null
  mem_percent?: number | null
  mem_percent_raw?: string | null
  mem_usage?: string | null
  mem_used_bytes?: number | null
  mem_limit_bytes?: number | null
  net_io?: string | null
  net_rx_bytes?: number | null
  net_tx_bytes?: number | null
  block_io?: string | null
  block_read_bytes?: number | null
  block_write_bytes?: number | null
  pids?: number | null
}

type ResourcesTotal = {
  containers_total?: number
  containers_with_stats?: number
  host_cpus?: number | null
  host_memory_bytes?: number | null
  cpu_percent?: number | null
  cpu_percent_of_host?: number | null
  mem_used_bytes?: number | null
  mem_percent_of_host?: number | null
  net_rx_bytes?: number | null
  net_tx_bytes?: number | null
  net_total_bytes?: number | null
  block_read_bytes?: number | null
  block_write_bytes?: number | null
  block_total_bytes?: number | null
  size_rw_bytes?: number | null
  pids?: number | null
  disk_images_bytes?: number | null
  disk_containers_bytes?: number | null
  disk_volumes_bytes?: number | null
  disk_build_cache_bytes?: number | null
  disk_total_bytes?: number | null
}

type DockerData = {
  installed: boolean
  available: boolean
  active: boolean
  binary?: string | null
  version?: string | null
  server_version?: string | null
  error?: string | null
  containers?: number
  containers_running?: number
  containers_paused?: number
  containers_stopped?: number
  images?: number
  volumes?: number
  networks?: number
  driver?: string
  root_dir?: string
  operating_system?: string
  architecture?: string
  cpus?: number
  memory_total?: number
  swarm?: string
  name?: string
  containers_list?: ContainerRow[]
  stats?: StatsRow[]
  images_list?: any[]
  volumes_list?: any[]
  networks_list?: any[]
  disk_usage?: any
  resources_total?: ResourcesTotal | null
  info?: any
}

function MetricTile({
  title,
  value,
  hint,
}: {
  title: string
  value: ReactNode
  hint?: string
}) {
  return (
    <div
      style={{
        padding: 14,
        borderRadius: 14,
        border: '1px solid var(--la-panel-border)',
        background: 'color-mix(in srgb, var(--la-panel) 60%, transparent)',
        height: '100%',
      }}
    >
      <div className="la-panel-title" style={{ marginBottom: 8 }}>
        {title}
      </div>
      <div className="mono" style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.02em' }}>
        {value}
      </div>
      {hint ? (
        <div style={{ color: 'var(--la-muted)', fontSize: 12, marginTop: 4 }}>{hint}</div>
      ) : null}
    </div>
  )
}

function stateColor(state?: string) {
  const s = (state || '').toLowerCase()
  if (s === 'running') return 'success'
  if (s === 'paused') return 'warning'
  if (s === 'exited' || s === 'dead') return 'default'
  if (s === 'restarting' || s === 'created') return 'processing'
  return 'default'
}

function dash(v: unknown): string {
  if (v == null || v === '') return '—'
  return String(v)
}

function formatIoPair(rx?: number | null, tx?: number | null, fallback?: string | null): string {
  if (rx != null || tx != null) {
    return `${formatBytes(rx ?? 0)} / ${formatBytes(tx ?? 0)}`
  }
  return dash(fallback)
}

function PercentCell({
  percent,
  label,
  tooltip,
}: {
  percent?: number | null
  label?: string
  tooltip?: string
}) {
  if (percent == null || Number.isNaN(percent)) {
    return <Typography.Text type="secondary">—</Typography.Text>
  }
  const color = pctColor(percent)
  const body = (
    <div style={{ minWidth: 88 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          gap: 8,
          marginBottom: 2,
          fontSize: 12,
        }}
      >
        <span className="mono" style={{ color, fontWeight: 600 }}>
          {percent.toFixed(percent >= 10 ? 1 : 2)}%
        </span>
        {label ? (
          <span className="mono" style={{ color: 'var(--la-muted)', fontSize: 11 }}>
            {label}
          </span>
        ) : null}
      </div>
      <Progress
        percent={Math.min(100, Math.max(0, percent))}
        showInfo={false}
        size="small"
        strokeColor={color}
        trailColor="color-mix(in srgb, var(--la-muted) 18%, transparent)"
      />
    </div>
  )
  return tooltip ? <Tooltip title={tooltip}>{body}</Tooltip> : body
}

function DiskUsageCards({ disk }: { disk: any }) {
  const rows: any[] = Array.isArray(disk) ? disk : disk ? [disk] : []
  if (!rows.length) {
    return <Typography.Text type="secondary">No disk data</Typography.Text>
  }
  return (
    <Row gutter={[12, 12]}>
      {rows.map((r, i) => (
        <Col xs={24} sm={12} md={8} key={`${r.Type || r.type || i}`}>
          <div
            style={{
              padding: 14,
              borderRadius: 14,
              border: '1px solid var(--la-panel-border)',
              background: 'color-mix(in srgb, var(--la-panel) 60%, transparent)',
            }}
          >
            <div className="la-panel-title" style={{ marginBottom: 8 }}>
              {r.Type || r.type || '—'}
            </div>
            <div className="mono" style={{ fontSize: 18, fontWeight: 600 }}>
              {r.Size || r.size || '—'}
            </div>
            <div style={{ color: 'var(--la-muted)', fontSize: 12, marginTop: 4 }}>
              Active: {r.Active || r.active || '—'}
              {r.Reclaimable || r.reclaimable
                ? ` · Reclaimable: ${r.Reclaimable || r.reclaimable}`
                : ''}
            </div>
          </div>
        </Col>
      ))}
    </Row>
  )
}

export function DockerPage() {
  const { moduleOpts } = useAppSettings()
  const opts = moduleOpts('docker')
  const [data, setData] = useState<DockerData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const next = await api<DockerData>('/api/docker')
      setData(next)
      setError(null)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const t = window.setInterval(() => void load(), 10000)
    return () => window.clearInterval(t)
  }, [load])

  if (error && !data) return <Alert type="error" message={error} showIcon />
  if (!data) return <Typography.Text type="secondary">Loading…</Typography.Text>

  if (!data.installed) {
    return (
      <div className="la-page">
        <PageHeader title="Docker" subtitle="Containers, images, volumes, and networks" />
        <Alert
          type="info"
          showIcon
          message="Docker is not installed"
          description="The docker binary is not on this host — the daemon is not polled in detail, so no extra load is created."
        />
      </div>
    )
  }

  if (!data.available) {
    return (
      <div className="la-page">
        <PageHeader
          docsKey="docker"
          title="Docker"
          subtitle={data.version ? `client ${data.version}` : data.binary || undefined}
        />
        <Alert
          type="warning"
          showIcon
          message="Docker unavailable"
          description={data.error || 'Daemon is not responding. Check the docker service and permissions on /var/run/docker.sock.'}
        />
      </div>
    )
  }

  return (
    <div className="la-page">
      <PageHeader
        live
        title="Docker"
        subtitle={
          data.server_version
            ? `server ${data.server_version}${data.version ? ` · client ${data.version}` : ''} · auto-refresh 10s`
            : data.version || undefined
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
              Refresh
            </Button>
            <Tag color="success" style={{ marginInlineEnd: 0 }}>
              active
            </Tag>
          </Space>
        }
      />

      {error ? <Alert type="warning" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Panel title="Containers">
            <div className="mono display" style={{ fontSize: 32, fontWeight: 700 }}>
              {data.containers_running ?? 0}
              <span style={{ fontSize: 14, color: 'var(--la-muted)', fontWeight: 500 }}>
                /{data.containers ?? 0}
              </span>
            </div>
            <Typography.Text type="secondary">running / total</Typography.Text>
          </Panel>
        </Col>
        <Col xs={12} md={6}>
          <Panel title="Images">
            <div className="mono display" style={{ fontSize: 32, fontWeight: 700 }}>
              {data.images ?? 0}
            </div>
          </Panel>
        </Col>
        <Col xs={12} md={6}>
          <Panel title="Volumes">
            <div className="mono display" style={{ fontSize: 32, fontWeight: 700 }}>
              {data.volumes ?? 0}
            </div>
          </Panel>
        </Col>
        <Col xs={12} md={6}>
          <Panel title="Networks">
            <div className="mono display" style={{ fontSize: 32, fontWeight: 700 }}>
              {data.networks ?? 0}
            </div>
          </Panel>
        </Col>
      </Row>

      {data.resources_total ? (
        <Panel
          title="Total resources"
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              sum of {data.resources_total.containers_with_stats ?? 0} running · host{' '}
              {data.resources_total.host_cpus ?? data.cpus ?? '—'} CPU /{' '}
              {formatBytes(data.resources_total.host_memory_bytes ?? data.memory_total)}
            </Typography.Text>
          }
        >
          <Row gutter={[16, 16]}>
            <Col xs={12} md={6}>
              <GaugeCard
                title="CPU (all containers)"
                percent={data.resources_total.cpu_percent_of_host}
                subtitle={
                  data.resources_total.cpu_percent != null
                    ? `${data.resources_total.cpu_percent.toFixed(1)}% core-eq · of host`
                    : undefined
                }
              />
            </Col>
            <Col xs={12} md={6}>
              <GaugeCard
                title="RAM (all containers)"
                percent={data.resources_total.mem_percent_of_host}
                subtitle={
                  data.resources_total.mem_used_bytes != null
                    ? `${formatBytes(data.resources_total.mem_used_bytes)} / ${formatBytes(
                        data.resources_total.host_memory_bytes ?? data.memory_total,
                      )}`
                    : undefined
                }
              />
            </Col>
            <Col xs={24} md={12}>
              <Row gutter={[12, 12]}>
                <Col xs={12} sm={8}>
                  <MetricTile
                    title="Network I/O"
                    value={formatIoPair(
                      data.resources_total.net_rx_bytes,
                      data.resources_total.net_tx_bytes,
                    )}
                    hint="RX / TX total"
                  />
                </Col>
                <Col xs={12} sm={8}>
                  <MetricTile
                    title="Block I/O"
                    value={formatIoPair(
                      data.resources_total.block_read_bytes,
                      data.resources_total.block_write_bytes,
                    )}
                    hint="Read / Write total"
                  />
                </Col>
                <Col xs={12} sm={8}>
                  <MetricTile
                    title="PIDs"
                    value={dash(data.resources_total.pids)}
                    hint="processes in containers"
                  />
                </Col>
                <Col xs={12} sm={8}>
                  <MetricTile
                    title="Writable disk"
                    value={formatBytes(data.resources_total.size_rw_bytes)}
                    hint="container RW layers"
                  />
                </Col>
                <Col xs={12} sm={8}>
                  <MetricTile
                    title="Images disk"
                    value={formatBytes(data.resources_total.disk_images_bytes)}
                    hint="docker images"
                  />
                </Col>
                <Col xs={12} sm={8}>
                  <MetricTile
                    title="Docker disk"
                    value={formatBytes(data.resources_total.disk_total_bytes)}
                    hint={
                      [
                        data.resources_total.disk_volumes_bytes != null
                          ? `vol ${formatBytes(data.resources_total.disk_volumes_bytes)}`
                          : null,
                        data.resources_total.disk_build_cache_bytes != null
                          ? `cache ${formatBytes(data.resources_total.disk_build_cache_bytes)}`
                          : null,
                      ]
                        .filter(Boolean)
                        .join(' · ') || 'images + containers + volumes'
                    }
                  />
                </Col>
              </Row>
            </Col>
          </Row>
        </Panel>
      ) : null}

      <Panel>
        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }}>
          <Descriptions.Item label="Host">{data.name || '—'}</Descriptions.Item>
          <Descriptions.Item label="Driver">{data.driver || '—'}</Descriptions.Item>
          <Descriptions.Item label="OS">{data.operating_system || '—'}</Descriptions.Item>
          <Descriptions.Item label="Arch">{data.architecture || '—'}</Descriptions.Item>
          <Descriptions.Item label="CPUs">{data.cpus ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="Memory">
            <span className="mono">{formatBytes(data.memory_total)}</span>
          </Descriptions.Item>
          <Descriptions.Item label="Root dir" span={2}>
            <span className="mono">{data.root_dir || '—'}</span>
          </Descriptions.Item>
          <Descriptions.Item label="Swarm">{data.swarm || '—'}</Descriptions.Item>
          <Descriptions.Item label="Stopped">{data.containers_stopped ?? 0}</Descriptions.Item>
          <Descriptions.Item label="Paused">{data.containers_paused ?? 0}</Descriptions.Item>
          <Descriptions.Item label="Binary">
            <span className="mono">{data.binary}</span>
          </Descriptions.Item>
        </Descriptions>
      </Panel>

      {data.disk_usage ? (
        <Panel title="Disk usage (docker system df)">
          <DiskUsageCards disk={data.disk_usage} />
        </Panel>
      ) : null}

      <Panel padded={false} bodyStyle={{ padding: '4px 12px 12px' }}>
        <Tabs
          items={[
            {
              key: 'containers',
              label: `Containers (${data.containers_list?.length || 0})`,
              children: (
                <Table<ContainerRow>
                  size="small"
                  rowKey={(r) => r.id_full || r.id}
                  pagination={tablePagination(25)}
                  scroll={{ x: 1400 }}
                  dataSource={data.containers_list || []}
                  columns={[
                    {
                      title: 'Name',
                      dataIndex: 'names',
                      fixed: 'left',
                      width: 160,
                      ellipsis: true,
                      render: (v, r) => (
                        <Tooltip title={r.id_full || r.id}>
                          <span className="mono">{v || r.id}</span>
                        </Tooltip>
                      ),
                    },
                    {
                      title: 'State',
                      dataIndex: 'state',
                      width: 100,
                      render: (v) => <Tag color={stateColor(v)}>{v || '—'}</Tag>,
                    },
                    {
                      title: 'CPU',
                      dataIndex: 'cpu_percent',
                      width: 120,
                      sorter: (a, b) => (a.cpu_percent ?? -1) - (b.cpu_percent ?? -1),
                      render: (v) => <PercentCell percent={v} />,
                    },
                    {
                      title: 'Memory',
                      dataIndex: 'mem_percent',
                      width: 150,
                      sorter: (a, b) => (a.mem_percent ?? -1) - (b.mem_percent ?? -1),
                      render: (_, r) => (
                        <PercentCell
                          percent={r.mem_percent}
                          label={
                            r.mem_used_bytes != null ? formatBytes(r.mem_used_bytes) : undefined
                          }
                          tooltip={
                            r.mem_usage ||
                            (r.mem_used_bytes != null
                              ? `${formatBytes(r.mem_used_bytes)} / ${formatBytes(r.mem_limit_bytes)}`
                              : undefined)
                          }
                        />
                      ),
                    },
                    {
                      title: 'Net I/O',
                      key: 'net',
                      width: 150,
                      sorter: (a, b) =>
                        (a.net_rx_bytes ?? 0) +
                        (a.net_tx_bytes ?? 0) -
                        ((b.net_rx_bytes ?? 0) + (b.net_tx_bytes ?? 0)),
                      render: (_, r) => (
                        <Tooltip title="RX / TX">
                          <span className="mono" style={{ fontSize: 12 }}>
                            {formatIoPair(r.net_rx_bytes, r.net_tx_bytes, r.net_io)}
                          </span>
                        </Tooltip>
                      ),
                    },
                    {
                      title: 'Block I/O',
                      key: 'block',
                      width: 150,
                      sorter: (a, b) =>
                        (a.block_read_bytes ?? 0) +
                        (a.block_write_bytes ?? 0) -
                        ((b.block_read_bytes ?? 0) + (b.block_write_bytes ?? 0)),
                      render: (_, r) => (
                        <Tooltip title="Read / Write">
                          <span className="mono" style={{ fontSize: 12 }}>
                            {formatIoPair(r.block_read_bytes, r.block_write_bytes, r.block_io)}
                          </span>
                        </Tooltip>
                      ),
                    },
                    {
                      title: 'Disk',
                      key: 'disk',
                      width: 120,
                      sorter: (a, b) => (a.size_rw_bytes ?? -1) - (b.size_rw_bytes ?? -1),
                      render: (_, r) => (
                        <Tooltip
                          title={
                            r.size_virtual_bytes != null
                              ? `Writable: ${formatBytes(r.size_rw_bytes)} · Virtual: ${formatBytes(r.size_virtual_bytes)}`
                              : r.size || undefined
                          }
                        >
                          <span className="mono" style={{ fontSize: 12 }}>
                            {r.size_rw_bytes != null ? formatBytes(r.size_rw_bytes) : dash(r.size)}
                          </span>
                        </Tooltip>
                      ),
                    },
                    {
                      title: 'PIDs',
                      dataIndex: 'pids',
                      width: 70,
                      sorter: (a, b) => (a.pids ?? -1) - (b.pids ?? -1),
                      render: (v) => <span className="mono">{dash(v)}</span>,
                    },
                    { title: 'Image', dataIndex: 'image', ellipsis: true, width: 180 },
                    { title: 'Status', dataIndex: 'status', ellipsis: true, width: 160 },
                    { title: 'Ports', dataIndex: 'ports', ellipsis: true, width: 140 },
                  ]}
                />
              ),
            },
            {
              key: 'stats',
              label: `Stats (${data.stats?.length || 0})`,
              children: (data.stats || []).length ? (
                <Table<StatsRow>
                  size="small"
                  rowKey={(r) => `${r.id}-${r.name}`}
                  pagination={false}
                  scroll={{ x: 1100 }}
                  dataSource={data.stats || []}
                  columns={[
                    {
                      title: 'Name',
                      dataIndex: 'name',
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'CPU',
                      dataIndex: 'cpu_percent',
                      width: 120,
                      sorter: (a, b) => (a.cpu_percent ?? -1) - (b.cpu_percent ?? -1),
                      defaultSortOrder: 'descend',
                      render: (v) => <PercentCell percent={v} />,
                    },
                    {
                      title: 'Memory',
                      dataIndex: 'mem_percent',
                      width: 160,
                      sorter: (a, b) => (a.mem_percent ?? -1) - (b.mem_percent ?? -1),
                      render: (_, r) => (
                        <PercentCell
                          percent={r.mem_percent}
                          label={
                            r.mem_used_bytes != null ? formatBytes(r.mem_used_bytes) : undefined
                          }
                          tooltip={r.mem_usage || undefined}
                        />
                      ),
                    },
                    {
                      title: 'MEM usage',
                      dataIndex: 'mem_usage',
                      render: (v, r) => (
                        <span className="mono">
                          {r.mem_used_bytes != null
                            ? `${formatBytes(r.mem_used_bytes)} / ${formatBytes(r.mem_limit_bytes)}`
                            : dash(v)}
                        </span>
                      ),
                    },
                    {
                      title: 'NET I/O',
                      key: 'net',
                      render: (_, r) => (
                        <span className="mono">
                          {formatIoPair(r.net_rx_bytes, r.net_tx_bytes, r.net_io)}
                        </span>
                      ),
                    },
                    {
                      title: 'Block I/O',
                      key: 'block',
                      render: (_, r) => (
                        <span className="mono">
                          {formatIoPair(r.block_read_bytes, r.block_write_bytes, r.block_io)}
                        </span>
                      ),
                    },
                    {
                      title: 'PIDs',
                      dataIndex: 'pids',
                      width: 70,
                      render: (v) => <span className="mono">{dash(v)}</span>,
                    },
                  ]}
                />
              ) : (
                <Alert type="info" showIcon message="No running containers for stats" />
              ),
            },
            {
              key: 'images',
              label: `Images (${data.images_list?.length || 0})`,
              children: (
                <Table
                  size="small"
                  rowKey={(r) => r.id_full || `${r.repository}:${r.tag}`}
                  pagination={tablePagination(25)}
                  dataSource={data.images_list || []}
                  columns={[
                    {
                      title: 'ID',
                      dataIndex: 'id',
                      width: 100,
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'Repository',
                      dataIndex: 'repository',
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    { title: 'Tag', dataIndex: 'tag', width: 120 },
                    {
                      title: 'Size',
                      dataIndex: 'size',
                      width: 110,
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    { title: 'Created', dataIndex: 'created', width: 180 },
                  ]}
                />
              ),
            },
            {
              key: 'volumes',
              label: `Volumes (${data.volumes_list?.length || 0})`,
              children: (
                <Table
                  size="small"
                  rowKey={(r) => r.name}
                  pagination={tablePagination(25)}
                  dataSource={data.volumes_list || []}
                  columns={[
                    {
                      title: 'Name',
                      dataIndex: 'name',
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    { title: 'Driver', dataIndex: 'driver', width: 120 },
                    { title: 'Scope', dataIndex: 'scope', width: 100 },
                    {
                      title: 'Mountpoint',
                      dataIndex: 'mountpoint',
                      ellipsis: true,
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    { title: 'Created', dataIndex: 'created', width: 180 },
                  ]}
                />
              ),
            },
            {
              key: 'networks',
              label: `Networks (${data.networks_list?.length || 0})`,
              children: (
                <Table
                  size="small"
                  rowKey={(r) => r.id || r.name}
                  pagination={tablePagination(25)}
                  dataSource={data.networks_list || []}
                  columns={[
                    {
                      title: 'ID',
                      dataIndex: 'id',
                      width: 100,
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'Name',
                      dataIndex: 'name',
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    { title: 'Driver', dataIndex: 'driver', width: 120 },
                    { title: 'Scope', dataIndex: 'scope', width: 100 },
                    {
                      title: 'IPv6',
                      dataIndex: 'ipv6',
                      width: 80,
                      render: (v) => (v ? 'yes' : 'no'),
                    },
                    {
                      title: 'Internal',
                      dataIndex: 'internal',
                      width: 90,
                      render: (v) => (v ? 'yes' : 'no'),
                    },
                  ]}
                />
              ),
            },
            {
              key: 'info',
              label: 'Info',
              children: data.info ? (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Descriptions size="small" column={1} bordered>
                    <Descriptions.Item label="ID">
                      <span className="mono">{data.info.ID || '—'}</span>
                    </Descriptions.Item>
                    <Descriptions.Item label="Kernel">
                      {data.info.KernelVersion || '—'}
                    </Descriptions.Item>
                    <Descriptions.Item label="Storage driver">
                      {data.info.Driver || '—'}
                    </Descriptions.Item>
                    <Descriptions.Item label="Logging driver">
                      {data.info.LoggingDriver || '—'}
                    </Descriptions.Item>
                    <Descriptions.Item label="Cgroup driver">
                      {data.info.CgroupDriver || '—'}
                    </Descriptions.Item>
                    <Descriptions.Item label="Plugins">
                      <span className="mono" style={{ fontSize: 12 }}>
                        {JSON.stringify(data.info.Plugins || {}, null, 0)}
                      </span>
                    </Descriptions.Item>
                    <Descriptions.Item label="Runtimes">
                      <span className="mono" style={{ fontSize: 12 }}>
                        {Object.keys(data.info.Runtimes || {}).join(', ') || '—'}
                      </span>
                    </Descriptions.Item>
                  </Descriptions>
                  {opts.show_info_raw !== false ? (
                    <pre className="la-log" style={{ maxHeight: 360 }}>
                      {JSON.stringify(data.info, null, 2)}
                    </pre>
                  ) : null}
                </Space>
              ) : (
                <Alert type="info" showIcon message="Info unavailable" />
              ),
            },
          ]}
        />
      </Panel>
    </div>
  )
}
