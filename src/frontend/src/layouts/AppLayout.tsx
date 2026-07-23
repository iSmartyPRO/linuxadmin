import { Layout, Menu, Button, Typography, Switch, Tooltip, Spin } from 'antd'
import {
  DashboardOutlined,
  HistoryOutlined,
  SafetyCertificateOutlined,
  FireOutlined,
  DatabaseOutlined,
  SettingOutlined,
  LogoutOutlined,
  MoonOutlined,
  SunOutlined,
  DockerOutlined,
  ApiOutlined,
  TeamOutlined,
  CloudServerOutlined,
  HddOutlined,
  NodeIndexOutlined,
  SafetyOutlined,
  LockOutlined,
} from '@ant-design/icons'
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../api/auth'
import { useAppSettings, type ModuleKey } from '../api/settings'

const { Header, Sider, Content } = Layout

type Props = {
  dark: boolean
  onToggleTheme: () => void
}

const MENU: Array<{
  key: string
  module?: ModuleKey
  icon: React.ReactNode
  label: string
  to: string
}> = [
  { key: '/', module: 'overview', icon: <DashboardOutlined />, label: 'Overview', to: '/' },
  {
    key: '/history',
    module: 'history',
    icon: <HistoryOutlined />,
    label: 'History',
    to: '/history',
  },
  {
    key: '/fail2ban',
    module: 'fail2ban',
    icon: <SafetyCertificateOutlined />,
    label: 'Fail2ban',
    to: '/fail2ban',
  },
  {
    key: '/firewall',
    module: 'firewall',
    icon: <FireOutlined />,
    label: 'Firewall',
    to: '/firewall',
  },
  {
    key: '/docker',
    module: 'docker',
    icon: <DockerOutlined />,
    label: 'Docker',
    to: '/docker',
  },
  {
    key: '/network',
    module: 'network',
    icon: <ApiOutlined />,
    label: 'Network',
    to: '/network',
  },
  {
    key: '/disks',
    module: 'disks',
    icon: <HddOutlined />,
    label: 'Disks',
    to: '/disks',
  },
  {
    key: '/ssh-tunnel',
    module: 'ssh_tunnel',
    icon: <NodeIndexOutlined />,
    label: 'SSH Tunnel',
    to: '/ssh-tunnel',
  },
  {
    key: '/wireguard',
    module: 'wireguard',
    icon: <SafetyOutlined />,
    label: 'WireGuard',
    to: '/wireguard',
  },
  {
    key: '/openvpn',
    module: 'openvpn',
    icon: <LockOutlined />,
    label: 'OpenVPN',
    to: '/openvpn',
  },
  {
    key: '/users',
    module: 'users',
    icon: <TeamOutlined />,
    label: 'Users',
    to: '/users',
  },
  {
    key: '/services',
    module: 'services',
    icon: <CloudServerOutlined />,
    label: 'Services',
    to: '/services',
  },
  {
    key: '/postgres',
    module: 'postgres',
    icon: <DatabaseOutlined />,
    label: 'PostgreSQL',
    to: '/postgres',
  },
  { key: '/settings', icon: <SettingOutlined />, label: 'Settings', to: '/settings' },
]

export function AppLayout({ dark, onToggleTheme }: Props) {
  const { username, logout } = useAuth()
  const { loading, appName, isModuleEnabled } = useAppSettings()
  const location = useLocation()
  const selected = '/' + (location.pathname.split('/')[1] || '')

  const items = MENU.filter((item) => !item.module || isModuleEnabled(item.module)).map((item) => ({
    key: item.key,
    icon: item.icon,
    label: <Link to={item.to}>{item.label}</Link>,
  }))

  // If current route's module is disabled, bounce to settings
  const current = MENU.find((m) => m.key === (selected === '/' ? '/' : selected))
  if (!loading && current?.module && !isModuleEnabled(current.module)) {
    return <Navigate to="/settings" replace />
  }

  return (
    <Layout style={{ minHeight: '100vh', background: 'transparent' }}>
      <Sider
        className="la-sider"
        breakpoint="lg"
        collapsedWidth={72}
        width={248}
        style={{
          background: 'var(--la-sider)',
          borderRight: '1px solid var(--la-panel-border)',
          backdropFilter: 'blur(20px)',
          position: 'sticky',
          top: 0,
          height: '100vh',
        }}
      >
        <div
          style={{
            height: 72,
            margin: '8px 14px 4px',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <div className="la-brand-mark">LA</div>
          <div style={{ overflow: 'hidden' }}>
            <div className="display" style={{ fontWeight: 700, fontSize: 16, lineHeight: 1.1 }}>
              {appName}
            </div>
            <div style={{ fontSize: 11, color: 'var(--la-muted)', marginTop: 2 }}>host control</div>
          </div>
        </div>

        {loading ? (
          <div style={{ padding: 24, textAlign: 'center' }}>
            <Spin size="small" />
          </div>
        ) : (
          <Menu
            mode="inline"
            selectedKeys={[selected === '/' ? '/' : selected]}
            items={items}
          />
        )}

        <div style={{ padding: '12px 16px 20px', borderTop: '1px solid var(--la-panel-border)' }}>
          <div style={{ fontSize: 11, color: 'var(--la-muted)', marginBottom: 4 }}>session</div>
          <Typography.Text ellipsis style={{ display: 'block', fontWeight: 600 }}>
            {username}
          </Typography.Text>
        </div>
      </Sider>

      <Layout style={{ background: 'transparent' }}>
        <Header
          style={{
            background: 'transparent',
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
            paddingInline: 24,
            gap: 12,
            height: 64,
            lineHeight: '64px',
          }}
        >
          <Tooltip title={dark ? 'Light theme' : 'Dark theme'}>
            <div
              className="la-panel"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                padding: '6px 12px',
                borderRadius: 999,
              }}
            >
              <SunOutlined style={{ color: dark ? 'var(--la-muted)' : 'var(--la-accent)' }} />
              <Switch size="small" checked={dark} onChange={onToggleTheme} />
              <MoonOutlined style={{ color: dark ? 'var(--la-accent-soft)' : 'var(--la-muted)' }} />
            </div>
          </Tooltip>
          <Button icon={<LogoutOutlined />} onClick={logout}>
            Log out
          </Button>
        </Header>
        <Content className="la-content-shell" style={{ margin: '0 20px 20px' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
