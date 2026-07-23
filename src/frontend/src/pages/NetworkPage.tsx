import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Col,
  Input,
  Row,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import { useAppSettings } from '../api/settings'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { tablePagination } from '../utils/tablePagination'

type ConnRow = {
  pid?: number | null
  process?: string | null
  username?: string | null
  cmdline?: string | null
  status: string
  family: string
  ip_version: string
  local_addr: string
  remote_addr: string
  local?: { ip?: string; port?: number }
  remote?: { ip?: string; port?: number }
}

type NetworkData = {
  available: boolean
  disabled?: boolean
  error?: string | null
  allow_mutations?: boolean
  allow_kill?: boolean
  listening?: number
  established?: number
  total?: number
  by_status?: Record<string, number>
  interfaces_up?: number
  listening_ports?: ConnRow[]
  connections?: ConnRow[]
  interfaces_detail?: Array<{
    name: string
    isup: boolean
    speed: number
    mtu: number
    ipv4: string[]
    ipv6: string[]
  }>
}

function statusColor(status: string) {
  const s = status.toUpperCase()
  if (s === 'LISTEN') return 'processing'
  if (s === 'ESTABLISHED') return 'success'
  if (s === 'TIME_WAIT' || s === 'CLOSE_WAIT') return 'warning'
  return 'default'
}

export function NetworkPage() {
  const { moduleOpts } = useAppSettings()
  const opts = moduleOpts('network')
  const [data, setData] = useState<NetworkData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [busy, setBusy] = useState(false)

  const load = () => {
    void api<NetworkData>('/api/network')
      .then(setData)
      .catch((e) => setError(String(e)))
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [])

  const canMut = !!(data?.allow_mutations ?? opts.allow_mutations)
  const canKill = canMut && opts.allow_kill !== false

  const setIface = async (name: string, state: 'up' | 'down') => {
    setBusy(true)
    try {
      const res = await api<{ ok?: boolean; error?: string }>('/api/network/iface', {
        method: 'POST',
        body: JSON.stringify({ name, state }),
      })
      if (res?.ok === false) message.error(res.error || 'Error')
      else {
        message.success(`${name} → ${state}`)
        load()
      }
    } catch (e) {
      message.error(String(e))
    } finally {
      setBusy(false)
    }
  }

  const killPid = async (pid: number) => {
    setBusy(true)
    try {
      const res = await api<{ ok?: boolean; error?: string }>('/api/network/kill', {
        method: 'POST',
        body: JSON.stringify({ pid, signal: 'TERM' }),
      })
      if (res?.ok === false) message.error(res.error || 'Error')
      else {
        message.success(`kill TERM ${pid}`)
        load()
      }
    } catch (e) {
      message.error(String(e))
    } finally {
      setBusy(false)
    }
  }

  const listening = useMemo(() => {
    const rows = data?.listening_ports || []
    const q = filter.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(
      (r) =>
        r.local_addr?.toLowerCase().includes(q) ||
        r.process?.toLowerCase().includes(q) ||
        String(r.pid || '').includes(q) ||
        r.username?.toLowerCase().includes(q) ||
        r.cmdline?.toLowerCase().includes(q),
    )
  }, [data, filter])

  const connections = useMemo(() => {
    let rows = data?.connections || []
    if (statusFilter) {
      rows = rows.filter((r) => r.status === statusFilter)
    }
    const q = filter.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(
      (r) =>
        r.local_addr?.toLowerCase().includes(q) ||
        r.remote_addr?.toLowerCase().includes(q) ||
        r.process?.toLowerCase().includes(q) ||
        String(r.pid || '').includes(q) ||
        r.username?.toLowerCase().includes(q) ||
        r.cmdline?.toLowerCase().includes(q),
    )
  }, [data, filter, statusFilter])

  const statusOptions = useMemo(() => {
    const keys = Object.keys(data?.by_status || {}).filter((k) => k !== 'LISTEN')
    return keys.map((k) => ({ value: k, label: `${k} (${data?.by_status?.[k] || 0})` }))
  }, [data])

  if (error) return <Alert type="error" message={error} showIcon />
  if (!data) return <Typography.Text type="secondary">Loading…</Typography.Text>

  if (data.disabled || !data.available) {
    return (
      <div className="la-page">
        <PageHeader title="Network" subtitle="Ports and processes" />
        <Alert
          type="warning"
          showIcon
          message={data.disabled ? 'Module disabled' : 'Network unavailable'}
          description={data.error || 'No data'}
        />
      </div>
    )
  }

  const connColumns = [
    {
      title: 'PID',
      dataIndex: 'pid',
      width: 80,
      render: (v: number | null) => <span className="mono">{v ?? '—'}</span>,
    },
    {
      title: 'Process',
      dataIndex: 'process',
      width: 140,
      ellipsis: true,
      render: (v: string) => <span className="mono">{v || '—'}</span>,
    },
    {
      title: 'User',
      dataIndex: 'username',
      width: 100,
      ellipsis: true,
    },
    {
      title: 'Proto',
      dataIndex: 'family',
      width: 70,
      render: (v: string, r: ConnRow) => (
        <span className="mono">
          {v}/{r.ip_version}
        </span>
      ),
    },
    {
      title: 'Local',
      dataIndex: 'local_addr',
      render: (v: string) => <span className="mono">{v}</span>,
    },
    {
      title: 'Remote',
      dataIndex: 'remote_addr',
      render: (v: string) => <span className="mono">{v}</span>,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      width: 130,
      render: (v: string) => <Tag color={statusColor(v)}>{v}</Tag>,
    },
    ...(canKill
      ? [
          {
            title: '',
            key: 'kill',
            width: 80,
            render: (_: unknown, r: ConnRow) =>
              r.pid ? (
                <Button
                  danger
                  type="link"
                  size="small"
                  disabled={busy}
                  onClick={() => void killPid(r.pid!)}
                >
                  Kill
                </Button>
              ) : null,
          },
        ]
      : []),
  ]

  return (
    <div className="la-page">
      <PageHeader
        title="Network"
        subtitle="Listening ports, active connections, and the processes holding them"
        live
        extra={
          <Space wrap>
            <Input.Search
              allowClear
              placeholder="Filter: port, PID, process…"
              style={{ width: 260 }}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <Button icon={<ReloadOutlined />} onClick={load}>
              Refresh
            </Button>
          </Space>
        }
      />

      {!canMut ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Read-only mode. Enable “Allow management” for Network in Settings (iface up/down, kill)."
        />
      ) : null}

      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Panel title="Listening">
            <div className="mono display" style={{ fontSize: 32, fontWeight: 700 }}>
              {data.listening ?? 0}
            </div>
          </Panel>
        </Col>
        <Col xs={12} md={6}>
          <Panel title="Established">
            <div className="mono display" style={{ fontSize: 32, fontWeight: 700 }}>
              {data.established ?? 0}
            </div>
          </Panel>
        </Col>
        <Col xs={12} md={6}>
          <Panel title="Total sockets">
            <div className="mono display" style={{ fontSize: 32, fontWeight: 700 }}>
              {data.total ?? 0}
            </div>
          </Panel>
        </Col>
        <Col xs={12} md={6}>
          <Panel title="Interfaces up">
            <div className="mono display" style={{ fontSize: 32, fontWeight: 700 }}>
              {data.interfaces_up ?? 0}
            </div>
          </Panel>
        </Col>
      </Row>

      {opts.show_interfaces !== false && (data.interfaces_detail || []).length ? (
        <Panel title="Interfaces" padded={false} bodyStyle={{ padding: '8px 8px 12px' }}>
          <Table
            size="small"
            rowKey="name"
            pagination={false}
            dataSource={data.interfaces_detail}
            columns={[
              {
                title: 'Name',
                dataIndex: 'name',
                render: (v) => <span className="mono">{v}</span>,
              },
              {
                title: 'State',
                dataIndex: 'isup',
                width: 90,
                render: (v) => (
                  <Tag color={v ? 'success' : 'default'}>{v ? 'up' : 'down'}</Tag>
                ),
              },
              {
                title: 'Speed',
                dataIndex: 'speed',
                width: 100,
                render: (v) => <span className="mono">{v ? `${v} Mb/s` : '—'}</span>,
              },
              { title: 'MTU', dataIndex: 'mtu', width: 80 },
              {
                title: 'IPv4',
                dataIndex: 'ipv4',
                render: (v: string[]) => (
                  <span className="mono">{(v || []).join(', ') || '—'}</span>
                ),
              },
              {
                title: 'IPv6',
                dataIndex: 'ipv6',
                ellipsis: true,
                render: (v: string[]) => (
                  <span className="mono">{(v || []).slice(0, 2).join(', ') || '—'}</span>
                ),
              },
              ...(canMut
                ? [
                    {
                      title: '',
                      key: 'act',
                      width: 120,
                      render: (_: unknown, row: { name: string; isup: boolean }) =>
                        row.name === 'lo' ? null : (
                          <Button
                            size="small"
                            type="link"
                            loading={busy}
                            onClick={() => void setIface(row.name, row.isup ? 'down' : 'up')}
                          >
                            {row.isup ? 'Down' : 'Up'}
                          </Button>
                        ),
                    },
                  ]
                : []),
            ]}
          />
        </Panel>
      ) : null}

      <Panel padded={false} bodyStyle={{ padding: '4px 12px 12px' }}>
        <Tabs
          items={[
            ...(opts.show_listening !== false
              ? [
                  {
                    key: 'listen',
                    label: `Listening (${listening.length})`,
                    children: (
                      <Table
                        size="small"
                        rowKey={(r) =>
                          `${r.pid}-${r.local_addr}-${r.family}-${r.status}`
                        }
                        pagination={tablePagination(25)}
                        scroll={{ x: true }}
                        dataSource={listening}
                        columns={connColumns.filter((c) => c.dataIndex !== 'remote_addr')}
                        expandable={{
                          expandedRowRender: (r) => (
                            <span className="mono" style={{ fontSize: 12, color: 'var(--la-muted)' }}>
                              {r.cmdline || 'cmdline unavailable'}
                            </span>
                          ),
                        }}
                      />
                    ),
                  },
                ]
              : []),
            {
              key: 'conns',
              label: `Connections (${connections.length})`,
              children: (
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  <Select
                    allowClear
                    placeholder="Filter by status"
                    style={{ width: 240 }}
                    options={statusOptions}
                    value={statusFilter}
                    onChange={setStatusFilter}
                  />
                  <Table
                    size="small"
                    rowKey={(r, i) =>
                      `${r.pid}-${r.local_addr}-${r.remote_addr}-${r.status}-${i}`
                    }
                    pagination={tablePagination(25)}
                    scroll={{ x: true }}
                    dataSource={connections}
                    columns={connColumns}
                    expandable={{
                      expandedRowRender: (r) => (
                        <span className="mono" style={{ fontSize: 12, color: 'var(--la-muted)' }}>
                          {r.cmdline || 'cmdline unavailable'}
                        </span>
                      ),
                    }}
                  />
                </Space>
              ),
            },
            {
              key: 'status',
              label: 'By status',
              children: (
                <Space wrap>
                  {Object.entries(data.by_status || {}).map(([k, v]) => (
                    <Tag key={k} color={statusColor(k)} className="mono">
                      {k}: {v}
                    </Tag>
                  ))}
                </Space>
              ),
            },
          ]}
        />
      </Panel>
    </div>
  )
}
