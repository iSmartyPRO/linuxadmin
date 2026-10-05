import { useCallback, useEffect, useState } from 'react'
import { Alert, Spin, Tabs } from 'antd'
import { ExperimentOutlined, HistoryOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import { SpeedtestPanel } from '../components/speedtest/SpeedtestPanel'
import { IperfPanel } from '../components/speedtest/IperfPanel'
import { HistoryPanel } from '../components/speedtest/HistoryPanel'
import type { HistoryItem, SpeedInfo } from '../components/speedtest/types'
import { loadUnit, saveUnit, type RateUnit } from '../speedtest/format'
import '../speedtest/speedtest.css'

const TAB_KEY = 'lnxadmin_speed_tab'

export function SpeedtestPage() {
  const [info, setInfo] = useState<SpeedInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [unit, setUnit] = useState<RateUnit>(loadUnit)
  const [tab, setTab] = useState(() => localStorage.getItem(TAB_KEY) || 'speedtest')

  const loadInfo = useCallback(async () => {
    try {
      setInfo(await api<SpeedInfo>('/api/speedtest/info'))
      setError(null)
    } catch (e) {
      setError(String(e))
    }
  }, [])

  const loadHistory = useCallback(async () => {
    try {
      const res = await api<{ items: HistoryItem[] }>('/api/speedtest/history')
      setHistory(res.items)
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    void loadInfo()
    void loadHistory()
  }, [loadInfo, loadHistory])

  const changeUnit = (u: RateUnit) => {
    setUnit(u)
    saveUnit(u)
  }

  const changeTab = (k: string) => {
    setTab(k)
    localStorage.setItem(TAB_KEY, k)
    if (k === 'history') void loadHistory()
  }

  return (
    <div className="la-page stg-page">
      <PageHeader
        title="Speedtest"
        subtitle="Measure throughput and latency like speedtest.net — between your browser and this host, from this host to the Internet, or with iperf3 against any server."
        docsKey="speedtest"
      />
      {error ? <Alert type="error" showIcon message="Cannot load Speedtest" description={error} /> : null}
      {!info && !error ? (
        <div style={{ padding: 64, display: 'grid', placeItems: 'center' }}>
          <Spin size="large" />
        </div>
      ) : null}
      {info ? (
        <Tabs
          activeKey={tab}
          onChange={changeTab}
          className="stg-tabs"
          items={[
            {
              key: 'speedtest',
              label: (
                <span>
                  <ThunderboltOutlined /> Speedtest
                </span>
              ),
              children: <SpeedtestPanel info={info} unit={unit} onUnitChange={changeUnit} onFinished={() => void loadHistory()} />,
            },
            {
              key: 'iperf',
              label: (
                <span>
                  <ExperimentOutlined /> iperf3
                </span>
              ),
              children: <IperfPanel info={info} unit={unit} onRefresh={() => void loadInfo()} />,
            },
            {
              key: 'history',
              label: (
                <span>
                  <HistoryOutlined /> History
                </span>
              ),
              children: <HistoryPanel items={history} unit={unit} canDelete={info.can_run} onChanged={() => void loadHistory()} />,
            },
          ]}
        />
      ) : null}
    </div>
  )
}
