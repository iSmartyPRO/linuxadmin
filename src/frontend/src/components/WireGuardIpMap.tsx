import { Tooltip, Typography } from 'antd'

export type IpMapCell = {
  ip: string
  host?: number | null
  state: 'free' | 'peer' | 'server' | string
  peer_id?: string
  peer_name?: string
  enabled?: boolean
  notes?: string
}

export type IpMapData = {
  network: string
  server_ip: string
  prefixlen: number
  version: number
  total_usable: number
  reserved: number
  used: number
  free: number
  shown: number
  truncated: boolean
  cells: IpMapCell[]
}

type Props = {
  map: IpMapData
  canMutate?: boolean
  onFreeClick?: (ip: string) => void
  onPeerClick?: (peerId: string) => void
}

function cellTitle(c: IpMapCell): string {
  if (c.state === 'server') return `${c.ip}\nWireGuard server`
  if (c.state === 'peer') {
    const status = c.enabled === false ? 'disabled' : 'enabled'
    const notes = c.notes ? `\n${c.notes}` : ''
    return `${c.ip}\n${c.peer_name || 'peer'} (${status})${notes}`
  }
  return `${c.ip}\nFree — click to create peer`
}

export function WireGuardIpMap({ map, canMutate, onFreeClick, onPeerClick }: Props) {
  const usedPct = map.total_usable
    ? Math.round(((map.used + map.reserved) / map.total_usable) * 100)
    : 0

  return (
    <div className="wg-ipmap">
      <div className="wg-ipmap-head">
        <div>
          <Typography.Text strong className="mono">
            {map.network}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ marginLeft: 10, fontSize: 12 }}>
            {map.used} used · {map.free} free · {map.reserved} server
            {map.truncated ? ` · showing first ${map.shown}` : ''}
          </Typography.Text>
        </div>
        <div className="wg-ipmap-meter" title={`${usedPct}% occupied`}>
          <div className="wg-ipmap-meter-fill" style={{ width: `${Math.min(100, usedPct)}%` }} />
        </div>
      </div>

      <div className="wg-ipmap-legend">
        <span>
          <i className="wg-ipmap-swatch is-free" /> Free
        </span>
        <span>
          <i className="wg-ipmap-swatch is-peer" /> Peer
        </span>
        <span>
          <i className="wg-ipmap-swatch is-peer-off" /> Disabled
        </span>
        <span>
          <i className="wg-ipmap-swatch is-server" /> Server
        </span>
      </div>

      <div className="wg-ipmap-grid" role="grid" aria-label={`IP map for ${map.network}`}>
        {map.cells.map((c) => {
          const disabledPeer = c.state === 'peer' && c.enabled === false
          const cls = [
            'wg-ipmap-cell',
            c.state === 'free' ? 'is-free' : '',
            c.state === 'peer' ? (disabledPeer ? 'is-peer-off' : 'is-peer') : '',
            c.state === 'server' ? 'is-server' : '',
            c.state === 'free' && canMutate ? 'is-clickable' : '',
            c.state === 'peer' ? 'is-clickable' : '',
          ]
            .filter(Boolean)
            .join(' ')

          const label =
            c.host != null
              ? String(c.host)
              : c.ip.includes(':')
                ? c.ip.split(':').pop()
                : c.ip.split('.').pop()

          return (
            <Tooltip
              key={c.ip}
              title={<pre style={{ margin: 0, fontFamily: 'var(--la-mono)', fontSize: 11 }}>{cellTitle(c)}</pre>}
              mouseEnterDelay={0.15}
            >
              <button
                type="button"
                className={cls}
                aria-label={cellTitle(c).replace(/\n/g, ', ')}
                onClick={() => {
                  if (c.state === 'free' && canMutate && onFreeClick) {
                    onFreeClick(c.ip)
                    return
                  }
                  if (c.state === 'peer' && c.peer_id && onPeerClick) {
                    onPeerClick(c.peer_id)
                  }
                }}
              >
                <span className="wg-ipmap-host">{label}</span>
                {c.state === 'peer' && c.peer_name ? (
                  <span className="wg-ipmap-name">{c.peer_name}</span>
                ) : null}
              </button>
            </Tooltip>
          )
        })}
      </div>
    </div>
  )
}
