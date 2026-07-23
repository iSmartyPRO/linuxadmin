import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Descriptions,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { PlusOutlined, ReloadOutlined, DeleteOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import { useAppSettings } from '../api/settings'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { tablePagination } from '../utils/tablePagination'

export function FirewallPage() {
  const { moduleOpts } = useAppSettings()
  const opts = moduleOpts('firewall')
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(() => {
    void api('/api/security/firewall')
      .then(setData)
      .catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const canMut = !!data?.allow_mutations
  const backend = data?.backend

  const run = async (body: Record<string, unknown>, okMsg: string) => {
    setBusy(true)
    try {
      const res = await api<{ ok?: boolean; error?: string }>('/api/security/firewall/action', {
        method: 'POST',
        body: JSON.stringify(body),
      })
      if (res?.ok === false) {
        message.error(res.error || 'Error')
        return false
      }
      message.success(okMsg)
      load()
      return true
    } catch (e) {
      message.error(String(e))
      return false
    } finally {
      setBusy(false)
    }
  }

  if (error) return <Alert type="error" message={error} showIcon />
  if (!data) return <Typography.Text type="secondary">Loading…</Typography.Text>

  if (data.backend === 'none') {
    return (
      <div className="la-page">
        <PageHeader title="Firewall" />
        <Alert type="warning" showIcon message="Firewall not detected (ufw / firewalld / nft / iptables)" />
      </div>
    )
  }

  const managed = backend === 'ufw' || backend === 'firewalld'

  return (
    <div className="la-page">
      <PageHeader
        title="Firewall"
        subtitle={`Backend ${data.backend}`}
        extra={
          <Space wrap>
            <Tag color={data.enabled ? 'success' : 'default'} style={{ marginInlineEnd: 0 }}>
              {data.enabled ? 'enabled' : 'disabled'}
            </Tag>
            <Button icon={<ReloadOutlined />} onClick={load}>
              Refresh
            </Button>
            {canMut && managed ? (
              <>
                <Button loading={busy} onClick={() => void run({ action: 'reload' }, 'Reload')}>
                  Reload
                </Button>
                {data.enabled ? (
                  <Button
                    danger
                    loading={busy}
                    onClick={() => void run({ action: 'disable' }, 'Firewall disabled')}
                  >
                    Disable
                  </Button>
                ) : (
                  <Button
                    type="primary"
                    loading={busy}
                    onClick={() => void run({ action: 'enable' }, 'Firewall enabled')}
                  >
                    Enable
                  </Button>
                )}
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={() => {
                    form.resetFields()
                    form.setFieldsValue({
                      action: backend === 'ufw' ? 'allow' : 'add-port',
                      proto: 'tcp',
                      port: '22',
                    })
                    setAddOpen(true)
                  }}
                >
                  Add
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
          message="Read-only mode. Enable “Allow management” for Firewall in Settings."
        />
      ) : !managed ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`Rule management for “${backend}” is not supported — use ufw or firewalld.`}
        />
      ) : null}

      <Panel>
        <Descriptions size="small" column={{ xs: 1, sm: 2 }}>
          <Descriptions.Item label="Backend">
            <Tag color="processing">{data.backend}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Service">
            {data.active_service ? 'active' : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="Defaults" span={2}>
            {data.defaults?.raw || '—'}
          </Descriptions.Item>
        </Descriptions>
      </Panel>

      {data.zones?.length ? (
        <Panel title="firewalld zones" padded={false} bodyStyle={{ padding: '8px 8px 12px' }}>
          <Table
            size="small"
            rowKey="name"
            pagination={false}
            dataSource={data.zones}
            columns={[
              { title: 'Zone', dataIndex: 'name' },
              {
                title: 'Services',
                dataIndex: 'services',
                render: (v) => (Array.isArray(v) ? v.join(', ') : String(v || '—')),
              },
              {
                title: 'Ports',
                dataIndex: 'ports',
                render: (v) => (Array.isArray(v) ? v.join(', ') : String(v || '—')),
              },
              {
                title: 'Interfaces',
                dataIndex: 'interfaces',
                render: (v) => (Array.isArray(v) ? v.join(', ') : String(v || '—')),
              },
            ]}
          />
        </Panel>
      ) : null}

      {(data.rules || []).length ? (
        <Panel title="Rules" padded={false} bodyStyle={{ padding: '8px 8px 12px' }}>
          <Table
            size="small"
            rowKey={(_, i) => String(i)}
            pagination={tablePagination(25)}
            dataSource={data.rules}
            columns={[
              { title: '#', dataIndex: 'number', width: 60 },
              { title: 'Action', dataIndex: 'action', width: 100 },
              { title: 'Dir', dataIndex: 'direction', width: 100 },
              { title: 'Details', dataIndex: 'details', ellipsis: true },
              ...(canMut && backend === 'ufw'
                ? [
                    {
                      title: '',
                      key: 'del',
                      width: 70,
                      render: (_: unknown, row: any) =>
                        row.number ? (
                          <Button
                            danger
                            type="text"
                            size="small"
                            icon={<DeleteOutlined />}
                            loading={busy}
                            onClick={() =>
                              void run(
                                { action: 'delete', number: Number(row.number) },
                                `Deleted rule #${row.number}`,
                              )
                            }
                          />
                        ) : null,
                    },
                  ]
                : []),
            ]}
          />
        </Panel>
      ) : null}

      {data.raw && opts.show_raw !== false ? (
        <Panel title="Raw output" padded={false} bodyStyle={{ padding: 12 }}>
          <pre className="la-log">{data.raw}</pre>
        </Panel>
      ) : null}

      {opts.show_logs !== false ? (
        <Panel title="Log (DROP/REJECT)" padded={false} bodyStyle={{ padding: 12 }}>
          <pre className="la-log">{(data.log_tail || []).join('\n') || 'No entries'}</pre>
        </Panel>
      ) : null}

      <Modal
        title="Add rule"
        open={addOpen}
        confirmLoading={busy}
        onCancel={() => setAddOpen(false)}
        onOk={() => {
          void form.validateFields().then(async (vals) => {
            const body: Record<string, unknown> = {
              action: vals.action,
              port: vals.port,
              proto: vals.proto,
              source: vals.source || undefined,
              zone: vals.zone || undefined,
              rule: vals.rule || undefined,
            }
            const ok = await run(body, 'Rule applied')
            if (ok) setAddOpen(false)
          })
        }}
      >
        <Form form={form} layout="vertical">
          {backend === 'ufw' ? (
            <>
              <Form.Item name="action" label="Action" rules={[{ required: true }]}>
                <Select
                  options={[
                    { value: 'allow', label: 'allow' },
                    { value: 'deny', label: 'deny' },
                    { value: 'reject', label: 'reject' },
                    { value: 'limit', label: 'limit' },
                  ]}
                />
              </Form.Item>
              <Form.Item name="port" label="Port" rules={[{ required: true }]}>
                <Input className="mono" placeholder="22 or 22/tcp" />
              </Form.Item>
              <Form.Item name="proto" label="Proto">
                <Select
                  options={[
                    { value: 'tcp', label: 'tcp' },
                    { value: 'udp', label: 'udp' },
                    { value: 'any', label: 'any' },
                  ]}
                />
              </Form.Item>
              <Form.Item name="source" label="From (optional CIDR/IP)">
                <Input className="mono" placeholder="203.0.113.0/24" />
              </Form.Item>
            </>
          ) : (
            <>
              <Form.Item name="action" label="Action" rules={[{ required: true }]}>
                <Select
                  options={[
                    { value: 'add-port', label: 'add-port' },
                    { value: 'remove-port', label: 'remove-port' },
                    { value: 'add-service', label: 'add-service' },
                    { value: 'remove-service', label: 'remove-service' },
                  ]}
                />
              </Form.Item>
              <Form.Item
                noStyle
                shouldUpdate={(prev, cur) => prev.action !== cur.action}
              >
                {({ getFieldValue }) => {
                  const a = getFieldValue('action')
                  if (a === 'add-service' || a === 'remove-service') {
                    return (
                      <Form.Item name="rule" label="Service" rules={[{ required: true }]}>
                        <Input className="mono" placeholder="http / https / ssh" />
                      </Form.Item>
                    )
                  }
                  return (
                    <>
                      <Form.Item name="port" label="Port" rules={[{ required: true }]}>
                        <Input className="mono" placeholder="443 or 443/tcp" />
                      </Form.Item>
                      <Form.Item name="proto" label="Proto">
                        <Select
                          options={[
                            { value: 'tcp', label: 'tcp' },
                            { value: 'udp', label: 'udp' },
                          ]}
                        />
                      </Form.Item>
                    </>
                  )
                }}
              </Form.Item>
              <Form.Item name="zone" label="Zone (optional)">
                <Input className="mono" placeholder="public" />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>
    </div>
  )
}
