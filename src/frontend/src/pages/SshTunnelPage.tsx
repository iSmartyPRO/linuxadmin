import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  PlusOutlined,
  ReloadOutlined,
  DeleteOutlined,
  KeyOutlined,
  CopyOutlined,
  DownloadOutlined,
  SafetyCertificateOutlined,
  ApiOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import { api, apiDownload } from '../api/client'
import { useAccess } from '../api/access'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { formatBytes, formatDuration, formatRate } from '../utils/format'
import { tablePagination } from '../utils/tablePagination'

type Destination = { host: string; port: number; label?: string }

type TunnelUser = {
  username: string
  comment: string
  enabled: boolean
  exists: boolean
  home?: string
  in_group?: boolean | null
  destinations: Destination[]
  destinations_count: number
  keys_count: number
  created_at?: string
  updated_at?: string
}

type Overview = {
  available: boolean
  disabled?: boolean
  error?: string
  allow_mutations?: boolean
  group?: string
  group_exists?: boolean
  sshd_dropin?: string
  sshd_dropin_exists?: boolean
  sshd_dropin_managed?: boolean
  public_hostname?: string
  public_port?: number
  username_prefix?: string
  users: TunnelUser[]
  count?: number
  active_sessions?: number
  sessions?: TunnelSession[]
  sessions_available?: boolean
  sessions_error?: string
}

type TunnelSession = {
  session_key: string
  username: string
  pid: number
  remote_ip?: string
  remote_port?: number
  remote?: string
  local_port?: number
  started_at?: string
  duration_seconds?: number
  cmdline?: string
  forwards?: Array<{ host?: string; port?: number; peer?: string }>
  forwards_count?: number
  bytes_sent?: number | null
  bytes_recv?: number | null
  bytes_sent_rate?: number | null
  bytes_recv_rate?: number | null
}

type ConnHistoryRow = {
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
  bytes_sent?: number | null
  bytes_recv?: number | null
  bytes_sent_rate?: number | null
  bytes_recv_rate?: number | null
}

type UserDetail = {
  available: boolean
  error?: string
  allow_mutations?: boolean
  public_hostname?: string
  public_port?: number
  user?: TunnelUser & {
    keys: Array<{ fingerprint: string; type: string; comment: string; key_preview: string }>
  }
}

export function SshTunnelPage() {
  const { canMutate } = useAccess()
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [detail, setDetail] = useState<UserDetail['user'] | null>(null)
  const [detailMeta, setDetailMeta] = useState<{ host?: string; port?: number }>({})
  const [createForm] = Form.useForm()
  const [destForm] = Form.useForm()
  const [keyForm] = Form.useForm()
  const [addKeyOpen, setAddKeyOpen] = useState(false)
  const [genOpen, setGenOpen] = useState(false)
  const [privateKeyModal, setPrivateKeyModal] = useState<{
    private_key: string
    public_key: string
    fingerprint?: string
    suggested_filename?: string
    comment?: string
  } | null>(null)
  /** Kept in memory after keygen so ZIP pack can include the private key. */
  const [sessionPrivateKey, setSessionPrivateKey] = useState<{
    username: string
    private_key: string
    filename: string
  } | null>(null)
  const [configModal, setConfigModal] = useState<{
    config: string
    usage: string[]
    local_forwards: Array<{ host: string; port: number; label?: string; local_port: number }>
    local_port_mode: string
  } | null>(null)
  const [packBusy, setPackBusy] = useState(false)
  const [configBuilderOpen, setConfigBuilderOpen] = useState(false)
  const [historyRows, setHistoryRows] = useState<ConnHistoryRow[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [configMode, setConfigMode] = useState<'random' | 'same' | 'custom'>('random')
  /** user_owned = only pubkey was added (BYOK); include_session = pack private key if available */
  const [packKeyMode, setPackKeyMode] = useState<'user_owned' | 'include_session'>('user_owned')
  const [packIdentityFile, setPackIdentityFile] = useState('~/.ssh/id_ed25519')
  const [forwardRows, setForwardRows] = useState<
    Array<{ host: string; port: number; label?: string; local_port: number }>
  >([])
  const [genForm] = Form.useForm()

  const randLocalPort = () => 20000 + Math.floor(Math.random() * 30000)

  const openConfigBuilder = () => {
    if (!detail) return
    const rows = (detail.destinations || []).map((d) => ({
      host: d.host,
      port: d.port,
      label: d.label,
      local_port: randLocalPort(),
    }))
    setForwardRows(rows)
    setConfigMode('random')
    const hasSessionKey = sessionPrivateKey?.username === detail.username
    setPackKeyMode(hasSessionKey ? 'include_session' : 'user_owned')
    setPackIdentityFile(
      hasSessionKey
        ? `~/.ssh/${sessionPrivateKey!.filename}`
        : '~/.ssh/id_ed25519',
    )
    setConfigBuilderOpen(true)
  }

  const applyPortMode = (mode: 'random' | 'same' | 'custom') => {
    setConfigMode(mode)
    if (mode === 'custom') return
    setForwardRows((rows) =>
      rows.map((r) => ({
        ...r,
        local_port:
          mode === 'same' && r.port >= 1024 ? r.port : randLocalPort(),
      })),
    )
  }

  const generateConfig = async () => {
    if (!detail) return
    try {
      const local_forwards = forwardRows.map((r) => ({
        host: r.host,
        port: r.port,
        label: r.label || '',
        local_port: r.local_port,
      }))
      const identity =
        packKeyMode === 'include_session' && sessionPrivateKey?.username === detail.username
          ? `~/.ssh/${sessionPrivateKey.filename}`
          : packIdentityFile.trim() || '~/.ssh/id_ed25519'
      const res = await api<{
        ok: boolean
        config?: string
        usage?: string[]
        error?: string
      }>(`/api/ssh-tunnel/users/${encodeURIComponent(detail.username)}/ssh-config`, {
        method: 'POST',
        body: JSON.stringify({
          local_port_mode: configMode,
          local_forwards,
          identity_file: identity,
        }),
      })
      if (!res.ok || !res.config) {
        message.error(res.error || 'Error')
        return
      }
      setConfigBuilderOpen(false)
      setConfigModal({
        config: res.config,
        usage: res.usage || [],
        local_forwards,
        local_port_mode: configMode,
      })
    } catch (e) {
      message.error(String(e))
    }
  }

  const downloadClientPack = async (opts?: {
    local_forwards?: Array<{ host: string; port: number; label?: string; local_port: number }>
    local_port_mode?: string
    private_key?: string
    private_key_filename?: string
    /** Force BYOK even if session key exists */
    user_owned?: boolean
    identity_file?: string
  }) => {
    if (!detail) return
    const forwards =
      opts?.local_forwards ||
      configModal?.local_forwards ||
      (detail.destinations || []).map((d) => ({
        host: d.host,
        port: d.port,
        label: d.label || '',
        local_port: 20000 + Math.floor(Math.random() * 30000),
      }))
    const mode = opts?.local_port_mode || configModal?.local_port_mode || 'random'
    const keyFromSession =
      sessionPrivateKey?.username === detail.username ? sessionPrivateKey : null
    const wantKey =
      opts?.private_key ||
      (opts?.user_owned
        ? undefined
        : packKeyMode === 'include_session'
          ? keyFromSession?.private_key
          : undefined)
    const private_key = opts?.private_key || wantKey
    const private_key_filename =
      opts?.private_key_filename ||
      (private_key ? keyFromSession?.filename : undefined) ||
      undefined
    const identity_file =
      opts?.identity_file ||
      (private_key && keyFromSession
        ? `~/.ssh/${keyFromSession.filename}`
        : packIdentityFile.trim() || '~/.ssh/id_ed25519')

    setPackBusy(true)
    try {
      const { blob, filename } = await apiDownload(
        `/api/ssh-tunnel/users/${encodeURIComponent(detail.username)}/client-pack`,
        {
          method: 'POST',
          body: JSON.stringify({
            local_port_mode: mode,
            local_forwards: forwards,
            identity_file,
            private_key: private_key || undefined,
            private_key_filename: private_key_filename || undefined,
          }),
        },
      )
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename || `ssh-tunnel-${detail.username}.zip`
      a.click()
      URL.revokeObjectURL(url)
      message.success(
        private_key
          ? 'ZIP downloaded (config + private key + instructions.html)'
          : 'ZIP downloaded (BYOK: config + instructions, without private key)',
      )
    } catch (e) {
      message.error(String(e))
    } finally {
      setPackBusy(false)
    }
  }

  const loadHistory = useCallback(() => {
    const to = new Date()
    const from = new Date(to.getTime() - 24 * 3600 * 1000)
    setHistoryLoading(true)
    void api<ConnHistoryRow[]>(
      `/api/history/ssh-tunnel/connections?from=${encodeURIComponent(from.toISOString())}&to=${encodeURIComponent(to.toISOString())}&limit=50`,
    )
      .then(setHistoryRows)
      .catch(() => setHistoryRows([]))
      .finally(() => setHistoryLoading(false))
  }, [])

  const load = useCallback(() => {
    void api<Overview>('/api/ssh-tunnel')
      .then(setData)
      .catch((e) => setError(String(e)))
    loadHistory()
  }, [loadHistory])

  useEffect(() => {
    load()
    const t = window.setInterval(load, 10000)
    return () => window.clearInterval(t)
  }, [load])

  const canMut = !!data?.allow_mutations && canMutate('ssh_tunnel')

  const users = useMemo(() => {
    const q = filter.trim().toLowerCase()
    const rows = data?.users || []
    if (!q) return rows
    return rows.filter(
      (u) =>
        u.username.toLowerCase().includes(q) ||
        u.comment.toLowerCase().includes(q) ||
        (u.destinations || []).some(
          (d) =>
            d.host.toLowerCase().includes(q) ||
            String(d.port).includes(q) ||
            (d.label || '').toLowerCase().includes(q),
        ),
    )
  }, [data, filter])

  const runMut = async (fn: () => Promise<any>, okMsg: string) => {
    setBusy(true)
    try {
      const res = await fn()
      if (res?.ok === false) {
        message.error(res.error || 'Error')
        return null
      }
      if (res?.warning) message.warning(res.warning)
      else if (res?.warnings?.length) message.warning(res.warnings.join('; '))
      else message.success(okMsg)
      load()
      return res
    } catch (e) {
      message.error(String(e))
      return null
    } finally {
      setBusy(false)
    }
  }

  const openUser = async (username: string) => {
    try {
      const res = await api<UserDetail>(`/api/ssh-tunnel/users/${encodeURIComponent(username)}`)
      if (!res.user) {
        message.error(res.error || 'Not found')
        return
      }
      setDetail(res.user)
      setDetailMeta({ host: res.public_hostname, port: res.public_port })
      destForm.setFieldsValue({
        destinations: (res.user.destinations || []).map((d) => ({
          host: d.host,
          port: d.port,
          label: d.label || '',
        })),
      })
    } catch (e) {
      message.error(String(e))
    }
  }

  const refreshDetail = async () => {
    if (detail?.username) await openUser(detail.username)
  }

  const copyText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      message.success('Copied')
    } catch {
      message.error('Failed to copy')
    }
  }

  const downloadText = (filename: string, text: string) => {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  if (error) return <Alert type="error" message={error} showIcon />
  if (!data) return <Typography.Text type="secondary">Loading…</Typography.Text>
  if (data.disabled) {
    return <Alert type="warning" message={data.error || 'SSH Tunnel module disabled'} showIcon />
  }

  return (
    <div className="la-page">
      <PageHeader
        docsKey="ssh_tunnel"
        title="SSH Tunnel"
        subtitle={`${data.count || 0} user(s) · ${data.active_sessions || 0} online · jump ${data.public_hostname}:${data.public_port} · group ${data.group}`}
        extra={
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={load}>
              Refresh
            </Button>
            <Button
              icon={<SafetyCertificateOutlined />}
              disabled={!canMut}
              loading={busy}
              onClick={() =>
                void runMut(
                  () =>
                    api('/api/ssh-tunnel/ensure', {
                      method: 'POST',
                      body: JSON.stringify({ reload_sshd: true }),
                    }),
                  'SSH infrastructure applied',
                )
              }
            >
              Apply sshd
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              disabled={!canMut}
              onClick={() => {
                createForm.resetFields()
                createForm.setFieldsValue({
                  username: data.username_prefix || 'tun-',
                  destinations: [{ host: '', port: 5432, label: '' }],
                })
                setCreateOpen(true)
              }}
            >
              New user
            </Button>
          </Space>
        }
      />

      {!canMut ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Read-only mode. Enable “Allow changes” for SSH Tunnel in Settings (root/sudo required)."
        />
      ) : null}

      <Panel title="Gateway status">
        <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }}>
          <Descriptions.Item label="Group">
            <Tag color={data.group_exists ? 'success' : 'warning'}>{data.group}</Tag>
            {data.group_exists ? 'exists' : 'will be created on Apply'}
          </Descriptions.Item>
          <Descriptions.Item label="sshd drop-in">
            <span className="mono" style={{ fontSize: 12 }}>
              {data.sshd_dropin}
            </span>
            <div>
              {data.sshd_dropin_managed ? (
                <Tag color="success">managed</Tag>
              ) : data.sshd_dropin_exists ? (
                <Tag color="warning">exists</Tag>
              ) : (
                <Tag>missing</Tag>
              )}
            </div>
          </Descriptions.Item>
          <Descriptions.Item label="Name prefix">
            <span className="mono">{data.username_prefix}</span>
          </Descriptions.Item>
        </Descriptions>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          Users get nologin shell, PasswordAuthentication no, LocalForward only to
          allowed <span className="mono">host:port</span> via{' '}
          <span className="mono">permitopen</span> in authorized_keys.
        </Typography.Paragraph>
      </Panel>

      <Panel
        title={`Active SSH connections (${data.active_sessions || 0})`}
        style={{ marginTop: 16 }}
        extra={
          <Space size={12}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              auto-refresh 10s
            </Typography.Text>
            <Link to="/history" style={{ fontSize: 12 }}>
              <HistoryOutlined /> Full history
            </Link>
          </Space>
        }
      >
        {data.sessions_error ? (
          <Alert type="warning" showIcon message={data.sessions_error} style={{ marginBottom: 12 }} />
        ) : null}
        <Table
          size="small"
          rowKey={(r) => r?.session_key || `${r?.username}-${r?.pid}`}
          dataSource={data.sessions || []}
          pagination={tablePagination(10)}
          locale={{ emptyText: 'No active tunnel sessions' }}
          columns={[
            {
              title: 'User',
              dataIndex: 'username',
              render: (v: string) => <span className="mono">{v}</span>,
            },
            {
              title: 'Client',
              dataIndex: 'remote',
              render: (_: unknown, r?: TunnelSession) => (
                <span className="mono">{r?.remote || r?.remote_ip || '—'}</span>
              ),
            },
            {
              title: 'Duration',
              dataIndex: 'duration_seconds',
              width: 110,
              render: (v?: number, r?: TunnelSession) => {
                if (v != null) return <span className="mono">{formatDuration(v)}</span>
                if (r?.started_at) {
                  const sec = Math.max(
                    0,
                    Math.floor((Date.now() - new Date(r.started_at).getTime()) / 1000),
                  )
                  return <span className="mono">{formatDuration(sec)}</span>
                }
                return '—'
              },
            },
            {
              title: 'Network',
              key: 'network',
              width: 200,
              render: (_: unknown, r?: TunnelSession) => (
                <div className="mono" style={{ fontSize: 12, lineHeight: 1.45 }}>
                  <div>
                    ↓ {formatRate(r?.bytes_recv_rate)} · {formatBytes(r?.bytes_recv)}
                  </div>
                  <div>
                    ↑ {formatRate(r?.bytes_sent_rate)} · {formatBytes(r?.bytes_sent)}
                  </div>
                </div>
              ),
            },
            {
              title: 'PID',
              dataIndex: 'pid',
              width: 90,
              render: (v: number) => <span className="mono">{v}</span>,
            },
            {
              title: 'Started',
              dataIndex: 'started_at',
              width: 170,
              render: (v?: string) =>
                v ? (
                  <span className="mono" style={{ fontSize: 12 }}>
                    {new Date(v).toLocaleString()}
                  </span>
                ) : (
                  '—'
                ),
            },
            {
              title: 'Forwards',
              dataIndex: 'forwards',
              render: (fw: TunnelSession['forwards']) =>
                fw?.length ? (
                  <Space wrap size={[4, 4]}>
                    {fw.map((f, i) => (
                      <Tag key={`${f.peer || f.host}-${i}`} className="mono">
                        {f.peer || `${f.host}:${f.port}`}
                      </Tag>
                    ))}
                  </Space>
                ) : (
                  <Typography.Text type="secondary">—</Typography.Text>
                ),
            },
          ]}
        />
      </Panel>

      <Panel
        title="Recent connections (24h)"
        style={{ marginTop: 16 }}
        extra={
          <Space size={12}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {historyLoading ? 'loading…' : `${historyRows.length} record(s)`}
            </Typography.Text>
            <Link to="/history" style={{ fontSize: 12 }}>
              Open History →
            </Link>
          </Space>
        }
      >
        <Table
          size="small"
          rowKey="id"
          loading={historyLoading}
          dataSource={historyRows}
          pagination={tablePagination(10)}
          locale={{ emptyText: 'No connection history yet — enable “Write connection history” in Settings' }}
          columns={[
            {
              title: 'Status',
              dataIndex: 'status',
              width: 90,
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
              render: (_: unknown, r?: ConnHistoryRow) => (
                <span className="mono">{r?.remote || r?.remote_ip || '—'}</span>
              ),
            },
            {
              title: 'Start',
              dataIndex: 'started_at',
              width: 160,
              render: (v: string) => (
                <span className="mono" style={{ fontSize: 12 }}>
                  {new Date(v).toLocaleString()}
                </span>
              ),
            },
            {
              title: 'End',
              dataIndex: 'ended_at',
              width: 160,
              render: (v?: string | null) =>
                v ? (
                  <span className="mono" style={{ fontSize: 12 }}>
                    {new Date(v).toLocaleString()}
                  </span>
                ) : (
                  '—'
                ),
            },
            {
              title: 'Duration',
              dataIndex: 'duration_seconds',
              width: 110,
              render: (v: number | null | undefined, r?: ConnHistoryRow) => {
                if (r?.status === 'active' && r.started_at) {
                  const sec = Math.max(
                    0,
                    Math.floor((Date.now() - new Date(r.started_at).getTime()) / 1000),
                  )
                  return <span className="mono">{formatDuration(sec)}</span>
                }
                return <span className="mono">{formatDuration(v)}</span>
              },
            },
            {
              title: 'Traffic',
              key: 'traffic',
              width: 150,
              render: (_: unknown, r?: ConnHistoryRow) => (
                <span className="mono" style={{ fontSize: 12 }}>
                  ↓ {formatBytes(r?.bytes_recv)} · ↑ {formatBytes(r?.bytes_sent)}
                </span>
              ),
            },
            {
              title: 'Fwd',
              dataIndex: 'forwards_count',
              width: 60,
              render: (v?: number) => v ?? 0,
            },
          ]}
        />
      </Panel>

      <Panel
        title="Tunnel users"
        style={{ marginTop: 16 }}
        extra={
          <Input
            allowClear
            placeholder="Filter…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ width: 220 }}
          />
        }
      >
        <Table
          size="small"
          rowKey="username"
          dataSource={users}
          pagination={tablePagination(25)}
          onRow={(row) => ({
            onClick: () => void openUser(row.username),
            style: { cursor: 'pointer' },
          })}
          columns={[
            {
              title: 'User',
              dataIndex: 'username',
              render: (v, row) => (
                <Space>
                  <span className="mono">{v}</span>
                  {!row.exists ? <Tag color="error">no system user</Tag> : null}
                </Space>
              ),
            },
            { title: 'Comment', dataIndex: 'comment', ellipsis: true },
            {
              title: 'Destinations',
              key: 'dests',
              render: (_, row) => (
                <Space wrap size={[4, 4]}>
                  {(row.destinations || []).slice(0, 4).map((d) => (
                    <Tag key={`${d.host}:${d.port}`} className="mono">
                      {d.host}:{d.port}
                    </Tag>
                  ))}
                  {(row.destinations || []).length > 4 ? (
                    <Tag>+{(row.destinations || []).length - 4}</Tag>
                  ) : null}
                  {!row.destinations?.length ? <Tag>none</Tag> : null}
                </Space>
              ),
            },
            {
              title: 'Keys',
              dataIndex: 'keys_count',
              width: 70,
              render: (v) => <span className="mono">{v}</span>,
            },
            {
              title: '',
              key: 'act',
              width: 90,
              render: (_, row) => (
                <Button
                  size="small"
                  type="link"
                  onClick={(e) => {
                    e.stopPropagation()
                    void openUser(row.username)
                  }}
                >
                  Open
                </Button>
              ),
            },
          ]}
        />
      </Panel>

      <Modal
        title="New tunnel user"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        confirmLoading={busy}
        onOk={() => {
          void createForm.validateFields().then(async (vals) => {
            const res = await runMut(
              () =>
                api('/api/ssh-tunnel/users', {
                  method: 'POST',
                  body: JSON.stringify({
                    username: vals.username,
                    comment: vals.comment || '',
                    destinations: (vals.destinations || []).filter((d: Destination) => d?.host),
                  }),
                }),
              'User created',
            )
            if (res?.ok) {
              setCreateOpen(false)
              if (res.username) void openUser(res.username)
            }
          })
        }}
        okText="Create"
        width={640}
      >
        <Form form={createForm} layout="vertical">
          <Form.Item
            name="username"
            label={`Name (prefix ${data.username_prefix})`}
            rules={[{ required: true }]}
          >
            <Input className="mono" placeholder={`${data.username_prefix}alice`} />
          </Form.Item>
          <Form.Item name="comment" label="Comment">
            <Input placeholder="e.g. PG access for 1C" />
          </Form.Item>
          <Form.List name="destinations">
            {(fields, { add, remove }) => (
              <>
                <div style={{ marginBottom: 8, fontWeight: 600 }}>Allowed destinations</div>
                {fields.map((field) => (
                  <Space key={field.key} align="start" style={{ display: 'flex', marginBottom: 8 }}>
                    <Form.Item
                      {...field}
                      name={[field.name, 'host']}
                      rules={[{ required: true, message: 'host' }]}
                      style={{ marginBottom: 0 }}
                    >
                      <Input placeholder="host / IP" className="mono" style={{ width: 200 }} />
                    </Form.Item>
                    <Form.Item
                      {...field}
                      name={[field.name, 'port']}
                      rules={[{ required: true }]}
                      style={{ marginBottom: 0 }}
                    >
                      <InputNumber min={1} max={65535} placeholder="port" style={{ width: 100 }} />
                    </Form.Item>
                    <Form.Item {...field} name={[field.name, 'label']} style={{ marginBottom: 0 }}>
                      <Input placeholder="label" style={{ width: 140 }} />
                    </Form.Item>
                    <Button danger type="text" icon={<DeleteOutlined />} onClick={() => remove(field.name)} />
                  </Space>
                ))}
                <Button type="dashed" onClick={() => add({ host: '', port: 5432, label: '' })} block>
                  Add destination
                </Button>
              </>
            )}
          </Form.List>
        </Form>
      </Modal>

      <Drawer
        width={720}
        open={!!detail}
        onClose={() => setDetail(null)}
        title={
          detail ? (
            <Space>
              <ApiOutlined />
              <span className="mono">{detail.username}</span>
            </Space>
          ) : null
        }
        extra={
          detail ? (
            <Space>
              <Button
                danger
                disabled={!canMut}
                icon={<DeleteOutlined />}
                onClick={() => {
                  Modal.confirm({
                    title: `Delete ${detail.username}?`,
                    content: 'The system user, home, and registry entry will be removed.',
                    okType: 'danger',
                    onOk: async () => {
                      const res = await runMut(
                        () =>
                          api(`/api/ssh-tunnel/users/${encodeURIComponent(detail.username)}`, {
                            method: 'DELETE',
                          }),
                        'Deleted',
                      )
                      if (res?.ok) setDetail(null)
                    },
                  })
                }}
              >
                Delete
              </Button>
            </Space>
          ) : null
        }
      >
        {detail ? (
          <>
            <Descriptions size="small" column={1} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="Comment">{detail.comment || '—'}</Descriptions.Item>
              <Descriptions.Item label="Home">
                <span className="mono">{detail.home || '—'}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Jump">
                <span className="mono">
                  {detailMeta.host}:{detailMeta.port}
                </span>
              </Descriptions.Item>
            </Descriptions>

            <Typography.Title level={5}>Destinations</Typography.Title>
            <Form form={destForm} layout="vertical">
              <Form.List name="destinations">
                {(fields, { add, remove }) => (
                  <>
                    {fields.map((field) => (
                      <Space
                        key={field.key}
                        align="start"
                        style={{ display: 'flex', marginBottom: 8 }}
                      >
                        <Form.Item
                          {...field}
                          name={[field.name, 'host']}
                          rules={[{ required: true }]}
                          style={{ marginBottom: 0 }}
                        >
                          <Input className="mono" placeholder="host" style={{ width: 200 }} disabled={!canMut} />
                        </Form.Item>
                        <Form.Item
                          {...field}
                          name={[field.name, 'port']}
                          rules={[{ required: true }]}
                          style={{ marginBottom: 0 }}
                        >
                          <InputNumber min={1} max={65535} style={{ width: 100 }} disabled={!canMut} />
                        </Form.Item>
                        <Form.Item {...field} name={[field.name, 'label']} style={{ marginBottom: 0 }}>
                          <Input placeholder="label" style={{ width: 140 }} disabled={!canMut} />
                        </Form.Item>
                        <Button
                          danger
                          type="text"
                          disabled={!canMut}
                          icon={<DeleteOutlined />}
                          onClick={() => remove(field.name)}
                        />
                      </Space>
                    ))}
                    <Space style={{ marginBottom: 16 }}>
                      <Button
                        type="dashed"
                        disabled={!canMut}
                        onClick={() => add({ host: '', port: 5432, label: '' })}
                      >
                        Add
                      </Button>
                      <Button
                        type="primary"
                        disabled={!canMut}
                        loading={busy}
                        onClick={() => {
                          void destForm.validateFields().then(async (vals) => {
                            const res = await runMut(
                              () =>
                                api(
                                  `/api/ssh-tunnel/users/${encodeURIComponent(detail.username)}/destinations`,
                                  {
                                    method: 'PUT',
                                    body: JSON.stringify({
                                      destinations: (vals.destinations || []).filter(
                                        (d: Destination) => d?.host,
                                      ),
                                    }),
                                  },
                                ),
                              'Destinations saved',
                            )
                            if (res?.ok) void refreshDetail()
                          })
                        }}
                      >
                        Save destinations
                      </Button>
                    </Space>
                  </>
                )}
              </Form.List>
            </Form>

            <Typography.Title level={5}>
              SSH keys{' '}
              <Space>
                <Button
                  size="small"
                  icon={<PlusOutlined />}
                  disabled={!canMut}
                  onClick={() => {
                    keyForm.resetFields()
                    setAddKeyOpen(true)
                  }}
                >
                  Add pubkey
                </Button>
                <Button
                  size="small"
                  icon={<KeyOutlined />}
                  disabled={!canMut}
                  onClick={() => setGenOpen(true)}
                >
                  Generate keypair
                </Button>
              </Space>
            </Typography.Title>
            <Table
              size="small"
              rowKey="fingerprint"
              pagination={false}
              dataSource={detail.keys || []}
              columns={[
                {
                  title: 'Fingerprint',
                  dataIndex: 'fingerprint',
                  render: (v) => <span className="mono" style={{ fontSize: 12 }}>{v}</span>,
                },
                { title: 'Type', dataIndex: 'type', width: 110 },
                { title: 'Comment', dataIndex: 'comment', ellipsis: true },
                {
                  title: '',
                  width: 70,
                  render: (_, row) => (
                    <Button
                      danger
                      type="text"
                      size="small"
                      disabled={!canMut}
                      icon={<DeleteOutlined />}
                      onClick={() => {
                        void runMut(
                          () =>
                            api(
                              `/api/ssh-tunnel/users/${encodeURIComponent(detail.username)}/keys?fingerprint=${encodeURIComponent(row.fingerprint)}`,
                              { method: 'DELETE' },
                            ),
                          'Key deleted',
                        ).then((res) => {
                          if (res?.ok) void refreshDetail()
                        })
                      }}
                    />
                  ),
                },
              ]}
            />

            <Typography.Title level={5} style={{ marginTop: 24 }}>
              SSH config template
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
              By default local ports are random (20000–49999) to avoid conflicts with
              services on the client PC. You can set “same as remote” or a custom local port.
            </Typography.Paragraph>
            <Button icon={<DownloadOutlined />} onClick={openConfigBuilder}>
              Configure ports / show ssh config
            </Button>
          </>
        ) : null}
      </Drawer>

      <Modal
        title="LocalForward — local ports"
        open={configBuilderOpen}
        onCancel={() => setConfigBuilderOpen(false)}
        width={720}
        okText="Generate config"
        onOk={() => void generateConfig()}
      >
        <Form layout="vertical">
          <Form.Item label="Local port mode">
            <Select
              value={configMode}
              onChange={(v) => applyPortMode(v)}
              options={[
                {
                  value: 'random',
                  label: 'Random port (recommended, no conflicts)',
                },
                {
                  value: 'same',
                  label: 'Same as remote (e.g. 3389 → 3389)',
                },
                {
                  value: 'custom',
                  label: 'Set manually',
                },
              ]}
            />
          </Form.Item>
          <Form.Item
            label="Private key in ZIP"
            extra="If the user sent only a public key, choose «User’s own key» — private key stays with them."
          >
            <Select
              value={packKeyMode}
              onChange={(v: 'user_owned' | 'include_session') => {
                setPackKeyMode(v)
                if (v === 'user_owned') {
                  setPackIdentityFile('~/.ssh/id_ed25519')
                } else if (
                  sessionPrivateKey &&
                  sessionPrivateKey.username === detail?.username
                ) {
                  setPackIdentityFile(`~/.ssh/${sessionPrivateKey.filename}`)
                }
              }}
              options={[
                {
                  value: 'user_owned',
                  label: 'User’s own key (BYOK — pubkey only, no private key in ZIP)',
                },
                {
                  value: 'include_session',
                  label: sessionPrivateKey?.username === detail?.username
                    ? 'Include private key generated in this session'
                    : 'Include private key (generate keypair first)',
                  disabled: sessionPrivateKey?.username !== detail?.username,
                },
              ]}
            />
          </Form.Item>
          <Form.Item
            label="IdentityFile (path on client PC)"
            extra="Written into ssh_config. For BYOK point to the user’s existing private key."
          >
            <Input
              className="mono"
              value={packIdentityFile}
              onChange={(e) => setPackIdentityFile(e.target.value)}
              placeholder="~/.ssh/id_ed25519"
            />
          </Form.Item>
        </Form>
        {!forwardRows.length ? (
          <Alert type="warning" showIcon message="Add destinations first" />
        ) : (
          <Table
            size="small"
            pagination={false}
            rowKey={(r) => `${r.host}:${r.port}`}
            dataSource={forwardRows}
            columns={[
              {
                title: 'Destination',
                render: (_, r) => (
                  <span className="mono">
                    {r.host}:{r.port}
                    {r.label ? ` · ${r.label}` : ''}
                  </span>
                ),
              },
              {
                title: 'Local port',
                width: 160,
                render: (_, r, idx) => (
                  <InputNumber
                    className="mono"
                    min={1}
                    max={65535}
                    value={r.local_port}
                    onChange={(v) => {
                      const n = Number(v) || r.port
                      setConfigMode('custom')
                      setForwardRows((rows) =>
                        rows.map((row, i) => (i === idx ? { ...row, local_port: n } : row)),
                      )
                    }}
                    style={{ width: 120 }}
                  />
                ),
              },
              {
                title: '',
                width: 110,
                render: (_row, _r, idx) => (
                  <Button
                    size="small"
                    type="link"
                    onClick={() => {
                      setConfigMode('custom')
                      setForwardRows((rows) =>
                        rows.map((row, i) =>
                          i === idx ? { ...row, local_port: randLocalPort() } : row,
                        ),
                      )
                    }}
                  >
                    Random
                  </Button>
                ),
              },
            ]}
          />
        )}
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          Config will contain:{' '}
          <span className="mono">LocalForward &lt;local&gt; &lt;host&gt;:&lt;remote&gt;</span>
        </Typography.Paragraph>
      </Modal>

      <Modal
        title="Add public key"
        open={addKeyOpen}
        onCancel={() => setAddKeyOpen(false)}
        confirmLoading={busy}
        onOk={() => {
          void keyForm.validateFields().then(async (vals) => {
            if (!detail) return
            const res = await runMut(
              () =>
                api(`/api/ssh-tunnel/users/${encodeURIComponent(detail.username)}/keys`, {
                  method: 'POST',
                  body: JSON.stringify(vals),
                }),
              'Key added',
            )
            if (res?.ok) {
              setAddKeyOpen(false)
              void refreshDetail()
            }
          })
        }}
      >
        <Form form={keyForm} layout="vertical">
          <Form.Item name="public_key" label="Public key" rules={[{ required: true }]}>
            <Input.TextArea
              rows={4}
              className="mono"
              placeholder="ssh-rsa AAAA… comment"
            />
          </Form.Item>
          <Form.Item name="comment" label="Comment (optional, overrides value from key)">
            <Input placeholder="tun-alice@jump.example (ssh-tunnel)" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Generate SSH keypair"
        open={genOpen}
        onCancel={() => setGenOpen(false)}
        confirmLoading={busy}
        onOk={() => {
          void genForm.validateFields().then(async (vals) => {
            if (!detail) return
            const res = await runMut(
              () =>
                api(`/api/ssh-tunnel/users/${encodeURIComponent(detail.username)}/keys/generate`, {
                  method: 'POST',
                  body: JSON.stringify({
                    key_type: 'rsa',
                    bits: 4096,
                    comment: vals.comment || undefined,
                  }),
                }),
              'Key generated',
            )
            if (res?.ok && res.private_key) {
              setGenOpen(false)
              setPrivateKeyModal({
                private_key: res.private_key,
                public_key: res.public_key,
                fingerprint: res.fingerprint,
                suggested_filename: res.suggested_filename,
                comment: res.comment,
              })
              setSessionPrivateKey({
                username: detail.username,
                private_key: res.private_key,
                filename:
                  res.suggested_filename || `${detail.username}_rsa4096`,
              })
              void refreshDetail()
            }
          })
        }}
        okText="Generate RSA 4096"
        afterOpenChange={(open) => {
          if (open && detail) {
            const host = detailMeta.host || 'jump'
            genForm.setFieldsValue({
              comment: `${detail.username}@${host} (ssh-tunnel)`,
            })
          }
        }}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="Key type: RSA (-t rsa -b 4096). Ed25519 is not used by default."
        />
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="The private key is shown once and is not stored on the server. Give it to the user immediately."
        />
        <Form form={genForm} layout="vertical">
          <Form.Item
            name="comment"
            label="Comment (-C)"
            extra="Goes into .pub / authorized_keys — useful to identify the key on the client and jump host."
            rules={[{ required: true, message: 'Enter a comment' }]}
          >
            <Input className="mono" placeholder="tun-alice@jump.example (ssh-tunnel)" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Private key (one-time)"
        open={!!privateKeyModal}
        onCancel={() => setPrivateKeyModal(null)}
        width={720}
        footer={[
          <Button
            key="copy"
            icon={<CopyOutlined />}
            onClick={() => privateKeyModal && void copyText(privateKeyModal.private_key)}
          >
            Copy private
          </Button>,
          <Button
            key="dl"
            icon={<DownloadOutlined />}
            onClick={() =>
              privateKeyModal &&
              downloadText(
                privateKeyModal.suggested_filename ||
                  `${detail?.username || 'tunnel'}_rsa4096`,
                privateKeyModal.private_key,
              )
            }
          >
            Download key
          </Button>,
          <Button
            key="zip"
            type="primary"
            icon={<DownloadOutlined />}
            loading={packBusy}
            onClick={() =>
              privateKeyModal &&
              void downloadClientPack({
                private_key: privateKeyModal.private_key,
                private_key_filename:
                  privateKeyModal.suggested_filename ||
                  `${detail?.username || 'tunnel'}_rsa4096`,
              })
            }
          >
            Download ZIP pack
          </Button>,
          <Button key="ok" onClick={() => setPrivateKeyModal(null)}>
            Close
          </Button>,
        ]}
      >
        {privateKeyModal ? (
          <>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="ZIP pack includes private key, ssh_config, and premium instructions.html for the user."
            />
            <Typography.Paragraph type="secondary">
              RSA 4096 · Fingerprint:{' '}
              <span className="mono">{privateKeyModal.fingerprint}</span>
              {privateKeyModal.comment ? (
                <>
                  <br />
                  Comment: <span className="mono">{privateKeyModal.comment}</span>
                </>
              ) : null}
            </Typography.Paragraph>
            <Input.TextArea
              className="mono"
              rows={12}
              value={privateKeyModal.private_key}
              readOnly
            />
          </>
        ) : null}
      </Modal>

      <Modal
        title="SSH config"
        open={!!configModal}
        onCancel={() => setConfigModal(null)}
        width={720}
        footer={[
          <Button
            key="copy"
            icon={<CopyOutlined />}
            onClick={() => configModal && void copyText(configModal.config)}
          >
            Copy
          </Button>,
          <Button
            key="dl"
            icon={<DownloadOutlined />}
            onClick={() =>
              configModal &&
              downloadText(`ssh-config-${detail?.username || 'tunnel'}.txt`, configModal.config)
            }
          >
            Download
          </Button>,
          <Button
            key="zip"
            type="primary"
            icon={<DownloadOutlined />}
            loading={packBusy}
            onClick={() => void downloadClientPack()}
          >
            Download ZIP pack
          </Button>,
          <Button key="ok" onClick={() => setConfigModal(null)}>
            Close
          </Button>,
        ]}
      >
        {configModal ? (
          <>
            <Alert
              type={packKeyMode === 'include_session' ? 'info' : 'success'}
              showIcon
              style={{ marginBottom: 12 }}
              message={
                packKeyMode === 'include_session' &&
                sessionPrivateKey?.username === detail?.username
                  ? 'ZIP pack: instructions.html + ssh_config + private key from this session.'
                  : 'ZIP pack (BYOK): instructions.html + ssh_config only. Private key is not included — user keeps the key that matches the added pubkey.'
              }
            />
            <ul style={{ paddingLeft: 18, color: 'var(--la-muted)' }}>
              {configModal.usage.map((u) => (
                <li key={u}>{u}</li>
              ))}
            </ul>
            <Input.TextArea className="mono" rows={16} value={configModal.config} readOnly />
          </>
        ) : null}
      </Modal>
    </div>
  )
}
