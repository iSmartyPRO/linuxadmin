import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ConfigProvider, App as AntApp, theme, Spin } from 'antd'
import enUS from 'antd/locale/en_US'
import { useEffect, useMemo, useState } from 'react'
import { AuthProvider, useAuth } from './api/auth'
import { SetupStatusProvider, useSetupStatus } from './api/setupStatus'
import { AppSettingsProvider } from './api/settings'
import { AccessProvider } from './api/access'
import { AppLayout } from './layouts/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { SetupWizardPage } from './pages/SetupWizardPage'
import { DashboardPage } from './pages/DashboardPage'
import { HistoryPage } from './pages/HistoryPage'
import { Fail2banPage } from './pages/Fail2banPage'
import { FirewallPage } from './pages/FirewallPage'
import { DockerPage } from './pages/DockerPage'
import { NetworkPage } from './pages/NetworkPage'
import { DisksPage } from './pages/DisksPage'
import { SshTunnelPage } from './pages/SshTunnelPage'
import { WireGuardPage } from './pages/WireGuardPage'
import { OpenVpnPage } from './pages/OpenVpnPage'
import { NginxPage } from './pages/NginxPage'
import { UsersPage } from './pages/UsersPage'
import { ServicesPage } from './pages/ServicesPage'
import { PostgresPage } from './pages/PostgresPage'
import { ModuleSettingsDetailPage } from './pages/ModuleSettingsDetailPage'
import {
  SettingsAccessPage,
  SettingsConnectionPage,
  SettingsModulesPage,
  SettingsPage,
  SettingsProjectPage,
} from './pages/SettingsPage'
import { LegacyModuleSettingsRedirect } from './pages/LegacyModuleSettingsRedirect'
import { ModuleGate } from './components/ModuleGate'
import { buildAntdTheme } from './theme/tokens'

function Protected({ children }: { children: React.ReactNode }) {
  const { token, loading } = useAuth()
  const { configured } = useSetupStatus()
  if (loading || configured === null) {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }
  if (!configured) return <Navigate to="/setup" replace />
  if (!token) return <Navigate to="/login" replace />
  return (
    <AppSettingsProvider>
      <AccessProvider>{children}</AccessProvider>
    </AppSettingsProvider>
  )
}

function Shell() {
  const [dark, setDark] = useState(() => localStorage.getItem('lnxadmin_theme') === 'dark')
  const algorithm = useMemo(() => (dark ? theme.darkAlgorithm : theme.defaultAlgorithm), [dark])
  const themed = useMemo(() => buildAntdTheme(dark), [dark])
  const { configured } = useSetupStatus()

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
  }, [dark])

  return (
    <ConfigProvider locale={enUS} theme={{ algorithm, ...themed }}>
      <AntApp>
        <Routes>
          <Route
            path="/setup"
            element={
              configured === null ? (
                <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
                  <Spin size="large" />
                </div>
              ) : configured ? (
                <Navigate to="/login" replace />
              ) : (
                <SetupWizardPage />
              )
            }
          />
          <Route
            path="/login"
            element={
              configured === false ? <Navigate to="/setup" replace /> : <LoginPage />
            }
          />
          <Route
            path="/"
            element={
              <Protected>
                <AppLayout
                  dark={dark}
                  onToggleTheme={() => {
                    setDark((v) => {
                      const next = !v
                      localStorage.setItem('lnxadmin_theme', next ? 'dark' : 'light')
                      return next
                    })
                  }}
                />
              </Protected>
            }
          >
            <Route
              index
              element={
                <ModuleGate module="overview">
                  <DashboardPage />
                </ModuleGate>
              }
            />
            <Route
              path="history"
              element={
                <ModuleGate module="history">
                  <HistoryPage />
                </ModuleGate>
              }
            />
            <Route
              path="fail2ban"
              element={
                <ModuleGate module="fail2ban">
                  <Fail2banPage />
                </ModuleGate>
              }
            />
            <Route
              path="firewall"
              element={
                <ModuleGate module="firewall">
                  <FirewallPage />
                </ModuleGate>
              }
            />
            <Route
              path="docker"
              element={
                <ModuleGate module="docker">
                  <DockerPage />
                </ModuleGate>
              }
            />
            <Route
              path="network"
              element={
                <ModuleGate module="network">
                  <NetworkPage />
                </ModuleGate>
              }
            />
            <Route
              path="disks"
              element={
                <ModuleGate module="disks">
                  <DisksPage />
                </ModuleGate>
              }
            />
            <Route
              path="ssh-tunnel"
              element={
                <ModuleGate module="ssh_tunnel">
                  <SshTunnelPage />
                </ModuleGate>
              }
            />
            <Route
              path="wireguard"
              element={
                <ModuleGate module="wireguard">
                  <WireGuardPage />
                </ModuleGate>
              }
            />
            <Route
              path="openvpn"
              element={
                <ModuleGate module="openvpn">
                  <OpenVpnPage />
                </ModuleGate>
              }
            />
            <Route
              path="nginx"
              element={
                <ModuleGate module="nginx">
                  <NginxPage />
                </ModuleGate>
              }
            />
            <Route
              path="users"
              element={
                <ModuleGate module="users">
                  <UsersPage />
                </ModuleGate>
              }
            />
            <Route
              path="services"
              element={
                <ModuleGate module="services">
                  <ServicesPage />
                </ModuleGate>
              }
            />
            <Route
              path="postgres"
              element={
                <ModuleGate module="postgres">
                  <PostgresPage />
                </ModuleGate>
              }
            />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="settings/project" element={<SettingsProjectPage />} />
            <Route path="settings/connection" element={<SettingsConnectionPage />} />
            <Route path="settings/modules" element={<SettingsModulesPage />} />
            <Route path="settings/access" element={<SettingsAccessPage />} />
            <Route path="settings/module/:moduleKey" element={<ModuleSettingsDetailPage />} />
            <Route path="settings/modules/:moduleKey" element={<LegacyModuleSettingsRedirect />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AntApp>
    </ConfigProvider>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <SetupStatusProvider>
          <Shell />
        </SetupStatusProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
