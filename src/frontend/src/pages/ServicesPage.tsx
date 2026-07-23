import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Col,
  Descriptions,
  Drawer,
  Input,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  ReloadOutlined,
  PoweroffOutlined,
  CheckCircleOutlined,
  StopOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { tablePagination } from '../utils/tablePagination'

type ServiceRow = {
  unit: string
  load: string
  active: string
  sub: string
  description: string
  enabled?: string
}

type Overview = {
  available: boolean
  disabled?: boolean
  error?: string | null
  services: ServiceRow[]
  counts?: { total?: number; active?: number; failed?: number; inactive?: number }
  allow_mutations?: boolean
}

type Detail = {
  available: boolean
  error?: string
  unit: string
  info: Record<string, string>
  status_text?: string
  journal?: string[]
  active?: string
  sub?: string
  enabled?: string
  description?: string
  main_pid?: string
  fragment?: string
  allow_mutations?: boolean
}

function activeColor(state?: string) {
  if (state === 'active') return 'success'
  if (state === 'failed') return 'error'
  if (state === 'activating' || state === 'deactivating') return 'processing'
  return 'default'
}

export function ServicesPage() {
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [stateFilter, setStateFilter] = useState<string | undefined>('active')
  const [detail, setDetail] = useState<Detail | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(() => {
    void api<Overview>('/api/services')
      .then(setData)
      .catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const rows = useMemo(() => {
    let list = data?.services || []
    if (stateFilter) {
      list = list.filter((s) => s.active === stateFilter)
    }
    const q = filter.trim().toLowerCase()
    if (q) {
      list = list.filter(
        (s) =>
          s.unit.toLowerCase().includes(q) ||
          s.description?.toLowerCase().includes(q) ||
          s.sub?.toLowerCase().includes(q),
      )
    }
    return list
  }, [data, filter, stateFilter])

  const openDetail = async (unit: string) => {
    try {
      const d = await api<Detail>(`/api/services/${encodeURIComponent(unit)}`)
      setDetail(d)
    } catch (e) {
      message.error(String(e))
    }
  }

  const runAction = async (unit: string, action: string) => {
    setBusy(`${unit}:${action}`)
    try {
      const res = await api<{ ok: boolean; error?: string }>(
        `/api/services/${encodeURIComponent(unit)}/action`,
        { method: 'POST', body: JSON.stringify({ action }) },
      )
      if (!res.ok) {
        message.error(res.error || 'Error')
        return
      }
      message.success(`${action} · ${unit}`)
      load()
      if (detail?.unit === unit) await openDetail(unit)
    } catch (e) {
      message.error(String(e))
    } finally {
      setBusy(null)
    }
  }

  if (error) return <Alert type="error" message={error} showIcon />
  if (!data) return <Typography.Text type="secondary">Loading…</Typography.Text>

  if (data.disabled || !data.available) {
    return (
      <div className="la-page">
        <PageHeader title="Services" />
        <Alert type="warning" showIcon message={data.error || 'Module unavailable'} />
      </div>
    )
  }

  const counts = data.counts || {}

  return (
    <div className="la-page">
      <PageHeader
        title="Services"
        subtitle="systemd services: status, logs, and management"
        extra={
          <Space wrap>
            <Input.Search
              allowClear
              placeholder="Filter unit / description"
              style={{ width: 260 }}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <Select
              allowClear
              placeholder="Active state"
              style={{ width: 160 }}
              value={stateFilter}
              onChange={setStateFilter}
              options={[
                { value: 'active', label: 'active' },
                { value: 'failed', label: 'failed' },
                { value: 'inactive', label: 'inactive' },
                { value: 'activating', label: 'activating' },
              ]}
            />
            <Button icon={<ReloadOutlined />} onClick={load}>
              Refresh
            </Button>
          </Space>
        }
      />

      {!data.allow_mutations ? (
        <Alert
          type="info"
          showIcon
          message="View-only mode"
          description="To start/stop/restart/enable/disable, enable “Allow management” in Settings → Services."
        />
      ) : null}

      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Panel title="Total">
            <div className="mono display" style={{ fontSize: 32, fontWeight: 700 }}>
              {counts.total ?? 0}
            </div>
          </Panel>
        </Col>
        <Col xs={12} md={6}>
          <Panel title="Active">
            <div className="mono display" style={{ fontSize: 32, fontWeight: 700, color: 'var(--la-ok)' }}>
              {counts.active ?? 0}
            </div>
          </Panel>
        </Col>
        <Col xs={12} md={6}>
          <Panel title="Failed">
            <div
              className="mono display"
              style={{ fontSize: 32, fontWeight: 700, color: 'var(--la-danger)' }}
            >
              {counts.failed ?? 0}
            </div>
          </Panel>
        </Col>
        <Col xs={12} md={6}>
          <Panel title="Inactive">
            <div className="mono display" style={{ fontSize: 32, fontWeight: 700 }}>
              {counts.inactive ?? 0}
            </div>
          </Panel>
        </Col>
      </Row>

      <Panel title={`Services (${rows.length})`} padded={false} bodyStyle={{ padding: '8px 8px 12px' }}>
        <Table
          size="small"
          rowKey="unit"
          pagination={tablePagination(25)}
          dataSource={rows}
          onRow={(r) => ({
            onClick: () => void openDetail(r.unit),
            style: { cursor: 'pointer' },
          })}
          columns={[
            {
              title: 'Unit',
              dataIndex: 'unit',
              render: (v) => (
                <span className="mono" style={{ fontWeight: 600 }}>
                  {v}
                </span>
              ),
            },
            {
              title: 'Active',
              dataIndex: 'active',
              width: 110,
              render: (v) => <Tag color={activeColor(v)}>{v}</Tag>,
            },
            {
              title: 'Sub',
              dataIndex: 'sub',
              width: 110,
              render: (v) => <span className="mono">{v}</span>,
            },
            {
              title: 'Enabled',
              dataIndex: 'enabled',
              width: 110,
              render: (v) => <Tag>{v || '—'}</Tag>,
            },
            {
              title: 'Description',
              dataIndex: 'description',
              ellipsis: true,
            },
            ...(data.allow_mutations
              ? [
                  {
                    title: '',
                    key: 'actions',
                    width: 200,
                    render: (_: unknown, r: ServiceRow) => (
                      <Space
                        size={4}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Button
                          size="small"
                          icon={<PlayCircleOutlined />}
                          loading={busy === `${r.unit}:start`}
                          onClick={() => void runAction(r.unit, 'start')}
                        />
                        <Button
                          size="small"
                          icon={<PauseCircleOutlined />}
                          loading={busy === `${r.unit}:stop`}
                          onClick={() => void runAction(r.unit, 'stop')}
                        />
                        <Button
                          size="small"
                          icon={<ReloadOutlined />}
                          loading={busy === `${r.unit}:restart`}
                          onClick={() => void runAction(r.unit, 'restart')}
                        />
                      </Space>
                    ),
                  },
                ]
              : []),
          ]}
        />
      </Panel>

      <Drawer
        title={detail ? detail.unit : 'Service'}
        open={!!detail}
        onClose={() => setDetail(null)}
        width={560}
        destroyOnHidden
      >
        {detail?.available === false ? (
          <Alert type="error" message={detail.error || 'Error'} />
        ) : detail ? (
          <Space orientation="vertical" style={{ width: '100%' }} size="large">
            <Space wrap>
              <Tag color={activeColor(detail.active)}>{detail.active}</Tag>
              <Tag>{detail.sub}</Tag>
              <Tag>{detail.enabled || '—'}</Tag>
            </Space>

            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="Description">
                {detail.description || detail.info?.Description || '—'}
              </Descriptions.Item>
              <Descriptions.Item label="Main PID">
                <span className="mono">{detail.main_pid || detail.info?.MainPID || '—'}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Unit file">
                <span className="mono">{detail.fragment || detail.info?.FragmentPath || '—'}</span>
              </Descriptions.Item>
              <Descriptions.Item label="User/Group">
                <span className="mono">
                  {detail.info?.User || '—'} / {detail.info?.Group || '—'}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="Memory">
                <span className="mono">{detail.info?.MemoryCurrent || '—'}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Tasks">
                <span className="mono">{detail.info?.TasksCurrent || '—'}</span>
              </Descriptions.Item>
            </Descriptions>

            {detail.allow_mutations ? (
              <Space wrap>
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  loading={busy === `${detail.unit}:start`}
                  onClick={() => void runAction(detail.unit, 'start')}
                >
                  Start
                </Button>
                <Button
                  icon={<PoweroffOutlined />}
                  loading={busy === `${detail.unit}:stop`}
                  onClick={() => void runAction(detail.unit, 'stop')}
                >
                  Stop
                </Button>
                <Button
                  icon={<ReloadOutlined />}
                  loading={busy === `${detail.unit}:restart`}
                  onClick={() => void runAction(detail.unit, 'restart')}
                >
                  Restart
                </Button>
                <Button
                  icon={<ReloadOutlined />}
                  loading={busy === `${detail.unit}:reload`}
                  onClick={() => void runAction(detail.unit, 'reload')}
                >
                  Reload
                </Button>
                <Button
                  icon={<CheckCircleOutlined />}
                  loading={busy === `${detail.unit}:enable`}
                  onClick={() => void runAction(detail.unit, 'enable')}
                >
                  Enable
                </Button>
                <Button
                  icon={<StopOutlined />}
                  loading={busy === `${detail.unit}:disable`}
                  onClick={() => void runAction(detail.unit, 'disable')}
                >
                  Disable
                </Button>
              </Space>
            ) : null}

            <div>
              <div className="la-panel-title" style={{ marginBottom: 8 }}>
                journalctl
              </div>
              <pre className="la-log">{(detail.journal || []).join('\n') || 'No entries'}</pre>
            </div>

            {detail.status_text ? (
              <div>
                <div className="la-panel-title" style={{ marginBottom: 8 }}>
                  systemctl status
                </div>
                <pre className="la-log">{detail.status_text}</pre>
              </div>
            ) : null}
          </Space>
        ) : null}
      </Drawer>
    </div>
  )
}
