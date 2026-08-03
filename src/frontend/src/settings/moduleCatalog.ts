export type ModuleSettingKey =
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

export type ModuleCatalogItem = {
  key: ModuleSettingKey
  title: string
  description: string
  group: string
}

export const MODULE_CATALOG: ModuleCatalogItem[] = [
  {
    key: 'overview',
    title: 'Overview',
    description: 'Host dashboard: live metrics, gauges, charts, disks, processes',
    group: 'Monitoring',
  },
  {
    key: 'history',
    title: 'History',
    description: 'Charts of past metric snapshots',
    group: 'Monitoring',
  },
  {
    key: 'fail2ban',
    title: 'Fail2ban',
    description: 'Jails, banned IPs, log',
    group: 'Security',
  },
  {
    key: 'firewall',
    title: 'Firewall',
    description: 'ufw / firewalld / nft / iptables rules',
    group: 'Security',
  },
  {
    key: 'docker',
    title: 'Docker',
    description: 'Containers, images, volumes, networks',
    group: 'Runtime',
  },
  {
    key: 'network',
    title: 'Network',
    description: 'Listening ports, connections, and processes',
    group: 'Runtime',
  },
  {
    key: 'disks',
    title: 'Disks',
    description: 'Volumes, I/O, and directory size analysis',
    group: 'Runtime',
  },
  {
    key: 'users',
    title: 'Users & Groups',
    description: 'Linux system users and groups',
    group: 'Runtime',
  },
  {
    key: 'services',
    title: 'Services',
    description: 'systemd services: status and management',
    group: 'Runtime',
  },
  {
    key: 'postgres',
    title: 'PostgreSQL',
    description: 'DB monitoring, connection, statements, history',
    group: 'Data',
  },
  {
    key: 'ssh_tunnel',
    title: 'SSH Tunnel',
    description: 'Jump host: users, keys, destinations, ssh config',
    group: 'VPN / Access',
  },
  {
    key: 'wireguard',
    title: 'WireGuard',
    description: 'VPN server, peers, routes, client configs & QR',
    group: 'VPN / Access',
  },
  {
    key: 'openvpn',
    title: 'OpenVPN',
    description: 'VPN server, clients, routes, .ovpn profiles',
    group: 'VPN / Access',
  },
  {
    key: 'nginx',
    title: 'Nginx Edge',
    description: 'Reverse proxy, TLS/SNI, LE certs, templates (Carbonio, Nextcloud, …)',
    group: 'Edge / Proxy',
  },
]

export function getModuleMeta(key: string): ModuleCatalogItem | undefined {
  return MODULE_CATALOG.find((m) => m.key === key)
}
