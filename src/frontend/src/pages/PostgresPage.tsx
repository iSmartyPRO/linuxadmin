import { useEffect, useState } from 'react'
import {
  Alert,
  Col,
  Progress,
  Row,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { api } from '../api/client'
import { formatBytes } from '../utils/format'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'

export function PostgresPage() {
  const [status, setStatus] = useState<any>(null)
  const [activity, setActivity] = useState<any[]>([])
  const [statements, setStatements] = useState<any>(null)
  const [tables, setTables] = useState<any[]>([])
  const [locks, setLocks] = useState<any[]>([])
  const [dbList, setDbList] = useState<string[]>([])
  const [selectedDb, setSelectedDb] = useState<string | undefined>()

  const load = async () => {
    const st = await api<any>('/api/postgres/status')
    setStatus(st)
    if (!st.available) return
    const [act, stmt, dbs, lcks] = await Promise.all([
      api<any>('/api/postgres/activity'),
      api<any>('/api/postgres/statements'),
      api<any>('/api/postgres/databases'),
      api<any>('/api/postgres/locks'),
    ])
    setActivity(Array.isArray(act) ? act : act.rows || [])
    setStatements(stmt)
    setDbList(dbs.databases || [])
    setLocks(Array.isArray(lcks) ? lcks : lcks.rows || [])
  }

  useEffect(() => {
    void load().catch(() => null)
  }, [])

  useEffect(() => {
    if (!status?.available) return
    const q = selectedDb ? `?database=${encodeURIComponent(selectedDb)}` : ''
    void api<any>(`/api/postgres/tables${q}`)
      .then((r) => setTables(Array.isArray(r) ? r : r.rows || []))
      .catch(() => setTables([]))
  }, [selectedDb, status?.available])

  if (!status) return <Typography.Text type="secondary">Loading…</Typography.Text>
  if (!status.available) {
    return (
      <div className="la-page">
        <PageHeader title="PostgreSQL" subtitle="Cluster monitoring" />
        <Alert
          type="warning"
          showIcon
          message="PostgreSQL unavailable"
          description={
            <>
              {status.error || 'Check monitoring credentials in Settings.'}
              {status.capabilities?.hints?.length ? (
                <ul style={{ marginBottom: 0 }}>
                  {status.capabilities.hints.map((h: string) => (
                    <li key={h}>{h}</li>
                  ))}
                </ul>
              ) : null}
            </>
          }
        />
      </div>
    )
  }

  const usage = status.connection_usage_percent ?? 0
  const caps = status.capabilities || {}

  return (
    <div className="la-page">
      <PageHeader
        title="PostgreSQL"
        subtitle={`v${status.version} · ${status.host}:${status.port}${status.username ? ` · ${status.username}` : ''}`}
      />

      {(caps.hints || []).length ? (
        <Alert
          type="info"
          showIcon
          message="Recommendations to improve monitoring"
          description={
            <ul style={{ marginBottom: 0 }}>
              {caps.hints.map((h: string) => (
                <li key={h}>{h}</li>
              ))}
            </ul>
          }
        />
      ) : null}

      <Space wrap>
        <Tag color={caps.is_pg_monitor ? 'success' : 'warning'}>
          pg_monitor: {caps.is_pg_monitor ? 'yes' : 'no'}
        </Tag>
        <Tag color={caps.can_read_settings ? 'success' : 'default'}>
          read settings: {caps.can_read_settings ? 'yes' : 'no'}
        </Tag>
        <Tag color={caps.pg_stat_statements ? 'success' : 'default'}>
          pg_stat_statements: {caps.pg_stat_statements ? 'yes' : 'no'}
        </Tag>
        {caps.current_user ? <Tag className="mono">user: {caps.current_user}</Tag> : null}
      </Space>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <Panel title="Connections">
            <div className="mono display" style={{ fontSize: 36, fontWeight: 700, lineHeight: 1.1 }}>
              {status.connections}
              <span style={{ fontSize: 16, color: 'var(--la-muted)', fontWeight: 500 }}>
                /{status.max_connections}
              </span>
            </div>
            <Progress
              percent={usage}
              status={usage > 85 ? 'exception' : 'normal'}
              format={(p) => `${p?.toFixed?.(0)}%`}
              strokeColor={usage > 85 ? 'var(--la-danger)' : 'var(--la-accent)'}
              style={{ marginTop: 12 }}
            />
          </Panel>
        </Col>
        <Col xs={24} md={8}>
          <Panel title="Version">
            <Typography.Title level={4} style={{ margin: 0 }} className="mono">
              {status.version}
            </Typography.Title>
            <Typography.Text type="secondary" className="mono">
              {status.host}:{status.port}
            </Typography.Text>
          </Panel>
        </Col>
        <Col xs={24} md={8}>
          <Panel title="pg_stat_statements">
            <Tag color={status.pg_stat_statements_available ? 'success' : 'default'}>
              {status.pg_stat_statements_available ? 'available' : 'not installed'}
            </Tag>
            {!status.pg_stat_statements_available ? (
              <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                shared_preload_libraries + CREATE EXTENSION (see docs/postgres-monitoring.md).
              </Typography.Paragraph>
            ) : null}
          </Panel>
        </Col>
      </Row>

      <Panel title="Databases" padded={false} bodyStyle={{ padding: '8px 8px 12px' }}>
        <Table
          size="small"
          rowKey="name"
          pagination={false}
          dataSource={status.databases || []}
          columns={[
            { title: 'DB', dataIndex: 'name', render: (v) => <span className="mono">{v}</span> },
            { title: 'Backends', dataIndex: 'backends', width: 90 },
            {
              title: 'Cache hit %',
              dataIndex: 'cache_hit_ratio',
              render: (v) => (v == null ? '—' : <span className="mono">{v.toFixed(2)}</span>),
            },
            { title: 'Commits', dataIndex: 'commits' },
            { title: 'Rollbacks', dataIndex: 'rollbacks' },
            { title: 'Deadlocks', dataIndex: 'deadlocks' },
            {
              title: 'Size',
              dataIndex: 'size_bytes',
              render: (v) => <span className="mono">{formatBytes(v)}</span>,
            },
          ]}
        />
      </Panel>

      <Panel padded={false} bodyStyle={{ padding: '4px 12px 12px' }}>
        <Tabs
          items={[
            {
              key: 'activity',
              label: 'Sessions',
              children: (
                <Table
                  size="small"
                  rowKey="pid"
                  dataSource={activity}
                  scroll={{ x: true }}
                  columns={[
                    { title: 'PID', dataIndex: 'pid', width: 80 },
                    { title: 'User', dataIndex: 'usename', width: 100 },
                    { title: 'DB', dataIndex: 'datname', width: 120 },
                    { title: 'State', dataIndex: 'state', width: 100 },
                    { title: 'Wait', dataIndex: 'wait_event', width: 120 },
                    {
                      title: 'Duration s',
                      dataIndex: 'query_duration_seconds',
                      width: 100,
                      render: (v) => (v == null ? '—' : Number(v).toFixed(1)),
                    },
                    { title: 'Query', dataIndex: 'query', ellipsis: true },
                  ]}
                />
              ),
            },
            {
              key: 'statements',
              label: 'Top queries',
              children: statements?.available ? (
                <Table
                  size="small"
                  rowKey={(r: { queryid?: string }) => String(r.queryid)}
                  dataSource={statements.statements || []}
                  columns={[
                    { title: 'Calls', dataIndex: 'calls', width: 80 },
                    {
                      title: 'Total ms',
                      dataIndex: 'total_exec_time',
                      width: 100,
                      render: (v) => Number(v).toFixed(1),
                    },
                    {
                      title: 'Mean ms',
                      dataIndex: 'mean_exec_time',
                      width: 100,
                      render: (v) => Number(v).toFixed(2),
                    },
                    { title: 'Rows', dataIndex: 'rows', width: 80 },
                    { title: 'Query', dataIndex: 'query', ellipsis: true },
                  ]}
                />
              ) : (
                <Alert type="info" showIcon message={statements?.hint || statements?.error || 'No data'} />
              ),
            },
            {
              key: 'tables',
              label: 'Tables',
              children: (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Select
                    allowClear
                    placeholder="Database"
                    style={{ width: 240 }}
                    options={dbList.map((d) => ({ value: d, label: d }))}
                    value={selectedDb}
                    onChange={setSelectedDb}
                  />
                  <Table
                    size="small"
                    rowKey={(r) => `${r.schemaname}.${r.table_name}`}
                    dataSource={tables}
                    columns={[
                      { title: 'Schema', dataIndex: 'schemaname', width: 100 },
                      { title: 'Table', dataIndex: 'table_name' },
                      { title: 'Seq scan', dataIndex: 'seq_scan', width: 90 },
                      { title: 'Idx scan', dataIndex: 'idx_scan', width: 90 },
                      { title: 'Live', dataIndex: 'n_live_tup', width: 90 },
                      { title: 'Dead', dataIndex: 'n_dead_tup', width: 90 },
                    ]}
                  />
                </Space>
              ),
            },
            {
              key: 'locks',
              label: 'Locks',
              children: (
                <Table
                  size="small"
                  rowKey={(_, i) => String(i)}
                  dataSource={locks}
                  columns={[
                    { title: 'PID', dataIndex: 'pid', width: 80 },
                    { title: 'Mode', dataIndex: 'mode', width: 140 },
                    {
                      title: 'Granted',
                      dataIndex: 'granted',
                      width: 90,
                      render: (v) =>
                        v ? <Tag color="success">yes</Tag> : <Tag color="error">no</Tag>,
                    },
                    { title: 'User', dataIndex: 'usename', width: 100 },
                    { title: 'DB', dataIndex: 'datname', width: 120 },
                    { title: 'Query', dataIndex: 'query', ellipsis: true },
                  ]}
                />
              ),
            },
            {
              key: 'replication',
              label: 'Replication',
              children: (status.replication || []).length ? (
                <Table
                  size="small"
                  rowKey={(_, i) => String(i)}
                  dataSource={status.replication}
                  columns={[
                    { title: 'App', dataIndex: 'application_name' },
                    { title: 'Client', dataIndex: 'client_addr' },
                    { title: 'State', dataIndex: 'state' },
                    { title: 'Sync', dataIndex: 'sync_state' },
                    {
                      title: 'Replay lag s',
                      dataIndex: 'replay_lag_seconds',
                      render: (v) => (v == null ? '—' : Number(v).toFixed(2)),
                    },
                  ]}
                />
              ) : (
                <Alert type="info" showIcon message="No replicas detected" />
              ),
            },
          ]}
        />
      </Panel>
    </div>
  )
}
