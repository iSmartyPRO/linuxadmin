import { useCallback, useEffect, useMemo, useState, type MouseEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Col, Row, Switch, Tag, Typography, message } from 'antd'
import { RightOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import { useAppSettings } from '../api/settings'
import { MODULE_CATALOG } from '../settings/moduleCatalog'

type Bundle = {
  modules: Record<string, Record<string, any>>
}

export function ModulesSettingsGrid() {
  const navigate = useNavigate()
  const { refresh } = useAppSettings()
  const [modules, setModules] = useState<Record<string, Record<string, any>>>({})
  const [savingKey, setSavingKey] = useState<string | null>(null)

  const load = useCallback(async () => {
    const res = await api<Bundle>('/api/settings')
    setModules(res.modules || {})
  }, [])

  useEffect(() => {
    void load().catch((e) => message.error(String(e)))
  }, [load])

  const groups = useMemo(() => {
    const map = new Map<string, typeof MODULE_CATALOG>()
    for (const item of MODULE_CATALOG) {
      const list = map.get(item.group) || []
      list.push(item)
      map.set(item.group, list)
    }
    return Array.from(map.entries())
  }, [])

  const toggleEnabled = async (key: string, enabled: boolean, e: MouseEvent) => {
    e.stopPropagation()
    setSavingKey(key)
    const next = {
      ...modules,
      [key]: { ...(modules[key] || {}), enabled },
    }
    setModules(next)
    try {
      const res = await api<Bundle>('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({ modules: { [key]: { enabled } } }),
      })
      setModules(res.modules)
      await refresh()
      message.success(enabled ? `${key} enabled` : `${key} disabled`)
    } catch (err) {
      message.error(String(err))
      await load()
    } finally {
      setSavingKey(null)
    }
  }

  return (
    <div style={{ marginTop: 4 }}>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
        Toggle a module on/off with the switch. Open a card for detailed options
        {modules.postgres ? ' (PostgreSQL connection lives inside the PostgreSQL card)' : ''}.
      </Typography.Paragraph>

      {groups.map(([group, items]) => (
        <div key={group} style={{ marginBottom: 24 }}>
          <Typography.Text
            type="secondary"
            style={{
              display: 'block',
              fontSize: 12,
              fontWeight: 600,
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              marginBottom: 10,
            }}
          >
            {group}
          </Typography.Text>
          <Row gutter={[12, 12]}>
            {items.map((item) => {
              const enabled = modules[item.key]?.enabled !== false
              return (
                <Col xs={24} sm={12} lg={8} key={item.key}>
                  <button
                    type="button"
                    onClick={() => navigate(`/settings/modules/${item.key}`)}
                    className="la-panel"
                    style={{
                      width: '100%',
                      textAlign: 'left',
                      cursor: 'pointer',
                      padding: 16,
                      border: '1px solid var(--la-panel-border)',
                      background: 'var(--la-panel)',
                      borderRadius: 14,
                      minHeight: 128,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 10,
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'flex-start',
                        justifyContent: 'space-between',
                        gap: 12,
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 700, fontSize: 15 }}>{item.title}</div>
                        <Tag
                          color={enabled ? 'success' : 'default'}
                          style={{ marginTop: 6, marginInlineEnd: 0 }}
                        >
                          {enabled ? 'Enabled' : 'Disabled'}
                        </Tag>
                      </div>
                      <Switch
                        checked={enabled}
                        loading={savingKey === item.key}
                        onClick={(_, e) => void toggleEnabled(item.key, !enabled, e as any)}
                      />
                    </div>
                    <div style={{ color: 'var(--la-muted)', fontSize: 13, lineHeight: 1.45, flex: 1 }}>
                      {item.description}
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        fontSize: 12,
                        fontWeight: 600,
                        color: 'var(--la-accent-deep)',
                      }}
                    >
                      Configure <RightOutlined style={{ fontSize: 10 }} />
                    </div>
                  </button>
                </Col>
              )
            })}
          </Row>
        </div>
      ))}
    </div>
  )
}
