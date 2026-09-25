import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  QRCode,
  Radio,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  ReloadOutlined,
  DownloadOutlined,
  PlusOutlined,
  CopyOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  QrcodeOutlined,
  ToolOutlined,
  DeleteOutlined,
  EditOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAccess } from '../api/access'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { WireGuardIpMap, type IpMapData } from '../components/WireGuardIpMap'
import { formatBytes, formatDuration } from '../utils/format'
import { tablePagination } from '../utils/tablePagination'

type Peer = {
  id: string
  name: string
  public_key?: string
  address?: string
  route_mode?: string
  allowed_ips_client?: string[]
  dns_mode?: 'none' | 'server' | 'custom' | string
  dns?: string
  persistent_keepalive?: number
  enabled?: boolean
  notes?: string
  has_preshared_key?: boolean
  online?: boolean
  remote_ip?: string | null
  remote_port?: number | null
  endpoint_runtime?: string | null
  latest_handshake_ago_human?: string
  transfer_rx?: number
  transfer_tx?: number
  transfer_rx_human?: string
  transfer_tx_human?: string
}

type LivePeer = Peer & {
  peer_id?: string | null
}

type WgFeatures = {
  show_live_peers?: boolean
  show_ip_map?: boolean
  record_history?: boolean
  online_handshake_seconds?: number
}

type Overview = {
  available: boolean
  disabled?: boolean
  error?: string
  allow_mutations?: boolean
  installed?: boolean
  tools?: { wg?: boolean; wg_quick?: boolean; pkg_manager?: string | null }
  server?: {
    interface?: string
    address?: string
    listen_port?: number
    public_key?: string
    dns?: string
    endpoint?: string
    mtu?: number
    nat_enabled?: boolean
    wan_interface?: string
  } | null
  peers?: Peer[]
  peer_count?: number
  online_count?: number
  live_peers?: LivePeer[]
  features?: WgFeatures
  status?: {
    up?: boolean
    error?: string
    raw?: string
    online_count?: number
    online_handshake_seconds?: number
  }
  route_presets?: Record<string, { label: string; description: string }>
  conf_path?: string
  conf_exists?: boolean
  ip_map?: IpMapData | null
}

type ConnHistoryRow = {
  id: number
  peer_name: string
  vpn_address?: string | null
  remote?: string | null
  remote_ip?: string | null
  status: string
  started_at: string
  ended_at?: string | null
  duration_seconds?: number | null
  transfer_rx?: number | null
  transfer_tx?: number | null
}

type PeerMutResult = {
  ok: boolean
  error?: string
  client_config?: string
  peer?: Peer
  apply_error?: string
}

function hostOnly(address?: string): string {
  return (address || '').split('/')[0].trim()
}

export function WireGuardPage() {
  const { canMutate } = useAccess()
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [serverOpen, setServerOpen] = useState(false)
  const [peerOpen, setPeerOpen] = useState(false)
  const [editingPeer, setEditingPeer] = useState<Peer | null>(null)
  const [configModal, setConfigModal] = useState<{
    name: string
    filename: string
    config: string
  } | null>(null)
  const [serverForm] = Form.useForm()
  const [peerForm] = Form.useForm()
  const routeMode = Form.useWatch('route_mode', peerForm)
  const peerDnsMode = Form.useWatch('dns_mode', peerForm)
  const [historyRows, setHistoryRows] = useState<ConnHistoryRow[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  const loadHistory = useCallback(() => {
    const to = new Date()
    const from = new Date(to.getTime() - 24 * 3600 * 1000)
    setHistoryLoading(true)
    void api<ConnHistoryRow[]>(
      `/api/history/wireguard/connections?from=${encodeURIComponent(from.toISOString())}&to=${encodeURIComponent(to.toISOString())}&limit=50`,
    )
      .then(setHistoryRows)
      .catch(() => setHistoryRows([]))
      .finally(() => setHistoryLoading(false))
  }, [])

  const load = useCallback(() => {
    void api<Overview>('/api/wireguard')
      .then(setData)
      .catch((e) => setError(String(e)))
    loadHistory()
  }, [loadHistory])

  useEffect(() => {
    load()
    const t = window.setInterval(load, 10000)
    return () => window.clearInterval(t)
  }, [load])

  const canMut = !!data?.allow_mutations && canMutate('wireguard')
  const presets = data?.route_presets || {}

  const runMut = async (fn: () => Promise<any>, okMsg: string) => {
    setBusy(true)
    try {
      const res = await fn()
      if (res?.ok === false) {
        message.error(res.error || 'Error')
        return null
      }
      if (res?.apply_error) message.warning(`Saved, but apply failed: ${res.apply_error}`)
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

  const copyText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      message.success('Copied')
    } catch {
      message.error('Copy failed')
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

  const openPeerConfig = async (peerId: string) => {
    try {
      const res = await api<{
        ok: boolean
        error?: string
        filename?: string
        config?: string
        peer?: Peer
      }>(`/api/wireguard/peers/${encodeURIComponent(peerId)}/config`)
      if (!res.ok || !res.config) {
        message.error(res.error || 'Failed to load config')
        return
      }
      setConfigModal({
        name: res.peer?.name || peerId,
        filename: res.filename || `${peerId}.conf`,
        config: res.config,
      })
    } catch (e) {
      message.error(String(e))
    }
  }

  const routeHelp = useMemo(() => {
    const p = presets[routeMode || 'vpn_only']
    return p?.description || ''
  }, [presets, routeMode])

  const openCreatePeer = (prefillIp?: string) => {
    setEditingPeer(null)
    peerForm.resetFields()
    peerForm.setFieldsValue({
      name: '',
      address: prefillIp || '',
      route_mode: 'vpn_only',
      allowed_ips_text: '',
      dns_mode: 'none',
      dns: '',
      persistent_keepalive: 25,
      use_preshared_key: true,
      notes: '',
      enabled: true,
      apply: true,
    })
    setPeerOpen(true)
  }

  const openEditPeer = (peer: Peer) => {
    setEditingPeer(peer)
    peerForm.setFieldsValue({
      name: peer.name,
      address: hostOnly(peer.address),
      route_mode: peer.route_mode || 'vpn_only',
      allowed_ips_text: (peer.allowed_ips_client || []).join(', '),
      dns_mode: peer.dns_mode || (peer.dns ? 'custom' : 'none'),
      dns: peer.dns || '',
      persistent_keepalive: peer.persistent_keepalive ?? 25,
      notes: peer.notes || '',
      enabled: peer.enabled !== false,
      apply: true,
    })
    setPeerOpen(true)
  }

  const openEditPeerById = (peerId: string) => {
    const peer = (data?.peers || []).find((p) => p.id === peerId)
    if (peer) openEditPeer(peer)
  }

  const buildPeerPayload = (values: Record<string, any>) => {
    const payload: Record<string, unknown> = {
      name: values.name,
      address: values.address || undefined,
      route_mode: values.route_mode,
      allowed_ips_client:
        values.route_mode === 'custom'
          ? String(values.allowed_ips_text || '')
              .split(/[,\n]/)
              .map((s: string) => s.trim())
              .filter(Boolean)
          : undefined,
      dns_mode: values.dns_mode,
      dns: values.dns_mode === 'custom' ? values.dns || '' : '',
      persistent_keepalive: values.persistent_keepalive,
      notes: values.notes || '',
      apply: values.apply !== false,
    }
    if (!editingPeer) {
      payload.use_preshared_key = values.use_preshared_key !== false
    } else {
      payload.enabled = values.enabled !== false
    }
    return payload
  }

  if (error) return <Alert type="error" message={error} showIcon />
  if (!data) return <Typography.Text type="secondary">Loading…</Typography.Text>
  if (data.disabled) {
    return <Alert type="warning" message={data.error || 'WireGuard module disabled'} showIcon />
  }

  return (
    <div className="la-page">
      <PageHeader
        docsKey="wireguard"
        title="WireGuard"
        subtitle={
          data.server
            ? `${data.server.interface} · ${data.status?.up ? 'UP' : 'DOWN'} · ${data.peer_count || 0} peer(s)${
                data.features?.show_live_peers !== false
                  ? ` · ${data.online_count ?? data.status?.online_count ?? 0} online`
                  : ''
              }`
            : 'Create a WireGuard VPN server and issue client configs with QR codes'
        }
        extra={
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={load}>
              Refresh
            </Button>
            {!data.installed ? (
              <Button
                type="primary"
                icon={<ToolOutlined />}
                disabled={!canMut}
                loading={busy}
                onClick={() =>
                  void runMut(
                    () => api('/api/wireguard/install', { method: 'POST', body: '{}' }),
                    'WireGuard tools installed',
                  )
                }
              >
                Install tools
              </Button>
            ) : null}
            <Button
              disabled={!canMut || !data.installed}
              onClick={() => {
                const s = data.server
                serverForm.setFieldsValue({
                  interface: s?.interface || 'wg0',
                  address: s?.address || '10.66.0.1/24',
                  listen_port: s?.listen_port || 51820,
                  dns: s?.dns || '',
                  endpoint: s?.endpoint || '',
                  mtu: s?.mtu || 1420,
                  nat_enabled: s?.nat_enabled !== false,
                  wan_interface: s?.wan_interface || '',
                  rotate_keys: false,
                })
                setServerOpen(true)
              }}
            >
              {data.server ? 'Edit server' : 'Create server'}
            </Button>
            <Button
              icon={<PlayCircleOutlined />}
              disabled={!canMut || !data.server}
              loading={busy}
              onClick={() =>
                void runMut(
                  () => api('/api/wireguard/server/apply', { method: 'POST', body: '{}' }),
                  'WireGuard applied (wg-quick up)',
                )
              }
            >
              Apply / Start
            </Button>
            <Button
              icon={<PauseCircleOutlined />}
              disabled={!canMut || !data.server}
              loading={busy}
              onClick={() =>
                void runMut(
                  () => api('/api/wireguard/server/stop', { method: 'POST', body: '{}' }),
                  'WireGuard stopped',
                )
              }
            >
              Stop
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              disabled={!canMut || !data.server}
              onClick={() => openCreatePeer()}
            >
              Add peer
            </Button>
          </Space>
        }
      />

      {!canMut ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Read-only mode. Enable “Allow changes” for WireGuard in Settings (needs root/sudo)."
        />
      ) : null}

      {!data.installed ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="WireGuard tools not found"
          description={`Install wireguard-tools via the button above (package manager: ${data.tools?.pkg_manager || 'unknown'}).`}
        />
      ) : null}

      <Panel title="Server">
        {data.server ? (
          <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }}>
            <Descriptions.Item label="Status">
              <Tag color={data.status?.up ? 'success' : 'default'}>
                {data.status?.up ? 'UP' : 'DOWN'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Interface">
              <span className="mono">{data.server.interface}</span>
            </Descriptions.Item>
            <Descriptions.Item label="Address">
              <span className="mono">{data.server.address}</span>
            </Descriptions.Item>
            <Descriptions.Item label="Listen port">
              <span className="mono">{data.server.listen_port}</span>
            </Descriptions.Item>
            <Descriptions.Item label="Endpoint (for clients)">
              <span className="mono">{data.server.endpoint}</span>
            </Descriptions.Item>
            <Descriptions.Item label="DNS (optional)">
              <span className="mono">
                {data.server.dns || '— (not pushed; peers keep OS/corporate DNS by default)'}
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="NAT / forwarding">
              {data.server.nat_enabled ? (
                <Tag color="success">on ({data.server.wan_interface || 'auto'})</Tag>
              ) : (
                <Tag>off</Tag>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="Public key" span={2}>
              <Typography.Text className="mono" copyable style={{ fontSize: 12 }}>
                {data.server.public_key}
              </Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="Config file">
              <span className="mono" style={{ fontSize: 12 }}>
                {data.conf_path} {data.conf_exists ? '' : '(not written yet)'}
              </span>
            </Descriptions.Item>
          </Descriptions>
        ) : (
          <Typography.Text type="secondary">
            No server yet. Click “Create server”, then add peers and Apply / Start.
          </Typography.Text>
        )}
      </Panel>

      {data.features?.show_live_peers !== false ? (
        <Panel
          title={`Active connections (${data.online_count ?? data.live_peers?.length ?? 0})`}
          style={{ marginTop: 16 }}
          extra={
            <Space size={12}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                handshake ≤ {data.features?.online_handshake_seconds ?? 180}s · refresh 10s
              </Typography.Text>
              <Link to="/history" style={{ fontSize: 12 }}>
                <HistoryOutlined /> Full history
              </Link>
            </Space>
          }
        >
          {data.status?.error && !data.status?.up ? (
            <Alert type="warning" showIcon message={data.status.error} style={{ marginBottom: 12 }} />
          ) : null}
          <Table
            size="small"
            rowKey={(r) => r.public_key || r.id || r.name}
            dataSource={data.live_peers || []}
            pagination={tablePagination(10)}
            locale={{ emptyText: 'No peers with a recent handshake' }}
            columns={[
              {
                title: 'Peer',
                dataIndex: 'name',
                render: (v: string) => <span className="mono">{v}</span>,
              },
              {
                title: 'VPN IP',
                dataIndex: 'address',
                render: (v?: string) => <span className="mono">{v || '—'}</span>,
              },
              {
                title: 'Endpoint',
                key: 'endpoint',
                render: (_: unknown, r: LivePeer) => (
                  <span className="mono">
                    {r.endpoint_runtime ||
                      (r.remote_ip
                        ? `${r.remote_ip}${r.remote_port ? `:${r.remote_port}` : ''}`
                        : '—')}
                  </span>
                ),
              },
              {
                title: 'Handshake',
                dataIndex: 'latest_handshake_ago_human',
                width: 120,
                render: (v?: string) => (
                  <span className="mono" style={{ fontSize: 12 }}>
                    {v || 'never'}
                  </span>
                ),
              },
              {
                title: 'Transfer',
                key: 'transfer',
                width: 180,
                render: (_: unknown, r: LivePeer) => (
                  <div className="mono" style={{ fontSize: 12, lineHeight: 1.45 }}>
                    <div>↓ {r.transfer_rx_human || formatBytes(r.transfer_rx)}</div>
                    <div>↑ {r.transfer_tx_human || formatBytes(r.transfer_tx)}</div>
                  </div>
                ),
              },
            ]}
          />
        </Panel>
      ) : null}

      <Panel
        title="Connection archive (24h)"
        style={{ marginTop: 16 }}
        extra={
          <Space size={12}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {historyLoading
                ? 'loading…'
                : data.features?.record_history
                  ? `${historyRows.length} record(s)`
                  : 'history off'}
            </Typography.Text>
            <Link to="/history" style={{ fontSize: 12 }}>
              Open History →
            </Link>
          </Space>
        }
      >
        {!data.features?.record_history ? (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="Connection archive is disabled"
            description="Enable “Write connection history to DB” in WireGuard module settings to record connect/disconnect events."
          />
        ) : null}
        <Table
          size="small"
          rowKey="id"
          loading={historyLoading}
          dataSource={historyRows}
          pagination={tablePagination(10)}
          locale={{
            emptyText: data.features?.record_history
              ? 'No connection history yet'
              : 'Enable history in Settings to start recording',
          }}
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
              render: (_: unknown, r?: ConnHistoryRow) => (
                <span className="mono">{r?.remote || r?.remote_ip || '—'}</span>
              ),
            },
            {
              title: 'Start',
              dataIndex: 'started_at',
              width: 170,
              render: (v: string) => (
                <span className="mono" style={{ fontSize: 12 }}>
                  {new Date(v).toLocaleString()}
                </span>
              ),
            },
            {
              title: 'Duration',
              dataIndex: 'duration_seconds',
              width: 110,
              render: (v?: number | null, r?: ConnHistoryRow) => {
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
              title: 'Transfer',
              key: 'xfer',
              width: 160,
              render: (_: unknown, r?: ConnHistoryRow) => (
                <span className="mono" style={{ fontSize: 12 }}>
                  ↓ {formatBytes(r?.transfer_rx)} · ↑ {formatBytes(r?.transfer_tx)}
                </span>
              ),
            },
          ]}
        />
      </Panel>

      <Panel title={`Peers (${data.peer_count || 0})`} style={{ marginTop: 16 }}>
        <Table
          size="small"
          rowKey="id"
          dataSource={data.peers || []}
          pagination={tablePagination(10)}
          locale={{ emptyText: 'No peers yet' }}
          columns={[
            {
              title: 'Name',
              dataIndex: 'name',
              render: (v: string, r: Peer) => (
                <Space size={6}>
                  <span className="mono">{v}</span>
                  {data.features?.show_live_peers !== false && r.online ? (
                    <Tag color="success">online</Tag>
                  ) : null}
                </Space>
              ),
            },
            {
              title: 'Address',
              dataIndex: 'address',
              render: (v: string) => <span className="mono">{v}</span>,
            },
            {
              title: 'Routes',
              dataIndex: 'route_mode',
              render: (mode: string, r: Peer) => (
                <div>
                  <Tag>{presets[mode || 'vpn_only']?.label || mode}</Tag>
                  <div className="mono" style={{ fontSize: 11, color: 'var(--la-muted)' }}>
                    {(r.allowed_ips_client || []).join(', ') || '—'}
                  </div>
                </div>
              ),
            },
            {
              title: 'DNS',
              key: 'dns',
              width: 140,
              render: (_: unknown, r: Peer) => {
                const mode = r.dns_mode || (r.dns ? 'custom' : 'none')
                if (mode === 'none') return <Tag>OS / corporate</Tag>
                if (mode === 'server') return <Tag color="blue">server</Tag>
                return (
                  <span className="mono" style={{ fontSize: 11 }}>
                    {r.dns || '—'}
                  </span>
                )
              },
            },
            {
              title: 'Enabled',
              dataIndex: 'enabled',
              width: 90,
              render: (v: boolean) => (
                <Tag color={v ? 'success' : 'default'}>{v ? 'yes' : 'no'}</Tag>
              ),
            },
            {
              title: 'Actions',
              key: 'actions',
              render: (_: unknown, r: Peer) => (
                <Space wrap size="small">
                  <Button
                    size="small"
                    icon={<QrcodeOutlined />}
                    onClick={() => void openPeerConfig(r.id)}
                  >
                    QR / Config
                  </Button>
                  <Button
                    size="small"
                    icon={<EditOutlined />}
                    disabled={!canMut}
                    onClick={() => openEditPeer(r)}
                  >
                    Edit
                  </Button>
                  <Button
                    size="small"
                    disabled={!canMut}
                    onClick={() =>
                      void runMut(
                        () =>
                          api(`/api/wireguard/peers/${encodeURIComponent(r.id)}`, {
                            method: 'PUT',
                            body: JSON.stringify({ enabled: !r.enabled, apply: true }),
                          }),
                        r.enabled ? 'Peer disabled' : 'Peer enabled',
                      )
                    }
                  >
                    {r.enabled ? 'Disable' : 'Enable'}
                  </Button>
                  <Button
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    disabled={!canMut}
                    onClick={() => {
                      Modal.confirm({
                        title: `Delete peer “${r.name}”?`,
                        onOk: () =>
                          runMut(
                            () =>
                              api(`/api/wireguard/peers/${encodeURIComponent(r.id)}`, {
                                method: 'DELETE',
                              }),
                            'Peer deleted',
                          ),
                      })
                    }}
                  />
                </Space>
              ),
            },
          ]}
        />
      </Panel>

      {data.ip_map ? (
        <Panel
          title="Address map"
          style={{ marginTop: 16 }}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              phpIPAM-style occupancy · free cell → create · peer cell → edit
            </Typography.Text>
          }
        >
          <WireGuardIpMap
            map={data.ip_map}
            canMutate={canMut}
            onFreeClick={(ip) => openCreatePeer(ip)}
            onPeerClick={openEditPeerById}
          />
        </Panel>
      ) : null}

      {data.status?.raw ? (
        <Panel title="wg show" style={{ marginTop: 16 }}>
          <pre className="mono" style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap' }}>
            {data.status.raw}
          </pre>
        </Panel>
      ) : null}

      <Modal
        title={data.server ? 'Edit WireGuard server' : 'Create WireGuard server'}
        open={serverOpen}
        onCancel={() => setServerOpen(false)}
        onOk={() => serverForm.submit()}
        confirmLoading={busy}
        okText="Save"
        width={560}
        destroyOnHidden
      >
        <Form
          form={serverForm}
          layout="vertical"
          onFinish={(values) =>
            void runMut(
              () =>
                api('/api/wireguard/server', {
                  method: 'POST',
                  body: JSON.stringify(values),
                }),
              'Server saved — click Apply / Start to activate',
            ).then((res) => {
              if (res?.ok) setServerOpen(false)
            })
          }
        >
          <Form.Item name="interface" label="Interface" rules={[{ required: true }]}>
            <Input className="mono" placeholder="wg0" />
          </Form.Item>
          <Form.Item
            name="address"
            label="Server address (CIDR)"
            extra="VPN network gateway, e.g. 10.66.0.1/24 — this subnet drives the address map"
            rules={[{ required: true }]}
          >
            <Input className="mono" />
          </Form.Item>
          <Form.Item name="listen_port" label="Listen port" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} min={1} max={65535} />
          </Form.Item>
          <Form.Item
            name="endpoint"
            label="Public endpoint for clients"
            extra="Must include port, e.g. vpn.example.com:51820 (host alone breaks Windows/mobile import)"
            rules={[
              { required: true, message: 'Endpoint is required' },
              {
                validator: async (_, value) => {
                  const v = String(value || '').trim()
                  if (!v) return
                  const m = v.match(/:(\d{1,5})$/)
                  if (!m) throw new Error('Use host:port, e.g. vpn.example.com:51820')
                  const port = Number(m[1])
                  if (port < 1 || port > 65535) throw new Error('Port must be 1–65535')
                },
              },
            ]}
          >
            <Input className="mono" placeholder="vpn.example.com:51820" />
          </Form.Item>
          <Form.Item
            name="dns"
            label="Default DNS for peers (optional)"
            extra="Not written into client configs automatically. Peers that choose “Use server DNS” get this value. Leave empty for corporate / domain clients."
          >
            <Input className="mono" placeholder="empty = do not push DNS" />
          </Form.Item>
          <Form.Item name="mtu" label="MTU">
            <InputNumber style={{ width: '100%' }} min={1280} max={9000} />
          </Form.Item>
          <Form.Item name="nat_enabled" label="NAT + IP forwarding (internet via VPN)" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="wan_interface" label="WAN interface for NAT" extra="Auto-detected if empty">
            <Input className="mono" placeholder="eth0 / ens3" />
          </Form.Item>
          <Form.Item name="rotate_keys" label="Rotate server keys" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editingPeer ? `Edit peer — ${editingPeer.name}` : 'Add peer / device'}
        open={peerOpen}
        onCancel={() => {
          setPeerOpen(false)
          setEditingPeer(null)
        }}
        onOk={() => peerForm.submit()}
        confirmLoading={busy}
        okText={editingPeer ? 'Save & re-issue config' : 'Create'}
        width={600}
        destroyOnHidden
      >
        <Form
          form={peerForm}
          layout="vertical"
          onFinish={(values) => {
            const payload = buildPeerPayload(values)
            void runMut(async () => {
              const res = editingPeer
                ? await api<PeerMutResult>(
                    `/api/wireguard/peers/${encodeURIComponent(editingPeer.id)}`,
                    { method: 'PUT', body: JSON.stringify(payload) },
                  )
                : await api<PeerMutResult>('/api/wireguard/peers', {
                    method: 'POST',
                    body: JSON.stringify(payload),
                  })
              if (res.ok && res.client_config && res.peer) {
                setConfigModal({
                  name: res.peer.name,
                  filename: `${res.peer.name}.conf`,
                  config: res.client_config,
                })
              }
              return res
            }, editingPeer ? 'Peer updated — import the new config on the client' : 'Peer created').then(
              (res) => {
                if (res?.ok) {
                  setPeerOpen(false)
                  setEditingPeer(null)
                }
              },
            )
          }}
        >
          <Form.Item
            name="name"
            label="Device name"
            extra="Rename anytime. Letters, digits, ._- ; max 32."
            rules={[{ required: true }]}
          >
            <Input className="mono" placeholder="phone / laptop" />
          </Form.Item>
          <Form.Item
            name="address"
            label="Client IP"
            extra={
              data.server?.address
                ? `Must be free inside ${data.server.address}. Leave empty on create to auto-assign. Or pick a free cell on the address map.`
                : 'Leave empty to auto-assign'
            }
          >
            <Input className="mono" placeholder="e.g. 10.77.77.12" />
          </Form.Item>
          <Form.Item
            name="route_mode"
            label="Traffic through VPN (AllowedIPs)"
            extra={routeHelp}
            rules={[{ required: true }]}
          >
            <Radio.Group
              style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
              options={Object.entries(presets).map(([value, meta]) => ({
                value,
                label: (
                  <span>
                    {meta.label}
                    <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12 }}>
                      {meta.description}
                    </Typography.Text>
                  </span>
                ),
              }))}
            />
          </Form.Item>
          {routeMode === 'custom' ? (
            <Form.Item
              name="allowed_ips_text"
              label="Custom AllowedIPs"
              extra="Comma or newline separated CIDRs"
              rules={[{ required: true }]}
            >
              <Input.TextArea
                rows={3}
                className="mono"
                placeholder="10.77.77.0/24, 192.168.10.0/24"
              />
            </Form.Item>
          ) : null}
          <Form.Item
            name="dns_mode"
            label="Client DNS"
            extra="WireGuard DNS= overrides the OS resolver. Keep OS / corporate DNS for domain-joined laptops."
            rules={[{ required: true }]}
          >
            <Radio.Group
              style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
              options={[
                {
                  value: 'none',
                  label: (
                    <span>
                      Keep OS / corporate DNS
                      <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12 }}>
                        No DNS= in config — recommended for domain users
                      </Typography.Text>
                    </span>
                  ),
                },
                {
                  value: 'server',
                  label: (
                    <span>
                      Use server DNS
                      <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12 }}>
                        Push the optional server DNS field (if set)
                      </Typography.Text>
                    </span>
                  ),
                },
                {
                  value: 'custom',
                  label: (
                    <span>
                      Custom DNS
                      <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12 }}>
                        Set specific resolvers for this peer only
                      </Typography.Text>
                    </span>
                  ),
                },
              ]}
            />
          </Form.Item>
          {peerDnsMode === 'custom' ? (
            <Form.Item
              name="dns"
              label="Custom DNS servers"
              rules={[{ required: true, message: 'Enter at least one DNS' }]}
            >
              <Input className="mono" placeholder="1.1.1.1, 8.8.8.8" />
            </Form.Item>
          ) : null}
          <Form.Item name="persistent_keepalive" label="PersistentKeepalive (sec)">
            <InputNumber style={{ width: '100%' }} min={0} max={600} />
          </Form.Item>
          {!editingPeer ? (
            <Form.Item name="use_preshared_key" label="Preshared key" valuePropName="checked">
              <Switch />
            </Form.Item>
          ) : (
            <Form.Item name="enabled" label="Enabled" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
          <Form.Item name="notes" label="Notes">
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`Client config — ${configModal?.name || ''}`}
        open={!!configModal}
        onCancel={() => setConfigModal(null)}
        width={640}
        footer={
          <Space wrap>
            <Button
              icon={<CopyOutlined />}
              onClick={() => configModal && void copyText(configModal.config)}
            >
              Copy
            </Button>
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              onClick={() =>
                configModal && downloadText(configModal.filename, configModal.config)
              }
            >
              Download .conf
            </Button>
            <Button onClick={() => setConfigModal(null)}>Close</Button>
          </Space>
        }
      >
        {configModal ? (
          <div style={{ display: 'grid', gap: 16, gridTemplateColumns: '160px 1fr' }}>
            <div style={{ textAlign: 'center' }}>
              <QRCode value={configModal.config} size={148} errorLevel="M" />
              <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
                Scan in the WireGuard app
              </Typography.Text>
            </div>
            <pre
              className="mono"
              style={{
                margin: 0,
                fontSize: 12,
                maxHeight: 360,
                overflow: 'auto',
                padding: 12,
                background: 'var(--la-panel)',
                borderRadius: 8,
                border: '1px solid var(--la-panel-border)',
              }}
            >
              {configModal.config}
            </pre>
          </div>
        ) : null}
      </Modal>
    </div>
  )
}
