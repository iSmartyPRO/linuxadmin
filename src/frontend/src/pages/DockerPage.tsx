import { useEffect, useState } from 'react'
import {
  Alert,
  Col,
  Descriptions,
  Row,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { api } from '../api/client'
import { useAppSettings } from '../api/settings'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { tablePagination } from '../utils/tablePagination'
import { formatBytes } from '../utils/format'

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
  containers_list?: any[]
  stats?: any[]
  images_list?: any[]
  volumes_list?: any[]
  networks_list?: any[]
  disk_usage?: any
  info?: any
}

function stateColor(state?: string) {
  const s = (state || '').toLowerCase()
  if (s === 'running') return 'success'
  if (s === 'paused') return 'warning'
  if (s === 'exited' || s === 'dead') return 'default'
  if (s === 'restarting' || s === 'created') return 'processing'
  return 'default'
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

  useEffect(() => {
    void api<DockerData>('/api/docker')
      .then(setData)
      .catch((e) => setError(String(e)))
  }, [])

  if (error) return <Alert type="error" message={error} showIcon />
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
        title="Docker"
        subtitle={
          data.server_version
            ? `server ${data.server_version}${data.version ? ` · client ${data.version}` : ''}`
            : data.version || undefined
        }
        extra={
          <Tag color="success" style={{ marginInlineEnd: 0 }}>
            active
          </Tag>
        }
      />

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
                <Table
                  size="small"
                  rowKey={(r) => r.id_full || r.id}
                  pagination={tablePagination(25)}
                  scroll={{ x: true }}
                  dataSource={data.containers_list || []}
                  columns={[
                    {
                      title: 'ID',
                      dataIndex: 'id',
                      width: 100,
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'Name',
                      dataIndex: 'names',
                      ellipsis: true,
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    { title: 'Image', dataIndex: 'image', ellipsis: true },
                    {
                      title: 'State',
                      dataIndex: 'state',
                      width: 110,
                      render: (v) => <Tag color={stateColor(v)}>{v || '—'}</Tag>,
                    },
                    { title: 'Status', dataIndex: 'status', ellipsis: true },
                    { title: 'Ports', dataIndex: 'ports', ellipsis: true },
                    { title: 'Created', dataIndex: 'created', width: 180 },
                  ]}
                />
              ),
            },
            {
              key: 'stats',
              label: `Stats (${data.stats?.length || 0})`,
              children: (data.stats || []).length ? (
                <Table
                  size="small"
                  rowKey={(r) => `${r.id}-${r.name}`}
                  pagination={false}
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
                      width: 90,
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'MEM %',
                      dataIndex: 'mem_percent',
                      width: 90,
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'MEM usage',
                      dataIndex: 'mem_usage',
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'NET I/O',
                      dataIndex: 'net_io',
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'Block I/O',
                      dataIndex: 'block_io',
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'PIDs',
                      dataIndex: 'pids',
                      width: 70,
                      render: (v) => <span className="mono">{v}</span>,
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
