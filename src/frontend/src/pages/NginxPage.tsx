import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Col,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  ReloadOutlined,
  ToolOutlined,
  PlusOutlined,
  DeleteOutlined,
  CloudUploadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  EyeOutlined,
  SafetyCertificateOutlined,
  RollbackOutlined,
  ApiOutlined,
  AppstoreOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip as RTooltip } from 'recharts'
import { api } from '../api/client'
import { useAccess } from '../api/access'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { tablePagination } from '../utils/tablePagination'

type Backend = { host: string; port: number; weight?: number; ok?: boolean }
type Route = {
  id: string
  name: string
  domain?: string
  aliases?: string[]
  proxy_type: string
  frontend_ip?: string
  frontend_port?: number
  backend_host?: string
  backend_port?: number
  backends?: Backend[]
  backend_proto?: string
  lb_method?: string
  cert_id?: string
  enabled?: boolean
  websocket?: boolean
  http2?: boolean
  logging?: boolean
  client_max_body_size?: string
  connect_timeout?: number
  send_timeout?: number
  read_timeout?: number
  allow_ips?: string[]
  deny_ips?: string[]
  session_timeout?: number
  tcp_keepalive?: number
}

type Cert = {
  id: string
  name: string
  source?: string
  not_after?: string
  days_left?: number | null
  expired?: boolean
  sans?: string[]
  subject?: string
  issuer?: string
}

type Overview = {
  available: boolean
  disabled?: boolean
  error?: string
  allow_mutations?: boolean
  installed?: boolean
  version?: string
  tools?: { nginx?: boolean; openssl?: boolean; certbot?: boolean; pkg_manager?: string | null }
  status?: { active?: boolean; state?: string; since?: string }
  stub_status?: {
    available?: boolean
    active_connections?: number
    requests?: number
    reading?: number
    writing?: number
    waiting?: number
  }
  routes?: Route[]
  route_count?: number
  routes_enabled?: number
  routes_by_type?: Record<string, number>
  certificates?: Cert[]
  certificate_count?: number
  certs_expiring?: Array<{ id: string; name?: string; days_left?: number; not_after?: string }>
  backends?: Array<{ route_id: string; route_name?: string; host: string; port: number; ok: boolean }>
  backends_ok?: number
  backends_down?: number
  last_apply?: { at?: string; backup?: string; ok?: boolean } | null
  last_reload?: string | null
  acme?: { email?: string; environment?: string; auto_renew?: boolean; renew_days_before?: number }
  dns_providers?: Array<{ id: string; name: string; type: string }>
  proxy_types?: Record<string, { label: string; layer: string }>
  lb_methods?: string[]
  templates?: RouteTemplate[]
  template_categories?: string[]
}

type RouteTemplate = {
  id: string
  title: string
  category: string
  icon?: string
  summary: string
  hints?: string[]
  required_overrides?: string[]
  defaults: Record<string, any>
  proxy_type?: string
}

type FieldIssue = { field: string; message: string }

const TYPE_COLORS = ['#0f766e', '#0369a1', '#b45309', '#7c3aed', '#be123c', '#15803d']

function routeToFormValues(r?: Partial<Route> | Record<string, any> | null) {
  const d = r || {}
  return {
    name: d.name || '',
    domain: d.domain || '',
    aliases: Array.isArray(d.aliases) ? d.aliases.join(', ') : d.aliases || '',
    proxy_type: d.proxy_type || 'http_reverse',
    frontend_ip: d.frontend_ip || '0.0.0.0',
    frontend_port:
      d.frontend_port ||
      (d.proxy_type === 'http_reverse' ? 80 : d.proxy_type === 'tcp' || d.proxy_type === 'udp' ? d.frontend_port : 443),
    backend_host: d.backend_host || d.backends?.[0]?.host || '',
    backend_port: d.backend_port || d.backends?.[0]?.port || 8080,
    backend_proto: d.backend_proto || 'http',
    lb_method: d.lb_method || 'round_robin',
    cert_id: d.cert_id || undefined,
    enabled: d.enabled !== false,
    websocket: d.websocket !== false,
    http2: d.http2 !== false,
    logging: d.logging !== false,
    client_max_body_size: d.client_max_body_size || '100m',
    connect_timeout: d.connect_timeout || 60,
    send_timeout: d.send_timeout || 300,
    read_timeout: d.read_timeout || 300,
    allow_ips: Array.isArray(d.allow_ips) ? d.allow_ips.join(', ') : d.allow_ips || '',
    deny_ips: Array.isArray(d.deny_ips) ? d.deny_ips.join(', ') : d.deny_ips || '',
    session_timeout: d.session_timeout || 3600,
    tcp_keepalive: d.tcp_keepalive ?? 60,
    apply: false,
  }
}

function formToRouteBody(v: Record<string, any>, editingId?: string) {
  const splitList = (s: string) =>
    String(s || '')
      .split(/[,\s]+/)
      .map((x) => x.trim())
      .filter(Boolean)
  return {
    id: editingId,
    name: v.name,
    domain: v.domain,
    aliases: splitList(v.aliases),
    proxy_type: v.proxy_type,
    frontend_ip: v.frontend_ip,
    frontend_port: v.frontend_port,
    backend_host: v.backend_host,
    backend_port: v.backend_port,
    backend_proto: v.backend_proto,
    lb_method: v.lb_method,
    cert_id: v.cert_id || null,
    enabled: v.enabled,
    websocket: v.websocket,
    http2: v.http2,
    logging: v.logging,
    client_max_body_size: v.client_max_body_size,
    connect_timeout: v.connect_timeout,
    send_timeout: v.send_timeout,
    read_timeout: v.read_timeout,
    allow_ips: splitList(v.allow_ips),
    deny_ips: splitList(v.deny_ips),
    session_timeout: v.session_timeout,
    tcp_keepalive: v.tcp_keepalive,
    apply: !!v.apply,
  }
}

export function NginxPage() {
  const { canMutate } = useAccess()
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [routeOpen, setRouteOpen] = useState(false)
  const [tplOpen, setTplOpen] = useState(false)
  const [tplCategory, setTplCategory] = useState<string>('all')
  const [activeTemplate, setActiveTemplate] = useState<RouteTemplate | null>(null)
  const [routeErrors, setRouteErrors] = useState<FieldIssue[]>([])
  const [routeWarnings, setRouteWarnings] = useState<FieldIssue[]>([])
  const [certOpen, setCertOpen] = useState(false)
  const [acmeOpen, setAcmeOpen] = useState(false)
  const [acmeTxt, setAcmeTxt] = useState<{
    name?: string
    value?: string
    domain?: string
  } | null>(null)
  const [acmeHint, setAcmeHint] = useState<string | null>(null)
  const [acmePoll, setAcmePoll] = useState(false)
  const [preview, setPreview] = useState<{ http?: string; stream?: string } | null>(null)
  const [logs, setLogs] = useState<{ kind: string; content: string; path?: string } | null>(null)
  const [backups, setBackups] = useState<Array<{ id: string }>>([])
  const [editing, setEditing] = useState<Route | null>(null)
  const [routeForm] = Form.useForm()
  const [certForm] = Form.useForm()
  const [acmeForm] = Form.useForm()
  const proxyType = Form.useWatch('proxy_type', routeForm)

  const load = useCallback(() => {
    void api<Overview>('/api/nginx')
      .then(setData)
      .catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const canMut = !!data?.allow_mutations && canMutate('nginx')

  const runMut = async (fn: () => Promise<any>, okMsg: string) => {
    setBusy(true)
    try {
      const res = await fn()
      if (res?.ok === false) {
        if (Array.isArray(res.errors) && res.errors.length) {
          setRouteErrors(res.errors)
          message.error(res.error || res.errors[0]?.message || 'Validation failed')
        } else {
          message.error(res.error || 'Error')
        }
        if (Array.isArray(res.warnings)) setRouteWarnings(res.warnings)
        return null
      }
      if (Array.isArray(res?.warnings) && res.warnings.length) {
        setRouteWarnings(res.warnings)
        message.warning(res.warnings[0].message)
      }
      if (res?.apply?.ok === false) message.warning(`Saved, apply failed: ${res.apply.error}`)
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

  const pieData = useMemo(() => {
    const by = data?.routes_by_type || {}
    return Object.entries(by).map(([name, value]) => ({ name, value }))
  }, [data?.routes_by_type])

  const templates = data?.templates || []
  const filteredTemplates = useMemo(() => {
    if (tplCategory === 'all') return templates
    return templates.filter((t) => t.category === tplCategory)
  }, [templates, tplCategory])

  const openRouteModal = (route?: Route) => {
    setEditing(route || null)
    setActiveTemplate(null)
    setRouteErrors([])
    setRouteWarnings([])
    routeForm.setFieldsValue(routeToFormValues(route))
    setRouteOpen(true)
  }

  const openFromTemplate = (tpl: RouteTemplate) => {
    setEditing(null)
    setActiveTemplate(tpl)
    setRouteErrors([])
    setRouteWarnings([])
    routeForm.setFieldsValue(routeToFormValues(tpl.defaults))
    setTplOpen(false)
    setRouteOpen(true)
    message.info(`Template “${tpl.title}” applied — adjust domain / backend if needed`)
  }

  const validateRouteDraft = async () => {
    try {
      const v = await routeForm.validateFields()
      const body = {
        ...formToRouteBody(v, editing?.id),
        template_id: activeTemplate?.id,
      }
      const res = await api<{
        ok: boolean
        errors?: FieldIssue[]
        warnings?: FieldIssue[]
        error?: string
      }>('/api/nginx/routes/validate', { method: 'POST', body: JSON.stringify(body) })
      setRouteErrors(res.errors || [])
      setRouteWarnings(res.warnings || [])
      if (!res.ok) {
        message.error(res.errors?.[0]?.message || res.error || 'Validation failed')
        return false
      }
      if (res.warnings?.length) message.warning(`${res.warnings.length} warning(s) — review before apply`)
      else message.success('Validation OK')
      return true
    } catch (e) {
      message.error(String(e))
      return false
    }
  }

  const saveRoute = async () => {
    const v = await routeForm.validateFields()
    const body = formToRouteBody(v, editing?.id)
    setBusy(true)
    try {
      let res: any
      if (activeTemplate && !editing) {
        const { id: _id, apply, ...overrides } = body
        res = await api('/api/nginx/routes/from-template', {
          method: 'POST',
          body: JSON.stringify({
            template_id: activeTemplate.id,
            apply: !!apply,
            overrides,
          }),
        })
      } else {
        res = await api('/api/nginx/routes', { method: 'POST', body: JSON.stringify(body) })
      }
      if (res?.ok === false) {
        setRouteErrors(res.errors || [])
        setRouteWarnings(res.warnings || [])
        message.error(res.error || res.errors?.[0]?.message || 'Error')
        return
      }
      setRouteErrors([])
      setRouteWarnings(res.warnings || [])
      if (res?.warnings?.length) message.warning(res.warnings[0].message)
      if (res?.apply?.ok === false) message.warning(`Saved, apply failed: ${res.apply.error}`)
      else message.success(editing ? 'Route updated' : 'Route created')
      setRouteOpen(false)
      setActiveTemplate(null)
      load()
    } catch (e) {
      message.error(String(e))
    } finally {
      setBusy(false)
    }
  }

  const loadPreview = async () => {
    try {
      const res = await api<{ ok: boolean; http?: string; stream?: string; error?: string }>(
        '/api/nginx/config/preview',
      )
      if (!res.ok) {
        message.error(res.error || 'Preview failed')
        return
      }
      setPreview({ http: res.http, stream: res.stream })
    } catch (e) {
      message.error(String(e))
    }
  }

  const loadLogs = async (kind: string) => {
    try {
      const res = await api<{ ok: boolean; content?: string; path?: string; error?: string }>(
        `/api/nginx/logs?kind=${encodeURIComponent(kind)}`,
      )
      if (!res.ok) {
        message.error(res.error || 'Failed to load logs')
        return
      }
      setLogs({ kind, content: res.content || '', path: res.path })
    } catch (e) {
      message.error(String(e))
    }
  }

  const loadBackups = async () => {
    try {
      const res = await api<{ ok: boolean; backups: Array<{ id: string }> }>('/api/nginx/backups')
      setBackups(res.backups || [])
    } catch {
      setBackups([])
    }
  }

  useEffect(() => {
    if (!acmePoll) return
    const t = window.setInterval(() => {
      void api<{
        ok: boolean
        status?: string
        pending?: boolean
        txt?: { name?: string; value?: string; domain?: string }
        result?: { ok?: boolean; error?: string }
      }>('/api/nginx/acme/dns-challenge')
        .then((res) => {
          if (res.txt) setAcmeTxt(res.txt)
          if (res.status === 'done' && res.result?.ok) {
            setAcmePoll(false)
            message.success('Certificate issued via DNS-01')
            setAcmeOpen(false)
            setAcmeTxt(null)
            load()
          } else if (res.status === 'failed' || res.status === 'timeout') {
            setAcmePoll(false)
            message.error(res.result?.error || 'DNS-01 failed')
          }
        })
        .catch(() => null)
    }, 3000)
    return () => window.clearInterval(t)
  }, [acmePoll, load])

  if (error) return <Alert type="error" message={error} showIcon />
  if (!data) return <Typography.Text type="secondary">Loading…</Typography.Text>
  if (data.disabled) {
    return <Alert type="warning" message={data.error || 'Nginx module disabled'} showIcon />
  }

  const proxyTypes = data.proxy_types || {}
  const isStream =
    proxyType === 'tls_passthrough' || proxyType === 'tcp' || proxyType === 'udp'
  const isHttps = proxyType === 'https_reverse'
  const isPassthrough = proxyType === 'tls_passthrough'

  const dashboard = (
    <div className="la-page" style={{ padding: 0 }}>
      {!data.installed ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="Nginx is not installed on this host"
          description="Install the package to manage edge proxy routes, certificates, and TLS passthrough."
          action={
            <Button
              type="primary"
              icon={<ToolOutlined />}
              disabled={!canMut}
              loading={busy}
              onClick={() =>
                void runMut(
                  () => api('/api/nginx/install', { method: 'POST', body: '{}' }),
                  'Nginx installed',
                )
              }
            >
              Install Nginx
            </Button>
          }
        />
      ) : null}

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Panel title="Nginx status">
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Tag color={data.status?.active ? 'success' : 'default'} icon={data.status?.active ? <CheckCircleOutlined /> : <CloseCircleOutlined />}>
                {data.status?.state || 'unknown'}
              </Tag>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {data.version || '—'}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Last reload: {data.last_reload || '—'}
              </Typography.Text>
            </Space>
          </Panel>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Panel title="Routes">
            <Typography.Title level={2} style={{ margin: 0 }}>
              {data.routes_enabled ?? 0}
            </Typography.Title>
            <Typography.Text type="secondary">enabled / {data.route_count ?? 0} total</Typography.Text>
          </Panel>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Panel title="Backends">
            <Space>
              <Tag color="success">{data.backends_ok ?? 0} up</Tag>
              <Tag color={data.backends_down ? 'error' : 'default'}>{data.backends_down ?? 0} down</Tag>
            </Space>
            <div style={{ marginTop: 8 }}>
              <Progress
                percent={
                  (data.backends_ok || 0) + (data.backends_down || 0)
                    ? Math.round(
                        ((data.backends_ok || 0) /
                          ((data.backends_ok || 0) + (data.backends_down || 0))) *
                          100,
                      )
                    : 100
                }
                size="small"
                status={data.backends_down ? 'exception' : 'success'}
              />
            </div>
          </Panel>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Panel title="Connections">
            {data.stub_status?.available ? (
              <>
                <Typography.Title level={2} style={{ margin: 0 }}>
                  {data.stub_status.active_connections ?? 0}
                </Typography.Title>
                <Typography.Text type="secondary">
                  R {data.stub_status.reading} · W {data.stub_status.writing} · Wait{' '}
                  {data.stub_status.waiting}
                </Typography.Text>
              </>
            ) : (
              <Typography.Text type="secondary">stub_status after apply</Typography.Text>
            )}
          </Panel>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={10}>
          <Panel title="Routes by type">
            {pieData.length ? (
              <div style={{ height: 220 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={pieData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85} paddingAngle={2}>
                      {pieData.map((_, i) => (
                        <Cell key={i} fill={TYPE_COLORS[i % TYPE_COLORS.length]} />
                      ))}
                    </Pie>
                    <RTooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <Typography.Text type="secondary">No active routes yet</Typography.Text>
            )}
            <Space wrap style={{ marginTop: 8 }}>
              {pieData.map((d, i) => (
                <Tag key={d.name} color={TYPE_COLORS[i % TYPE_COLORS.length]}>
                  {(proxyTypes[d.name]?.label || d.name) + `: ${d.value}`}
                </Tag>
              ))}
            </Space>
          </Panel>
        </Col>
        <Col xs={24} lg={14}>
          <Panel title="Certificates & expiry">
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="Stored">{data.certificate_count ?? 0}</Descriptions.Item>
              <Descriptions.Item label="Expiring soon">
                {(data.certs_expiring || []).length ? (
                  <Space wrap>
                    {(data.certs_expiring || []).map((c) => (
                      <Tag key={c.id} color="warning">
                        {c.name || c.id}: {c.days_left ?? '?'}d
                      </Tag>
                    ))}
                  </Space>
                ) : (
                  <Typography.Text type="secondary">None within renewal window</Typography.Text>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="ACME">
                {data.acme?.email || 'email not set'} · {data.acme?.environment || 'production'}
              </Descriptions.Item>
            </Descriptions>
          </Panel>
        </Col>
      </Row>

      <Panel title="Backend health" style={{ marginTop: 16 }}>
        <Table
          size="small"
          rowKey={(r) => `${r.route_id}-${r.host}-${r.port}`}
          dataSource={data.backends || []}
          pagination={tablePagination(8)}
          columns={[
            { title: 'Route', dataIndex: 'route_name' },
            {
              title: 'Backend',
              render: (_, r) => `${r.host}:${r.port}`,
            },
            {
              title: 'Status',
              dataIndex: 'ok',
              render: (ok: boolean) =>
                ok ? <Tag color="success">up</Tag> : <Tag color="error">down</Tag>,
            },
          ]}
        />
      </Panel>
    </div>
  )

  const routesTab = (
    <Panel
      title="Proxy routes"
      extra={
        <Space wrap>
          <Button
            icon={<AppstoreOutlined />}
            disabled={!canMut || !data.installed}
            onClick={() => {
              setTplCategory('all')
              setTplOpen(true)
            }}
          >
            From template
          </Button>
          <Button type="primary" icon={<PlusOutlined />} disabled={!canMut || !data.installed} onClick={() => openRouteModal()}>
            Add route
          </Button>
        </Space>
      }
    >
      <Table
        size="small"
        rowKey="id"
        dataSource={data.routes || []}
        pagination={tablePagination(10)}
        columns={[
          {
            title: 'Name',
            dataIndex: 'name',
            render: (n, r) => (
              <Space>
                <span>{n}</span>
                {!r.enabled ? <Tag>disabled</Tag> : null}
              </Space>
            ),
          },
          {
            title: 'Type',
            dataIndex: 'proxy_type',
            render: (t: string) => <Tag>{proxyTypes[t]?.label || t}</Tag>,
          },
          {
            title: 'Frontend',
            render: (_, r) => `${r.domain || '—'} · ${r.frontend_ip || '0.0.0.0'}:${r.frontend_port}`,
          },
          {
            title: 'Backend',
            render: (_, r) =>
              (r.backends || [])
                .map((b) => `${b.host}:${b.port}`)
                .join(', ') || `${r.backend_host}:${r.backend_port}`,
          },
          {
            title: 'Flags',
            render: (_, r) => (
              <Space size={4} wrap>
                {r.websocket ? <Tag>WS</Tag> : null}
                {r.http2 ? <Tag>H2</Tag> : null}
                {r.proxy_type === 'tls_passthrough' ? <Tag color="purple">SNI / backend cert</Tag> : null}
                {r.cert_id ? <Tag icon={<SafetyCertificateOutlined />}>TLS</Tag> : null}
              </Space>
            ),
          },
          {
            title: '',
            width: 160,
            render: (_, r) => (
              <Space>
                <Button size="small" disabled={!canMut} onClick={() => openRouteModal(r)}>
                  Edit
                </Button>
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  disabled={!canMut}
                  onClick={() =>
                    void runMut(
                      () =>
                        api(`/api/nginx/routes/${encodeURIComponent(r.id)}?apply=false`, {
                          method: 'DELETE',
                        }),
                      'Route deleted',
                    )
                  }
                />
              </Space>
            ),
          },
        ]}
      />
    </Panel>
  )

  const certsTab = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Panel
        title="Certificates"
        extra={
          <Space>
            <Button disabled={!canMut} icon={<CloudUploadOutlined />} onClick={() => { certForm.resetFields(); setCertOpen(true) }}>
              Upload PEM
            </Button>
            <Button disabled={!canMut || !data.installed} onClick={() => setAcmeOpen(true)}>
              Let&apos;s Encrypt
            </Button>
          </Space>
        }
      >
        <Table
          size="small"
          rowKey="id"
          dataSource={data.certificates || []}
          pagination={tablePagination(8)}
          columns={[
            { title: 'Name', dataIndex: 'name' },
            { title: 'Source', dataIndex: 'source', render: (s) => <Tag>{s || '—'}</Tag> },
            {
              title: 'SAN',
              dataIndex: 'sans',
              render: (sans: string[]) => (sans || []).slice(0, 3).join(', ') || '—',
            },
            {
              title: 'Expires',
              render: (_, c) =>
                c.expired ? (
                  <Tag color="error">expired</Tag>
                ) : (
                  <span>
                    {c.not_after || '—'}{' '}
                    {c.days_left != null ? <Tag color={c.days_left <= 30 ? 'warning' : 'default'}>{c.days_left}d</Tag> : null}
                  </span>
                ),
            },
            {
              title: '',
              width: 80,
              render: (_, c) => (
                <Button
                  size="small"
                  danger
                  disabled={!canMut}
                  icon={<DeleteOutlined />}
                  onClick={() =>
                    void runMut(
                      () => api(`/api/nginx/certificates/${encodeURIComponent(c.id)}`, { method: 'DELETE' }),
                      'Certificate deleted',
                    )
                  }
                />
              ),
            },
          ]}
        />
      </Panel>
      {isPassthrough ? null : null}
      <Alert
        type="info"
        showIcon
        message="TLS Passthrough"
        description="For TLS Passthrough routes, certificates are installed and renewed on the backend server — Nginx only routes by SNI without decryption."
      />
    </Space>
  )

  const configTab = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Space wrap>
        <Button icon={<EyeOutlined />} onClick={() => void loadPreview()}>
          Preview config
        </Button>
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          disabled={!canMut || !data.installed}
          loading={busy}
          onClick={() =>
            void runMut(
              () => api('/api/nginx/config/apply', { method: 'POST', body: '{}' }),
              'Configuration applied (nginx -t + reload)',
            )
          }
        >
          Apply (test + reload)
        </Button>
        <Button
          disabled={!canMut || !data.installed}
          onClick={() =>
            void runMut(
              () => api('/api/nginx/service/reload', { method: 'POST', body: '{}' }),
              'Nginx reloaded',
            )
          }
        >
          Reload
        </Button>
        <Button
          disabled={!canMut || !data.installed}
          icon={<PauseCircleOutlined />}
          onClick={() =>
            void runMut(
              () => api('/api/nginx/service/stop', { method: 'POST', body: '{}' }),
              'Nginx stopped',
            )
          }
        >
          Stop
        </Button>
        <Button
          disabled={!canMut || !data.installed}
          onClick={() =>
            void runMut(
              () => api('/api/nginx/service/start', { method: 'POST', body: '{}' }),
              'Nginx started',
            )
          }
        >
          Start
        </Button>
        <Button
          disabled={!canMut}
          onClick={() =>
            void runMut(
              () => api('/api/nginx/backups', { method: 'POST', body: '{}' }),
              'Backup created',
            ).then(() => void loadBackups())
          }
        >
          Backup now
        </Button>
        <Button onClick={() => void loadBackups()}>List backups</Button>
      </Space>
      {preview ? (
        <Row gutter={16}>
          <Col xs={24} lg={12}>
            <Panel title="HTTP config">
              <pre style={{ maxHeight: 360, overflow: 'auto', fontSize: 11 }}>{preview.http}</pre>
            </Panel>
          </Col>
          <Col xs={24} lg={12}>
            <Panel title="Stream config">
              <pre style={{ maxHeight: 360, overflow: 'auto', fontSize: 11 }}>{preview.stream}</pre>
            </Panel>
          </Col>
        </Row>
      ) : null}
      {backups.length ? (
        <Panel title="Backups">
          <Table
            size="small"
            rowKey="id"
            dataSource={backups}
            pagination={tablePagination(6)}
            columns={[
              { title: 'ID', dataIndex: 'id' },
              {
                title: '',
                width: 120,
                render: (_, b) => (
                  <Button
                    size="small"
                    icon={<RollbackOutlined />}
                    disabled={!canMut}
                    onClick={() =>
                      void runMut(
                        () =>
                          api(`/api/nginx/backups/${encodeURIComponent(b.id)}/rollback`, {
                            method: 'POST',
                            body: '{}',
                          }),
                        'Rolled back',
                      )
                    }
                  >
                    Rollback
                  </Button>
                ),
              },
            ]}
          />
        </Panel>
      ) : null}
    </Space>
  )

  const logsTab = (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Space wrap>
        {['error', 'access', 'app'].map((k) => (
          <Button key={k} onClick={() => void loadLogs(k)}>
            {k}
          </Button>
        ))}
      </Space>
      {logs ? (
        <Panel title={`Log: ${logs.kind}`} extra={<Typography.Text type="secondary">{logs.path}</Typography.Text>}>
          <pre style={{ maxHeight: 480, overflow: 'auto', fontSize: 11, margin: 0 }}>{logs.content || '(empty)'}</pre>
        </Panel>
      ) : (
        <Typography.Text type="secondary">Select a log to view</Typography.Text>
      )}
    </Space>
  )

  return (
    <div className="la-page">
      <PageHeader
        docsKey="nginx"
        title="Nginx Edge"
        subtitle={
          data.installed
            ? `${data.status?.active ? 'Running' : 'Stopped'} · ${data.routes_enabled || 0} route(s) · ${data.certificate_count || 0} cert(s)`
            : 'Install Nginx to publish services via reverse proxy, TLS termination, or SNI passthrough'
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
                    () => api('/api/nginx/install', { method: 'POST', body: '{}' }),
                    'Nginx installed',
                  )
                }
              >
                Install
              </Button>
            ) : (
              <Button
                type="primary"
                icon={<ApiOutlined />}
                disabled={!canMut}
                loading={busy}
                onClick={() =>
                  void runMut(
                    () => api('/api/nginx/config/apply', { method: 'POST', body: '{}' }),
                    'Applied',
                  )
                }
              >
                Apply config
              </Button>
            )}
          </Space>
        }
      />

      <Tabs
        items={[
          { key: 'dash', label: 'Dashboard', children: dashboard },
          { key: 'routes', label: 'Routes', children: routesTab },
          { key: 'certs', label: 'Certificates', children: certsTab },
          { key: 'config', label: 'Config & apply', children: configTab },
          { key: 'logs', label: 'Logs', children: logsTab },
        ]}
      />

      <Modal
        title={
          editing
            ? 'Edit route'
            : activeTemplate
              ? `New route — ${activeTemplate.title}`
              : 'Add route'
        }
        open={routeOpen}
        onCancel={() => {
          setRouteOpen(false)
          setActiveTemplate(null)
          setRouteErrors([])
          setRouteWarnings([])
        }}
        confirmLoading={busy}
        width={760}
        destroyOnHidden
        footer={[
          <Button
            key="validate"
            icon={<CheckCircleOutlined />}
            onClick={() => void validateRouteDraft()}
            disabled={busy}
          >
            Check for errors
          </Button>,
          <Button
            key="cancel"
            onClick={() => {
              setRouteOpen(false)
              setActiveTemplate(null)
            }}
          >
            Cancel
          </Button>,
          <Button key="save" type="primary" loading={busy} onClick={() => void saveRoute()}>
            Save route
          </Button>,
        ]}
      >
        {activeTemplate ? (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message={`Template: ${activeTemplate.title}`}
            description={
              <div>
                <div>{activeTemplate.summary}</div>
                {(activeTemplate.hints || []).length ? (
                  <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                    {activeTemplate.hints!.map((h) => (
                      <li key={h}>{h}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            }
          />
        ) : null}
        {routeErrors.length ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 12 }}
            message="Validation errors"
            description={
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {routeErrors.map((e, i) => (
                  <li key={`${e.field}-${i}`}>
                    <Typography.Text code>{e.field}</Typography.Text>: {e.message}
                  </li>
                ))}
              </ul>
            }
          />
        ) : null}
        {routeWarnings.length ? (
          <Alert
            type="warning"
            showIcon
            icon={<WarningOutlined />}
            style={{ marginBottom: 12 }}
            message="Warnings"
            description={
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {routeWarnings.map((e, i) => (
                  <li key={`${e.field}-${i}`}>
                    <Typography.Text code>{e.field}</Typography.Text>: {e.message}
                  </li>
                ))}
              </ul>
            }
          />
        ) : null}
        <Form form={routeForm} layout="vertical">
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="name" label="Name" rules={[{ required: true }]}>
                <Input placeholder="app-prod" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="proxy_type" label="Proxy type" rules={[{ required: true }]}>
                <Select
                  options={Object.entries(proxyTypes).map(([k, v]) => ({
                    value: k,
                    label: v.label,
                  }))}
                />
              </Form.Item>
            </Col>
          </Row>
          {!isStream || isPassthrough ? (
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item name="domain" label="Domain" rules={[{ required: !isStream || isPassthrough }]}>
                  <Input placeholder="app.example.com" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="aliases" label="Aliases (comma-separated)">
                  <Input placeholder="www.app.example.com" />
                </Form.Item>
              </Col>
            </Row>
          ) : null}
          {isPassthrough ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message="TLS Passthrough"
              description="Traffic is not decrypted. Install/renew the certificate on the backend."
            />
          ) : null}
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="frontend_ip" label="Frontend IP">
                <Input />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="frontend_port" label="Frontend port" rules={[{ required: true }]}>
                <InputNumber style={{ width: '100%' }} min={1} max={65535} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="lb_method" label="Load balancing">
                <Select options={(data.lb_methods || []).map((m) => ({ value: m, label: m }))} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={10}>
              <Form.Item name="backend_host" label="Backend host / DNS / docker:svc" rules={[{ required: true }]}>
                <Input placeholder="127.0.0.1 or docker:web" />
              </Form.Item>
            </Col>
            <Col span={7}>
              <Form.Item name="backend_port" label="Backend port" rules={[{ required: true }]}>
                <InputNumber style={{ width: '100%' }} min={1} max={65535} />
              </Form.Item>
            </Col>
            <Col span={7}>
              <Form.Item name="backend_proto" label="Backend proto">
                <Select
                  options={[
                    { value: 'http', label: 'http' },
                    { value: 'https', label: 'https' },
                    { value: 'tcp', label: 'tcp' },
                    { value: 'udp', label: 'udp' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          {isHttps ? (
            <Form.Item name="cert_id" label="Certificate" rules={[{ required: true, message: 'HTTPS requires a certificate' }]}>
              <Select
                allowClear
                options={(data.certificates || []).map((c) => ({
                  value: c.id,
                  label: `${c.name} (${c.sans?.[0] || c.id})`,
                }))}
              />
            </Form.Item>
          ) : null}
          {!isStream ? (
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item name="client_max_body_size" label="Max body">
                  <Input />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="connect_timeout" label="Connect timeout (s)">
                  <InputNumber style={{ width: '100%' }} min={1} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="read_timeout" label="Read timeout (s)">
                  <InputNumber style={{ width: '100%' }} min={1} />
                </Form.Item>
              </Col>
            </Row>
          ) : (
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item name="session_timeout" label="Session timeout (s)">
                  <InputNumber style={{ width: '100%' }} min={1} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="tcp_keepalive" label="TCP keepalive (s)">
                  <InputNumber style={{ width: '100%' }} min={0} />
                </Form.Item>
              </Col>
            </Row>
          )}
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="allow_ips" label="Allow IPs/CIDR">
                <Input placeholder="10.0.0.0/8, 192.168.1.10" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="deny_ips" label="Deny IPs/CIDR">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Space size="large" wrap>
            <Form.Item name="enabled" label="Enabled" valuePropName="checked">
              <Switch />
            </Form.Item>
            {!isStream ? (
              <>
                <Form.Item name="websocket" label="WebSocket" valuePropName="checked">
                  <Switch />
                </Form.Item>
                <Form.Item name="http2" label="HTTP/2" valuePropName="checked">
                  <Switch />
                </Form.Item>
              </>
            ) : null}
            <Form.Item name="logging" label="Logging" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="apply" label="Apply now" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      <Modal
        title="Route templates"
        open={tplOpen}
        onCancel={() => setTplOpen(false)}
        footer={null}
        width={880}
        destroyOnHidden
      >
        <Space wrap style={{ marginBottom: 16 }}>
          <Button type={tplCategory === 'all' ? 'primary' : 'default'} onClick={() => setTplCategory('all')}>
            All
          </Button>
          {(data.template_categories || []).map((c) => (
            <Button key={c} type={tplCategory === c ? 'primary' : 'default'} onClick={() => setTplCategory(c)}>
              {c}
            </Button>
          ))}
        </Space>
        <Row gutter={[12, 12]}>
          {filteredTemplates.map((tpl) => (
            <Col xs={24} sm={12} key={tpl.id}>
              <div
                className="la-panel"
                style={{ padding: 14, height: '100%', cursor: canMut ? 'pointer' : 'default' }}
                onClick={() => {
                  if (canMut) openFromTemplate(tpl)
                }}
              >
                <Space style={{ marginBottom: 6 }}>
                  <Tag>{tpl.category}</Tag>
                  <Tag color="processing">{proxyTypes[tpl.proxy_type || '']?.label || tpl.proxy_type}</Tag>
                </Space>
                <Typography.Title level={5} style={{ margin: '0 0 6px' }}>
                  {tpl.title}
                </Typography.Title>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 10, minHeight: 40 }}>
                  {tpl.summary}
                </Typography.Paragraph>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  Backend {(tpl.defaults.backend_host || '?') + ':' + (tpl.defaults.backend_port || '?')} · port{' '}
                  {tpl.defaults.frontend_port}
                </Typography.Text>
                <div style={{ marginTop: 10 }}>
                  <Button type="link" size="small" disabled={!canMut} style={{ padding: 0 }}>
                    Use template →
                  </Button>
                </div>
              </div>
            </Col>
          ))}
        </Row>
        {!filteredTemplates.length ? (
          <Typography.Text type="secondary">No templates in this category</Typography.Text>
        ) : null}
      </Modal>

      <Modal
        title="Upload certificate (PEM)"
        open={certOpen}
        onCancel={() => setCertOpen(false)}
        onOk={() =>
          void certForm.validateFields().then((v) =>
            runMut(
              () =>
                api('/api/nginx/certificates', {
                  method: 'POST',
                  body: JSON.stringify({
                    name: v.name,
                    certificate_pem: v.certificate_pem,
                    private_key_pem: v.private_key_pem,
                    chain_pem: v.chain_pem || '',
                  }),
                }),
              'Certificate uploaded',
            ).then((res) => {
              if (res) setCertOpen(false)
            }),
          )
        }
        confirmLoading={busy}
        width={640}
        destroyOnHidden
      >
        <Form form={certForm} layout="vertical">
          <Form.Item name="name" label="Name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="certificate_pem" label="Certificate / fullchain PEM" rules={[{ required: true }]}>
            <Input.TextArea rows={5} />
          </Form.Item>
          <Form.Item name="chain_pem" label="Chain PEM (optional)">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="private_key_pem" label="Private key PEM" rules={[{ required: true }]}>
            <Input.TextArea rows={5} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Let's Encrypt / ACME"
        open={acmeOpen}
        onCancel={() => {
          setAcmeOpen(false)
          setAcmeHint(null)
          if (!acmePoll) setAcmeTxt(null)
        }}
        confirmLoading={busy}
        destroyOnHidden
        footer={
          acmeTxt
            ? [
                <Button
                  key="confirm"
                  type="primary"
                  loading={busy}
                  onClick={() =>
                    void runMut(
                      () =>
                        api('/api/nginx/acme/dns-challenge/confirm', {
                          method: 'POST',
                          body: '{}',
                        }),
                      'TXT confirmed — validating…',
                    )
                  }
                >
                  I added the TXT record
                </Button>,
                <Button key="close" onClick={() => setAcmeOpen(false)}>
                  Close
                </Button>,
              ]
            : [
                <Button key="cancel" onClick={() => setAcmeOpen(false)}>
                  Cancel
                </Button>,
                <Button
                  key="ok"
                  type="primary"
                  loading={busy}
                  onClick={() =>
                    void acmeForm.validateFields().then(async (v) => {
                      setBusy(true)
                      setAcmeHint(null)
                      try {
                        const res = await api<{
                          ok: boolean
                          pending?: boolean
                          error?: string
                          hint?: string
                          suggested_challenge?: string
                          txt?: { name?: string; value?: string; domain?: string }
                          message?: string
                        }>('/api/nginx/acme/issue', {
                          method: 'POST',
                          body: JSON.stringify({
                            domains: String(v.domains)
                              .split(/[,\s]+/)
                              .map((s: string) => s.trim())
                              .filter(Boolean),
                            email: v.email,
                            challenge: v.challenge,
                            dns_provider_id: v.dns_provider_id || undefined,
                            manual_dns: v.challenge === 'dns-01' && !v.dns_provider_id,
                            dry_run: !!v.dry_run,
                            skip_public_check: !!v.skip_public_check,
                          }),
                        })
                        if (!res.ok) {
                          setAcmeHint(res.hint || res.error || 'ACME failed')
                          message.error(res.error || 'ACME failed')
                          if (res.suggested_challenge === 'dns-01') {
                            acmeForm.setFieldValue('challenge', 'dns-01')
                          }
                          return
                        }
                        if (res.pending && res.txt) {
                          setAcmeTxt(res.txt)
                          setAcmePoll(true)
                          message.info(res.message || 'Add TXT record in DNS, then confirm')
                          return
                        }
                        message.success(v.dry_run ? 'ACME dry-run OK' : 'Certificate issued')
                        setAcmeOpen(false)
                        load()
                      } catch (e) {
                        message.error(String(e))
                      } finally {
                        setBusy(false)
                      }
                    })
                  }
                >
                  Start
                </Button>,
              ]
        }
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="mail.whitehills.kg public :80 is Carbonio"
          description={
            <span>
              HTTP-01 will fail while Carbonio answers the public IP and redirects to HTTPS. Prefer{' '}
              <b>DNS-01 Manual</b> (add TXT at AsiaInfo), or point TCP/80 to this host, or on Carbonio proxy{' '}
              <Typography.Text code>/.well-known/acme-challenge/</Typography.Text> to{' '}
              <Typography.Text code>192.168.22.2</Typography.Text> without HTTPS redirect.
            </span>
          }
        />
        {acmeHint ? (
          <Alert type="error" showIcon style={{ marginBottom: 12 }} message={acmeHint} />
        ) : null}
        {acmeTxt ? (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="Create this DNS TXT record"
            description={
              <div>
                <Descriptions size="small" column={1}>
                  <Descriptions.Item label="Name / host">
                    <Typography.Text copyable code>
                      {acmeTxt.name}
                    </Typography.Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="Type">TXT</Descriptions.Item>
                  <Descriptions.Item label="Value">
                    <Typography.Text copyable code style={{ wordBreak: 'break-all' }}>
                      {acmeTxt.value}
                    </Typography.Text>
                  </Descriptions.Item>
                </Descriptions>
                <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                  In AsiaInfo DNS panel add TXT for <code>_acme-challenge</code> under the mail host (or the FQDN
                  above). Wait ~1–2 minutes for propagation, then click <b>I added the TXT record</b>.
                </Typography.Paragraph>
              </div>
            }
          />
        ) : (
          <Form
            form={acmeForm}
            layout="vertical"
            initialValues={{
              challenge: 'dns-01',
              email: data.acme?.email || '',
              dry_run: false,
              domains: 'mail.whitehills.kg',
              skip_public_check: false,
            }}
          >
            <Form.Item name="domains" label="Domains" rules={[{ required: true }]}>
              <Input placeholder="mail.whitehills.kg" />
            </Form.Item>
            <Form.Item name="email" label="ACME email" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="challenge" label="Challenge">
              <Select
                options={[
                  { value: 'dns-01', label: 'DNS-01 Manual (recommended — AsiaInfo / any DNS)' },
                  { value: 'http-01', label: 'HTTP-01 (needs public :80 on this Nginx)' },
                ]}
              />
            </Form.Item>
            <Form.Item
              noStyle
              shouldUpdate={(prev, cur) => prev.challenge !== cur.challenge}
            >
              {({ getFieldValue }) =>
                getFieldValue('challenge') === 'dns-01' ? (
                  <Form.Item
                    name="dns_provider_id"
                    label="DNS API provider (optional)"
                    extra="Leave empty for Manual TXT at your registrar"
                  >
                    <Select
                      allowClear
                      placeholder="Manual TXT (no API)"
                      options={(data.dns_providers || []).map((p) => ({
                        value: p.id,
                        label: `${p.name} (${p.type})`,
                      }))}
                    />
                  </Form.Item>
                ) : (
                  <Form.Item
                    name="skip_public_check"
                    label="Skip public :80 check"
                    valuePropName="checked"
                    extra="Only if Carbonio already proxies /.well-known/acme-challenge to this host"
                  >
                    <Switch />
                  </Form.Item>
                )
              }
            </Form.Item>
            <Form.Item name="dry_run" label="Test (staging / dry-run)" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Form>
        )}
      </Modal>
    </div>
  )
}
