import { useMemo, useState } from 'react'
import { Button, Popconfirm, Segmented, Table, Tag, Tooltip, message } from 'antd'
import { CloudOutlined, DeleteOutlined, DesktopOutlined, ExperimentOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api } from '../../api/client'
import { Panel } from '../Panel'
import { PremiumAreaChart } from '../PremiumAreaChart'
import { fmtMs, fmtSpeedNum, PHASE_COLORS, toUnit, unitLabel, type RateUnit } from '../../speedtest/format'
import type { HistoryItem } from './types'

const KIND: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  browser: { label: 'Browser', color: 'cyan', icon: <DesktopOutlined /> },
  internet: { label: 'Internet', color: 'blue', icon: <CloudOutlined /> },
  iperf: { label: 'iperf3', color: 'purple', icon: <ExperimentOutlined /> },
}

export function HistoryPanel({
  items,
  unit,
  canDelete,
  onChanged,
}: {
  items: HistoryItem[]
  unit: RateUnit
  canDelete: boolean
  onChanged: () => void
}) {
  const [kind, setKind] = useState<string>('all')
  const rows = useMemo(() => (kind === 'all' ? items : items.filter((i) => i.kind === kind)), [items, kind])
  const chart = useMemo(
    () =>
      [...rows]
        .reverse()
        .map((r) => ({
          t: dayjs(r.at * 1000).format('DD.MM HH:mm'),
          ...(r.download_bps != null ? { dl: Number(toUnit(r.download_bps, unit).toFixed(2)) } : {}),
          ...(r.upload_bps != null ? { ul: Number(toUnit(r.upload_bps, unit).toFixed(2)) } : {}),
        })),
    [rows, unit],
  )

  const remove = async (id?: string) => {
    try {
      await api(`/api/speedtest/history${id ? `?id=${encodeURIComponent(id)}` : ''}`, { method: 'DELETE' })
      onChanged()
    } catch (e) {
      message.error(String(e))
    }
  }

  const best = (key: 'download_bps' | 'upload_bps') => Math.max(0, ...rows.map((r) => r[key] || 0))

  return (
    <div className="stg-stack">
      <div className="stg-iperf-bar">
        <Segmented
          value={kind}
          onChange={(v) => setKind(String(v))}
          options={[
            { label: 'All', value: 'all' },
            { label: 'Browser', value: 'browser' },
            { label: 'Internet', value: 'internet' },
            { label: 'iperf3', value: 'iperf' },
          ]}
        />
        {canDelete && items.length ? (
          <Popconfirm title="Clear all speed test history?" onConfirm={() => void remove()}>
            <Button danger icon={<DeleteOutlined />}>
              Clear history
            </Button>
          </Popconfirm>
        ) : null}
      </div>

      <div className="stg-tiles">
        <div className="stg-tile is-done" style={{ ['--tile-color' as string]: PHASE_COLORS.download.solid }}>
          <div className="stg-tile-head"><span className="stg-tile-label">Best download</span></div>
          <div className="stg-tile-value"><span>{rows.length ? fmtSpeedNum(toUnit(best('download_bps'), unit)) : '—'}</span><small>{unitLabel(unit)}</small></div>
        </div>
        <div className="stg-tile is-done" style={{ ['--tile-color' as string]: PHASE_COLORS.upload.solid }}>
          <div className="stg-tile-head"><span className="stg-tile-label">Best upload</span></div>
          <div className="stg-tile-value"><span>{rows.length ? fmtSpeedNum(toUnit(best('upload_bps'), unit)) : '—'}</span><small>{unitLabel(unit)}</small></div>
        </div>
        <div className="stg-tile is-done" style={{ ['--tile-color' as string]: PHASE_COLORS.ping.solid }}>
          <div className="stg-tile-head"><span className="stg-tile-label">Lowest ping</span></div>
          <div className="stg-tile-value">
            <span>{rows.some((r) => r.ping_ms != null) ? fmtMs(Math.min(...rows.filter((r) => r.ping_ms != null).map((r) => r.ping_ms as number))) : '—'}</span>
            <small>ms</small>
          </div>
        </div>
        <div className="stg-tile is-done" style={{ ['--tile-color' as string]: '#38bdf8' }}>
          <div className="stg-tile-head"><span className="stg-tile-label">Tests</span></div>
          <div className="stg-tile-value"><span>{rows.length}</span></div>
        </div>
      </div>

      {chart.length > 1 ? (
        <Panel title="Trend">
          <PremiumAreaChart
            data={chart}
            xKey="t"
            height={220}
            series={[
              { key: 'dl', label: 'Download', color: PHASE_COLORS.download.solid, formatValue: (v) => `${fmtSpeedNum(v)} ${unitLabel(unit)}` },
              { key: 'ul', label: 'Upload', color: PHASE_COLORS.upload.solid, formatValue: (v) => `${fmtSpeedNum(v)} ${unitLabel(unit)}` },
            ]}
            yFormatter={(v) => fmtSpeedNum(v)}
          />
        </Panel>
      ) : null}

      <Panel title="Results" padded={false} bodyStyle={{ padding: '8px 8px 4px' }}>
        <Table
          size="middle"
          rowKey="id"
          dataSource={rows}
          pagination={{ pageSize: 15, hideOnSinglePage: true }}
          columns={[
            {
              title: 'When',
              dataIndex: 'at',
              width: 150,
              render: (v: number) => <Tooltip title={dayjs(v * 1000).format('YYYY-MM-DD HH:mm:ss')}>{dayjs(v * 1000).format('DD.MM.YYYY HH:mm')}</Tooltip>,
            },
            {
              title: 'Type',
              dataIndex: 'kind',
              width: 120,
              render: (v: string, r: HistoryItem) => (
                <Tag color={KIND[v]?.color} icon={KIND[v]?.icon}>
                  {KIND[v]?.label || v}
                  {r.protocol ? ` · ${r.protocol.toUpperCase()}` : ''}
                </Tag>
              ),
            },
            {
              title: 'Target',
              dataIndex: 'target',
              render: (v: string, r: HistoryItem) => (
                <div>
                  <span className="mono">{v || '—'}</span>
                  <div className="stg-muted" style={{ fontSize: 12 }}>
                    {r.kind === 'browser' && r.client_ip ? `from ${r.client_ip}` : null}
                    {r.kind === 'iperf' ? `${r.direction}${r.parallel ? ` · ${r.parallel} streams` : ''}` : null}
                    {r.kind === 'internet' && r.meta?.public_ip ? `public IP ${r.meta.public_ip}` : null}
                  </div>
                </div>
              ),
            },
            { title: 'Ping', dataIndex: 'ping_ms', width: 90, render: (v?: number) => <span className="mono">{v != null ? `${fmtMs(v)} ms` : '—'}</span> },
            {
              title: 'Download',
              dataIndex: 'download_bps',
              width: 140,
              sorter: (a: HistoryItem, b: HistoryItem) => (a.download_bps || 0) - (b.download_bps || 0),
              render: (v?: number) =>
                v != null ? (
                  <b className="mono" style={{ color: PHASE_COLORS.download.solid }}>
                    {fmtSpeedNum(toUnit(v, unit))} <small>{unitLabel(unit)}</small>
                  </b>
                ) : (
                  '—'
                ),
            },
            {
              title: 'Upload',
              dataIndex: 'upload_bps',
              width: 140,
              sorter: (a: HistoryItem, b: HistoryItem) => (a.upload_bps || 0) - (b.upload_bps || 0),
              render: (v?: number) =>
                v != null ? (
                  <b className="mono" style={{ color: PHASE_COLORS.upload.solid }}>
                    {fmtSpeedNum(toUnit(v, unit))} <small>{unitLabel(unit)}</small>
                  </b>
                ) : (
                  '—'
                ),
            },
            {
              title: 'Quality',
              key: 'q',
              width: 150,
              render: (_: unknown, r: HistoryItem) => (
                <span className="mono stg-muted">
                  {r.jitter_ms != null ? `jitter ${fmtMs(r.jitter_ms)} ms` : ''}
                  {r.loss_pct != null ? ` · loss ${r.loss_pct}%` : ''}
                  {r.retr != null ? `${r.retr} retr` : ''}
                </span>
              ),
            },
            { title: 'By', dataIndex: 'by', width: 100 },
            ...(canDelete
              ? [
                  {
                    title: '',
                    key: 'del',
                    width: 48,
                    render: (_: unknown, r: HistoryItem) => (
                      <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => void remove(r.id)} />
                    ),
                  },
                ]
              : []),
          ]}
        />
      </Panel>
    </div>
  )
}
