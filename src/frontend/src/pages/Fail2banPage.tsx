import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Col,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Space,
  Switch,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  ReloadOutlined,
  StopOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  CloseOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'
import { useAppSettings } from '../api/settings'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { formatFail2banDurationHint } from '../utils/fail2banTime'

type Jail = {
  name: string
  currently_banned?: number
  total_banned?: number
  currently_failed?: number
  total_failed?: number
  bantime?: string
  findtime?: string
  maxretry?: string
  bantime_hint?: string
  findtime_hint?: string
  filter?: string
  banned_ips?: string[]
  ignoreip?: string[]
}

export function Fail2banPage() {
  const { moduleOpts } = useAppSettings()
  const opts = moduleOpts('fail2ban')
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [banOpen, setBanOpen] = useState<{ jail: string } | null>(null)
  const [paramsOpen, setParamsOpen] = useState<Jail | null>(null)
  const [ignoreOpen, setIgnoreOpen] = useState<{ jail: string } | null>(null)
  const [banForm] = Form.useForm()
  const [paramsForm] = Form.useForm()
  const [ignoreForm] = Form.useForm()

  const load = useCallback(() => {
    void api('/api/security/fail2ban')
      .then(setData)
      .catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const canMut = !!data?.allow_mutations
  const help = data?.param_help || {}

  const run = async (body: Record<string, unknown>, okMsg: string) => {
    setBusy(true)
    try {
      const res = await api<{ ok?: boolean; error?: string; warning?: string }>(
        '/api/security/fail2ban/action',
        {
          method: 'POST',
          body: JSON.stringify(body),
        },
      )
      if (res?.ok === false) {
        message.error(res.error || 'Error')
        return false
      }
      if (res?.warning) message.warning(res.warning)
      else message.success(okMsg)
      load()
      return true
    } catch (e) {
      message.error(String(e))
      return false
    } finally {
      setBusy(false)
    }
  }

  const openParams = (jail: Jail) => {
    paramsForm.setFieldsValue({
      bantime: jail.bantime ?? '',
      findtime: jail.findtime ?? '',
      maxretry: jail.maxretry ? Number(jail.maxretry) : undefined,
      persist: true,
    })
    setParamsOpen(jail)
  }

  const findtimeWatch = Form.useWatch('findtime', paramsForm)
  const bantimeWatch = Form.useWatch('bantime', paramsForm)
  const findtimeHint = formatFail2banDurationHint(findtimeWatch)
  const bantimeHint = formatFail2banDurationHint(bantimeWatch)

  if (error) return <Alert type="error" message={error} showIcon />
  if (!data) return <Typography.Text type="secondary">Loading…</Typography.Text>

  if (!data.installed) {
    return (
      <div className="la-page">
        <PageHeader title="Fail2ban" subtitle="Protection against brute-force attacks" />
        <Alert
          type="info"
          showIcon
          message="Fail2ban is not installed"
          description="Install fail2ban and start the service to see jails and banned IPs."
        />
      </div>
    )
  }

  return (
    <div className="la-page">
      <PageHeader
        title="Fail2ban"
        subtitle={`${data.version || 'version unknown'} · ${data.jails_count} jail(s)`}
        extra={
          <Space wrap>
            <Tag color={data.active ? 'success' : 'warning'} style={{ marginInlineEnd: 0 }}>
              {data.active ? 'active' : 'inactive'}
            </Tag>
            <Button icon={<ReloadOutlined />} onClick={load}>
              Refresh
            </Button>
            {canMut ? (
              <>
                <Button
                  loading={busy}
                  onClick={() => void run({ action: 'reload' }, 'Fail2ban reload')}
                >
                  Reload
                </Button>
                {data.active ? (
                  <Button
                    danger
                    icon={<StopOutlined />}
                    loading={busy}
                    onClick={() => void run({ action: 'stop' }, 'Fail2ban stopped')}
                  >
                    Stop
                  </Button>
                ) : (
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    loading={busy}
                    onClick={() => void run({ action: 'start' }, 'Fail2ban started')}
                  >
                    Start
                  </Button>
                )}
                <Button
                  loading={busy}
                  onClick={() => void run({ action: 'restart' }, 'Fail2ban restart')}
                >
                  Restart
                </Button>
              </>
            ) : null}
          </Space>
        }
      />

      {!canMut ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Read-only mode. Enable “Allow management” for Fail2ban in Settings."
        />
      ) : (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Ban conditions: maxretry failures within findtime → ban for bantime. Can be saved to jail.d."
        />
      )}

      <Panel>
        <Descriptions size="small" column={{ xs: 1, sm: 2 }}>
          <Descriptions.Item label="Binary">
            <span className="mono">{data.binary}</span>
          </Descriptions.Item>
          <Descriptions.Item label="Jails">{data.jails_count}</Descriptions.Item>
          <Descriptions.Item label="Configs" span={2}>
            {(data.config_paths || []).join(', ')}
          </Descriptions.Item>
        </Descriptions>
      </Panel>

      <Row gutter={[16, 16]}>
        {(data.jails_detail || []).map((jail: Jail) => (
          <Col xs={24} lg={12} key={jail.name}>
            <Panel
              title={jail.name}
              extra={
                <Space wrap>
                  <Tag color={jail.currently_banned ? 'error' : 'default'}>
                    banned {jail.currently_banned}
                  </Tag>
                  {canMut ? (
                    <>
                      <Button
                        size="small"
                        icon={<SettingOutlined />}
                        onClick={() => openParams(jail)}
                      >
                        Conditions
                      </Button>
                      <Button
                        size="small"
                        icon={<PlusOutlined />}
                        onClick={() => {
                          banForm.resetFields()
                          setBanOpen({ jail: jail.name })
                        }}
                      >
                        Ban IP
                      </Button>
                    </>
                  ) : null}
                </Space>
              }
            >
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="Currently banned">{jail.currently_banned}</Descriptions.Item>
                <Descriptions.Item label="Total banned">{jail.total_banned}</Descriptions.Item>
                <Descriptions.Item label="Failed now">{jail.currently_failed}</Descriptions.Item>
                <Descriptions.Item label="Failed total">{jail.total_failed}</Descriptions.Item>
                <Descriptions.Item label="bantime">
                  <span className="mono">{jail.bantime || '—'}</span>
                  {jail.bantime_hint ? (
                    <Typography.Text type="secondary"> ({jail.bantime_hint})</Typography.Text>
                  ) : null}
                </Descriptions.Item>
                <Descriptions.Item label="findtime">
                  <span className="mono">{jail.findtime || '—'}</span>
                  {jail.findtime_hint ? (
                    <Typography.Text type="secondary"> ({jail.findtime_hint})</Typography.Text>
                  ) : null}
                </Descriptions.Item>
                <Descriptions.Item label="maxretry">
                  <span className="mono">{jail.maxretry || '—'}</span>
                </Descriptions.Item>
                <Descriptions.Item label="filter">{jail.filter || '—'}</Descriptions.Item>
              </Descriptions>

              <Typography.Paragraph style={{ marginTop: 12, marginBottom: 8 }} type="secondary">
                Whitelist (ignoreip)
                {canMut ? (
                  <Button
                    type="link"
                    size="small"
                    onClick={() => {
                      ignoreForm.resetFields()
                      setIgnoreOpen({ jail: jail.name })
                    }}
                  >
                    + IP/CIDR
                  </Button>
                ) : null}
              </Typography.Paragraph>
              <Space wrap>
                {(jail.ignoreip || []).length
                  ? jail.ignoreip!.map((ip) => (
                      <Tag
                        key={ip}
                        className="mono"
                        closable={canMut}
                        closeIcon={<CloseOutlined />}
                        onClose={(e) => {
                          e.preventDefault()
                          void run(
                            { action: 'del-ignoreip', jail: jail.name, ip },
                            `ignoreip − ${ip}`,
                          )
                        }}
                      >
                        {ip}
                      </Tag>
                    ))
                  : '—'}
              </Space>

              <Typography.Paragraph style={{ marginTop: 12, marginBottom: 8 }} type="secondary">
                Banned IP
              </Typography.Paragraph>
              <Space wrap>
                {(jail.banned_ips || []).length
                  ? jail.banned_ips!.map((ip) => (
                      <Tag
                        key={ip}
                        className="mono"
                        closable={canMut}
                        closeIcon={<CloseOutlined />}
                        onClose={(e) => {
                          e.preventDefault()
                          void run({ action: 'unban', jail: jail.name, ip }, `Unban ${ip}`)
                        }}
                      >
                        {ip}
                      </Tag>
                    ))
                  : '—'}
              </Space>
            </Panel>
          </Col>
        ))}
      </Row>

      {opts.show_logs !== false ? (
        <Panel title="Log (tail)" padded={false} bodyStyle={{ padding: 12 }}>
          <pre className="la-log">{(data.log_tail || []).join('\n') || 'Log unavailable'}</pre>
        </Panel>
      ) : null}

      <Modal
        title={banOpen ? `Ban IP · ${banOpen.jail}` : 'Ban IP'}
        open={!!banOpen}
        confirmLoading={busy}
        onCancel={() => setBanOpen(null)}
        onOk={() => {
          void banForm.validateFields().then(async (vals) => {
            if (!banOpen) return
            const ok = await run(
              { action: 'ban', jail: banOpen.jail, ip: vals.ip },
              `Ban ${vals.ip}`,
            )
            if (ok) setBanOpen(null)
          })
        }}
      >
        <Form form={banForm} layout="vertical">
          <Form.Item name="ip" label="IP" rules={[{ required: true }]}>
            <Input className="mono" placeholder="203.0.113.10" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={paramsOpen ? `Ban conditions · ${paramsOpen.name}` : 'Conditions'}
        open={!!paramsOpen}
        confirmLoading={busy}
        width={520}
        okText="Apply"
        onCancel={() => setParamsOpen(null)}
        onOk={() => {
          void paramsForm.validateFields().then(async (vals) => {
            if (!paramsOpen) return
            const ok = await run(
              {
                action: 'set-params',
                jail: paramsOpen.name,
                bantime: vals.bantime || undefined,
                findtime: vals.findtime || undefined,
                maxretry: vals.maxretry ?? undefined,
                persist: vals.persist !== false,
              },
              'Jail parameters applied',
            )
            if (ok) setParamsOpen(null)
          })
        }}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="If maxretry failures occur within findtime, the IP is banned for bantime."
        />
        <Form form={paramsForm} layout="vertical">
          <Form.Item
            name="maxretry"
            label="maxretry"
            extra={help.maxretry || 'Number of attempts before ban'}
            rules={[{ required: true, message: 'Enter maxretry' }]}
          >
            <InputNumber min={1} max={100000} style={{ width: '100%' }} className="mono" />
          </Form.Item>
          <Form.Item
            name="findtime"
            label="findtime"
            extra={
              <span>
                {help.findtime || 'Window: 600, 10m, 1h'}
                {findtimeHint ? (
                  <>
                    <br />
                    <span className="mono" style={{ color: 'var(--la-accent-deep)', fontWeight: 600 }}>
                      ≈ {findtimeHint}
                    </span>
                  </>
                ) : findtimeWatch ? (
                  <>
                    <br />
                    <Typography.Text type="danger">Unrecognized — enter seconds or 10m / 1h / 1d</Typography.Text>
                  </>
                ) : null}
              </span>
            }
            rules={[{ required: true, message: 'Enter findtime' }]}
          >
            <Input className="mono" placeholder="10m or 600" />
          </Form.Item>
          <Form.Item
            name="bantime"
            label="bantime"
            extra={
              <span>
                {help.bantime || 'Duration: 3600, 1h, 1d, -1 (permanent)'}
                {bantimeHint ? (
                  <>
                    <br />
                    <span className="mono" style={{ color: 'var(--la-accent-deep)', fontWeight: 600 }}>
                      ≈ {bantimeHint}
                    </span>
                  </>
                ) : bantimeWatch ? (
                  <>
                    <br />
                    <Typography.Text type="danger">Unrecognized — enter seconds or 10m / 1h / 1d / -1</Typography.Text>
                  </>
                ) : null}
              </span>
            }
            rules={[{ required: true, message: 'Enter bantime' }]}
          >
            <Input className="mono" placeholder="1h or 86400" />
          </Form.Item>
          <Form.Item
            name="persist"
            label="Save to /etc/fail2ban/jail.d (after reboot/reload)"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={ignoreOpen ? `Whitelist · ${ignoreOpen.jail}` : 'Whitelist'}
        open={!!ignoreOpen}
        confirmLoading={busy}
        onCancel={() => setIgnoreOpen(null)}
        onOk={() => {
          void ignoreForm.validateFields().then(async (vals) => {
            if (!ignoreOpen) return
            const ok = await run(
              { action: 'add-ignoreip', jail: ignoreOpen.jail, ip: vals.ip },
              `ignoreip + ${vals.ip}`,
            )
            if (ok) setIgnoreOpen(null)
          })
        }}
      >
        <Form form={ignoreForm} layout="vertical">
          <Form.Item
            name="ip"
            label="IP or CIDR"
            extra={help.ignoreip}
            rules={[{ required: true }]}
          >
            <Input className="mono" placeholder="192.168.1.0/24" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
