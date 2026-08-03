import { Link } from 'react-router-dom'
import {
  SafetyCertificateOutlined,
  FireOutlined,
  DatabaseOutlined,
  DockerOutlined,
  ApiOutlined,
  HddOutlined,
  NodeIndexOutlined,
  SafetyOutlined,
  LockOutlined,
  GlobalOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons'
import { motion } from 'framer-motion'

type Props = {
  kind:
    | 'fail2ban'
    | 'firewall'
    | 'postgres'
    | 'docker'
    | 'network'
    | 'disks'
    | 'ssh_tunnel'
    | 'wireguard'
    | 'openvpn'
    | 'nginx'
  title: string
  ok: boolean
  description: string
  to: string
}

const icons = {
  fail2ban: <SafetyCertificateOutlined />,
  firewall: <FireOutlined />,
  postgres: <DatabaseOutlined />,
  docker: <DockerOutlined />,
  network: <ApiOutlined />,
  disks: <HddOutlined />,
  ssh_tunnel: <NodeIndexOutlined />,
  wireguard: <SafetyOutlined />,
  openvpn: <LockOutlined />,
  nginx: <GlobalOutlined />,
}

export function StatusCard({ kind, title, ok, description, to }: Props) {
  return (
    <Link to={to} style={{ textDecoration: 'none', display: 'block', height: '100%' }}>
      <motion.div
        whileHover={{ y: -3 }}
        transition={{ type: 'spring', stiffness: 380, damping: 28 }}
        className="la-panel"
        style={{
          height: '100%',
          padding: 18,
          cursor: 'pointer',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 'auto -20% -40% auto',
            width: 140,
            height: 140,
            borderRadius: '50%',
            background: ok
              ? 'radial-gradient(circle, color-mix(in srgb, var(--la-ok) 28%, transparent), transparent 70%)'
              : 'radial-gradient(circle, color-mix(in srgb, var(--la-warn) 22%, transparent), transparent 70%)',
            pointerEvents: 'none',
          }}
        />
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 14,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span
              style={{
                width: 36,
                height: 36,
                borderRadius: 12,
                display: 'grid',
                placeItems: 'center',
                background: 'color-mix(in srgb, var(--la-accent) 12%, transparent)',
                color: 'var(--la-accent-deep)',
                fontSize: 16,
              }}
            >
              {icons[kind]}
            </span>
            <strong style={{ fontSize: 15 }}>{title}</strong>
          </div>
          <span
            className="mono"
            style={{
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.04em',
              padding: '4px 8px',
              borderRadius: 999,
              color: ok ? 'var(--la-ok)' : 'var(--la-muted)',
              background: ok
                ? 'color-mix(in srgb, var(--la-ok) 14%, transparent)'
                : 'color-mix(in srgb, var(--la-muted) 12%, transparent)',
            }}
          >
            {ok ? 'OK' : 'NO'}
          </span>
        </div>
        <div style={{ color: 'var(--la-muted)', fontSize: 13, lineHeight: 1.45, minHeight: 38 }}>
          {description}
        </div>
        <div
          style={{
            marginTop: 14,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--la-accent-deep)',
          }}
        >
          Open <ArrowRightOutlined style={{ fontSize: 10 }} />
        </div>
      </motion.div>
    </Link>
  )
}
