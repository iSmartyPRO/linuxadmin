import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Space,
  Switch,
  Typography,
  message,
} from 'antd'
import {
  ApiOutlined,
  AppstoreOutlined,
  ArrowLeftOutlined,
  ControlOutlined,
  RightOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'
import { useAccess } from '../api/access'
import { useAppSettings } from '../api/settings'
import { AccessSettingsPanel } from '../components/AccessSettingsPanel'
import { ModulesSettingsGrid } from '../components/ModulesSettingsGrid'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'

type AppConfig = {
  name: string
  metrics_interval_seconds: number
  history_interval_seconds: number
  retention_days: number
}

const SECTIONS = [
  {
    to: '/settings/project',
    title: 'Project',
    description: 'Application name, live refresh, and how long history is kept.',
    icon: <ControlOutlined />,
  },
  {
    to: '/settings/connection',
    title: 'Connection',
    description: 'Panel database, admin account, bind address, and CORS.',
    icon: <ApiOutlined />,
  },
  {
    to: '/settings/modules',
    title: 'Modules',
    description: 'Turn modules on or off and open options for each one.',
    icon: <AppstoreOutlined />,
  },
  {
    to: '/settings/access',
    title: 'Access',
    description: 'Panel users, roles, and API keys.',
    icon: <TeamOutlined />,
  },
]

function SettingsBack({ to, label }: { to: string; label: string }) {
  return (
    <Link to={to}>
      <Button icon={<ArrowLeftOutlined />}>{label}</Button>
    </Link>
  )
}

function SettingsSection({
  title,
  subtitle,
  docsKey,
  children,
}: {
  title: string
  subtitle: string
  docsKey?: string
  children: ReactNode
}) {
  return (
    <div className="la-page" style={{ maxWidth: 960 }}>
      <PageHeader
        title={title}
        subtitle={subtitle}
        docsKey={docsKey}
        extra={<SettingsBack to="/settings" label="Settings" />}
      />
      <Panel>{children}</Panel>
    </div>
  )
}

export function SettingsPage() {
  return (
    <div className="la-page" style={{ maxWidth: 960 }}>
      <PageHeader
        title="Settings"
        subtitle="Choose a section. Each one opens on its own page."
        docsKey="settings"
      />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
          gap: 14,
        }}
      >
        {SECTIONS.map((section) => (
          <Link key={section.to} to={section.to} style={{ textDecoration: 'none' }}>
            <span className="la-panel la-settings-card" style={{ minHeight: 148 }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 18 }}>
                <span style={{ color: 'var(--la-link)' }}>{section.icon}</span>
                <span style={{ fontWeight: 700, fontSize: 17 }}>{section.title}</span>
              </span>
              <span style={{ color: 'var(--la-muted)', fontSize: 14, lineHeight: 1.45, flex: 1 }}>
                {section.description}
              </span>
              <span
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  fontSize: 13,
                  fontWeight: 600,
                  color: 'var(--la-link)',
                }}
              >
                Open <RightOutlined style={{ fontSize: 10 }} />
              </span>
            </span>
          </Link>
        ))}
      </div>
    </div>
  )
}

export function SettingsProjectPage() {
  const { refresh } = useAppSettings()
  const { can } = useAccess()
  const [appForm] = Form.useForm<AppConfig>()
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!can('settings', 'read')) return
    void api<{ app: AppConfig }>('/api/settings')
      .then((bundle) => appForm.setFieldsValue(bundle.app))
      .catch((e) => message.error(String(e)))
  }, [appForm, can])

  return (
    <SettingsSection
      title="Project"
      subtitle="Name shown in the panel, and how metrics and history are stored."
      docsKey="settings"
    >
      {!can('settings', 'read') ? (
        <Alert type="warning" showIcon message="No access to project settings." />
      ) : (
        <Form
          form={appForm}
          layout="vertical"
          style={{ maxWidth: 520 }}
          onFinish={async (values) => {
            setLoading(true)
            try {
              await api('/api/settings', {
                method: 'PUT',
                body: JSON.stringify({ app: values }),
              })
              await refresh()
              message.success('Saved')
            } catch (e) {
              message.error(String(e))
            } finally {
              setLoading(false)
            }
          }}
        >
          <Form.Item name="name" label="Application name" rules={[{ required: true, max: 128 }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="metrics_interval_seconds"
            label="Live metrics interval (sec)"
            extra="How often to refresh CPU/RAM over WebSocket"
          >
            <InputNumber min={0.5} max={60} step={0.5} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="history_interval_seconds"
            label="History write interval (sec)"
            extra="System metric snapshots in PostgreSQL"
          >
            <InputNumber min={5} max={3600} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="retention_days" label="History retention (days)">
            <InputNumber min={1} max={3650} style={{ width: '100%' }} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>
            Save
          </Button>
        </Form>
      )}
    </SettingsSection>
  )
}

export function SettingsConnectionPage() {
  const { can } = useAccess()
  const [connForm] = Form.useForm()
  const [savingConn, setSavingConn] = useState(false)
  const [testing, setTesting] = useState(false)

  const load = async () => {
    if (!can('settings_connection', 'read')) return
    const conn = await api<{
      db_host: string
      db_port: number
      db_user: string
      db_name: string
      db_password_set: boolean
      admin_user: string
      cors_origins: string
      bind_host: string
      bind_port: number
    }>('/api/setup/connection')
    connForm.setFieldsValue({
      db_host: conn.db_host,
      db_port: conn.db_port,
      db_user: conn.db_user,
      db_name: conn.db_name,
      db_password: conn.db_password_set ? '********' : '',
      admin_user: conn.admin_user,
      admin_password: '',
      cors_origins: conn.cors_origins,
      bind_host: conn.bind_host,
      bind_port: conn.bind_port,
      rotate_jwt: false,
    })
  }

  useEffect(() => {
    void load().catch((e) => message.error(String(e)))
  }, [])

  return (
    <SettingsSection
      title="Connection"
      subtitle="Database, admin account, and how the panel is reached."
      docsKey="settings"
    >
      {!can('settings_connection', 'read') ? (
        <Alert type="warning" showIcon message="No access to connection settings." />
      ) : (
        <div style={{ maxWidth: 520 }}>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="Application database & bootstrap"
            description="These values are stored in .env. Changing the database reconnects live. Changing bind address or rotating JWT requires a process restart."
          />
          <Form
            form={connForm}
            layout="vertical"
            onFinish={async (values) => {
              setSavingConn(true)
              try {
                const res = await api<{
                  ok: boolean
                  message?: string
                  restart_required?: boolean
                }>('/api/setup/connection', {
                  method: 'PUT',
                  body: JSON.stringify({
                    db_host: values.db_host,
                    db_port: values.db_port,
                    db_user: values.db_user,
                    db_name: values.db_name,
                    db_password: values.db_password,
                    admin_user: values.admin_user,
                    admin_password: values.admin_password || undefined,
                    cors_origins: values.cors_origins,
                    bind_host: values.bind_host,
                    bind_port: values.bind_port,
                    rotate_jwt: !!values.rotate_jwt,
                  }),
                })
                message.success(res.message || 'Saved')
                if (res.restart_required) {
                  message.warning('Restart the service to apply bind/JWT changes (make restart)')
                }
                await load()
              } catch (e) {
                message.error(String(e))
              } finally {
                setSavingConn(false)
              }
            }}
          >
            <Typography.Text strong>PostgreSQL (panel database)</Typography.Text>
            <Form.Item name="db_host" label="Host" rules={[{ required: true }]} style={{ marginTop: 12 }}>
              <Input className="mono" />
            </Form.Item>
            <Form.Item name="db_port" label="Port" rules={[{ required: true }]}>
              <InputNumber style={{ width: '100%' }} min={1} max={65535} />
            </Form.Item>
            <Form.Item name="db_name" label="Database" rules={[{ required: true }]}>
              <Input className="mono" />
            </Form.Item>
            <Form.Item name="db_user" label="Username" rules={[{ required: true }]}>
              <Input className="mono" />
            </Form.Item>
            <Form.Item name="db_password" label="Password" extra="Leave ******** to keep current">
              <Input.Password />
            </Form.Item>
            <Space style={{ marginBottom: 16 }}>
              <Button
                loading={testing}
                onClick={() => {
                  void (async () => {
                    setTesting(true)
                    try {
                      const v = connForm.getFieldsValue()
                      const res = await api<{ ok: boolean; error?: string; version?: string }>(
                        '/api/setup/test-connection',
                        {
                          method: 'POST',
                          body: JSON.stringify({
                            host: v.db_host,
                            port: v.db_port,
                            username: v.db_user,
                            password: v.db_password,
                            database: v.db_name,
                          }),
                        },
                      )
                      if (res.ok) message.success(res.version?.split(',')[0] || 'OK')
                      else message.error(res.error || 'Failed')
                    } catch (e) {
                      message.error(String(e))
                    } finally {
                      setTesting(false)
                    }
                  })()
                }}
              >
                Test connection
              </Button>
            </Space>

            <Typography.Text strong>Admin account</Typography.Text>
            <Form.Item name="admin_user" label="Username" style={{ marginTop: 12 }}>
              <Input className="mono" />
            </Form.Item>
            <Form.Item
              name="admin_password"
              label="New password"
              extra="Leave empty to keep current password"
            >
              <Input.Password />
            </Form.Item>

            <Typography.Text strong>Network</Typography.Text>
            <Form.Item name="bind_host" label="Bind host" style={{ marginTop: 12 }}>
              <Input className="mono" />
            </Form.Item>
            <Form.Item name="bind_port" label="Bind port">
              <InputNumber style={{ width: '100%' }} min={1} max={65535} />
            </Form.Item>
            <Form.Item name="cors_origins" label="CORS origins">
              <Input.TextArea rows={2} className="mono" />
            </Form.Item>
            <Form.Item name="rotate_jwt" label="Rotate JWT secret" valuePropName="checked">
              <Switch />
            </Form.Item>

            <Button type="primary" htmlType="submit" loading={savingConn}>
              Save connection
            </Button>
          </Form>
        </div>
      )}
    </SettingsSection>
  )
}

export function SettingsModulesPage() {
  return (
    <div className="la-page" style={{ maxWidth: 1100 }}>
      <PageHeader
        title="Modules"
        subtitle="Toggle a module, or open it for detailed options."
        docsKey="settings"
        extra={<SettingsBack to="/settings" label="Settings" />}
      />
      <ModulesSettingsGrid />
    </div>
  )
}

export function SettingsAccessPage() {
  return (
    <SettingsSection
      title="Access"
      subtitle="Panel users, roles, and API keys."
      docsKey="settings_access"
    >
      <AccessSettingsPanel />
    </SettingsSection>
  )
}
