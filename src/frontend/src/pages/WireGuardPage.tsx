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
} from '@ant-design/icons'
import { api } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { tablePagination } from '../utils/tablePagination'

type Peer = {
  id: string
  name: string
  public_key?: string
  address?: string
  route_mode?: string
  allowed_ips_client?: string[]
  dns?: string
  persistent_keepalive?: number
  enabled?: boolean
  notes?: string
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
  status?: { up?: boolean; error?: string; raw?: string }
  route_presets?: Record<string, { label: string; description: string }>
  conf_path?: string
  conf_exists?: boolean
}

export function WireGuardPage() {
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [serverOpen, setServerOpen] = useState(false)
  const [peerOpen, setPeerOpen] = useState(false)
  const [configModal, setConfigModal] = useState<{
    name: string
    filename: string
    config: string
  } | null>(null)
  const [serverForm] = Form.useForm()
  const [peerForm] = Form.useForm()
  const routeMode = Form.useWatch('route_mode', peerForm)

  const load = useCallback(() => {
    void api<Overview>('/api/wireguard')
      .then(setData)
      .catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const canMut = !!data?.allow_mutations
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
    const p = presets[routeMode || 'full']
    return p?.description || ''
  }, [presets, routeMode])

  if (error) return <Alert type="error" message={error} showIcon />
  if (!data) return <Typography.Text type="secondary">Loading…</Typography.Text>
  if (data.disabled) {
    return <Alert type="warning" message={data.error || 'WireGuard module disabled'} showIcon />
  }

  return (
    <div className="la-page">
      <PageHeader
        title="WireGuard"
        subtitle={
          data.server
            ? `${data.server.interface} · ${data.status?.up ? 'UP' : 'DOWN'} · ${data.peer_count || 0} peer(s)`
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
                  dns: s?.dns || '1.1.1.1, 8.8.8.8',
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
              onClick={() => {
                peerForm.resetFields()
                peerForm.setFieldsValue({
                  route_mode: 'full',
                  persistent_keepalive: 25,
                  use_preshared_key: true,
                  apply: true,
                })
                setPeerOpen(true)
              }}
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
            <Descriptions.Item label="DNS">
              <span className="mono">{data.server.dns || '—'}</span>
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
              render: (v: string) => <span className="mono">{v}</span>,
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
                  <Tag>{presets[mode || 'full']?.label || mode}</Tag>
                  <div className="mono" style={{ fontSize: 11, color: 'var(--la-muted)' }}>
                    {(r.allowed_ips_client || []).join(', ') || '—'}
                  </div>
                </div>
              ),
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
            extra="VPN network gateway, e.g. 10.66.0.1/24"
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
            extra="host:port that peers use to reach this server"
          >
            <Input className="mono" placeholder="vpn.example.com:51820" />
          </Form.Item>
          <Form.Item name="dns" label="DNS pushed to clients">
            <Input className="mono" placeholder="1.1.1.1, 8.8.8.8" />
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
        title="Add peer / device"
        open={peerOpen}
        onCancel={() => setPeerOpen(false)}
        onOk={() => peerForm.submit()}
        confirmLoading={busy}
        okText="Create"
        width={560}
        destroyOnHidden
      >
        <Form
          form={peerForm}
          layout="vertical"
          onFinish={(values) =>
            void runMut(async () => {
              const res = await api<{
                ok: boolean
                error?: string
                client_config?: string
                peer?: Peer
                filename?: string
              }>('/api/wireguard/peers', {
                method: 'POST',
                body: JSON.stringify({
                  ...values,
                  allowed_ips_client:
                    values.route_mode === 'custom'
                      ? String(values.allowed_ips_text || '')
                          .split(/[,\n]/)
                          .map((s: string) => s.trim())
                          .filter(Boolean)
                      : undefined,
                }),
              })
              if (res.ok && res.client_config && res.peer) {
                setConfigModal({
                  name: res.peer.name,
                  filename: `${res.peer.name}.conf`,
                  config: res.client_config,
                })
              }
              return res
            }, 'Peer created').then((res) => {
              if (res?.ok) setPeerOpen(false)
            })
          }
        >
          <Form.Item name="name" label="Device name" rules={[{ required: true }]}>
            <Input className="mono" placeholder="phone / laptop" />
          </Form.Item>
          <Form.Item
            name="route_mode"
            label="Traffic through VPN"
            extra={routeHelp}
            rules={[{ required: true }]}
          >
            <Radio.Group
              style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
              options={Object.entries(presets).map(([value, meta]) => ({
                value,
                label: meta.label,
              }))}
            />
          </Form.Item>
          {routeMode === 'custom' ? (
            <Form.Item
              name="allowed_ips_text"
              label="Custom AllowedIPs"
              extra="Comma or newline separated CIDRs (client-side routes)"
              rules={[{ required: true }]}
            >
              <Input.TextArea rows={3} className="mono" placeholder="10.0.0.0/8, 192.168.1.0/24" />
            </Form.Item>
          ) : null}
          <Form.Item name="dns" label="DNS override (optional)">
            <Input className="mono" placeholder="Leave empty to use server DNS" />
          </Form.Item>
          <Form.Item name="persistent_keepalive" label="PersistentKeepalive (sec)">
            <InputNumber style={{ width: '100%' }} min={0} max={600} />
          </Form.Item>
          <Form.Item name="use_preshared_key" label="Preshared key" valuePropName="checked">
            <Switch />
          </Form.Item>
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
                background: 'var(--la-paper)',
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
