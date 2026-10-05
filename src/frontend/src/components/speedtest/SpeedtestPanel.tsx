import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Button, InputNumber, Popover, Segmented, Space, Switch, Tooltip, message } from 'antd'
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CloudOutlined,
  DashboardOutlined,
  DesktopOutlined,
  FieldTimeOutlined,
  HddOutlined,
  ReloadOutlined,
  SettingOutlined,
  StopOutlined,
  SwapOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { api } from '../../api/client'
import { Panel } from '../Panel'
import { PremiumAreaChart } from '../PremiumAreaChart'
import { SpeedGauge } from './SpeedGauge'
import { GoButton, GradeBadge, MetricTile, PhaseStepper, ProgressBar } from './StPieces'
import {
  DEFAULT_BROWSER_OPTIONS,
  runBrowserTest,
  type BrowserTestOptions,
  type BrowserUpdate,
} from '../../speedtest/browserTest'
import { useJob, isActive } from '../../speedtest/useJob'
import {
  bloatGrade,
  fmtMs,
  fmtSpeedNum,
  PHASE_COLORS,
  pickScale,
  toUnit,
  unitLabel,
  type PhaseColorKey,
  type RateUnit,
} from '../../speedtest/format'
import type { SpeedInfo } from './types'

type Mode = 'browser' | 'internet'

type View = {
  phase: string
  bps: number | null
  progress: number
  pingMs?: number
  jitterMs?: number
  downloadBps?: number
  uploadBps?: number
  loadedDownMs?: number
  loadedUpMs?: number
  latencyMs?: number
  series: Array<{ t: number; dl?: number; ul?: number }>
  error?: string
}

const EMPTY_VIEW: View = { phase: 'idle', bps: null, progress: 0, series: [] }

const STEPS = [
  { key: 'connect', label: 'Connect' },
  { key: 'ping', label: 'Latency' },
  { key: 'download', label: 'Download' },
  { key: 'upload', label: 'Upload' },
  { key: 'done', label: 'Result' },
]

const PHASE_LABEL: Record<string, string> = {
  connect: 'Connecting…',
  ping: 'Measuring latency',
  latency: 'Measuring latency',
  download: 'Download',
  upload: 'Upload',
  done: 'Complete',
}

const INTERNET_OPTS_KEY = 'lnxadmin_speed_inet_opts'
const BROWSER_OPTS_KEY = 'lnxadmin_speed_browser_opts'

type InternetOptions = { duration: number; streams: number; ip_version: 4 | 6 }
const DEFAULT_INTERNET: InternetOptions = { duration: 10, streams: 6, ip_version: 4 }

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback
  } catch {
    return fallback
  }
}

function median(xs: number[]): number | undefined {
  if (!xs.length) return undefined
  const s = [...xs].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

export function SpeedtestPanel({
  info,
  unit,
  onUnitChange,
  onFinished,
}: {
  info: SpeedInfo
  unit: RateUnit
  onUnitChange: (u: RateUnit) => void
  onFinished: () => void
}) {
  const internetAllowed = info.can_run && info.options?.allow_internet_test !== false
  // Resume a running Internet job after reload.
  const existing = info.jobs.find((j) => j.kind === 'internet')
  const [mode, setMode] = useState<Mode>(existing ? 'internet' : 'browser')
  const [view, setView] = useState<View>(EMPTY_VIEW)
  const [running, setRunning] = useState(false)
  const [maxSeen, setMaxSeen] = useState(0)
  const [bOpts, setBOpts] = useState<BrowserTestOptions>(() => loadJson(BROWSER_OPTS_KEY, DEFAULT_BROWSER_OPTIONS))
  const [iOpts, setIOpts] = useState<InternetOptions>(() => loadJson(INTERNET_OPTS_KEY, DEFAULT_INTERNET))
  const abortRef = useRef<AbortController | null>(null)
  const t0 = useRef(0)

  const [jobId, setJobId] = useState<string | null>(existing?.id ?? null)
  const { job } = useJob(mode === 'internet' ? jobId : null, 350)

  useEffect(() => localStorage.setItem(BROWSER_OPTS_KEY, JSON.stringify(bOpts)), [bOpts])
  useEffect(() => localStorage.setItem(INTERNET_OPTS_KEY, JSON.stringify(iOpts)), [iOpts])

  // ── Internet job → view ────────────────────────────
  const finishedRef = useRef<string | null>(null)
  useEffect(() => {
    if (!job || mode !== 'internet') return
    const idle = job.samples.filter((s) => s.kind === 'latency' && s.phase === 'idle').map((s) => s.ms as number)
    const loadedDl = job.samples.filter((s) => s.kind === 'latency' && s.phase === 'download').map((s) => s.ms as number)
    const loadedUl = job.samples.filter((s) => s.kind === 'latency' && s.phase === 'upload').map((s) => s.ms as number)
    const th = job.samples.filter((s) => s.kind === 'throughput')
    const last = th[th.length - 1]
    const lastDl = [...th].reverse().find((s) => s.phase === 'download')
    const lastUl = [...th].reverse().find((s) => s.phase === 'upload')
    const lastLat = [...job.samples].reverse().find((s) => s.kind === 'latency')
    const series = th.map((s) => ({
      t: Number(s.t.toFixed(2)),
      [s.phase === 'download' ? 'dl' : 'ul']: s.bps as number,
    }))
    const phase = isActive(job) ? (job.phase === 'latency' ? 'ping' : job.phase) : job.status === 'done' ? 'done' : 'idle'
    const active = isActive(job)
    setRunning(active)
    setView({
      phase,
      bps: active && (job.phase === 'download' || job.phase === 'upload') ? (last?.bps ?? 0) : null,
      progress: active ? (last && last.phase === job.phase ? last.progress : 0) : 1,
      pingMs: job.result.ping_ms ?? median(idle),
      jitterMs: job.result.jitter_ms,
      downloadBps: job.result.download?.bps ?? lastDl?.avg_bps,
      uploadBps: job.result.upload?.bps ?? lastUl?.avg_bps,
      loadedDownMs: job.result.download?.loaded_latency_ms ?? median(loadedDl),
      loadedUpMs: job.result.upload?.loaded_latency_ms ?? median(loadedUl),
      latencyMs: lastLat?.ms,
      series,
      error: job.status === 'error' ? job.error || 'Test failed' : undefined,
    })
    const peak = Math.max(0, ...th.map((s) => s.bps as number))
    setMaxSeen((m) => Math.max(m, peak))
    if (!active && finishedRef.current !== job.id) {
      finishedRef.current = job.id
      if (job.status === 'error') message.error(job.error || 'Internet speed test failed')
      if (job.status === 'done') onFinished()
    }
  }, [job, mode, onFinished])

  // ── Browser engine ─────────────────────────────────
  const startBrowser = useCallback(async () => {
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setRunning(true)
    setMaxSeen(0)
    t0.current = performance.now()
    setView({ ...EMPTY_VIEW, phase: 'connect' })
    let lastPush = 0
    const onUpdate = (u: BrowserUpdate) => {
      const now = performance.now()
      const t = (now - t0.current) / 1000
      setView((v) => {
        const series = v.series
        let nextSeries = series
        if ((u.phase === 'download' || u.phase === 'upload') && u.bps != null && now - lastPush > 240) {
          lastPush = now
          nextSeries = [...series, { t: Number(t.toFixed(2)), [u.phase === 'download' ? 'dl' : 'ul']: u.bps }]
        }
        return {
          ...v,
          phase: u.phase,
          bps: u.phase === 'download' || u.phase === 'upload' ? (u.bps ?? 0) : null,
          progress: u.progress ?? 0,
          pingMs: u.pingMs,
          jitterMs: u.jitterMs,
          downloadBps: u.phase === 'download' ? u.avgBps : u.downloadBps,
          uploadBps: u.phase === 'upload' ? u.avgBps : u.uploadBps,
          loadedDownMs: u.loadedDownMs,
          loadedUpMs: u.loadedUpMs,
          latencyMs: u.latencyMs,
          series: nextSeries,
        }
      })
      if (u.bps) setMaxSeen((m) => Math.max(m, u.bps || 0))
    }
    try {
      const res = await runBrowserTest(bOpts, onUpdate, ctrl.signal)
      await api('/api/speedtest/browser/result', {
        method: 'POST',
        body: JSON.stringify({
          ping_ms: res.pingMs,
          jitter_ms: res.jitterMs,
          download_bps: res.downloadBps,
          upload_bps: res.uploadBps,
          loaded_latency_ms: res.loadedDownMs,
          streams: bOpts.streams,
          duration: bOpts.duration,
          user_agent: navigator.userAgent.slice(0, 300),
        }),
      }).catch(() => {})
      onFinished()
    } catch (e) {
      const aborted = e instanceof DOMException && e.name === 'AbortError'
      setView((v) => ({ ...v, phase: aborted ? 'idle' : 'error', bps: null, error: aborted ? undefined : String(e) }))
      if (!aborted) message.error(`Speed test failed: ${String(e)}`)
    } finally {
      setRunning(false)
      abortRef.current = null
    }
  }, [bOpts, onFinished])

  const startInternet = useCallback(async () => {
    try {
      setMaxSeen(0)
      setView({ ...EMPTY_VIEW, phase: 'connect' })
      setRunning(true)
      const snap = await api<{ id: string }>('/api/speedtest/internet/start', {
        method: 'POST',
        body: JSON.stringify({ duration: iOpts.duration, streams: iOpts.streams, ip_version: iOpts.ip_version }),
      })
      setJobId(snap.id)
    } catch (e) {
      setRunning(false)
      setView(EMPTY_VIEW)
      message.error(String(e))
    }
  }, [iOpts])

  const start = () => (mode === 'browser' ? void startBrowser() : void startInternet())

  const stop = async () => {
    if (mode === 'browser') abortRef.current?.abort()
    else if (jobId) await api(`/api/speedtest/jobs/${jobId}/stop`, { method: 'POST', body: '{}' }).catch(() => {})
  }

  useEffect(() => () => abortRef.current?.abort(), [])

  const switchMode = (m: Mode) => {
    if (running) return
    setMode(m)
    setView(EMPTY_VIEW)
    if (m === 'browser') setJobId(null)
  }

  // ── Derived display ────────────────────────────────
  const phaseKey: PhaseColorKey =
    view.phase === 'upload' ? 'upload' : view.phase === 'ping' || view.phase === 'connect' ? 'ping' : 'download'
  const scale = useMemo(() => pickScale(Math.max(toUnit(maxSeen, unit), 1)), [maxSeen, unit])
  const showGauge = view.phase !== 'idle' || running
  const gaugeValue =
    view.bps != null
      ? toUnit(view.bps, unit)
      : view.phase === 'done'
        ? toUnit(view.downloadBps ?? 0, unit)
        : 0
  const grade = bloatGrade(view.pingMs, Math.max(view.loadedDownMs ?? 0, view.loadedUpMs ?? 0) || undefined)
  const chartData = useMemo(
    () =>
      view.series.map((p) => ({
        t: `${p.t.toFixed(1)}s`,
        ...(p.dl != null ? { dl: Number(toUnit(p.dl, unit).toFixed(2)) } : {}),
        ...(p.ul != null ? { ul: Number(toUnit(p.ul, unit).toFixed(2)) } : {}),
      })),
    [view.series, unit],
  )

  const endpoints =
    mode === 'browser'
      ? {
          a: { icon: <DesktopOutlined />, title: 'Your browser', sub: info.client_ip || '—' },
          b: { icon: <HddOutlined />, title: info.hostname, sub: info.server_ip || 'this host' },
        }
      : {
          a: { icon: <HddOutlined />, title: info.hostname, sub: job?.meta?.public_ip || 'public IP' },
          b: {
            icon: <CloudOutlined />,
            title: `Cloudflare${job?.meta?.colo ? ` · ${job.meta.colo}` : ''}`,
            sub: job?.meta?.country ? `${job.meta.country} · nearest edge` : 'nearest edge',
          },
        }

  const settingsContent =
    mode === 'browser' ? (
      <div className="stg-settings">
        <div className="stg-settings-row">
          <span>Parallel streams</span>
          <InputNumber size="small" min={1} max={16} value={bOpts.streams} onChange={(v) => setBOpts({ ...bOpts, streams: Number(v) || 6 })} />
        </div>
        <div className="stg-settings-row">
          <span>Duration per direction (s)</span>
          <InputNumber size="small" min={3} max={30} value={bOpts.duration} onChange={(v) => setBOpts({ ...bOpts, duration: Number(v) || 10 })} />
        </div>
        <div className="stg-settings-row">
          <span>Ping samples</span>
          <InputNumber size="small" min={5} max={100} value={bOpts.pingCount} onChange={(v) => setBOpts({ ...bOpts, pingCount: Number(v) || 20 })} />
        </div>
        <div className="stg-settings-row">
          <span>Download</span>
          <Switch size="small" checked={bOpts.download} onChange={(v) => setBOpts({ ...bOpts, download: v })} />
        </div>
        <div className="stg-settings-row">
          <span>Upload</span>
          <Switch size="small" checked={bOpts.upload} onChange={(v) => setBOpts({ ...bOpts, upload: v })} />
        </div>
        <Button size="small" type="link" onClick={() => setBOpts(DEFAULT_BROWSER_OPTIONS)} style={{ padding: 0 }}>
          Reset to optimal defaults
        </Button>
      </div>
    ) : (
      <div className="stg-settings">
        <div className="stg-settings-row">
          <span>Parallel connections</span>
          <InputNumber size="small" min={1} max={16} value={iOpts.streams} onChange={(v) => setIOpts({ ...iOpts, streams: Number(v) || 6 })} />
        </div>
        <div className="stg-settings-row">
          <span>Duration per direction (s)</span>
          <InputNumber size="small" min={3} max={60} value={iOpts.duration} onChange={(v) => setIOpts({ ...iOpts, duration: Number(v) || 10 })} />
        </div>
        <div className="stg-settings-row">
          <span>IP version</span>
          <Segmented
            size="small"
            value={iOpts.ip_version}
            options={[
              { label: 'IPv4', value: 4 },
              { label: 'IPv6', value: 6 },
            ]}
            onChange={(v) => setIOpts({ ...iOpts, ip_version: v as 4 | 6 })}
          />
        </div>
        <Button size="small" type="link" onClick={() => setIOpts(DEFAULT_INTERNET)} style={{ padding: 0 }}>
          Reset to optimal defaults
        </Button>
      </div>
    )

  const stepCurrent = view.phase === 'latency' ? 'ping' : view.phase

  return (
    <div className="stg-stack">
      <Panel className="stg-hero" padded={false}>
        <div className="stg-hero-aurora" data-phase={phaseKey} />
        <div className="stg-hero-inner">
          <div className="stg-hero-top">
            <Segmented
              value={mode}
              onChange={(v) => switchMode(v as Mode)}
              disabled={running}
              options={[
                { value: 'browser', label: <span className="stg-seg"><DesktopOutlined /> Browser ↔ This host</span> },
                {
                  value: 'internet',
                  disabled: !internetAllowed,
                  label: (
                    <Tooltip title={internetAllowed ? 'The server measures its own Internet uplink' : 'Requires Speedtest “full” permission and the Internet test enabled in Settings'}>
                      <span className="stg-seg"><CloudOutlined /> Host ↔ Internet</span>
                    </Tooltip>
                  ),
                },
              ]}
            />
            <Space>
              <Segmented
                size="small"
                value={unit}
                onChange={(v) => onUnitChange(v as RateUnit)}
                options={[
                  { label: 'Mbps', value: 'mbps' },
                  { label: 'MB/s', value: 'mbs' },
                ]}
              />
              <Popover trigger="click" placement="bottomRight" title="Test settings" content={settingsContent}>
                <Button shape="circle" icon={<SettingOutlined />} disabled={running} />
              </Popover>
            </Space>
          </div>

          <div className="stg-endpoints">
            <div className="stg-endpoint">
              <span className="stg-endpoint-icon">{endpoints.a.icon}</span>
              <div>
                <div className="stg-endpoint-title">{endpoints.a.title}</div>
                <div className="stg-endpoint-sub mono">{endpoints.a.sub}</div>
              </div>
            </div>
            <div className={`stg-link${running ? ' is-running' : ''}`} data-phase={phaseKey}>
              <span />
              <SwapOutlined />
              <span />
            </div>
            <div className="stg-endpoint is-right">
              <div>
                <div className="stg-endpoint-title">{endpoints.b.title}</div>
                <div className="stg-endpoint-sub mono">{endpoints.b.sub}</div>
              </div>
              <span className="stg-endpoint-icon">{endpoints.b.icon}</span>
            </div>
          </div>

          <div className="stg-stage">
            <AnimatePresence mode="wait">
              {!showGauge ? (
                <motion.div
                  key="go"
                  initial={{ opacity: 0, scale: 0.85 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 1.15 }}
                  transition={{ duration: 0.35 }}
                >
                  <GoButton
                    onClick={start}
                    disabled={mode === 'internet' && !internetAllowed}
                    hint={mode === 'browser' ? 'Measures the path between your browser and this server' : 'Measures this server’s Internet connection'}
                  />
                </motion.div>
              ) : (
                <motion.div
                  key="gauge"
                  className="stg-gauge-wrap"
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.4, ease: [0.2, 0.8, 0.2, 1] }}
                >
                  <SpeedGauge
                    value={view.phase === 'ping' || view.phase === 'connect' ? 0 : gaugeValue}
                    scale={scale}
                    unit={unitLabel(unit)}
                    phase={phaseKey}
                    active={running}
                    label={view.phase === 'done' ? 'Download' : PHASE_LABEL[view.phase] || view.phase}
                    sublabel={
                      view.phase === 'ping' && view.latencyMs != null
                        ? `${fmtMs(view.latencyMs)} ms`
                        : (view.phase === 'download' || view.phase === 'upload') && view.latencyMs != null
                          ? `latency under load ${fmtMs(view.latencyMs)} ms`
                          : undefined
                    }
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {showGauge ? (
            <div className="stg-controls">
              <PhaseStepper steps={STEPS} current={stepCurrent} />
              {running ? <ProgressBar value={view.progress} phase={phaseKey} /> : null}
              <Space>
                {running ? (
                  <Button danger icon={<StopOutlined />} onClick={() => void stop()}>
                    Stop
                  </Button>
                ) : (
                  <Button type="primary" size="large" shape="round" icon={<ReloadOutlined />} onClick={start}>
                    Test again
                  </Button>
                )}
              </Space>
              {view.error ? <div className="stg-error">{view.error}</div> : null}
            </div>
          ) : null}
        </div>
      </Panel>

      <div className="stg-tiles">
        <MetricTile
          icon={<FieldTimeOutlined />}
          label="Ping"
          value={fmtMs(view.pingMs)}
          unit="ms"
          color={PHASE_COLORS.ping.solid}
          active={view.phase === 'ping'}
          done={view.pingMs != null && view.phase !== 'ping'}
          sub={view.jitterMs != null ? `jitter ${fmtMs(view.jitterMs)} ms` : 'idle latency'}
          tooltip="Median round-trip time with an idle connection"
        />
        <MetricTile
          icon={<ArrowDownOutlined />}
          label="Download"
          value={view.downloadBps != null ? fmtSpeedNum(toUnit(view.downloadBps, unit)) : '—'}
          unit={unitLabel(unit)}
          color={PHASE_COLORS.download.solid}
          active={view.phase === 'download'}
          done={view.downloadBps != null && view.phase !== 'download'}
          sub={view.loadedDownMs != null ? `loaded latency ${fmtMs(view.loadedDownMs)} ms` : mode === 'browser' ? 'server → browser' : 'Internet → server'}
        />
        <MetricTile
          icon={<ArrowUpOutlined />}
          label="Upload"
          value={view.uploadBps != null ? fmtSpeedNum(toUnit(view.uploadBps, unit)) : '—'}
          unit={unitLabel(unit)}
          color={PHASE_COLORS.upload.solid}
          active={view.phase === 'upload'}
          done={view.uploadBps != null && view.phase !== 'upload'}
          sub={view.loadedUpMs != null ? `loaded latency ${fmtMs(view.loadedUpMs)} ms` : mode === 'browser' ? 'browser → server' : 'server → Internet'}
        />
        <MetricTile
          icon={<DashboardOutlined />}
          label="Responsiveness"
          value={grade ? <GradeBadge grade={grade.grade} color={grade.color} title="Bufferbloat grade: latency increase under load" /> : '—'}
          color={grade?.color || '#64748b'}
          done={!!grade && !running}
          sub={
            grade && view.pingMs != null
              ? `+${fmtMs(Math.max(0, Math.max(view.loadedDownMs ?? 0, view.loadedUpMs ?? 0) - view.pingMs))} ms under load`
              : 'bufferbloat grade'
          }
          tooltip="How much latency grows while the link is saturated. A/A+ is great for calls and gaming."
        />
      </div>

      <Panel
        title="Live throughput"
        extra={
          <span className="stg-legend">
            <i style={{ background: PHASE_COLORS.download.solid }} /> Download
            <i style={{ background: PHASE_COLORS.upload.solid }} /> Upload
          </span>
        }
      >
        {chartData.length ? (
          <PremiumAreaChart
            data={chartData}
            xKey="t"
            height={220}
            series={[
              { key: 'dl', label: 'Download', color: PHASE_COLORS.download.solid, formatValue: (v) => `${fmtSpeedNum(v)} ${unitLabel(unit)}` },
              { key: 'ul', label: 'Upload', color: PHASE_COLORS.upload.solid, formatValue: (v) => `${fmtSpeedNum(v)} ${unitLabel(unit)}` },
            ]}
            yFormatter={(v) => fmtSpeedNum(v)}
          />
        ) : (
          <div className="stg-empty-chart">
            <ThunderboltOutlined /> Press <b>GO</b> to start — the chart draws live while the test runs
          </div>
        )}
      </Panel>
    </div>
  )
}
