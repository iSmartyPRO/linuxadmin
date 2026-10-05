import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  AutoComplete,
  Badge,
  Button,
  Col,
  Collapse,
  Empty,
  Input,
  InputNumber,
  Row,
  Segmented,
  Select,
  Slider,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  ApiOutlined,
  ArrowDownOutlined,
  ArrowUpOutlined,
  CloudDownloadOutlined,
  CopyOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  PlayCircleOutlined,
  PoweroffOutlined,
  RocketOutlined,
  SoundOutlined,
  StopOutlined,
  SwapOutlined,
  ThunderboltOutlined,
  WifiOutlined,
} from '@ant-design/icons'
import { api } from '../../api/client'
import { Panel } from '../Panel'
import { PremiumAreaChart } from '../PremiumAreaChart'
import { SpeedGauge } from './SpeedGauge'
import { MetricTile, ProgressBar, StreamBars } from './StPieces'
import { useJob, isActive, type JobSample, type JobState } from '../../speedtest/useJob'
import {
  fmtBitsAuto,
  fmtBytesShort,
  fmtMs,
  fmtSpeedNum,
  PHASE_COLORS,
  pickScale,
  toUnit,
  unitLabel,
  type RateUnit,
} from '../../speedtest/format'
import type { SpeedInfo } from './types'

// ── Client options ───────────────────────────────────

type ClientOpts = {
  host: string
  port: number
  protocol: 'tcp' | 'udp'
  direction: 'upload' | 'download' | 'bidir'
  duration: number
  parallel: number
  interval: number
  omit: number
  bitrate: string
  window: string
  length: string
  mss: number | null
  congestion: string
  no_delay: boolean
  zerocopy: boolean
  ip_version: 4 | 6 | null
  bind: string
  tos: number | null
  connect_timeout_ms: number
}

const DEFAULT_CLIENT: ClientOpts = {
  host: '',
  port: 5201,
  protocol: 'tcp',
  direction: 'upload',
  duration: 10,
  parallel: 4,
  interval: 0.5,
  omit: 1,
  bitrate: '',
  window: '',
  length: '',
  mss: null,
  congestion: '',
  no_delay: false,
  zerocopy: false,
  ip_version: null,
  bind: '',
  tos: null,
  connect_timeout_ms: 5000,
}

type PresetKey = 'balanced' | 'quick' | 'max' | 'udp' | 'custom'

const PRESETS: Array<{ key: Exclude<PresetKey, 'custom'>; title: string; desc: string; icon: React.ReactNode; opts: Partial<ClientOpts> }> = [
  {
    key: 'balanced',
    title: 'Balanced',
    desc: 'TCP · 4 streams · 10 s',
    icon: <DashboardOutlined />,
    opts: { protocol: 'tcp', parallel: 4, duration: 10, omit: 1, interval: 0.5, bitrate: '', window: '', zerocopy: false },
  },
  {
    key: 'quick',
    title: 'Quick check',
    desc: 'TCP · 1 stream · 5 s',
    icon: <ThunderboltOutlined />,
    opts: { protocol: 'tcp', parallel: 1, duration: 5, omit: 0, interval: 0.5, bitrate: '', window: '', zerocopy: false },
  },
  {
    key: 'max',
    title: 'Max throughput',
    desc: 'TCP · 8 streams · 20 s · zero-copy',
    icon: <RocketOutlined />,
    opts: { protocol: 'tcp', parallel: 8, duration: 20, omit: 2, interval: 0.5, bitrate: '', window: '', zerocopy: true },
  },
  {
    key: 'udp',
    title: 'Call quality',
    desc: 'UDP · 50 Mbit/s · jitter & loss',
    icon: <SoundOutlined />,
    opts: { protocol: 'udp', parallel: 1, duration: 10, omit: 1, interval: 0.5, bitrate: '50M', window: '', zerocopy: false },
  },
]

const PUBLIC_SERVERS = [
  { host: 'iperf.he.net', port: 5201, note: 'Hurricane Electric · Fremont, US' },
  { host: 'ping.online.net', port: 5201, note: 'Scaleway · Paris, FR (5200–5209)' },
  { host: 'iperf3.moji.fr', port: 5201, note: 'Moji · Paris, FR (5200–5240)' },
  { host: 'speedtest.wtnet.de', port: 5201, note: 'wilhelm.tel · Hamburg, DE (5200–5209)' },
  { host: 'speedtest.serverius.net', port: 5002, note: 'Serverius · NL (port 5002)' },
]

const CLIENT_OPTS_KEY = 'lnxadmin_iperf_client_opts'
const RECENT_KEY = 'lnxadmin_iperf_recent'

function matchPreset(o: ClientOpts): PresetKey {
  for (const p of PRESETS) {
    const ok = Object.entries(p.opts).every(([k, v]) => (o as Record<string, unknown>)[k] === v)
    if (ok && o.direction && !o.length && o.mss == null && !o.congestion && !o.no_delay && o.ip_version == null && !o.bind && o.tos == null) {
      return p.key
    }
  }
  return 'custom'
}

function buildCommand(o: ClientOpts): string {
  const a = ['iperf3', '-c', o.host || '<host>', '-p', String(o.port), '-t', String(o.duration), '-P', String(o.parallel), '-i', String(o.interval)]
  if (o.omit) a.push('-O', String(o.omit))
  if (o.direction === 'download') a.push('-R')
  if (o.direction === 'bidir') a.push('--bidir')
  if (o.protocol === 'udp') a.push('-u', '-b', o.bitrate || '100M')
  else if (o.bitrate) a.push('-b', o.bitrate)
  if (o.window) a.push('-w', o.window)
  if (o.length) a.push('-l', o.length)
  if (o.mss && o.protocol === 'tcp') a.push('-M', String(o.mss))
  if (o.congestion && o.protocol === 'tcp') a.push('-C', o.congestion)
  if (o.no_delay && o.protocol === 'tcp') a.push('-N')
  if (o.zerocopy) a.push('-Z')
  if (o.ip_version === 4) a.push('-4')
  if (o.ip_version === 6) a.push('-6')
  if (o.bind) a.push('-B', o.bind)
  if (o.tos != null) a.push('-S', String(o.tos))
  return a.join(' ')
}

function copy(text: string) {
  void navigator.clipboard?.writeText(text).then(
    () => message.success('Copied'),
    () => message.error('Clipboard is not available'),
  )
}

// ── Live stats from interval samples ──────────────────

type LiveStats = {
  current: number
  avg: number
  peak: number
  tx?: number
  rx?: number
  retr: number
  lost: number
  packets: number
  jitter?: number
  bytes: number
  streams: Array<{ id: string; bps: number; retr?: number | null }>
  series: Array<Record<string, number | string>>
  elapsed: number
}

function liveStats(samples: JobSample[], session?: number): LiveStats {
  const iv = samples.filter((s) => s.kind === 'interval' && (session == null || s.session === session))
  const valid = iv.filter((s) => !s.omitted)
  const last = iv[iv.length - 1]
  const totals = valid.map((s) => (s.bps as number) || 0)
  const t0 = iv.length ? iv[0].t : 0
  return {
    current: last ? (last.bps as number) || 0 : 0,
    tx: last?.tx_bps,
    rx: last?.rx_bps,
    avg: totals.length ? totals.reduce((a, b) => a + b, 0) / totals.length : 0,
    peak: totals.length ? Math.max(...totals) : 0,
    retr: valid.reduce((a, s) => a + ((s.retr ?? 0) + (s.tx_retr ?? 0) + (s.rx_retr ?? 0)), 0),
    lost: valid.reduce((a, s) => a + ((s.lost ?? 0) + (s.rx_lost ?? 0)), 0),
    packets: valid.reduce((a, s) => a + ((s.packets ?? 0) + (s.rx_packets ?? 0)), 0),
    jitter: last?.jitter_ms ?? last?.rx_jitter_ms,
    bytes: valid.reduce((a, s) => a + ((s.bytes ?? 0) || (s.tx_bytes ?? 0) + (s.rx_bytes ?? 0)), 0),
    streams: (last?.streams as LiveStats['streams']) || [...(last?.tx_streams || []), ...(last?.rx_streams || [])],
    series: iv.map((s) => ({
      t: `${(s.t - t0).toFixed(1)}s`,
      ...(s.tx_bps != null || s.rx_bps != null
        ? { tx: (s.tx_bps ?? 0) / 1e6, rx: (s.rx_bps ?? 0) / 1e6 }
        : { bps: ((s.bps as number) || 0) / 1e6 }),
    })),
    elapsed: last ? (last.t as number) - t0 : 0,
  }
}

// ── Install hero ─────────────────────────────────────

function InstallHero({ info, onInstalled }: { info: SpeedInfo; onInstalled: () => void }) {
  const [busy, setBusy] = useState(false)
  const [log, setLog] = useState<string | null>(null)
  const allowed = info.can_run && info.options?.allow_install !== false
  const install = async () => {
    setBusy(true)
    setLog(null)
    try {
      const res = await api<{ ok: boolean; error?: string; log?: string }>('/api/speedtest/iperf/install', { method: 'POST', body: '{}' })
      setLog(res.log || null)
      if (res.ok) {
        message.success('iperf3 installed')
        onInstalled()
      } else {
        message.error(res.error || 'Install failed')
      }
    } catch (e) {
      message.error(String(e))
    } finally {
      setBusy(false)
    }
  }
  const cmd: Record<string, string> = {
    'apt-get': 'apt-get install -y iperf3',
    dnf: 'dnf install -y iperf3',
    yum: 'yum install -y iperf3',
    apk: 'apk add iperf3',
    pacman: 'pacman -S iperf3',
    zypper: 'zypper install iperf',
  }
  return (
    <Panel className="stg-install">
      <div className="stg-install-art">
        <ExperimentOutlined />
      </div>
      <h2 className="display">iperf3 is not installed</h2>
      <p>
        iperf3 measures raw TCP/UDP throughput between two hosts. Install it once to run this host as a client <b>or</b> a server, with live
        charts for every stream.
      </p>
      <div className="stg-install-meta">
        <Tag>package manager: {info.tools.pkg_manager || 'not detected'}</Tag>
        {info.tools.pkg_manager ? <code className="mono">{cmd[info.tools.pkg_manager]}</code> : null}
      </div>
      <Tooltip
        title={
          !info.can_run
            ? 'Requires Speedtest “full” permission'
            : info.options?.allow_install === false
              ? 'Enable “Allow package install” in Settings → Modules → Speedtest'
              : undefined
        }
      >
        <Button type="primary" size="large" shape="round" icon={<CloudDownloadOutlined />} loading={busy} disabled={!allowed || !info.tools.pkg_manager} onClick={() => void install()}>
          {busy ? 'Installing…' : 'Install iperf3 and continue'}
        </Button>
      </Tooltip>
      {log ? <pre className="la-log stg-install-log">{log}</pre> : null}
    </Panel>
  )
}

// ── Client ───────────────────────────────────────────

function IperfClient({ info, unit }: { info: SpeedInfo; unit: RateUnit }) {
  const [opts, setOpts] = useState<ClientOpts>(() => {
    try {
      return { ...DEFAULT_CLIENT, ...JSON.parse(localStorage.getItem(CLIENT_OPTS_KEY) || '{}') }
    } catch {
      return DEFAULT_CLIENT
    }
  })
  const [recent, setRecent] = useState<Array<{ host: string; port: number }>>(() => {
    try {
      return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]')
    } catch {
      return []
    }
  })
  const existing = info.jobs.find((j) => j.kind === 'iperf_client')
  const [jobId, setJobId] = useState<string | null>(existing?.id ?? null)
  const [starting, setStarting] = useState(false)
  const { job, stop } = useJob(jobId, 350)
  const running = isActive(job) || starting
  const preset = matchPreset(opts)
  const set = (patch: Partial<ClientOpts>) => setOpts((o) => ({ ...o, ...patch }))

  useEffect(() => localStorage.setItem(CLIENT_OPTS_KEY, JSON.stringify(opts)), [opts])

  const start = async () => {
    if (!opts.host.trim()) {
      message.warning('Enter the iperf3 server host')
      return
    }
    setStarting(true)
    try {
      const body = {
        ...opts,
        host: opts.host.trim(),
        bitrate: opts.bitrate || (opts.protocol === 'udp' ? '100M' : null),
        window: opts.window || null,
        length: opts.length || null,
        congestion: opts.congestion || null,
        bind: opts.bind || null,
      }
      const snap = await api<{ id: string }>('/api/speedtest/iperf/client', { method: 'POST', body: JSON.stringify(body) })
      setJobId(snap.id)
      const next = [{ host: body.host, port: opts.port }, ...recent.filter((r) => !(r.host === body.host && r.port === opts.port))].slice(0, 8)
      setRecent(next)
      localStorage.setItem(RECENT_KEY, JSON.stringify(next))
    } catch (e) {
      let msg = String(e)
      try {
        const j = JSON.parse(String(e).replace(/^Error:\s*/, ''))
        msg = Array.isArray(j.detail) ? j.detail.map((d: { msg: string }) => d.msg).join('; ') : j.detail || msg
      } catch {
        /* keep raw */
      }
      message.error(msg)
    } finally {
      setStarting(false)
    }
  }

  useEffect(() => {
    if (job && job.status === 'error' && job.error) message.error(job.error)
    // only when the job ends
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status])

  const hostOptions = useMemo(
    () => [
      ...(recent.length
        ? [
            {
              label: 'Recent',
              options: recent.map((r) => ({ value: `${r.host}:${r.port}`, label: <span className="mono">{`${r.host}:${r.port}`}</span> })),
            },
          ]
        : []),
      {
        label: 'Public iperf3 servers (may be busy)',
        options: PUBLIC_SERVERS.map((s) => ({
          value: `${s.host}:${s.port}`,
          label: (
            <div className="stg-ac-item">
              <span className="mono">{s.host}</span>
              <small>{s.note}</small>
            </div>
          ),
        })),
      },
    ],
    [recent],
  )

  const onHostChange = (v: string) => {
    const m = /^(.+):(\d{2,5})$/.exec(v)
    if (m && !m[1].includes(':')) set({ host: m[1], port: Number(m[2]) })
    else set({ host: v })
  }

  const stats = useMemo(() => liveStats(job?.samples || []), [job?.samples])
  const bidir = (job?.params?.direction ?? opts.direction) === 'bidir'
  const udp = (job?.params?.protocol ?? opts.protocol) === 'udp'
  const dirColor = (job?.params?.direction ?? opts.direction) === 'download' ? PHASE_COLORS.download : PHASE_COLORS.upload
  const scale = pickScale(Math.max(1, toUnit(Math.max(stats.peak, stats.current), unit)))
  const progress = job && running ? Math.min(1, stats.elapsed / (Number(job.params.duration) + Number(job.params.omit || 0))) : 0

  return (
    <Row gutter={[20, 20]}>
      <Col xs={24} xl={10}>
        <Panel title="Client" extra={<Tag color="blue">iperf3 -c</Tag>}>
          <div className="stg-form">
            <label className="stg-label">Server</label>
            <div className="stg-host-row">
              <AutoComplete
                value={opts.host}
                options={hostOptions}
                onChange={onHostChange}
                onSelect={(v: string) => onHostChange(v)}
                disabled={running}
                style={{ flex: 1 }}
                filterOption={(input, option) => String((option as { value?: string } | undefined)?.value ?? '').toLowerCase().includes(input.toLowerCase())}
              >
                <Input size="large" placeholder="10.0.0.5 or iperf.example.com" prefix={<ApiOutlined />} className="mono" />
              </AutoComplete>
              <InputNumber size="large" min={1} max={65535} value={opts.port} onChange={(v) => set({ port: Number(v) || 5201 })} disabled={running} style={{ width: 110 }} />
            </div>

            <label className="stg-label">Profile</label>
            <div className="stg-presets">
              {PRESETS.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  disabled={running}
                  className={`stg-preset${preset === p.key ? ' is-active' : ''}`}
                  onClick={() => set(p.opts)}
                >
                  <span className="stg-preset-icon">{p.icon}</span>
                  <span className="stg-preset-title">{p.title}</span>
                  <span className="stg-preset-desc">{p.desc}</span>
                </button>
              ))}
            </div>
            {preset === 'custom' ? <div className="stg-custom-note">Custom settings</div> : null}

            <Row gutter={12}>
              <Col span={10}>
                <label className="stg-label">Protocol</label>
                <Segmented
                  block
                  disabled={running}
                  value={opts.protocol}
                  onChange={(v) => set({ protocol: v as 'tcp' | 'udp', bitrate: v === 'udp' ? opts.bitrate || '100M' : '' })}
                  options={[
                    { label: 'TCP', value: 'tcp' },
                    { label: 'UDP', value: 'udp' },
                  ]}
                />
              </Col>
              <Col span={14}>
                <label className="stg-label">Direction</label>
                <Segmented
                  block
                  disabled={running}
                  value={opts.direction}
                  onChange={(v) => set({ direction: v as ClientOpts['direction'] })}
                  options={[
                    { label: <Tooltip title="This host sends (client → server)"><ArrowUpOutlined /> Up</Tooltip>, value: 'upload' },
                    { label: <Tooltip title="Server sends (-R)"><ArrowDownOutlined /> Down</Tooltip>, value: 'download' },
                    { label: <Tooltip title="Both at once (--bidir)"><SwapOutlined /> Both</Tooltip>, value: 'bidir' },
                  ]}
                />
              </Col>
            </Row>

            <label className="stg-label">
              Duration <b className="mono">{opts.duration} s</b>
            </label>
            <Slider
              disabled={running}
              min={1}
              max={Number(info.options?.max_duration_seconds || 60)}
              value={opts.duration}
              onChange={(v) => set({ duration: v })}
              marks={{ 5: '5', 10: '10', 30: '30' }}
            />
            <label className="stg-label">
              Parallel streams <b className="mono">{opts.parallel}</b>
            </label>
            <Slider
              disabled={running}
              min={1}
              max={Math.min(32, Number(info.options?.max_parallel || 32))}
              value={opts.parallel}
              onChange={(v) => set({ parallel: v })}
              marks={{ 1: '1', 4: '4', 8: '8', 16: '16' }}
            />
            {opts.protocol === 'udp' ? (
              <>
                <label className="stg-label">Target bitrate</label>
                <Input
                  disabled={running}
                  className="mono"
                  value={opts.bitrate}
                  placeholder="100M"
                  onChange={(e) => set({ bitrate: e.target.value })}
                  addonAfter="bit/s"
                />
              </>
            ) : null}

            <Collapse
              ghost
              className="stg-advanced"
              items={[
                {
                  key: 'adv',
                  label: 'Advanced options',
                  children: (
                    <div className="stg-adv-grid">
                      <div>
                        <label className="stg-label">Report interval (s)</label>
                        <InputNumber disabled={running} min={0.1} max={10} step={0.1} value={opts.interval} onChange={(v) => set({ interval: Number(v) || 0.5 })} style={{ width: '100%' }} />
                      </div>
                      <div>
                        <label className="stg-label">Omit first (s)</label>
                        <InputNumber disabled={running} min={0} max={30} value={opts.omit} onChange={(v) => set({ omit: Number(v) || 0 })} style={{ width: '100%' }} />
                      </div>
                      {opts.protocol === 'tcp' ? (
                        <div>
                          <label className="stg-label">Bitrate cap</label>
                          <Input disabled={running} className="mono" placeholder="unlimited" value={opts.bitrate} onChange={(e) => set({ bitrate: e.target.value })} />
                        </div>
                      ) : null}
                      <div>
                        <label className="stg-label">Window (-w)</label>
                        <Input disabled={running} className="mono" placeholder="auto (e.g. 4M)" value={opts.window} onChange={(e) => set({ window: e.target.value })} />
                      </div>
                      <div>
                        <label className="stg-label">Buffer length (-l)</label>
                        <Input disabled={running} className="mono" placeholder={opts.protocol === 'udp' ? 'auto (≈1460)' : '128K'} value={opts.length} onChange={(e) => set({ length: e.target.value })} />
                      </div>
                      {opts.protocol === 'tcp' ? (
                        <>
                          <div>
                            <label className="stg-label">MSS (-M)</label>
                            <InputNumber disabled={running} min={88} max={9216} placeholder="auto" value={opts.mss ?? undefined} onChange={(v) => set({ mss: v == null ? null : Number(v) })} style={{ width: '100%' }} />
                          </div>
                          <div>
                            <label className="stg-label">Congestion control</label>
                            <Select
                              disabled={running}
                              value={opts.congestion}
                              onChange={(v) => set({ congestion: v })}
                              options={[
                                { value: '', label: `system (${info.congestion.current || 'default'})` },
                                ...info.congestion.available.map((c) => ({ value: c, label: c })),
                              ]}
                            />
                          </div>
                        </>
                      ) : null}
                      <div>
                        <label className="stg-label">IP version</label>
                        <Segmented
                          block
                          disabled={running}
                          value={opts.ip_version ?? 0}
                          onChange={(v) => set({ ip_version: v === 0 ? null : (v as 4 | 6) })}
                          options={[
                            { label: 'Auto', value: 0 },
                            { label: 'IPv4', value: 4 },
                            { label: 'IPv6', value: 6 },
                          ]}
                        />
                      </div>
                      <div>
                        <label className="stg-label">Bind address (-B)</label>
                        <Select
                          disabled={running}
                          allowClear
                          placeholder="any"
                          value={opts.bind || undefined}
                          onChange={(v) => set({ bind: v || '' })}
                          options={info.addresses.map((a) => ({ value: a.ip, label: `${a.ip} · ${a.iface}` }))}
                        />
                      </div>
                      <div>
                        <label className="stg-label">TOS / DSCP (-S)</label>
                        <Select
                          disabled={running}
                          allowClear
                          placeholder="default"
                          value={opts.tos ?? undefined}
                          onChange={(v) => set({ tos: v ?? null })}
                          options={[
                            { value: 0xb8, label: 'EF (voice) · 0xB8' },
                            { value: 0x88, label: 'AF41 (video) · 0x88' },
                            { value: 0x48, label: 'AF21 · 0x48' },
                            { value: 0x20, label: 'CS1 (bulk) · 0x20' },
                          ]}
                        />
                      </div>
                      <div>
                        <label className="stg-label">Connect timeout (ms)</label>
                        <InputNumber disabled={running} min={100} max={120000} step={500} value={opts.connect_timeout_ms} onChange={(v) => set({ connect_timeout_ms: Number(v) || 5000 })} style={{ width: '100%' }} />
                      </div>
                      <div className="stg-switches">
                        {opts.protocol === 'tcp' ? (
                          <span>
                            <Switch size="small" disabled={running} checked={opts.no_delay} onChange={(v) => set({ no_delay: v })} /> No delay (-N)
                          </span>
                        ) : null}
                        <span>
                          <Switch size="small" disabled={running} checked={opts.zerocopy} onChange={(v) => set({ zerocopy: v })} /> Zero-copy (-Z)
                        </span>
                      </div>
                      <Button size="small" type="link" disabled={running} onClick={() => setOpts({ ...DEFAULT_CLIENT, host: opts.host, port: opts.port })} style={{ padding: 0 }}>
                        Reset to optimal defaults
                      </Button>
                    </div>
                  ),
                },
              ]}
            />

            <div className="stg-cmd">
              <code className="mono">{buildCommand(opts)}</code>
              <Button size="small" type="text" icon={<CopyOutlined />} onClick={() => copy(buildCommand(opts))} />
            </div>

            {running ? (
              <Button block size="large" danger icon={<StopOutlined />} onClick={() => void stop()}>
                Stop test
              </Button>
            ) : (
              <Button
                block
                size="large"
                type="primary"
                className="stg-start-btn"
                icon={<PlayCircleOutlined />}
                loading={starting}
                disabled={!info.can_run}
                onClick={() => void start()}
              >
                Start test
              </Button>
            )}
          </div>
        </Panel>
      </Col>

      <Col xs={24} xl={14}>
        <IperfLive
          job={job}
          stats={stats}
          unit={unit}
          scale={scale}
          bidir={bidir}
          udp={udp}
          color={dirColor}
          progress={progress}
          running={running}
          emptyText="Pick a server and press Start — throughput, streams and retransmits stream in live."
        />
      </Col>
    </Row>
  )
}

// ── Shared live view ─────────────────────────────────

function IperfLive({
  job,
  stats,
  unit,
  scale,
  bidir,
  udp,
  color,
  progress,
  running,
  emptyText,
  serverMode,
}: {
  job: JobState | null
  stats: LiveStats
  unit: RateUnit
  scale: number[]
  bidir: boolean
  udp: boolean
  color: { from: string; to: string; solid: string }
  progress: number
  running: boolean
  emptyText: string
  serverMode?: boolean
}) {
  const result = job?.result || {}
  const hasData = stats.series.length > 0
  const status = job?.status
  const phaseKey = color === PHASE_COLORS.download ? 'download' : 'upload'
  return (
    <div className="stg-stack">
      <Panel padded={false} className="stg-hero stg-hero-compact">
        <div className="stg-hero-aurora" data-phase={phaseKey} />
        <div className="stg-live-head">
          <div className="stg-live-status">
            {job ? (
              <Badge
                status={running ? 'processing' : status === 'done' ? 'success' : status === 'error' ? 'error' : 'default'}
                text={
                  <span className="stg-live-status-text">
                    {running ? (job.phase === 'connect' ? 'Connecting…' : serverMode ? job.phase : 'Running') : status}
                    {job.params?.host ? <span className="mono"> · {job.params.host}:{job.params.port}</span> : null}
                  </span>
                }
              />
            ) : (
              <span className="stg-muted">Idle</span>
            )}
          </div>
          {running && !serverMode ? <ProgressBar value={progress} phase={phaseKey} /> : null}
        </div>
        <div className="stg-live-gauge">
          <SpeedGauge
            value={hasData ? toUnit(running ? stats.current : stats.avg, unit) : null}
            scale={scale}
            unit={unitLabel(unit)}
            phase={phaseKey}
            active={running}
            size={360}
            label={running ? 'current' : hasData ? 'average' : undefined}
            sublabel={
              bidir && hasData
                ? `↑ ${fmtSpeedNum(toUnit(stats.tx, unit))}  ·  ↓ ${fmtSpeedNum(toUnit(stats.rx, unit))} ${unitLabel(unit)}`
                : undefined
            }
          />
        </div>
      </Panel>

      <div className="stg-tiles stg-tiles-5">
        <MetricTile icon={<DashboardOutlined />} label="Average" value={hasData ? fmtSpeedNum(toUnit(stats.avg, unit)) : '—'} unit={unitLabel(unit)} color={color.solid} done={hasData} />
        <MetricTile icon={<RocketOutlined />} label="Peak" value={hasData ? fmtSpeedNum(toUnit(stats.peak, unit)) : '—'} unit={unitLabel(unit)} color={color.solid} done={hasData} />
        {udp ? (
          <>
            <MetricTile icon={<WifiOutlined />} label="Jitter" value={fmtMs(result.receiver?.jitter_ms ?? stats.jitter)} unit="ms" color="#f59e0b" done={hasData} />
            <MetricTile
              icon={<ExperimentOutlined />}
              label="Loss"
              value={
                result.receiver?.loss_pct != null
                  ? result.receiver.loss_pct.toFixed(2)
                  : stats.packets
                    ? ((100 * stats.lost) / stats.packets).toFixed(2)
                    : '—'
              }
              unit="%"
              color="#ef4444"
              done={hasData}
              sub={stats.packets ? `${stats.lost}/${stats.packets} datagrams` : undefined}
            />
          </>
        ) : (
          <MetricTile
            icon={<ExperimentOutlined />}
            label="Retransmits"
            value={hasData ? String(result.sender?.retr ?? result.tx_sender?.retr ?? stats.retr) : '—'}
            color={stats.retr > 0 ? '#f59e0b' : '#10b981'}
            done={hasData}
            sub="TCP segments resent"
          />
        )}
        <MetricTile icon={<CloudDownloadOutlined />} label="Transferred" value={hasData ? fmtBytesShort(result.receiver?.bytes ?? stats.bytes) : '—'} color="#38bdf8" done={hasData} />
      </div>

      <Panel
        title="Throughput"
        extra={
          stats.streams.length > 1 ? <Tag>{stats.streams.length} streams</Tag> : null
        }
      >
        {hasData ? (
          <>
            <PremiumAreaChart
              data={stats.series}
              xKey="t"
              height={220}
              series={
                bidir
                  ? [
                      { key: 'tx', label: 'Send ↑', color: PHASE_COLORS.upload.solid, formatValue: (v) => fmtBitsAuto(v * 1e6) },
                      { key: 'rx', label: 'Receive ↓', color: PHASE_COLORS.download.solid, formatValue: (v) => fmtBitsAuto(v * 1e6) },
                    ]
                  : [{ key: 'bps', label: 'Throughput', color: color.solid, formatValue: (v) => fmtBitsAuto(v * 1e6) }]
              }
              yFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}G` : `${Math.round(v)}M`)}
            />
            {stats.streams.length > 1 ? (
              <div style={{ marginTop: 14 }}>
                <div className="la-panel-title" style={{ marginBottom: 8 }}>
                  Streams (latest interval)
                </div>
                <StreamBars streams={stats.streams} max={Math.max(...stats.streams.map((s) => s.bps))} color={`linear-gradient(90deg, ${color.from}, ${color.to})`} />
              </div>
            ) : null}
          </>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />
        )}
      </Panel>

      {!serverMode && job && !running && (result.sender || result.receiver || result.tx_sender) ? <SummaryCard result={result} unit={unit} /> : null}

      {job ? (
        <Collapse
          className="stg-raw"
          items={[
            {
              key: 'raw',
              label: (
                <span>
                  Raw iperf3 output <Typography.Text type="secondary">({job.log.length} lines)</Typography.Text>
                </span>
              ),
              children: <pre className="la-log stg-raw-log">{job.log.join('\n') || '—'}</pre>,
            },
          ]}
        />
      ) : null}
    </div>
  )
}

function SummaryCard({ result, unit }: { result: Record<string, any>; unit: RateUnit }) {
  const rows = [
    ['sender', 'Sender'],
    ['receiver', 'Receiver'],
    ['tx_sender', 'Send ↑ · sender'],
    ['tx_receiver', 'Send ↑ · receiver'],
    ['rx_sender', 'Receive ↓ · sender'],
    ['rx_receiver', 'Receive ↓ · receiver'],
  ]
    .filter(([k]) => result[k])
    .map(([k, label]) => ({ key: k, label, ...result[k] }))
  return (
    <Panel title="Summary">
      <Table
        size="small"
        pagination={false}
        rowKey="key"
        dataSource={rows}
        columns={[
          { title: 'Side', dataIndex: 'label' },
          { title: 'Bitrate', dataIndex: 'bps', render: (v: number) => <b className="mono">{`${fmtSpeedNum(toUnit(v, unit))} ${unitLabel(unit)}`}</b> },
          { title: 'Transferred', dataIndex: 'bytes', render: (v: number) => <span className="mono">{fmtBytesShort(v)}</span> },
          { title: 'Time', dataIndex: 'seconds', render: (v: number) => <span className="mono">{v} s</span> },
          {
            title: 'Retr / Jitter / Loss',
            key: 'q',
            render: (_: unknown, r: Record<string, any>) =>
              r.jitter_ms != null ? (
                <span className="mono">
                  {fmtMs(r.jitter_ms)} ms · {r.loss_pct ?? 0}% ({r.lost}/{r.packets})
                </span>
              ) : r.retr != null ? (
                <span className="mono">{r.retr} retr</span>
              ) : (
                '—'
              ),
          },
        ]}
      />
      {result.cpu_local != null ? (
        <div className="stg-cpu">
          <span>CPU local</span>
          <div className="stg-cpu-bar">
            <div style={{ width: `${Math.min(100, result.cpu_local)}%` }} />
          </div>
          <b className="mono">{result.cpu_local}%</b>
          <span>CPU remote</span>
          <div className="stg-cpu-bar">
            <div style={{ width: `${Math.min(100, result.cpu_remote)}%` }} />
          </div>
          <b className="mono">{result.cpu_remote}%</b>
        </div>
      ) : null}
    </Panel>
  )
}

// ── Server ───────────────────────────────────────────

type ServerOpts = { port: number; bind: string; interval: number; one_off: boolean; ip_version: 4 | 6 | null; idle_timeout: number | null; max_lifetime: number }
const DEFAULT_SERVER: ServerOpts = { port: 5201, bind: '', interval: 0.5, one_off: false, ip_version: null, idle_timeout: null, max_lifetime: 3600 }

function IperfServer({ info, unit }: { info: SpeedInfo; unit: RateUnit }) {
  const [opts, setOpts] = useState<ServerOpts>(DEFAULT_SERVER)
  const [servers, setServers] = useState(info.jobs.filter((j) => j.kind === 'iperf_server'))
  const [selected, setSelected] = useState<string | null>(servers[0]?.id ?? null)
  const [busy, setBusy] = useState(false)
  const { job, stop } = useJob(selected, 450)
  const set = (p: Partial<ServerOpts>) => setOpts((o) => ({ ...o, ...p }))

  const refresh = useCallback(async () => {
    try {
      const res = await api<{ jobs: SpeedInfo['jobs'] }>('/api/speedtest/jobs')
      const active = res.jobs.filter((j) => j.kind === 'iperf_server' && isActive(j))
      setServers(active)
      setSelected((cur) => (cur && res.jobs.some((j) => j.id === cur) ? cur : active[0]?.id ?? null))
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    const t = setInterval(() => void refresh(), 3000)
    return () => clearInterval(t)
  }, [refresh])

  const startServer = async () => {
    setBusy(true)
    try {
      const snap = await api<{ id: string }>('/api/speedtest/iperf/server', {
        method: 'POST',
        body: JSON.stringify({ ...opts, bind: opts.bind || null, idle_timeout: opts.idle_timeout || null }),
      })
      setSelected(snap.id)
      await refresh()
      message.success(`iperf3 server listening on :${opts.port}`)
    } catch (e) {
      message.error(String(e))
    } finally {
      setBusy(false)
    }
  }

  const running = isActive(job)
  const sessions: Array<Record<string, any>> = job?.meta?.sessions || []
  const lastSession = useMemo(() => {
    const ivs = (job?.samples || []).filter((s) => s.kind === 'interval')
    return ivs.length ? (ivs[ivs.length - 1].session as number) : undefined
  }, [job?.samples])
  const stats = useMemo(() => liveStats(job?.samples || [], lastSession), [job?.samples, lastSession])
  const scale = pickScale(Math.max(1, toUnit(Math.max(stats.peak, stats.current), unit)))
  const client = job?.meta?.current_client as string | null | undefined
  const port = job?.params?.port ?? opts.port
  const addrs = info.addresses.filter((a) => !job?.params?.bind || a.ip === job.params.bind)

  return (
    <Row gutter={[20, 20]}>
      <Col xs={24} xl={10}>
        <div className="stg-stack">
          <Panel title="Server" extra={<Tag color="purple">iperf3 -s</Tag>}>
            <div className="stg-form">
              <Row gutter={12}>
                <Col span={10}>
                  <label className="stg-label">Port</label>
                  <InputNumber size="large" min={1} max={65535} value={opts.port} onChange={(v) => set({ port: Number(v) || 5201 })} style={{ width: '100%' }} />
                </Col>
                <Col span={14}>
                  <label className="stg-label">Listen on</label>
                  <Select
                    size="large"
                    allowClear
                    placeholder="all addresses"
                    value={opts.bind || undefined}
                    onChange={(v) => set({ bind: v || '' })}
                    options={info.addresses.map((a) => ({ value: a.ip, label: `${a.ip} · ${a.iface}` }))}
                    style={{ width: '100%' }}
                  />
                </Col>
              </Row>
              <Collapse
                ghost
                className="stg-advanced"
                items={[
                  {
                    key: 'adv',
                    label: 'Advanced options',
                    children: (
                      <div className="stg-adv-grid">
                        <div>
                          <label className="stg-label">Report interval (s)</label>
                          <InputNumber min={0.1} max={10} step={0.1} value={opts.interval} onChange={(v) => set({ interval: Number(v) || 0.5 })} style={{ width: '100%' }} />
                        </div>
                        <div>
                          <label className="stg-label">Auto-stop after (s)</label>
                          <InputNumber min={0} max={604800} step={600} value={opts.max_lifetime} onChange={(v) => set({ max_lifetime: Number(v) || 0 })} style={{ width: '100%' }} />
                        </div>
                        <div>
                          <label className="stg-label">Idle timeout (s)</label>
                          <InputNumber min={1} max={86400} placeholder="none" value={opts.idle_timeout ?? undefined} onChange={(v) => set({ idle_timeout: v == null ? null : Number(v) })} style={{ width: '100%' }} />
                        </div>
                        <div>
                          <label className="stg-label">IP version</label>
                          <Segmented
                            block
                            value={opts.ip_version ?? 0}
                            onChange={(v) => set({ ip_version: v === 0 ? null : (v as 4 | 6) })}
                            options={[
                              { label: 'Auto', value: 0 },
                              { label: 'IPv4', value: 4 },
                              { label: 'IPv6', value: 6 },
                            ]}
                          />
                        </div>
                        <div className="stg-switches">
                          <span>
                            <Switch size="small" checked={opts.one_off} onChange={(v) => set({ one_off: v })} /> One test, then exit (-1)
                          </span>
                        </div>
                      </div>
                    ),
                  },
                ]}
              />
              <Button
                block
                size="large"
                type="primary"
                className="stg-start-btn is-server"
                icon={<PoweroffOutlined />}
                loading={busy}
                disabled={!info.can_run}
                onClick={() => void startServer()}
              >
                Start server on :{opts.port}
              </Button>
              <Alert
                type="info"
                showIcon
                message="Open the port in the firewall"
                description={`Clients need TCP and UDP ${opts.port} reachable on this host (Firewall module).`}
              />
            </div>
          </Panel>

          {servers.length ? (
            <Panel title="Running servers">
              <div className="stg-servers">
                {servers.map((s) => (
                  <div key={s.id} className={`stg-server${selected === s.id ? ' is-active' : ''}`} onClick={() => setSelected(s.id)}>
                    <span className="la-live-dot" />
                    <span className="mono">:{s.params.port}</span>
                    <span className="stg-muted">{s.params.bind || 'all addresses'}</span>
                    <Button
                      size="small"
                      danger
                      type="text"
                      icon={<StopOutlined />}
                      onClick={async (e) => {
                        e.stopPropagation()
                        await api(`/api/speedtest/jobs/${s.id}/stop`, { method: 'POST', body: '{}' }).catch(() => {})
                        await refresh()
                      }}
                    >
                      Stop
                    </Button>
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
        </div>
      </Col>

      <Col xs={24} xl={14}>
        {job ? (
          <div className="stg-stack">
            <Panel className="stg-listen">
              <div className="stg-listen-head">
                <div className={`stg-radar${running ? ' is-on' : ''}`}>
                  <span />
                  <span />
                  <WifiOutlined />
                </div>
                <div style={{ flex: 1 }}>
                  <div className="stg-listen-title">
                    {running ? (client ? `Receiving test from ${client}` : `Listening on :${port}`) : `Server ${job.status}`}
                  </div>
                  <div className="stg-muted">
                    {sessions.length} completed test{sessions.length === 1 ? '' : 's'} · started by {job.owner}
                  </div>
                </div>
                {running ? (
                  <Button danger icon={<StopOutlined />} onClick={() => void stop().then(refresh)}>
                    Stop
                  </Button>
                ) : null}
              </div>
              {running ? (
                <div className="stg-connect-cmds">
                  <div className="la-panel-title" style={{ marginBottom: 6 }}>
                    Run on the other host
                  </div>
                  {addrs.slice(0, 4).map((a) => {
                    const cmd = `iperf3 -c ${a.ip} -p ${port} -P 4 -t 10`
                    return (
                      <div key={a.ip} className="stg-cmd">
                        <code className="mono">{cmd}</code>
                        <Tag>{a.iface}</Tag>
                        <Button size="small" type="text" icon={<CopyOutlined />} onClick={() => copy(cmd)} />
                      </div>
                    )
                  })}
                </div>
              ) : null}
            </Panel>
            <IperfLive
              job={job}
              stats={stats}
              unit={unit}
              scale={scale}
              bidir={stats.tx != null || stats.rx != null}
              udp={false}
              color={PHASE_COLORS.download}
              progress={0}
              running={running && !!client}
              emptyText="Waiting for a client to connect…"
              serverMode
            />
            {sessions.length ? (
              <Panel title="Completed tests">
                <Table
                  size="small"
                  rowKey="session"
                  pagination={{ pageSize: 8, hideOnSinglePage: true }}
                  dataSource={sessions}
                  columns={[
                    { title: 'When', dataIndex: 'at', render: (v: number) => new Date(v * 1000).toLocaleTimeString() },
                    { title: 'Client', dataIndex: 'client', render: (v: string) => <span className="mono">{v || '—'}</span> },
                    {
                      title: 'Received',
                      key: 'rx',
                      render: (_: unknown, r: Record<string, any>) => {
                        const b = r.receiver || r.rx_receiver
                        return b ? <b className="mono">{`${fmtSpeedNum(toUnit(b.bps, unit))} ${unitLabel(unit)}`}</b> : '—'
                      },
                    },
                    {
                      title: 'Sent',
                      key: 'tx',
                      render: (_: unknown, r: Record<string, any>) => {
                        const b = r.sender || r.tx_sender
                        return b ? <span className="mono">{`${fmtSpeedNum(toUnit(b.bps, unit))} ${unitLabel(unit)}`}</span> : '—'
                      },
                    },
                    {
                      title: 'Quality',
                      key: 'q',
                      render: (_: unknown, r: Record<string, any>) => {
                        const b = r.receiver || r.sender || {}
                        if (b.jitter_ms != null) return <span className="mono">{fmtMs(b.jitter_ms)} ms · {b.loss_pct ?? 0}%</span>
                        return <span className="mono">{fmtBytesShort(b.bytes)}</span>
                      },
                    },
                  ]}
                />
              </Panel>
            ) : null}
          </div>
        ) : (
          <Panel>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="No server running. Start one to accept iperf3 tests from other hosts — incoming tests show up here live."
            />
          </Panel>
        )}
      </Col>
    </Row>
  )
}

// ── Tab root ─────────────────────────────────────────

export function IperfPanel({ info, unit, onRefresh }: { info: SpeedInfo; unit: RateUnit; onRefresh: () => void }) {
  const [side, setSide] = useState<'client' | 'server'>(() =>
    info.jobs.some((j) => j.kind === 'iperf_server') && !info.jobs.some((j) => j.kind === 'iperf_client') ? 'server' : 'client',
  )
  if (info.options?.allow_iperf === false) {
    return <Alert type="warning" showIcon message="iperf3 is disabled" description="Enable “Allow iperf3” in Settings → Modules → Speedtest." />
  }
  if (!info.tools.iperf3) return <InstallHero info={info} onInstalled={onRefresh} />
  return (
    <div className="stg-stack">
      <div className="stg-iperf-bar">
        <Segmented
          size="large"
          value={side}
          onChange={(v) => setSide(v as 'client' | 'server')}
          options={[
            { value: 'client', label: <span className="stg-seg"><ArrowUpOutlined /> Client</span> },
            { value: 'server', label: <span className="stg-seg"><WifiOutlined /> Server</span> },
          ]}
        />
        <Space size={6} wrap>
          <Tag color="green">iperf {info.tools.iperf3_version || ''}</Tag>
          <Tag>{info.congestion.current || 'tcp'}</Tag>
          {!info.can_run ? <Tag color="orange">read-only</Tag> : null}
        </Space>
      </div>
      {side === 'client' ? <IperfClient info={info} unit={unit} /> : <IperfServer info={info} unit={unit} />}
    </div>
  )
}
