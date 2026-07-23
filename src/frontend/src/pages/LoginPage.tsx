import { Alert, Button, Form, Input, Typography } from 'antd'
import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuth } from '../api/auth'

export function LoginPage() {
  const { login, token, loading } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (!loading && token) return <Navigate to="/" replace />

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1.1fr) minmax(320px, 440px)',
        position: 'relative',
        overflow: 'hidden',
      }}
      className="login-shell"
    >
      <style>{`
        @media (max-width: 900px) {
          .login-shell { grid-template-columns: 1fr !important; }
          .login-hero { min-height: 220px !important; padding: 32px 24px !important; }
        }
      `}</style>

      <section
        className="login-hero"
        style={{
          position: 'relative',
          padding: '56px 64px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          color: '#ecfeff',
          background:
            'radial-gradient(900px 500px at 20% 10%, rgba(45,212,191,0.28), transparent 55%), radial-gradient(700px 480px at 80% 80%, rgba(14,165,233,0.18), transparent 50%), linear-gradient(155deg, #06202a 0%, #0b1220 48%, #0f3d3a 100%)',
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 0,
            opacity: 0.25,
            backgroundImage:
              'linear-gradient(rgba(148,163,184,0.12) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,0.12) 1px, transparent 1px)',
            backgroundSize: '56px 56px',
            maskImage: 'radial-gradient(ellipse at 30% 40%, black, transparent 75%)',
            pointerEvents: 'none',
          }}
        />

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          style={{ position: 'relative' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 40 }}>
            <div className="la-brand-mark" style={{ width: 48, height: 48, fontSize: 18, borderRadius: 16 }}>
              LA
            </div>
            <div>
              <div className="display" style={{ fontSize: 22, fontWeight: 800 }}>
                Linux Admin
              </div>
              <div style={{ opacity: 0.7, fontSize: 13 }}>observability · security · postgres</div>
            </div>
          </div>

          <h1
            className="display"
            style={{
              margin: 0,
              fontSize: 'clamp(36px, 5vw, 56px)',
              fontWeight: 800,
              lineHeight: 1.05,
              maxWidth: 520,
            }}
          >
            Host control
            <br />
            without the noise.
          </h1>
          <p style={{ marginTop: 18, maxWidth: 460, opacity: 0.72, fontSize: 16, lineHeight: 1.55 }}>
            Live metrics, Fail2ban, firewall, and PostgreSQL — in one calm panel.
          </p>
        </motion.div>

        <div style={{ position: 'relative', display: 'flex', gap: 28, flexWrap: 'wrap', opacity: 0.8 }}>
          {['CPU / RAM live', 'pg_stat_*', 'security'].map((item) => (
            <span key={item} className="mono" style={{ fontSize: 12, letterSpacing: '0.06em' }}>
              {item}
            </span>
          ))}
        </div>
      </section>

      <section
        style={{
          display: 'grid',
          placeItems: 'center',
          padding: 28,
          background: 'color-mix(in srgb, var(--la-paper) 92%, #0d9488)',
        }}
      >
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, delay: 0.08 }}
          className="la-panel"
          style={{ width: '100%', maxWidth: 380, padding: 28 }}
        >
          <Typography.Title level={3} style={{ marginTop: 0, marginBottom: 4 }} className="display">
            Sign in
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 20 }}>
            Sign in to the administration panel
          </Typography.Paragraph>
          {error ? <Alert type="error" message={error} style={{ marginBottom: 16 }} showIcon /> : null}
          <Form
            layout="vertical"
            onFinish={async (values) => {
              setSubmitting(true)
              setError(null)
              try {
                await login(values.username, values.password)
              } catch (e) {
                setError(e instanceof Error ? e.message : 'Sign-in failed')
              } finally {
                setSubmitting(false)
              }
            }}
            initialValues={{ username: '', password: '' }}
          >
            <Form.Item name="username" label="Username" rules={[{ required: true }]}>
              <Input autoFocus size="large" />
            </Form.Item>
            <Form.Item name="password" label="Password" rules={[{ required: true }]}>
              <Input.Password size="large" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block size="large" loading={submitting}>
              Sign in
            </Button>
          </Form>
        </motion.div>
      </section>
    </div>
  )
}
