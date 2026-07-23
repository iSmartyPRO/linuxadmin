import { Descriptions, Tag } from 'antd'
import { resolveOsLogo } from '../utils/osLogo'
import { formatUptime } from '../utils/format'
import { Panel } from './Panel'

export type OsHostInfo = {
  hostname?: string
  fqdn?: string
  os?: string
  os_name?: string
  os_id?: string
  os_id_like?: string
  os_version?: string
  os_version_id?: string
  os_codename?: string
  os_pretty_name?: string
  os_home_url?: string
  kernel?: string
  kernel_version?: string
  system?: string
  arch?: string
  processor?: string
  virtualization?: string | null
  uptime_seconds?: number
  platform?: string
  python_version?: string
}

type Props = {
  host?: OsHostInfo | null
  cpuLogical?: number
  cpuPhysical?: number
}

export function OsInfoCard({ host, cpuLogical, cpuPhysical }: Props) {
  if (!host) {
    return (
      <Panel title="Operating system">
        <div style={{ color: 'var(--la-muted)' }}>Waiting for metrics…</div>
      </Panel>
    )
  }

  const logo = resolveOsLogo(host.os_id, host.os_id_like)
  const title = host.os_pretty_name || host.os || host.os_name || 'Linux'

  return (
    <Panel title="Operating system" padded={false}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '140px 1fr',
          gap: 20,
          padding: 18,
          alignItems: 'center',
        }}
        className="os-info-grid"
      >
        <div
          style={{
            display: 'grid',
            placeItems: 'center',
            minHeight: 120,
            padding: 16,
            borderRadius: 16,
            border: '1px solid var(--la-panel-border)',
            background:
              'radial-gradient(circle at 30% 20%, color-mix(in srgb, var(--la-accent) 12%, transparent), transparent 60%)',
          }}
        >
          <img
            src={logo}
            alt={title}
            style={{
              maxWidth: 96,
              maxHeight: 96,
              width: '100%',
              height: 'auto',
              objectFit: 'contain',
            }}
          />
        </div>

        <div>
          <div
            className="display"
            style={{ fontSize: 22, fontWeight: 700, marginBottom: 4, letterSpacing: '-0.03em' }}
          >
            {title}
          </div>
          <div style={{ color: 'var(--la-muted)', marginBottom: 12, fontSize: 13 }}>
            {host.hostname}
            {host.fqdn && host.fqdn !== host.hostname ? ` · ${host.fqdn}` : ''}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
            {host.os_id ? <Tag className="mono">{host.os_id}</Tag> : null}
            {host.os_codename ? <Tag>{host.os_codename}</Tag> : null}
            {host.arch ? <Tag className="mono">{host.arch}</Tag> : null}
            {host.virtualization ? <Tag color="processing">{host.virtualization}</Tag> : null}
          </div>

          <Descriptions size="small" column={{ xs: 1, sm: 2 }}>
            <Descriptions.Item label="Kernel">
              <span className="mono">{host.kernel || '—'}</span>
            </Descriptions.Item>
            <Descriptions.Item label="Uptime">
              <span className="mono">{formatUptime(host.uptime_seconds)}</span>
            </Descriptions.Item>
            <Descriptions.Item label="Version">
              {host.os_version || host.os_version_id || '—'}
            </Descriptions.Item>
            <Descriptions.Item label="CPU">
              <span className="mono">
                {cpuPhysical || '—'} phys / {cpuLogical || '—'} log
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="Processor" span={2}>
              <span className="mono" style={{ fontSize: 12 }}>
                {host.processor || '—'}
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="Platform" span={2}>
              <span className="mono" style={{ fontSize: 12 }}>
                {host.platform || '—'}
              </span>
            </Descriptions.Item>
          </Descriptions>
        </div>
      </div>
      <style>{`
        @media (max-width: 640px) {
          .os-info-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </Panel>
  )
}
