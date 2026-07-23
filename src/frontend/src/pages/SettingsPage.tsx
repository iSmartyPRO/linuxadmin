import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Collapse,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import { api } from '../api/client'
import { useAppSettings } from '../api/settings'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'

type AppConfig = {
  name: string
  metrics_interval_seconds: number
  history_interval_seconds: number
  retention_days: number
}

type PostgresSettings = {
  enabled: boolean
  record_history: boolean
  databases: string[]
  interval_seconds: number
  collect_statements: boolean
  host: string
  port: number
  username: string
  password: string
  database: string
  password_set?: boolean
}

type Bundle = {
  app: AppConfig
  modules: Record<string, Record<string, any>>
  postgres: PostgresSettings
}

type TestResult = {
  ok: boolean
  error?: string
  version?: string
  username?: string
  capabilities?: {
    can_connect?: boolean
    is_pg_monitor?: boolean
    can_read_settings?: boolean
    pg_stat_statements?: boolean
    current_user?: string
    shared_preload_libraries?: string | null
    hints?: string[]
  }
}

function CapTag({ ok, label }: { ok?: boolean; label: string }) {
  return (
    <Tag color={ok ? 'success' : 'default'}>
      {label}: {ok ? 'yes' : 'no'}
    </Tag>
  )
}

function ModuleSwitchRow({
  title,
  description,
  checked,
  onChange,
  children,
}: {
  title: string
  description: string
  checked: boolean
  onChange: (v: boolean) => void
  children?: React.ReactNode
}) {
  return (
    <div
      style={{
        padding: '16px 0',
        borderBottom: '1px solid var(--la-panel-border)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 16,
        }}
      >
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>{title}</div>
          <div style={{ color: 'var(--la-muted)', fontSize: 13 }}>{description}</div>
        </div>
        <Switch checked={checked} onChange={onChange} />
      </div>
      {checked && children ? (
        <div style={{ marginTop: 14, paddingLeft: 4 }}>{children}</div>
      ) : null}
    </div>
  )
}

function FineSwitch({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        padding: '6px 0',
      }}
    >
      <span style={{ fontSize: 13 }}>{label}</span>
      <Switch size="small" checked={checked} onChange={onChange} />
    </div>
  )
}

export function SettingsPage() {
  const { refresh } = useAppSettings()
  const [appForm] = Form.useForm<AppConfig>()
  const [pgForm] = Form.useForm<PostgresSettings>()
  const [connForm] = Form.useForm()
  const [modules, setModules] = useState<Record<string, Record<string, any>>>({})
  const [dbs, setDbs] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [savingModules, setSavingModules] = useState(false)
  const [savingConn, setSavingConn] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<TestResult | null>(null)

  const load = async () => {
    const [bundle, dbRes, conn] = await Promise.all([
      api<Bundle>('/api/settings'),
      api<{ databases: string[] }>('/api/postgres/databases').catch(() => ({ databases: [] })),
      api<{
        db_host: string
        db_port: number
        db_user: string
        db_name: string
        db_password_set: boolean
        admin_user: string
        cors_origins: string
        bind_host: string
        bind_port: number
      }>('/api/setup/connection').catch(() => null),
    ])
    appForm.setFieldsValue(bundle.app)
    pgForm.setFieldsValue({ ...bundle.postgres, password: bundle.postgres.password || '' })
    setModules(bundle.modules)
    setDbs(dbRes.databases || [])
    if (conn) {
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
  }

  useEffect(() => {
    void load().catch((e) => message.error(String(e)))
  }, [])

  const patchModule = (key: string, patch: Record<string, any>) => {
    setModules((prev) => ({
      ...prev,
      [key]: { ...(prev[key] || {}), ...patch },
    }))
  }

  const saveModules = async () => {
    setSavingModules(true)
    try {
      const res = await api<Bundle>('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({ modules }),
      })
      setModules(res.modules)
      pgForm.setFieldsValue({ ...res.postgres, password: res.postgres.password || '' })
      await refresh()
      message.success('Modules saved')
    } catch (e) {
      message.error(String(e))
    } finally {
      setSavingModules(false)
    }
  }

  const runTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const values = pgForm.getFieldsValue()
      const res = await api<TestResult>('/api/postgres/test-connection', {
        method: 'POST',
        body: JSON.stringify({
          host: values.host,
          port: values.port,
          username: values.username,
          password: values.password,
          database: values.database,
        }),
      })
      setTestResult(res)
      if (res.ok) message.success('Connection successful')
      else message.error(res.error || 'Connection error')
    } catch (e) {
      message.error(String(e))
    } finally {
      setTesting(false)
    }
  }

  const m = modules

  return (
    <div className="la-page" style={{ maxWidth: 860 }}>
      <PageHeader
        title="Settings"
        subtitle="Basic project settings and fine-tuning for monitoring modules. A disabled module is hidden from the menu."
      />

      <Panel padded={false} bodyStyle={{ padding: '8px 16px 16px' }}>
        <Tabs
          items={[
            {
              key: 'app',
              label: 'Project',
              children: (
                <Form
                  form={appForm}
                  layout="vertical"
                  style={{ maxWidth: 520, marginTop: 8 }}
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
                  <Form.Item
                    name="name"
                    label="Application name"
                    rules={[{ required: true, max: 128 }]}
                  >
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
              ),
            },
            {
              key: 'connection',
              label: 'Connection',
              children: (
                <div style={{ maxWidth: 520, marginTop: 8 }}>
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
              ),
            },
            {
              key: 'modules',
              label: 'Monitoring modules',
              children: (
                <div style={{ marginTop: 4 }}>
                  <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
                    All modules are enabled by default. Disabling hides the menu item and reduces load
                    (polling/collection stops).
                  </Typography.Paragraph>

                  <ModuleSwitchRow
                    title="Overview"
                    description="Host dashboard: live metrics, gauges, charts, disks, processes"
                    checked={!!m.overview?.enabled}
                    onChange={(v) => patchModule('overview', { enabled: v })}
                  >
                    <FineSwitch
                      label="Live WebSocket metrics"
                      checked={!!m.overview?.live_metrics}
                      onChange={(v) => patchModule('overview', { live_metrics: v })}
                    />
                    <FineSwitch
                      label="Status cards (Fail2ban / Firewall / Docker / PG)"
                      checked={!!m.overview?.status_cards}
                      onChange={(v) => patchModule('overview', { status_cards: v })}
                    />
                    <FineSwitch
                      label="Gauges CPU / RAM / Swap / Disk"
                      checked={!!m.overview?.gauges}
                      onChange={(v) => patchModule('overview', { gauges: v })}
                    />
                    <FineSwitch
                      label="CPU/RAM and network charts"
                      checked={!!m.overview?.charts}
                      onChange={(v) => patchModule('overview', { charts: v })}
                    />
                    <FineSwitch
                      label="Disks"
                      checked={!!m.overview?.disks}
                      onChange={(v) => patchModule('overview', { disks: v })}
                    />
                    <FineSwitch
                      label="Top processes"
                      checked={!!m.overview?.processes}
                      onChange={(v) => patchModule('overview', { processes: v })}
                    />
                    <FineSwitch
                      label="Temperatures"
                      checked={!!m.overview?.temperatures}
                      onChange={(v) => patchModule('overview', { temperatures: v })}
                    />
                  </ModuleSwitchRow>

                  <ModuleSwitchRow
                    title="History"
                    description="Charts of past metric snapshots"
                    checked={!!m.history?.enabled}
                    onChange={(v) => patchModule('history', { enabled: v })}
                  >
                    <FineSwitch
                      label="Write system snapshots to DB"
                      checked={!!m.history?.record}
                      onChange={(v) => patchModule('history', { record: v })}
                    />
                  </ModuleSwitchRow>

                  <ModuleSwitchRow
                    title="Fail2ban"
                    description="Jails, banned IPs, log"
                    checked={!!m.fail2ban?.enabled}
                    onChange={(v) => patchModule('fail2ban', { enabled: v })}
                  >
                    <FineSwitch
                      label="Allow management (ban/unban/reload/start/stop)"
                      checked={!!m.fail2ban?.allow_mutations}
                      onChange={(v) => patchModule('fail2ban', { allow_mutations: v })}
                    />
                    <FineSwitch
                      label="Show log tail"
                      checked={!!m.fail2ban?.show_logs}
                      onChange={(v) => patchModule('fail2ban', { show_logs: v })}
                    />
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>Log lines</span>
                      <InputNumber
                        size="small"
                        min={10}
                        max={500}
                        value={m.fail2ban?.log_lines ?? 80}
                        onChange={(v) => patchModule('fail2ban', { log_lines: v || 80 })}
                      />
                    </div>
                  </ModuleSwitchRow>

                  <ModuleSwitchRow
                    title="Firewall"
                    description="ufw / firewalld / nft / iptables rules"
                    checked={!!m.firewall?.enabled}
                    onChange={(v) => patchModule('firewall', { enabled: v })}
                  >
                    <FineSwitch
                      label="Allow management (enable/rules)"
                      checked={!!m.firewall?.allow_mutations}
                      onChange={(v) => patchModule('firewall', { allow_mutations: v })}
                    />
                    <FineSwitch
                      label="Raw output"
                      checked={!!m.firewall?.show_raw}
                      onChange={(v) => patchModule('firewall', { show_raw: v })}
                    />
                    <FineSwitch
                      label="Show DROP/REJECT log"
                      checked={!!m.firewall?.show_logs}
                      onChange={(v) => patchModule('firewall', { show_logs: v })}
                    />
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>Log lines</span>
                      <InputNumber
                        size="small"
                        min={10}
                        max={500}
                        value={m.firewall?.log_lines ?? 80}
                        onChange={(v) => patchModule('firewall', { log_lines: v || 80 })}
                      />
                    </div>
                  </ModuleSwitchRow>

                  <ModuleSwitchRow
                    title="Docker"
                    description="Containers, images, volumes, networks"
                    checked={!!m.docker?.enabled}
                    onChange={(v) => patchModule('docker', { enabled: v })}
                  >
                    <FineSwitch
                      label="Collect docker stats"
                      checked={!!m.docker?.collect_stats}
                      onChange={(v) => patchModule('docker', { collect_stats: v })}
                    />
                    <FineSwitch
                      label="Collect docker system df"
                      checked={!!m.docker?.collect_disk}
                      onChange={(v) => patchModule('docker', { collect_disk: v })}
                    />
                    <FineSwitch
                      label="Collect docker info"
                      checked={!!m.docker?.collect_info}
                      onChange={(v) => patchModule('docker', { collect_info: v })}
                    />
                    <FineSwitch
                      label="Show raw JSON info"
                      checked={!!m.docker?.show_info_raw}
                      onChange={(v) => patchModule('docker', { show_info_raw: v })}
                    />
                  </ModuleSwitchRow>

                  <ModuleSwitchRow
                    title="Network"
                    description="Listening ports, connections, and processes"
                    checked={!!m.network?.enabled}
                    onChange={(v) => patchModule('network', { enabled: v })}
                  >
                    <FineSwitch
                      label="Allow management (iface up/down, kill)"
                      checked={!!m.network?.allow_mutations}
                      onChange={(v) => patchModule('network', { allow_mutations: v })}
                    />
                    <FineSwitch
                      label="Allow process kill"
                      checked={!!m.network?.allow_kill}
                      onChange={(v) => patchModule('network', { allow_kill: v })}
                    />
                    <FineSwitch
                      label="Listening ports"
                      checked={!!m.network?.show_listening}
                      onChange={(v) => patchModule('network', { show_listening: v })}
                    />
                    <FineSwitch
                      label="Established connections"
                      checked={!!m.network?.show_established}
                      onChange={(v) => patchModule('network', { show_established: v })}
                    />
                    <FineSwitch
                      label="Other statuses (TIME_WAIT, etc.)"
                      checked={!!m.network?.show_other}
                      onChange={(v) => patchModule('network', { show_other: v })}
                    />
                    <FineSwitch
                      label="Network interfaces"
                      checked={!!m.network?.show_interfaces}
                      onChange={(v) => patchModule('network', { show_interfaces: v })}
                    />
                    <FineSwitch
                      label="Include localhost (127.0.0.1 / ::1)"
                      checked={!!m.network?.include_localhost}
                      onChange={(v) => patchModule('network', { include_localhost: v })}
                    />
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>Max table rows</span>
                      <InputNumber
                        size="small"
                        min={50}
                        max={5000}
                        value={m.network?.max_rows ?? 500}
                        onChange={(v) => patchModule('network', { max_rows: v || 500 })}
                      />
                    </div>
                  </ModuleSwitchRow>

                  <ModuleSwitchRow
                    title="Disks"
                    description="Volumes, I/O, and directory size analysis"
                    checked={!!m.disks?.enabled}
                    onChange={(v) => patchModule('disks', { enabled: v })}
                  >
                    <FineSwitch
                      label="Allow directory browsing"
                      checked={!!m.disks?.allow_browse}
                      onChange={(v) => patchModule('disks', { allow_browse: v })}
                    />
                    <FineSwitch
                      label="Include pseudo FS (tmpfs, etc.)"
                      checked={!!m.disks?.include_pseudo}
                      onChange={(v) => patchModule('disks', { include_pseudo: v })}
                    />
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>Max directory entries</span>
                      <InputNumber
                        size="small"
                        min={50}
                        max={5000}
                        value={m.disks?.max_entries ?? 500}
                        onChange={(v) => patchModule('disks', { max_entries: v || 500 })}
                      />
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>Scan timeout (sec)</span>
                      <InputNumber
                        size="small"
                        min={5}
                        max={120}
                        value={m.disks?.scan_timeout_seconds ?? 25}
                        onChange={(v) =>
                          patchModule('disks', { scan_timeout_seconds: v || 25 })
                        }
                      />
                    </div>
                  </ModuleSwitchRow>

                  <ModuleSwitchRow
                    title="Users & Groups"
                    description="Linux system users and groups"
                    checked={!!m.users?.enabled}
                    onChange={(v) => patchModule('users', { enabled: v })}
                  >
                    <FineSwitch
                      label="Allow changes (useradd/usermod/…)"
                      checked={!!m.users?.allow_mutations}
                      onChange={(v) => patchModule('users', { allow_mutations: v })}
                    />
                    <FineSwitch
                      label="Show system accounts (uid/gid < min)"
                      checked={!!m.users?.show_system_accounts}
                      onChange={(v) => patchModule('users', { show_system_accounts: v })}
                    />
                    <FineSwitch
                      label="Allow modifying system accounts"
                      checked={!!m.users?.allow_system_mutations}
                      onChange={(v) => patchModule('users', { allow_system_mutations: v })}
                    />
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>min UID/GID (below = system)</span>
                      <InputNumber
                        size="small"
                        min={0}
                        max={65535}
                        value={m.users?.min_uid ?? 1000}
                        onChange={(v) => patchModule('users', { min_uid: v ?? 1000 })}
                      />
                    </div>
                  </ModuleSwitchRow>

                  <ModuleSwitchRow
                    title="Services"
                    description="systemd services: status and management"
                    checked={!!m.services?.enabled}
                    onChange={(v) => patchModule('services', { enabled: v })}
                  >
                    <FineSwitch
                      label="Allow management (start/stop/restart/…)"
                      checked={!!m.services?.allow_mutations}
                      onChange={(v) => patchModule('services', { allow_mutations: v })}
                    />
                    <FineSwitch
                      label="Show inactive services"
                      checked={!!m.services?.show_inactive}
                      onChange={(v) => patchModule('services', { show_inactive: v })}
                    />
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>journalctl lines</span>
                      <InputNumber
                        size="small"
                        min={10}
                        max={500}
                        value={m.services?.log_lines ?? 80}
                        onChange={(v) => patchModule('services', { log_lines: v || 80 })}
                      />
                    </div>
                  </ModuleSwitchRow>

                  <ModuleSwitchRow
                    title="PostgreSQL"
                    description="DB monitoring (sessions, statements, locks…)"
                    checked={!!m.postgres?.enabled}
                    onChange={(v) => patchModule('postgres', { enabled: v })}
                  >
                    <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                      Connection and history collection are configured on the “PostgreSQL” tab.
                    </Typography.Text>
                  </ModuleSwitchRow>

                  <ModuleSwitchRow
                    title="SSH Tunnel"
                    description="Jump host: users, keys, destinations, ssh config"
                    checked={!!m.ssh_tunnel?.enabled}
                    onChange={(v) => patchModule('ssh_tunnel', { enabled: v })}
                  >
                    <FineSwitch
                      label="Allow changes (useradd/keys/sshd drop-in)"
                      checked={!!m.ssh_tunnel?.allow_mutations}
                      onChange={(v) => patchModule('ssh_tunnel', { allow_mutations: v })}
                    />
                    <FineSwitch
                      label="Show active SSH sessions"
                      checked={m.ssh_tunnel?.show_sessions !== false}
                      onChange={(v) => patchModule('ssh_tunnel', { show_sessions: v })}
                    />
                    <FineSwitch
                      label="Write connection history to DB"
                      checked={m.ssh_tunnel?.record_history !== false}
                      onChange={(v) => patchModule('ssh_tunnel', { record_history: v })}
                    />
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>History write interval (sec)</span>
                      <InputNumber
                        size="small"
                        min={5}
                        max={3600}
                        value={m.ssh_tunnel?.history_interval_seconds ?? 15}
                        onChange={(v) =>
                          patchModule('ssh_tunnel', { history_interval_seconds: v || 15 })
                        }
                      />
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>Username prefix</span>
                      <Input
                        size="small"
                        style={{ width: 140 }}
                        value={m.ssh_tunnel?.username_prefix ?? 'tun-'}
                        onChange={(e) =>
                          patchModule('ssh_tunnel', { username_prefix: e.target.value })
                        }
                      />
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>Public hostname (for ssh config)</span>
                      <Input
                        size="small"
                        style={{ width: 200 }}
                        placeholder="auto FQDN"
                        value={m.ssh_tunnel?.public_hostname ?? ''}
                        onChange={(e) =>
                          patchModule('ssh_tunnel', { public_hostname: e.target.value })
                        }
                      />
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>SSH port</span>
                      <InputNumber
                        size="small"
                        min={1}
                        max={65535}
                        value={m.ssh_tunnel?.public_port ?? 22}
                        onChange={(v) => patchModule('ssh_tunnel', { public_port: v || 22 })}
                      />
                    </div>
                  </ModuleSwitchRow>

                  <ModuleSwitchRow
                    title="WireGuard"
                    description="VPN server: peers, routes (full/split), client configs & QR codes"
                    checked={!!m.wireguard?.enabled}
                    onChange={(v) => patchModule('wireguard', { enabled: v })}
                  >
                    <FineSwitch
                      label="Allow changes (install tools / wg-quick / peers)"
                      checked={!!m.wireguard?.allow_mutations}
                      onChange={(v) => patchModule('wireguard', { allow_mutations: v })}
                    />
                    <FineSwitch
                      label="Allow package install (apt/dnf/…)"
                      checked={m.wireguard?.allow_install !== false}
                      onChange={(v) => patchModule('wireguard', { allow_install: v })}
                    />
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>Interface</span>
                      <Input
                        size="small"
                        style={{ width: 120 }}
                        className="mono"
                        value={m.wireguard?.interface ?? 'wg0'}
                        onChange={(e) => patchModule('wireguard', { interface: e.target.value })}
                      />
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>Public endpoint host</span>
                      <Input
                        size="small"
                        style={{ width: 200 }}
                        placeholder="auto FQDN / IP"
                        value={m.wireguard?.endpoint_host ?? ''}
                        onChange={(e) =>
                          patchModule('wireguard', { endpoint_host: e.target.value })
                        }
                      />
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>Listen port</span>
                      <InputNumber
                        size="small"
                        min={1}
                        max={65535}
                        value={m.wireguard?.default_listen_port ?? 51820}
                        onChange={(v) =>
                          patchModule('wireguard', { default_listen_port: v || 51820 })
                        }
                      />
                    </div>
                  </ModuleSwitchRow>

                  <ModuleSwitchRow
                    title="OpenVPN"
                    description="VPN server: clients, routes (full/split), .ovpn download (QR when small)"
                    checked={!!m.openvpn?.enabled}
                    onChange={(v) => patchModule('openvpn', { enabled: v })}
                  >
                    <FineSwitch
                      label="Allow changes (install / PKI / clients / systemctl)"
                      checked={!!m.openvpn?.allow_mutations}
                      onChange={(v) => patchModule('openvpn', { allow_mutations: v })}
                    />
                    <FineSwitch
                      label="Allow package install (apt/dnf/…)"
                      checked={m.openvpn?.allow_install !== false}
                      onChange={(v) => patchModule('openvpn', { allow_install: v })}
                    />
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>Instance name</span>
                      <Input
                        size="small"
                        style={{ width: 140 }}
                        className="mono"
                        value={m.openvpn?.instance ?? 'lnxadmin'}
                        onChange={(e) => patchModule('openvpn', { instance: e.target.value })}
                      />
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>Public endpoint host</span>
                      <Input
                        size="small"
                        style={{ width: 200 }}
                        placeholder="auto FQDN / IP"
                        value={m.openvpn?.endpoint_host ?? ''}
                        onChange={(e) =>
                          patchModule('openvpn', { endpoint_host: e.target.value })
                        }
                      />
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '6px 0',
                      }}
                    >
                      <span style={{ fontSize: 13 }}>Default port</span>
                      <InputNumber
                        size="small"
                        min={1}
                        max={65535}
                        value={m.openvpn?.default_port ?? 1194}
                        onChange={(v) => patchModule('openvpn', { default_port: v || 1194 })}
                      />
                    </div>
                  </ModuleSwitchRow>

                  <div style={{ marginTop: 20 }}>
                    <Button type="primary" onClick={() => void saveModules()} loading={savingModules}>
                      Save modules
                    </Button>
                  </div>
                </div>
              ),
            },
            {
              key: 'postgres',
              label: 'PostgreSQL',
              children: (
                <div style={{ marginTop: 8, maxWidth: 560 }}>
                  {!m.postgres?.enabled ? (
                    <Alert
                      type="warning"
                      showIcon
                      style={{ marginBottom: 16 }}
                      message="PostgreSQL module disabled"
                      description="Enable it on the “Monitoring modules” tab so the page and collection work again."
                    />
                  ) : null}
                  <Typography.Paragraph type="secondary">
                    Role with <Typography.Text code>pg_monitor</Typography.Text> privileges. Empty connection
                    fields = values from <Typography.Text code>.env</Typography.Text>.
                  </Typography.Paragraph>
                  <Form
                    form={pgForm}
                    layout="vertical"
                    onFinish={async (values) => {
                      setLoading(true)
                      try {
                        const res = await api<Bundle>('/api/settings', {
                          method: 'PUT',
                          body: JSON.stringify({
                            postgres: values,
                            modules: {
                              postgres: { enabled: values.enabled },
                            },
                          }),
                        })
                        pgForm.setFieldsValue({
                          ...res.postgres,
                          password: res.postgres.password || '',
                        })
                        setModules(res.modules)
                        await refresh()
                        message.success('Saved')
                      } catch (e) {
                        message.error(String(e))
                      } finally {
                        setLoading(false)
                      }
                    }}
                  >
                    <Form.Item name="enabled" label="Monitoring collection enabled" valuePropName="checked">
                      <Switch />
                    </Form.Item>
                    <Collapse
                      size="small"
                      style={{ marginBottom: 16 }}
                      items={[
                        {
                          key: 'conn',
                          label: 'Connection',
                          children: (
                            <>
                              <Form.Item name="host" label="Host">
                                <Input placeholder="localhost" />
                              </Form.Item>
                              <Form.Item name="port" label="Port">
                                <InputNumber min={1} max={65535} style={{ width: '100%' }} />
                              </Form.Item>
                              <Form.Item name="database" label="Database (service)">
                                <Input placeholder="lnxadmin" />
                              </Form.Item>
                              <Form.Item name="username" label="Username">
                                <Input placeholder="lnxadmin_monitor" autoComplete="off" />
                              </Form.Item>
                              <Form.Item
                                name="password"
                                label="Password"
                                extra="Leave ****** or empty to keep unchanged"
                              >
                                <Input.Password autoComplete="new-password" />
                              </Form.Item>
                            </>
                          ),
                        },
                      ]}
                      defaultActiveKey={['conn']}
                    />

                    <Form.Item name="record_history" label="Write PG history to DB" valuePropName="checked">
                      <Switch />
                    </Form.Item>
                    <Form.Item
                      name="collect_statements"
                      label="Collect pg_stat_statements"
                      valuePropName="checked"
                    >
                      <Switch />
                    </Form.Item>
                    <Form.Item name="interval_seconds" label="PG write interval (sec)">
                      <InputNumber min={10} max={3600} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item
                      name="databases"
                      label="Databases for detailed recording"
                      extra="Empty list = service DB only"
                    >
                      <Select mode="multiple" options={dbs.map((d) => ({ value: d, label: d }))} />
                    </Form.Item>

                    <Space wrap style={{ marginBottom: 16 }}>
                      <Button onClick={() => void runTest()} loading={testing}>
                        Test connection
                      </Button>
                      <Button type="primary" htmlType="submit" loading={loading}>
                        Save
                      </Button>
                    </Space>

                    {testResult ? (
                      <Alert
                        type={testResult.ok ? 'success' : 'error'}
                        showIcon
                        message={
                          testResult.ok
                            ? `OK · ${testResult.version} · user ${testResult.capabilities?.current_user || testResult.username}`
                            : testResult.error || 'Error'
                        }
                        description={
                          testResult.capabilities ? (
                            <Space wrap>
                              <CapTag ok={testResult.capabilities.can_connect} label="connect" />
                              <CapTag ok={testResult.capabilities.is_pg_monitor} label="pg_monitor" />
                              <CapTag
                                ok={testResult.capabilities.can_read_settings}
                                label="read settings"
                              />
                              <CapTag
                                ok={testResult.capabilities.pg_stat_statements}
                                label="pg_stat_statements"
                              />
                            </Space>
                          ) : null
                        }
                      />
                    ) : null}
                  </Form>
                </div>
              ),
            },
          ]}
        />
      </Panel>
    </div>
  )
}
