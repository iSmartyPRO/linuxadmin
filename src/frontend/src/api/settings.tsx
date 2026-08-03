import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api } from './client'
import { useAuth } from './auth'

export type ModuleKey =
  | 'overview'
  | 'history'
  | 'fail2ban'
  | 'firewall'
  | 'docker'
  | 'network'
  | 'disks'
  | 'users'
  | 'services'
  | 'postgres'
  | 'ssh_tunnel'
  | 'wireguard'
  | 'openvpn'
  | 'nginx'
  | 'settings'

export type ModulesConfig = Record<string, Record<string, any>>

type AppSettingsState = {
  loading: boolean
  appName: string
  modules: ModulesConfig
  refresh: () => Promise<void>
  isModuleEnabled: (key: ModuleKey) => boolean
  moduleOpts: (key: ModuleKey) => Record<string, any>
}

const DEFAULT_MODULES: ModulesConfig = {
  overview: {
    enabled: true,
    live_metrics: true,
    status_cards: true,
    gauges: true,
    charts: true,
    disks: true,
    processes: true,
    temperatures: true,
  },
  history: { enabled: true, record: true },
  fail2ban: { enabled: true, show_logs: true, log_lines: 80, allow_mutations: false },
  firewall: { enabled: true, show_raw: true, show_logs: true, log_lines: 80, allow_mutations: false },
  docker: {
    enabled: true,
    collect_stats: true,
    collect_disk: true,
    collect_info: true,
    show_info_raw: true,
  },
  network: {
    enabled: true,
    show_listening: true,
    show_established: true,
    show_other: true,
    show_interfaces: true,
    include_localhost: true,
    max_rows: 500,
    allow_mutations: false,
    allow_kill: true,
  },
  disks: {
    enabled: true,
    allow_browse: true,
    include_pseudo: false,
    max_entries: 500,
    scan_timeout_seconds: 25,
  },
  users: {
    enabled: true,
    allow_mutations: false,
    show_system_accounts: false,
    allow_system_mutations: false,
    min_uid: 1000,
  },
  services: {
    enabled: true,
    allow_mutations: false,
    show_inactive: true,
    log_lines: 80,
  },
  postgres: { enabled: true },
  ssh_tunnel: {
    enabled: true,
    allow_mutations: false,
    username_prefix: 'tun-',
    group: 'lnxadmin-tunnel',
    public_hostname: '',
    public_port: 22,
    show_sessions: true,
    record_history: true,
    history_interval_seconds: 15,
  },
  wireguard: {
    enabled: true,
    allow_mutations: false,
    allow_install: true,
    interface: 'wg0',
    default_listen_port: 51820,
  },
  openvpn: {
    enabled: true,
    allow_mutations: false,
    allow_install: true,
    instance: 'lnxadmin',
    default_port: 1194,
  },
  nginx: {
    enabled: true,
    allow_mutations: false,
    allow_install: true,
    acme_email: '',
    acme_environment: 'production',
    renew_days_before: 30,
    log_lines: 120,
  },
}

const AppSettingsContext = createContext<AppSettingsState | null>(null)

export function AppSettingsProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  const [loading, setLoading] = useState(true)
  const [appName, setAppName] = useState('Linux Admin')
  const [modules, setModules] = useState<ModulesConfig>(DEFAULT_MODULES)

  const refresh = useCallback(async () => {
    if (!token) {
      setModules(DEFAULT_MODULES)
      setAppName('Linux Admin')
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const res = await api<{ app: { name?: string }; modules: ModulesConfig }>(
        '/api/settings/modules',
      )
      setAppName(res.app?.name || 'Linux Admin')
      setModules({ ...DEFAULT_MODULES, ...(res.modules || {}) })
    } catch {
      setModules(DEFAULT_MODULES)
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const isModuleEnabled = useCallback(
    (key: ModuleKey) => Boolean(modules[key]?.enabled ?? true),
    [modules],
  )

  const moduleOpts = useCallback((key: ModuleKey) => modules[key] || {}, [modules])

  const value = useMemo(
    () => ({ loading, appName, modules, refresh, isModuleEnabled, moduleOpts }),
    [loading, appName, modules, refresh, isModuleEnabled, moduleOpts],
  )

  return <AppSettingsContext.Provider value={value}>{children}</AppSettingsContext.Provider>
}

export function useAppSettings() {
  const ctx = useContext(AppSettingsContext)
  if (!ctx) throw new Error('useAppSettings outside provider')
  return ctx
}
