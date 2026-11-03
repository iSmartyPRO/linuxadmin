import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
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
  Tag,
  Typography,
  message,
} from 'antd'
import { ArrowLeftOutlined, FolderOpenOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import { useAppSettings } from '../api/settings'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { getModuleMeta } from '../settings/moduleCatalog'
import { FolderPicker } from '../components/FolderPicker'

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
  }
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
        padding: '8px 0',
        borderBottom: '1px solid var(--la-panel-border)',
      }}
    >
      <span style={{ fontSize: 13 }}>{label}</span>
      <Switch checked={checked} onChange={onChange} />
    </div>
  )
}

function NumberRow({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  onChange: (v: number) => void
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        padding: '8px 0',
        borderBottom: '1px solid var(--la-panel-border)',
      }}
    >
      <span style={{ fontSize: 13 }}>{label}</span>
      <InputNumber size="small" min={min} max={max} value={value} onChange={(v) => onChange(Number(v))} />
    </div>
  )
}

function TextRow({
  label,
  value,
  placeholder,
  mono,
  onChange,
}: {
  label: string
  value: string
  placeholder?: string
  mono?: boolean
  onChange: (v: string) => void
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        padding: '8px 0',
        borderBottom: '1px solid var(--la-panel-border)',
      }}
    >
      <span style={{ fontSize: 13 }}>{label}</span>
      <Input
        size="small"
        style={{ width: 220 }}
        className={mono ? 'mono' : undefined}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  )
}

export function ModuleSettingsDetailPage() {
  const { moduleKey = '' } = useParams()
  const meta = getModuleMeta(moduleKey)
  const { refresh } = useAppSettings()
  const [mod, setMod] = useState<Record<string, any>>({})
  const [saving, setSaving] = useState(false)
  const [pgForm] = Form.useForm<PostgresSettings>()
  const [dbs, setDbs] = useState<string[]>([])
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [pgLoading, setPgLoading] = useState(false)

  const load = useCallback(async () => {
    const res = await api<Bundle>('/api/settings')
    setMod(res.modules?.[moduleKey] || { enabled: true })
    if (moduleKey === 'postgres') {
      pgForm.setFieldsValue({ ...res.postgres, password: res.postgres.password || '' })
      const dbRes = await api<{ databases: string[] }>('/api/postgres/databases').catch(() => ({
        databases: [] as string[],
      }))
      setDbs(dbRes.databases || [])
    }
  }, [moduleKey, pgForm])

  useEffect(() => {
    if (!meta) return
    void load().catch((e) => message.error(String(e)))
  }, [load, meta])

  if (!meta) return <Navigate to="/settings/modules" replace />

  const patch = (p: Record<string, any>) => setMod((prev) => ({ ...prev, ...p }))

  const saveModule = async () => {
    setSaving(true)
    try {
      const res = await api<Bundle>('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({ modules: { [moduleKey]: mod } }),
      })
      setMod(res.modules?.[moduleKey] || mod)
      await refresh()
      message.success('Saved')
    } catch (e) {
      message.error(settingError(e))
    } finally {
      setSaving(false)
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

  const savePostgres = async (values: PostgresSettings) => {
    setPgLoading(true)
    try {
      const res = await api<Bundle>('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({
          postgres: values,
          modules: { postgres: { ...mod, enabled: values.enabled } },
        }),
      })
      setMod(res.modules?.postgres || mod)
      pgForm.setFieldsValue({ ...res.postgres, password: res.postgres.password || '' })
      await refresh()
      message.success('PostgreSQL settings saved')
    } catch (e) {
      message.error(String(e))
    } finally {
      setPgLoading(false)
    }
  }

  return (
    <div className="la-page" style={{ maxWidth: 720 }}>
      <PageHeader
        title={meta.title}
        subtitle={meta.description}
        docsKey={moduleKey}
        extra={
          <Link to="/settings/modules">
            <Button icon={<ArrowLeftOutlined />}>Modules</Button>
          </Link>
        }
      />

      {moduleKey !== 'postgres' ? (
        <Panel title="Module" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
            <div>
              <Typography.Text strong>Enabled</Typography.Text>
              <div style={{ color: 'var(--la-muted)', fontSize: 13, marginTop: 4 }}>
                When off, the menu item is hidden and collection for this module stops.
              </div>
            </div>
            <Space>
              <Tag color={mod.enabled !== false ? 'success' : 'default'}>
                {mod.enabled !== false ? 'on' : 'off'}
              </Tag>
              <Switch checked={mod.enabled !== false} onChange={(v) => patch({ enabled: v })} />
            </Space>
          </div>
        </Panel>
      ) : null}

      {moduleKey !== 'postgres' ? (
        <Panel title="Options">
          <ModuleOptionsFields moduleKey={moduleKey} mod={mod} patch={patch} />
          <div style={{ marginTop: 20 }}>
            <Button type="primary" loading={saving} onClick={() => void saveModule()}>
              Save
            </Button>
          </div>
        </Panel>
      ) : (
        <Panel title="PostgreSQL options">
          <Typography.Paragraph type="secondary">
            Role with <Typography.Text code>pg_monitor</Typography.Text> privileges. Empty connection
            fields = values from <Typography.Text code>.env</Typography.Text>.
          </Typography.Paragraph>
          <Form form={pgForm} layout="vertical" onFinish={(v) => void savePostgres(v)}>
            <Form.Item name="enabled" label="Module & monitoring collection enabled" valuePropName="checked">
              <Switch
                onChange={(v) => {
                  patch({ enabled: v })
                  pgForm.setFieldValue('enabled', v)
                }}
              />
            </Form.Item>
            <Collapse
              size="small"
              style={{ marginBottom: 16 }}
              defaultActiveKey={['conn']}
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
              <Button type="primary" htmlType="submit" loading={pgLoading}>
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
              />
            ) : null}
          </Form>
        </Panel>
      )}
    </div>
  )
}

function settingError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e)
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown }
    if (typeof parsed.detail === 'string') return parsed.detail
  } catch {
    /* plain text */
  }
  return raw
}

type MountDraft = { id: string; name: string; path: string; read_only?: boolean }

/** 12 hex chars. crypto.randomUUID exists only in a secure context (HTTPS or localhost). */
function newMountId(): string {
  const bytes = new Uint8Array(6)
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes)
  } else {
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256)
  }
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

function FilesMountEditor({
  mod,
  patch,
}: {
  mod: Record<string, any>
  patch: (p: Record<string, any>) => void
}) {
  const roots: MountDraft[] = Array.isArray(mod.roots) ? mod.roots : []
  const [checking, setChecking] = useState<number | null>(null)
  const [picker, setPicker] = useState<number | null>(null)
  const update = (next: MountDraft[]) => patch({ roots: next })

  const check = async (index: number) => {
    const row = roots[index]
    if (!row) return
    setChecking(index)
    try {
      const res = await api<{ ok: boolean; path?: string; name?: string; error?: string }>('/api/files/check-path', {
        method: 'POST',
        body: JSON.stringify({ path: row.path }),
      })
      if (!res.ok || !res.path) {
        message.error(res.error || 'Path is not available')
        return
      }
      update(roots.map((item, i) => (i === index ? { ...item, path: res.path || item.path, name: item.name || res.name || item.name } : item)))
      message.success('Folder is available')
    } catch (e) {
      message.error(settingError(e))
    } finally {
      setChecking(null)
    }
  }

  return (
    <>
      <FineSwitch label="Allow changes (create, upload, edit, rename, move, delete)" checked={!!mod.allow_mutations} onChange={(v) => patch({ allow_mutations: v })} />
      <FineSwitch label="Show hidden files by default" checked={!!mod.show_hidden} onChange={(v) => patch({ show_hidden: v })} />
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: '8px 0',
          borderBottom: '1px solid var(--la-panel-border)',
        }}
      >
        <span style={{ fontSize: 13 }}>
          Open files and folders
          <div style={{ color: 'var(--la-muted)', fontSize: 12, marginTop: 2 }}>
            Default for this server. The Files toolbar can remember a different choice in this browser.
          </div>
        </span>
        <Select
          value={mod.open_click === 'single' ? 'single' : 'double'}
          style={{ width: 160, flex: 'none' }}
          options={[
            { value: 'double', label: 'Double click' },
            { value: 'single', label: 'Single click' },
          ]}
          onChange={(value) => patch({ open_click: value })}
        />
      </div>
      <NumberRow label="Preview limit (MB)" value={mod.max_preview_mb ?? 2} min={1} max={8} onChange={(v) => patch({ max_preview_mb: v || 2 })} />
      <NumberRow label="Upload limit (MB)" value={mod.max_upload_mb ?? 50} min={1} max={200} onChange={(v) => patch({ max_upload_mb: v || 50 })} />
      <Typography.Paragraph type="secondary" style={{ marginTop: 14 }}>
        Mounted folders show up in the sidebar under Files, each with the name you set. Paths stay jailed: links that leave the folder are blocked. The filesystem root and /proc, /sys, /dev, /run, /boot cannot be mounted.
      </Typography.Paragraph>
      {roots.map((root, index) => (
        <div key={root.id || index} className="fm-root-card">
          <Input
            placeholder="Menu name"
            value={root.name}
            onChange={(e) => update(roots.map((item, i) => (i === index ? { ...item, name: e.target.value } : item)))}
          />
          <div className="fm-path-row">
            <Input
              className="mono"
              placeholder="/var/lib/documents"
              value={root.path}
              onChange={(e) => update(roots.map((item, i) => (i === index ? { ...item, path: e.target.value } : item)))}
            />
            <Button icon={<FolderOpenOutlined />} onClick={() => setPicker(index)}>
              Browse
            </Button>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13 }}>Read only</span>
            <Switch checked={!!root.read_only} onChange={(v) => update(roots.map((item, i) => (i === index ? { ...item, read_only: v } : item)))} />
          </div>
          <Space>
            <Button size="small" loading={checking === index} onClick={() => void check(index)}>
              Check path
            </Button>
            <Button size="small" danger onClick={() => update(roots.filter((_, i) => i !== index))}>
              Remove
            </Button>
          </Space>
        </div>
      ))}
      <Button
        onClick={() =>
          update([
            ...roots,
            {
              id: newMountId(),
              name: '',
              path: '',
              read_only: false,
            },
          ])
        }
      >
        Add folder
      </Button>
      <FolderPicker
        open={picker !== null}
        initialPath={picker !== null ? roots[picker]?.path : ''}
        onClose={() => setPicker(null)}
        onSelect={(selected, name) => {
          if (picker === null) return
          update(
            roots.map((item, i) =>
              i === picker ? { ...item, path: selected, name: item.name || name } : item,
            ),
          )
          setPicker(null)
        }}
      />
    </>
  )
}

type RouteTemplateDraft = { key: string; label: string; description?: string; allowed_ips: string[] }

function RouteTemplatesEditor({
  mod,
  patch,
}: {
  mod: Record<string, any>
  patch: (p: Record<string, any>) => void
}) {
  const rows: RouteTemplateDraft[] = Array.isArray(mod.route_templates) ? mod.route_templates : []
  const update = (next: RouteTemplateDraft[]) => patch({ route_templates: next })
  const setRow = (index: number, p: Partial<RouteTemplateDraft>) =>
    update(rows.map((row, i) => (i === index ? { ...row, ...p } : row)))
  const routeOptions = [
    ...rows.filter((r) => r.key).map((r) => ({ value: `tpl:${r.key}`, label: `${r.label || r.key} (template)` })),
    { value: 'vpn_only', label: 'VPN subnet only' },
    { value: 'split_lan', label: 'All private LANs (RFC1918)' },
    { value: 'full', label: 'Full tunnel' },
    { value: 'custom', label: 'Custom routes' },
  ]

  return (
    <>
      <div style={{ padding: '8px 0', borderBottom: '1px solid var(--la-panel-border)' }}>
        <span style={{ fontSize: 13 }}>
          Route templates
          <div style={{ color: 'var(--la-muted)', fontSize: 12, marginTop: 2 }}>
            Named AllowedIPs sets shown as route modes when adding a peer. Editing a template updates every peer that
            uses it on its next config download (clients must re-import the config).
          </div>
        </span>
        {rows.map((row, index) => (
          <div
            key={`${index}-${row.key}`}
            style={{ marginTop: 10, padding: 10, border: '1px solid var(--la-panel-border)', borderRadius: 6 }}
          >
            <Space wrap style={{ marginBottom: 8 }}>
              <Input
                size="small"
                className="mono"
                style={{ width: 140 }}
                placeholder="key (a-z0-9_-)"
                value={row.key}
                onChange={(e) => setRow(index, { key: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '') })}
              />
              <Input
                size="small"
                style={{ width: 220 }}
                placeholder="Label, e.g. Company networks"
                value={row.label}
                onChange={(e) => setRow(index, { label: e.target.value })}
              />
              <Button size="small" danger onClick={() => update(rows.filter((_, i) => i !== index))}>
                Remove
              </Button>
            </Space>
            <Input
              size="small"
              style={{ marginBottom: 8 }}
              placeholder="Description (optional)"
              value={row.description || ''}
              onChange={(e) => setRow(index, { description: e.target.value })}
            />
            <Input.TextArea
              rows={3}
              className="mono"
              placeholder="192.168.10.0/24, 10.20.0.0/16"
              defaultValue={(row.allowed_ips || []).join(', ')}
              onBlur={(e) =>
                setRow(index, {
                  allowed_ips: e.target.value
                    .split(/[,\s]+/)
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
            />
          </div>
        ))}
        <Button
          size="small"
          style={{ marginTop: 10 }}
          onClick={() => update([...rows, { key: '', label: '', description: '', allowed_ips: [] }])}
        >
          Add template
        </Button>
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: '8px 0',
          borderBottom: '1px solid var(--la-panel-border)',
        }}
      >
        <span style={{ fontSize: 13 }}>Default route mode for new peers</span>
        <Select
          size="small"
          style={{ width: 240, flex: 'none' }}
          value={mod.default_route_mode || 'vpn_only'}
          options={routeOptions}
          onChange={(value) => patch({ default_route_mode: value })}
        />
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: '8px 0',
          borderBottom: '1px solid var(--la-panel-border)',
        }}
      >
        <span style={{ fontSize: 13 }}>Default client DNS for new peers</span>
        <Select
          size="small"
          style={{ width: 240, flex: 'none' }}
          value={mod.default_dns_mode || 'none'}
          options={[
            { value: 'none', label: 'Keep OS / corporate DNS' },
            { value: 'server', label: 'Use server DNS' },
            { value: 'custom', label: 'Custom DNS' },
          ]}
          onChange={(value) => patch({ default_dns_mode: value })}
        />
      </div>
    </>
  )
}

function ModuleOptionsFields({
  moduleKey,
  mod,
  patch,
}: {
  moduleKey: string
  mod: Record<string, any>
  patch: (p: Record<string, any>) => void
}) {
  switch (moduleKey) {
    case 'overview':
      return (
        <>
          <FineSwitch label="Live WebSocket metrics" checked={!!mod.live_metrics} onChange={(v) => patch({ live_metrics: v })} />
          <FineSwitch label="Gauges CPU / RAM / Swap / Disk" checked={!!mod.gauges} onChange={(v) => patch({ gauges: v })} />
          <FineSwitch label="CPU/RAM and network charts" checked={!!mod.charts} onChange={(v) => patch({ charts: v })} />
          <FineSwitch label="Disks" checked={!!mod.disks} onChange={(v) => patch({ disks: v })} />
          <FineSwitch label="Top processes" checked={!!mod.processes} onChange={(v) => patch({ processes: v })} />
          <FineSwitch label="Temperatures" checked={!!mod.temperatures} onChange={(v) => patch({ temperatures: v })} />
        </>
      )
    case 'history':
      return (
        <FineSwitch label="Write system snapshots to DB" checked={!!mod.record} onChange={(v) => patch({ record: v })} />
      )
    case 'fail2ban':
      return (
        <>
          <FineSwitch label="Allow management (install / ban/unban/reload/start/stop)" checked={!!mod.allow_mutations} onChange={(v) => patch({ allow_mutations: v })} />
          <FineSwitch label="Allow package install (apt/dnf/…)" checked={mod.allow_install !== false} onChange={(v) => patch({ allow_install: v })} />
          <FineSwitch label="Show log tail" checked={!!mod.show_logs} onChange={(v) => patch({ show_logs: v })} />
          <NumberRow label="Log lines" value={mod.log_lines ?? 80} min={10} max={500} onChange={(v) => patch({ log_lines: v || 80 })} />
        </>
      )
    case 'firewall':
      return (
        <>
          <FineSwitch label="Allow management (enable/rules)" checked={!!mod.allow_mutations} onChange={(v) => patch({ allow_mutations: v })} />
          <FineSwitch label="Raw output" checked={!!mod.show_raw} onChange={(v) => patch({ show_raw: v })} />
          <FineSwitch label="Show DROP/REJECT log" checked={!!mod.show_logs} onChange={(v) => patch({ show_logs: v })} />
          <NumberRow label="Log lines" value={mod.log_lines ?? 80} min={10} max={500} onChange={(v) => patch({ log_lines: v || 80 })} />
        </>
      )
    case 'docker':
      return (
        <>
          <FineSwitch label="Collect docker stats" checked={!!mod.collect_stats} onChange={(v) => patch({ collect_stats: v })} />
          <FineSwitch label="Collect docker system df" checked={!!mod.collect_disk} onChange={(v) => patch({ collect_disk: v })} />
          <FineSwitch label="Collect docker info" checked={!!mod.collect_info} onChange={(v) => patch({ collect_info: v })} />
          <FineSwitch label="Show raw JSON info" checked={!!mod.show_info_raw} onChange={(v) => patch({ show_info_raw: v })} />
        </>
      )
    case 'network':
      return (
        <>
          <FineSwitch label="Allow management (iface up/down, kill)" checked={!!mod.allow_mutations} onChange={(v) => patch({ allow_mutations: v })} />
          <FineSwitch label="Allow process kill" checked={!!mod.allow_kill} onChange={(v) => patch({ allow_kill: v })} />
          <FineSwitch label="Listening ports" checked={!!mod.show_listening} onChange={(v) => patch({ show_listening: v })} />
          <FineSwitch label="Established connections" checked={!!mod.show_established} onChange={(v) => patch({ show_established: v })} />
          <FineSwitch label="Other statuses (TIME_WAIT, etc.)" checked={!!mod.show_other} onChange={(v) => patch({ show_other: v })} />
          <FineSwitch label="Network interfaces" checked={!!mod.show_interfaces} onChange={(v) => patch({ show_interfaces: v })} />
          <FineSwitch label="Include localhost (127.0.0.1 / ::1)" checked={!!mod.include_localhost} onChange={(v) => patch({ include_localhost: v })} />
          <NumberRow label="Max table rows" value={mod.max_rows ?? 500} min={50} max={5000} onChange={(v) => patch({ max_rows: v || 500 })} />
        </>
      )
    case 'disks':
      return (
        <>
          <FineSwitch label="Allow directory browsing" checked={!!mod.allow_browse} onChange={(v) => patch({ allow_browse: v })} />
          <FineSwitch label="Include pseudo FS (tmpfs, etc.)" checked={!!mod.include_pseudo} onChange={(v) => patch({ include_pseudo: v })} />
          <NumberRow label="Max directory entries" value={mod.max_entries ?? 500} min={50} max={5000} onChange={(v) => patch({ max_entries: v || 500 })} />
          <NumberRow label="Scan timeout (sec)" value={mod.scan_timeout_seconds ?? 25} min={5} max={120} onChange={(v) => patch({ scan_timeout_seconds: v || 25 })} />
        </>
      )
    case 'users':
      return (
        <>
          <FineSwitch label="Allow changes (useradd/usermod/…)" checked={!!mod.allow_mutations} onChange={(v) => patch({ allow_mutations: v })} />
          <FineSwitch label="Show system accounts (uid/gid < min)" checked={!!mod.show_system_accounts} onChange={(v) => patch({ show_system_accounts: v })} />
          <FineSwitch label="Allow modifying system accounts" checked={!!mod.allow_system_mutations} onChange={(v) => patch({ allow_system_mutations: v })} />
          <NumberRow label="min UID/GID (below = system)" value={mod.min_uid ?? 1000} min={0} max={65535} onChange={(v) => patch({ min_uid: v ?? 1000 })} />
        </>
      )
    case 'services':
      return (
        <>
          <FineSwitch label="Allow management (start/stop/restart/…)" checked={!!mod.allow_mutations} onChange={(v) => patch({ allow_mutations: v })} />
          <FineSwitch label="Show inactive services" checked={!!mod.show_inactive} onChange={(v) => patch({ show_inactive: v })} />
          <NumberRow label="journalctl lines" value={mod.log_lines ?? 80} min={10} max={500} onChange={(v) => patch({ log_lines: v || 80 })} />
        </>
      )
    case 'ssh_tunnel':
      return (
        <>
          <FineSwitch label="Allow changes (useradd/keys/sshd drop-in)" checked={!!mod.allow_mutations} onChange={(v) => patch({ allow_mutations: v })} />
          <FineSwitch label="Show active SSH sessions" checked={mod.show_sessions !== false} onChange={(v) => patch({ show_sessions: v })} />
          <FineSwitch label="Write connection history to DB" checked={mod.record_history !== false} onChange={(v) => patch({ record_history: v })} />
          <NumberRow label="History write interval (sec)" value={mod.history_interval_seconds ?? 15} min={5} max={3600} onChange={(v) => patch({ history_interval_seconds: v || 15 })} />
          <TextRow label="Username prefix" value={mod.username_prefix ?? 'tun-'} onChange={(v) => patch({ username_prefix: v })} />
          <TextRow label="Public hostname (for ssh config)" value={mod.public_hostname ?? ''} placeholder="auto FQDN" onChange={(v) => patch({ public_hostname: v })} />
          <NumberRow
            label="Public SSH port (client config / NAT)"
            value={mod.public_port ?? 22}
            min={1}
            max={65535}
            onChange={(v) => patch({ public_port: v || 22 })}
          />
          <NumberRow
            label="Local sshd listen port (session detection)"
            value={mod.listen_port ?? 22}
            min={1}
            max={65535}
            onChange={(v) => patch({ listen_port: v || 22 })}
          />
        </>
      )
    case 'wireguard':
      return (
        <>
          <FineSwitch label="Allow changes (install tools / wg-quick / peers)" checked={!!mod.allow_mutations} onChange={(v) => patch({ allow_mutations: v })} />
          <FineSwitch label="Allow package install (apt/dnf/…)" checked={mod.allow_install !== false} onChange={(v) => patch({ allow_install: v })} />
          <FineSwitch
            label="Show live peer connections (wg dump)"
            checked={mod.show_live_peers !== false}
            onChange={(v) => patch({ show_live_peers: v })}
          />
          <FineSwitch
            label="Show IP address map"
            checked={mod.show_ip_map !== false}
            onChange={(v) => patch({ show_ip_map: v })}
          />
          <FineSwitch
            label="Write connection history to DB (opt-in, extra load)"
            checked={!!mod.record_history}
            onChange={(v) => patch({ record_history: v })}
          />
          <NumberRow
            label="History poll interval (seconds)"
            value={mod.history_interval_seconds ?? 30}
            min={10}
            max={600}
            onChange={(v) => patch({ history_interval_seconds: v || 30 })}
          />
          <NumberRow
            label="Online if handshake newer than (seconds)"
            value={mod.online_handshake_seconds ?? 180}
            min={30}
            max={3600}
            onChange={(v) => patch({ online_handshake_seconds: v || 180 })}
          />
          <TextRow label="Interface" value={mod.interface ?? 'wg0'} mono onChange={(v) => patch({ interface: v })} />
          <TextRow label="Public endpoint host" value={mod.endpoint_host ?? ''} placeholder="auto FQDN / IP" onChange={(v) => patch({ endpoint_host: v })} />
          <NumberRow label="Listen port" value={mod.default_listen_port ?? 51820} min={1} max={65535} onChange={(v) => patch({ default_listen_port: v || 51820 })} />
          <RouteTemplatesEditor mod={mod} patch={patch} />
        </>
      )
    case 'openvpn':
      return (
        <>
          <FineSwitch label="Allow changes (install / PKI / clients / systemctl)" checked={!!mod.allow_mutations} onChange={(v) => patch({ allow_mutations: v })} />
          <FineSwitch label="Allow package install (apt/dnf/…)" checked={mod.allow_install !== false} onChange={(v) => patch({ allow_install: v })} />
          <TextRow label="Instance name" value={mod.instance ?? 'lnxadmin'} mono onChange={(v) => patch({ instance: v })} />
          <TextRow label="Public endpoint host" value={mod.endpoint_host ?? ''} placeholder="auto FQDN / IP" onChange={(v) => patch({ endpoint_host: v })} />
          <NumberRow label="Default port" value={mod.default_port ?? 1194} min={1} max={65535} onChange={(v) => patch({ default_port: v || 1194 })} />
        </>
      )
    case 'nginx':
      return (
        <>
          <FineSwitch label="Allow changes (install / routes / certs / apply)" checked={!!mod.allow_mutations} onChange={(v) => patch({ allow_mutations: v })} />
          <FineSwitch label="Allow package install (apt/dnf/…)" checked={mod.allow_install !== false} onChange={(v) => patch({ allow_install: v })} />
          <TextRow label="ACME email" value={mod.acme_email ?? ''} placeholder="admin@example.com" onChange={(v) => patch({ acme_email: v })} />
          <TextRow label="ACME environment" value={mod.acme_environment ?? 'production'} placeholder="production | staging | custom" onChange={(v) => patch({ acme_environment: v })} />
          <NumberRow label="Renew days before expiry" value={mod.renew_days_before ?? 30} min={1} max={90} onChange={(v) => patch({ renew_days_before: v || 30 })} />
          <NumberRow label="Log lines" value={mod.log_lines ?? 120} min={20} max={2000} onChange={(v) => patch({ log_lines: v || 120 })} />
        </>
      )
    case 'files':
      return <FilesMountEditor mod={mod} patch={patch} />
    case 'speedtest':
      return (
        <>
          <FineSwitch label="Allow Host ↔ Internet test (Cloudflare edge)" checked={mod.allow_internet_test !== false} onChange={(v) => patch({ allow_internet_test: v })} />
          <FineSwitch label="Allow iperf3 client / server" checked={mod.allow_iperf !== false} onChange={(v) => patch({ allow_iperf: v })} />
          <FineSwitch label="Allow package install (iperf3 via apt/dnf/…)" checked={mod.allow_install !== false} onChange={(v) => patch({ allow_install: v })} />
          <NumberRow label="Max test duration (sec)" value={mod.max_duration_seconds ?? 60} min={5} max={3600} onChange={(v) => patch({ max_duration_seconds: v || 60 })} />
          <NumberRow label="Max parallel iperf3 streams" value={mod.max_parallel ?? 32} min={1} max={128} onChange={(v) => patch({ max_parallel: v || 32 })} />
          <NumberRow label="History size (results kept)" value={mod.history_size ?? 200} min={10} max={5000} onChange={(v) => patch({ history_size: v || 200 })} />
        </>
      )
    default:
      return <Typography.Text type="secondary">No extra options for this module.</Typography.Text>
  }
}
