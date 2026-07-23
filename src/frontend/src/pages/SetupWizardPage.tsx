import { Alert, Button, Form, Input, InputNumber, Steps, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { BrandLogo } from '../components/BrandLogo'
import { useSetupStatus } from '../api/setupStatus'

const SETUP_TOKEN_KEY = 'lnxadmin_setup_token'

type Status = {
  configured: boolean
  setup_token_required?: boolean
  localhost_only?: boolean
  suggested?: {
    db_host?: string
    db_port?: number
    db_user?: string
    db_name?: string
    admin_user?: string
  }
}

function getSetupToken(): string {
  try {
    return sessionStorage.getItem(SETUP_TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

function setSetupToken(token: string) {
  try {
    if (token) sessionStorage.setItem(SETUP_TOKEN_KEY, token)
    else sessionStorage.removeItem(SETUP_TOKEN_KEY)
  } catch {
    /* ignore */
  }
}

async function setupFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  }
  const token = getSetupToken()
  if (token) headers['X-Setup-Token'] = token

  const res = await fetch(path, {
    ...init,
    headers,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = data.detail
    const msg =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ')
          : data.message || res.statusText || 'Request failed'
    throw new Error(msg)
  }
  return data as T
}

export function SetupWizardPage() {
  const navigate = useNavigate()
  const { markConfigured } = useSetupStatus()
  const [status, setStatus] = useState<Status | null>(null)
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [setupToken, setSetupTokenState] = useState(getSetupToken())
  const [dbForm] = Form.useForm()
  const [adminForm] = Form.useForm()
  // Keep validated DB params in React state — Ant Design unmounts the Database
  // form on step 3 and can drop Input.Password values before Finish.
  const [dbParams, setDbParams] = useState<Record<string, unknown> | null>(null)

  useEffect(() => {
    void setupFetch<Status>('/api/setup/status')
      .then((s) => {
        setStatus(s)
        if (s.configured) {
          markConfigured()
          return
        }
        dbForm.setFieldsValue({
          host: s.suggested?.db_host || 'localhost',
          port: s.suggested?.db_port || 5432,
          username: s.suggested?.db_user || 'lnxadmin',
          database: s.suggested?.db_name || 'lnxadmin',
          password: '',
        })
        adminForm.setFieldsValue({
          admin_user: s.suggested?.admin_user || 'admin',
          admin_password: '',
          admin_password2: '',
          app_name: 'Linux Admin',
        })
      })
      .catch((e) => setError(String(e)))
  }, [adminForm, dbForm, markConfigured])

  if (status?.configured) return <Navigate to="/login" replace />

  const persistToken = (value: string) => {
    setSetupTokenState(value)
    setSetupToken(value.trim())
  }

  const testDb = async () => {
    setBusy(true)
    setError(null)
    try {
      if (status?.setup_token_required && !getSetupToken()) {
        throw new Error('Enter the setup token from LNXADMIN_SETUP_TOKEN')
      }
      const values = await dbForm.validateFields()
      const res = await setupFetch<{ ok: boolean; error?: string; version?: string }>(
        '/api/setup/test-db',
        { method: 'POST', body: JSON.stringify(values) },
      )
      if (!res.ok) throw new Error(res.error || 'Connection failed')
      setDbParams(values)
      message.success(res.version ? `Connected: ${res.version.split(',')[0]}` : 'Database OK')
      setStep(2)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const finish = async () => {
    setBusy(true)
    setError(null)
    try {
      if (status?.setup_token_required && !getSetupToken()) {
        throw new Error('Enter the setup token from LNXADMIN_SETUP_TOKEN')
      }
      const db = dbParams ?? (await dbForm.validateFields())
      if (!db?.password) {
        throw new Error('Database password is missing — go back to Database and test again')
      }
      const admin = await adminForm.validateFields()
      if (admin.admin_password !== admin.admin_password2) {
        throw new Error('Passwords do not match')
      }
      await setupFetch('/api/setup/complete', {
        method: 'POST',
        body: JSON.stringify({
          database: db,
          admin_user: admin.admin_user,
          admin_password: admin.admin_password,
          app_name: admin.app_name || 'Linux Admin',
          app_env: 'production',
        }),
      })
      // Update shared status before navigate — otherwise /login still sees
      // configured=false and bounces back to /setup (flash loop).
      markConfigured()
      setSetupToken('')
      message.success('Setup complete — sign in with your admin account')
      navigate('/login', { replace: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        padding: 24,
        background:
          'radial-gradient(900px 500px at 15% 0%, rgba(45,212,191,0.18), transparent 55%), linear-gradient(160deg, #0b1220, #0f3d3a)',
      }}
    >
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="la-panel"
        style={{ width: '100%', maxWidth: 560, padding: 28 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <BrandLogo size={40} />
          <Typography.Title level={3} className="display" style={{ margin: 0 }}>
            Initial setup
          </Typography.Title>
        </div>
        <Typography.Paragraph type="secondary">
          Configure the minimum required to start: PostgreSQL connection and an admin account.
          Everything else can be changed later in Settings.
        </Typography.Paragraph>

        <Steps
          size="small"
          current={step}
          style={{ marginBottom: 24 }}
          items={[{ title: 'Welcome' }, { title: 'Database' }, { title: 'Admin' }]}
        />

        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}

        {status?.localhost_only ? (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="Production setup is limited to localhost"
            description="Open the panel via SSH tunnel to 127.0.0.1, or set LNXADMIN_SETUP_TOKEN in .env to allow remote setup."
          />
        ) : null}

        {step === 0 ? (
          <div>
            <Typography.Paragraph>
              This wizard writes bootstrap values to <span className="mono">.env</span>, creates
              tables, and enables the panel. JWT secret is generated automatically.
            </Typography.Paragraph>
            {status?.setup_token_required ? (
              <div style={{ marginBottom: 16 }}>
                <Typography.Text style={{ display: 'block', marginBottom: 8 }}>
                  Setup token (<span className="mono">LNXADMIN_SETUP_TOKEN</span>)
                </Typography.Text>
                <Input.Password
                  className="mono"
                  value={setupToken}
                  onChange={(e) => persistToken(e.target.value)}
                  placeholder="Required for this host"
                />
              </div>
            ) : null}
            <Button type="primary" onClick={() => setStep(1)}>
              Continue
            </Button>
          </div>
        ) : null}

        {step === 1 ? (
          <Form form={dbForm} layout="vertical">
            <Form.Item name="host" label="PostgreSQL host" rules={[{ required: true }]}>
              <Input className="mono" />
            </Form.Item>
            <Form.Item name="port" label="Port" rules={[{ required: true }]}>
              <InputNumber style={{ width: '100%' }} min={1} max={65535} />
            </Form.Item>
            <Form.Item name="database" label="Database" rules={[{ required: true }]}>
              <Input className="mono" />
            </Form.Item>
            <Form.Item name="username" label="Username" rules={[{ required: true }]}>
              <Input className="mono" />
            </Form.Item>
            <Form.Item name="password" label="Password" rules={[{ required: true }]}>
              <Input.Password />
            </Form.Item>
            <div style={{ display: 'flex', gap: 8 }}>
              <Button onClick={() => setStep(0)}>Back</Button>
              <Button type="primary" loading={busy} onClick={() => void testDb()}>
                Test & continue
              </Button>
            </div>
          </Form>
        ) : null}

        {step === 2 ? (
          <Form form={adminForm} layout="vertical">
            <Form.Item name="app_name" label="Panel name">
              <Input />
            </Form.Item>
            <Form.Item name="admin_user" label="Admin username" rules={[{ required: true }]}>
              <Input className="mono" />
            </Form.Item>
            <Form.Item
              name="admin_password"
              label="Admin password"
              rules={[{ required: true, min: 8, message: 'At least 8 characters' }]}
            >
              <Input.Password />
            </Form.Item>
            <Form.Item
              name="admin_password2"
              label="Confirm password"
              rules={[{ required: true, min: 8 }]}
            >
              <Input.Password />
            </Form.Item>
            <div style={{ display: 'flex', gap: 8 }}>
              <Button onClick={() => setStep(1)}>Back</Button>
              <Button type="primary" loading={busy} onClick={() => void finish()}>
                Finish setup
              </Button>
            </div>
          </Form>
        ) : null}
      </motion.div>
    </div>
  )
}
