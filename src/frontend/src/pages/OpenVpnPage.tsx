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
  Select,
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

type Client = {
  id: string
  name: string
  route_mode?: string
  push_routes?: string[]
  redirect_gateway?: boolean
  dns?: string
  enabled?: boolean
  notes?: string
}

type Overview = {
  available: boolean
  disabled?: boolean
  error?: string
  allow_mutations?: boolean
  installed?: boolean
  tools?: { openvpn?: boolean; openssl?: boolean; pkg_manager?: string | null }
  server?: {
    instance?: string
    network?: string
    port?: number
    proto?: string
    dev?: string
    dns?: string
    endpoint_host?: string
    cipher?: string
    auth?: string
    nat_enabled?: boolean
    wan_interface?: string
    client_to_client?: boolean
    compress?: string
    max_clients?: number
    keepalive?: string
  } | null
  clients?: Client[]
  client_count?: number
  status?: { active?: boolean; state?: string; unit?: string }
  route_presets?: Record<string, { label: string; description: string }>
  conf_path?: string
  conf_exists?: boolean
}

export function OpenVpnPage() {
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [serverOpen, setServerOpen] = useState(false)
  const [clientOpen, setClientOpen] = useState(false)
  const [configModal, setConfigModal] = useState<{
    name: string
    filename: string
    config: string
    qrRecommended: boolean
  } | null>(null)
  const [serverForm] = Form.useForm()
  const [clientForm] = Form.useForm()
  const routeMode = Form.useWatch('route_mode', clientForm)

  const load = useCallback(() => {
    void api<Overview>('/api/openvpn')
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
    const blob = new Blob([text], { type: 'application/x-openvpn-profile;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  const openClientConfig = async (clientId: string) => {
    try {
      const res = await api<{
        ok: boolean
        error?: string
        filename?: string
        config?: string
        client?: Client
        qr_recommended?: boolean
      }>(`/api/openvpn/clients/${encodeURIComponent(clientId)}/config`)
      if (!res.ok || !res.config) {
        message.error(res.error || 'Failed to load config')
        return
      }
      setConfigModal({
        name: res.client?.name || clientId,
        filename: res.filename || `${clientId}.ovpn`,
        config: res.config,
        qrRecommended: !!res.qr_recommended,
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
    return <Alert type="warning" message={data.error || 'OpenVPN module disabled'} showIcon />
  }

  return (
    <div className="la-page">
      <PageHeader
        title="OpenVPN"
        subtitle={
          data.server
            ? `${data.server.instance} · ${data.status?.active ? 'UP' : 'DOWN'} · ${data.client_count || 0} client(s)`
            : 'Create an OpenVPN server and issue client .ovpn profiles'
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
                    () => api('/api/openvpn/install', { method: 'POST', body: '{}' }),
                    'OpenVPN tools installed',
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
                  network: s?.network || '10.8.0.0/24',
                  port: s?.port || 1194,
                  proto: s?.proto || 'udp',
                  dev: s?.dev || 'tun',
                  dns: s?.dns || '1.1.1.1, 8.8.8.8',
                  endpoint_host: s?.endpoint_host || '',
                  cipher: s?.cipher || 'AES-256-GCM',
                  auth: s?.auth || 'SHA256',
                  nat_enabled: s?.nat_enabled !== false,
                  wan_interface: s?.wan_interface || '',
                  client_to_client: s?.client_to_client !== false,
                  compress: s?.compress || 'off',
                  max_clients: s?.max_clients || 100,
                  keepalive: s?.keepalive || '10 120',
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
                  () => api('/api/openvpn/server/apply', { method: 'POST', body: '{}' }),
                  'OpenVPN applied (systemctl restart)',
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
                  () => api('/api/openvpn/server/stop', { method: 'POST', body: '{}' }),
                  'OpenVPN stopped',
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
                clientForm.resetFields()
                clientForm.setFieldsValue({
                  route_mode: 'full',
                  apply: true,
                })
                setClientOpen(true)
              }}
            >
              Add client
            </Button>
          </Space>
        }
      />

      {!canMut ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Read-only mode. Enable “Allow changes” for OpenVPN in Settings (needs root/sudo)."
        />
      ) : null}

      {!data.installed ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="OpenVPN / OpenSSL not found"
          description={`Install via the button above (package manager: ${data.tools?.pkg_manager || 'unknown'}).`}
        />
      ) : null}

      <Panel title="Server">
        {data.server ? (
          <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }}>
            <Descriptions.Item label="Status">
              <Tag color={data.status?.active ? 'success' : 'default'}>
                {data.status?.active ? 'UP' : data.status?.state || 'DOWN'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Unit">
              <span className="mono">{data.status?.unit || '—'}</span>
            </Descriptions.Item>
            <Descriptions.Item label="Network">
              <span className="mono">{data.server.network}</span>
            </Descriptions.Item>
            <Descriptions.Item label="Listen">
              <span className="mono">
                {data.server.proto}/{data.server.port} ({data.server.dev})
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="Endpoint (for clients)">
              <span className="mono">{data.server.endpoint_host}</span>
            </Descriptions.Item>
            <Descriptions.Item label="DNS">
              <span className="mono">{data.server.dns || '—'}</span>
            </Descriptions.Item>
            <Descriptions.Item label="Cipher / auth">
              <span className="mono">
                {data.server.cipher} / {data.server.auth}
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="NAT / forwarding">
              {data.server.nat_enabled ? (
                <Tag color="success">on ({data.server.wan_interface || 'auto'})</Tag>
              ) : (
                <Tag>off</Tag>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="Client-to-client">
              <Tag color={data.server.client_to_client ? 'success' : 'default'}>
                {data.server.client_to_client ? 'on' : 'off'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Config file" span={2}>
              <span className="mono" style={{ fontSize: 12 }}>
                {data.conf_path} {data.conf_exists ? '' : '(not written yet)'}
              </span>
            </Descriptions.Item>
          </Descriptions>
        ) : (
          <Typography.Text type="secondary">
            No server yet. Click “Create server”, then add clients and Apply / Start.
          </Typography.Text>
        )}
      </Panel>

      <Panel title={`Clients (${data.client_count || 0})`} style={{ marginTop: 16 }}>
        <Table
          size="small"
          rowKey="id"
          dataSource={data.clients || []}
          pagination={tablePagination(10)}
          locale={{ emptyText: 'No clients yet' }}
          columns={[
            {
              title: 'Name',
              dataIndex: 'name',
              render: (v: string) => <span className="mono">{v}</span>,
            },
            {
              title: 'Routes',
              dataIndex: 'route_mode',
              render: (mode: string, r: Client) => (
                <div>
                  <Tag>{presets[mode || 'full']?.label || mode}</Tag>
                  <div className="mono" style={{ fontSize: 11, color: 'var(--la-muted)' }}>
                    {r.redirect_gateway
                      ? 'redirect-gateway'
                      : (r.push_routes || []).join(', ') || 'VPN subnet only'}
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
              render: (_: unknown, r: Client) => (
                <Space wrap size="small">
                  <Button
                    size="small"
                    icon={<QrcodeOutlined />}
                    onClick={() => void openClientConfig(r.id)}
                  >
                    .ovpn / QR
                  </Button>
                  <Button
                    size="small"
                    disabled={!canMut}
                    onClick={() =>
                      void runMut(
                        () =>
                          api(`/api/openvpn/clients/${encodeURIComponent(r.id)}`, {
                            method: 'PUT',
                            body: JSON.stringify({ enabled: !r.enabled, apply: true }),
                          }),
                        r.enabled ? 'Client disabled' : 'Client enabled',
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
                        title: `Delete client “${r.name}”?`,
                        onOk: () =>
                          runMut(
                            () =>
                              api(`/api/openvpn/clients/${encodeURIComponent(r.id)}`, {
                                method: 'DELETE',
                              }),
                            'Client deleted',
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

      <Modal
        title={data.server ? 'Edit OpenVPN server' : 'Create OpenVPN server'}
        open={serverOpen}
        onCancel={() => setServerOpen(false)}
        onOk={() => serverForm.submit()}
        confirmLoading={busy}
        okText="Save"
        width={600}
        destroyOnHidden
      >
        <Form
          form={serverForm}
          layout="vertical"
          onFinish={(values) =>
            void runMut(
              () =>
                api('/api/openvpn/server', {
                  method: 'POST',
                  body: JSON.stringify(values),
                }),
              'Server saved — click Apply / Start to activate',
            ).then((res) => {
              if (res?.ok) setServerOpen(false)
            })
          }
        >
          <Form.Item
            name="network"
            label="VPN network (CIDR)"
            extra="Server becomes .1 in this subnet, e.g. 10.8.0.0/24"
            rules={[{ required: true }]}
          >
            <Input className="mono" />
          </Form.Item>
          <Space style={{ display: 'flex' }} size="middle" wrap>
            <Form.Item name="port" label="Listen port" rules={[{ required: true }]} style={{ minWidth: 140 }}>
              <InputNumber style={{ width: '100%' }} min={1} max={65535} />
            </Form.Item>
            <Form.Item name="proto" label="Protocol" rules={[{ required: true }]} style={{ minWidth: 120 }}>
              <Select
                options={[
                  { value: 'udp', label: 'UDP (recommended)' },
                  { value: 'tcp', label: 'TCP' },
                ]}
              />
            </Form.Item>
            <Form.Item name="dev" label="Device" rules={[{ required: true }]} style={{ minWidth: 120 }}>
              <Select
                options={[
                  { value: 'tun', label: 'tun (L3)' },
                  { value: 'tap', label: 'tap (L2)' },
                ]}
              />
            </Form.Item>
          </Space>
          <Form.Item
            name="endpoint_host"
            label="Public hostname / IP for clients"
            extra="Used in .ovpn as remote host (port is separate)"
          >
            <Input className="mono" placeholder="vpn.example.com" />
          </Form.Item>
          <Form.Item name="dns" label="DNS pushed to clients">
            <Input className="mono" placeholder="1.1.1.1, 8.8.8.8" />
          </Form.Item>
          <Space style={{ display: 'flex' }} size="middle" wrap>
            <Form.Item name="cipher" label="Cipher" style={{ minWidth: 200 }}>
              <Select
                options={[
                  { value: 'AES-256-GCM', label: 'AES-256-GCM' },
                  { value: 'AES-128-GCM', label: 'AES-128-GCM' },
                  { value: 'CHACHA20-POLY1305', label: 'CHACHA20-POLY1305' },
                ]}
              />
            </Form.Item>
            <Form.Item name="auth" label="Auth digest" style={{ minWidth: 160 }}>
              <Select
                options={[
                  { value: 'SHA256', label: 'SHA256' },
                  { value: 'SHA512', label: 'SHA512' },
                ]}
              />
            </Form.Item>
            <Form.Item name="compress" label="Compression" style={{ minWidth: 140 }}>
              <Select
                options={[
                  { value: 'off', label: 'Off (safer)' },
                  { value: 'lz4-v2', label: 'lz4-v2' },
                  { value: 'lz4', label: 'lz4' },
                ]}
              />
            </Form.Item>
          </Space>
          <Space style={{ display: 'flex' }} size="middle" wrap>
            <Form.Item name="max_clients" label="Max clients" style={{ minWidth: 140 }}>
              <InputNumber style={{ width: '100%' }} min={1} max={1000} />
            </Form.Item>
            <Form.Item
              name="keepalive"
              label="Keepalive"
              extra="ping timeout"
              style={{ minWidth: 160 }}
            >
              <Input className="mono" placeholder="10 120" />
            </Form.Item>
          </Space>
          <Form.Item name="nat_enabled" label="NAT + IP forwarding (internet via VPN)" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="wan_interface" label="WAN interface for NAT" extra="Auto-detected if empty">
            <Input className="mono" placeholder="eth0 / ens3" />
          </Form.Item>
          <Form.Item name="client_to_client" label="Allow clients to reach each other" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Add client / device"
        open={clientOpen}
        onCancel={() => setClientOpen(false)}
        onOk={() => clientForm.submit()}
        confirmLoading={busy}
        okText="Create"
        width={560}
        destroyOnHidden
      >
        <Form
          form={clientForm}
          layout="vertical"
          onFinish={(values) =>
            void runMut(async () => {
              const res = await api<{
                ok: boolean
                error?: string
                client_config?: string
                client?: Client
                filename?: string
                qr_recommended?: boolean
              }>('/api/openvpn/clients', {
                method: 'POST',
                body: JSON.stringify({
                  ...values,
                  push_routes:
                    values.route_mode === 'custom'
                      ? String(values.push_routes_text || '')
                          .split(/[,\n]/)
                          .map((s: string) => s.trim())
                          .filter(Boolean)
                      : undefined,
                }),
              })
              if (res.ok && res.client_config && res.client) {
                setConfigModal({
                  name: res.client.name,
                  filename: res.filename || `${res.client.name}.ovpn`,
                  config: res.client_config,
                  qrRecommended: !!res.qr_recommended,
                })
              }
              return res
            }, 'Client created').then((res) => {
              if (res?.ok) setClientOpen(false)
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
              name="push_routes_text"
              label="Custom routes to push"
              extra="Comma or newline separated CIDRs (server push)"
              rules={[{ required: true }]}
            >
              <Input.TextArea rows={3} className="mono" placeholder="10.0.0.0/8, 192.168.1.0/24" />
            </Form.Item>
          ) : null}
          <Form.Item name="dns" label="DNS override (optional)">
            <Input className="mono" placeholder="Leave empty to use server DNS" />
          </Form.Item>
          <Form.Item name="notes" label="Notes">
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`Client profile — ${configModal?.name || ''}`}
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
              Download .ovpn
            </Button>
            <Button onClick={() => setConfigModal(null)}>Close</Button>
          </Space>
        }
      >
        {configModal ? (
          <div
            style={{
              display: 'grid',
              gap: 16,
              gridTemplateColumns: configModal.qrRecommended ? '160px 1fr' : '1fr',
            }}
          >
            {configModal.qrRecommended ? (
              <div style={{ textAlign: 'center' }}>
                <QRCode value={configModal.config} size={148} errorLevel="L" />
                <Typography.Text
                  type="secondary"
                  style={{ fontSize: 12, display: 'block', marginTop: 8 }}
                >
                  Scan if your OpenVPN app supports QR
                </Typography.Text>
              </div>
            ) : (
              <Alert
                type="info"
                showIcon
                message="QR not shown — profile embeds certificates and is usually too large. Download the .ovpn file instead."
                style={{ marginBottom: 0 }}
              />
            )}
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
