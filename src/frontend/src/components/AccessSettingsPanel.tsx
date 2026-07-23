import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import { api } from '../api/client'
import { useAccess } from '../api/access'
import { ModuleDocsButton } from './ModuleDocsButton'
import { SimpleMarkdown } from './SimpleMarkdown'
import { tablePagination } from '../utils/tablePagination'

type Role = {
  id: number
  name: string
  slug: string
  description: string
  is_system: boolean
  permissions: Record<string, string>
}

type PanelUser = {
  id: number
  username: string
  display_name: string
  is_active: boolean
  is_superadmin: boolean
  role_id: number | null
  role: { id: number; name: string; slug: string } | null
}

type ApiKeyRow = {
  id: number
  user_id: number
  name: string
  key_prefix: string
  expires_at: string | null
  last_used_at: string | null
  active: boolean
}

type CatalogModule = { key: string; label: string; group: string }

const LEVELS = [
  { value: 'none', label: 'No access' },
  { value: 'read', label: 'Read only' },
  { value: 'full', label: 'Full' },
]

export function AccessSettingsPanel() {
  const { can, profile, refresh: refreshAccess } = useAccess()
  const canRead = can('settings_access', 'read')
  const canWrite = can('settings_access', 'full')

  const [roles, setRoles] = useState<Role[]>([])
  const [users, setUsers] = useState<PanelUser[]>([])
  const [keys, setKeys] = useState<ApiKeyRow[]>([])
  const [catalog, setCatalog] = useState<CatalogModule[]>([])
  const [apiDoc, setApiDoc] = useState<{ title: string; body: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const [userOpen, setUserOpen] = useState(false)
  const [roleOpen, setRoleOpen] = useState(false)
  const [keyOpen, setKeyOpen] = useState(false)
  const [editRole, setEditRole] = useState<Role | null>(null)
  const [userForm] = Form.useForm()
  const [roleForm] = Form.useForm()
  const [keyForm] = Form.useForm()
  const rolePerms = Form.useWatch('permissions', roleForm)

  const load = useCallback(async () => {
    if (!canRead) return
    const [r, u, k, c, d] = await Promise.all([
      api<{ roles: Role[] }>('/api/access/roles'),
      api<{ users: PanelUser[] }>('/api/access/users'),
      api<{ keys: ApiKeyRow[] }>('/api/access/api-keys'),
      api<{ modules: CatalogModule[] }>('/api/access/catalog'),
      api<{ title: string; body: string }>('/api/access/docs/api/integration'),
    ])
    setRoles(r.roles)
    setUsers(u.users)
    setKeys(k.keys)
    setCatalog(c.modules)
    setApiDoc(d)
  }, [canRead])

  useEffect(() => {
    void load().catch((e) => message.error(String(e)))
  }, [load])

  const roleOptions = useMemo(
    () => roles.map((r) => ({ value: r.id, label: r.name })),
    [roles],
  )

  if (!canRead) {
    return (
      <Alert
        type="warning"
        showIcon
        message="No access to Users / Roles / API keys"
        description="Ask a Super Admin to grant the settings_access permission on your role."
      />
    )
  }

  const openRole = (role?: Role) => {
    setEditRole(role || null)
    const perms: Record<string, string> = {}
    for (const m of catalog) perms[m.key] = role?.permissions?.[m.key] || 'none'
    roleForm.setFieldsValue({
      name: role?.name || '',
      slug: role?.slug || '',
      description: role?.description || '',
      permissions: perms,
    })
    setRoleOpen(true)
  }

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12, gap: 12 }}>
        <Typography.Paragraph type="secondary" style={{ margin: 0, maxWidth: 640 }}>
          Manage panel login users, RBAC roles (none / read / full per module), and API keys for
          integrations. OS accounts stay under the Users page.
        </Typography.Paragraph>
        <Space>
          <ModuleDocsButton docKey="settings_access" />
          <ModuleDocsButton docKey="api_integration" label="API docs" />
        </Space>
      </div>

      <Tabs
        items={[
          {
            key: 'users',
            label: 'Users',
            children: (
              <>
                <Button
                  type="primary"
                  disabled={!canWrite}
                  style={{ marginBottom: 12 }}
                  onClick={() => {
                    userForm.resetFields()
                    userForm.setFieldsValue({
                      role_id: roles.find((r) => r.slug === 'viewer')?.id,
                      is_active: true,
                      is_superadmin: false,
                    })
                    setUserOpen(true)
                  }}
                >
                  Add user
                </Button>
                <Table
                  size="small"
                  rowKey="id"
                  dataSource={users}
                  pagination={tablePagination(10)}
                  columns={[
                    { title: 'Username', dataIndex: 'username', render: (v) => <span className="mono">{v}</span> },
                    { title: 'Display name', dataIndex: 'display_name' },
                    {
                      title: 'Role',
                      render: (_, r) =>
                        r.is_superadmin ? <Tag color="gold">Super Admin</Tag> : r.role?.name || '—',
                    },
                    {
                      title: 'Active',
                      dataIndex: 'is_active',
                      render: (v) => <Tag color={v ? 'success' : 'default'}>{v ? 'yes' : 'no'}</Tag>,
                    },
                    {
                      title: 'Actions',
                      render: (_, r) => (
                        <Space>
                          <Button
                            size="small"
                            disabled={!canWrite}
                            onClick={() => {
                              userForm.setFieldsValue({
                                display_name: r.display_name,
                                role_id: r.role_id,
                                is_active: r.is_active,
                                is_superadmin: r.is_superadmin,
                                password: '',
                              })
                              Modal.confirm({
                                title: `Edit user ${r.username}`,
                                width: 480,
                                content: (
                                  <Form form={userForm} layout="vertical" style={{ marginTop: 16 }}>
                                    <Form.Item name="display_name" label="Display name">
                                      <Input />
                                    </Form.Item>
                                    <Form.Item name="role_id" label="Role" rules={[{ required: true }]}>
                                      <Select options={roleOptions} />
                                    </Form.Item>
                                    <Form.Item name="password" label="New password (optional)">
                                      <Input.Password />
                                    </Form.Item>
                                    <Form.Item name="is_active" label="Active" valuePropName="checked">
                                      <Switch />
                                    </Form.Item>
                                    {profile?.is_superadmin ? (
                                      <Form.Item
                                        name="is_superadmin"
                                        label="Super Admin"
                                        valuePropName="checked"
                                      >
                                        <Switch />
                                      </Form.Item>
                                    ) : null}
                                  </Form>
                                ),
                                onOk: async () => {
                                  const values = await userForm.validateFields()
                                  await api(`/api/access/users/${r.id}`, {
                                    method: 'PUT',
                                    body: JSON.stringify({
                                      ...values,
                                      password: values.password || undefined,
                                    }),
                                  })
                                  message.success('User updated')
                                  await load()
                                  await refreshAccess()
                                },
                              })
                            }}
                          >
                            Edit
                          </Button>
                          <Button
                            size="small"
                            danger
                            disabled={!canWrite || r.id === profile?.user_id}
                            onClick={() =>
                              Modal.confirm({
                                title: `Delete ${r.username}?`,
                                onOk: async () => {
                                  await api(`/api/access/users/${r.id}`, { method: 'DELETE' })
                                  message.success('Deleted')
                                  await load()
                                },
                              })
                            }
                          >
                            Delete
                          </Button>
                        </Space>
                      ),
                    },
                  ]}
                />
              </>
            ),
          },
          {
            key: 'roles',
            label: 'Roles',
            children: (
              <>
                <Button
                  type="primary"
                  disabled={!canWrite}
                  style={{ marginBottom: 12 }}
                  onClick={() => openRole()}
                >
                  Create role
                </Button>
                <Table
                  size="small"
                  rowKey="id"
                  dataSource={roles}
                  pagination={tablePagination(10)}
                  columns={[
                    { title: 'Name', dataIndex: 'name' },
                    {
                      title: 'Slug',
                      dataIndex: 'slug',
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'System',
                      dataIndex: 'is_system',
                      render: (v) => (v ? <Tag>system</Tag> : '—'),
                    },
                    { title: 'Description', dataIndex: 'description', ellipsis: true },
                    {
                      title: 'Actions',
                      render: (_, r) => (
                        <Space>
                          <Button size="small" disabled={!canWrite} onClick={() => openRole(r)}>
                            Edit
                          </Button>
                          <Button
                            size="small"
                            danger
                            disabled={!canWrite || r.is_system}
                            onClick={() =>
                              Modal.confirm({
                                title: `Delete role ${r.name}?`,
                                onOk: async () => {
                                  await api(`/api/access/roles/${r.id}`, { method: 'DELETE' })
                                  message.success('Role deleted')
                                  await load()
                                },
                              })
                            }
                          >
                            Delete
                          </Button>
                        </Space>
                      ),
                    },
                  ]}
                />
              </>
            ),
          },
          {
            key: 'keys',
            label: 'API keys',
            children: (
              <>
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message="API keys are shown once at creation. Use Bearer or X-API-Key header."
                />
                <Button
                  type="primary"
                  disabled={!canWrite}
                  style={{ marginBottom: 12 }}
                  onClick={() => {
                    keyForm.resetFields()
                    keyForm.setFieldsValue({ user_id: profile?.user_id, expires_days: 365 })
                    setKeyOpen(true)
                  }}
                >
                  Create API key
                </Button>
                <Table
                  size="small"
                  rowKey="id"
                  dataSource={keys}
                  pagination={tablePagination(10)}
                  columns={[
                    { title: 'Name', dataIndex: 'name' },
                    {
                      title: 'Prefix',
                      dataIndex: 'key_prefix',
                      render: (v) => <span className="mono">lnx_{v}_…</span>,
                    },
                    {
                      title: 'User',
                      dataIndex: 'user_id',
                      render: (id) => users.find((u) => u.id === id)?.username || id,
                    },
                    {
                      title: 'Status',
                      render: (_, r) => (
                        <Tag color={r.active ? 'success' : 'default'}>
                          {r.active ? 'active' : 'revoked'}
                        </Tag>
                      ),
                    },
                    {
                      title: 'Last used',
                      dataIndex: 'last_used_at',
                      render: (v) => (v ? new Date(v).toLocaleString() : '—'),
                    },
                    {
                      title: 'Actions',
                      render: (_, r) => (
                        <Button
                          size="small"
                          danger
                          disabled={!canWrite || !r.active}
                          onClick={() =>
                            Modal.confirm({
                              title: `Revoke key “${r.name}”?`,
                              onOk: async () => {
                                await api(`/api/access/api-keys/${r.id}`, { method: 'DELETE' })
                                message.success('Revoked')
                                await load()
                              },
                            })
                          }
                        >
                          Revoke
                        </Button>
                      ),
                    },
                  ]}
                />
              </>
            ),
          },
          {
            key: 'api-docs',
            label: 'API documentation',
            children: apiDoc ? (
              <div>
                <Typography.Title level={4}>{apiDoc.title}</Typography.Title>
                <SimpleMarkdown text={apiDoc.body} />
              </div>
            ) : (
              <Typography.Text type="secondary">Loading…</Typography.Text>
            ),
          },
        ]}
      />

      <Modal
        title="Add panel user"
        open={userOpen}
        onCancel={() => setUserOpen(false)}
        confirmLoading={busy}
        onOk={() => userForm.submit()}
        destroyOnHidden
      >
        <Form
          form={userForm}
          layout="vertical"
          onFinish={(values) => {
            setBusy(true)
            void api('/api/access/users', { method: 'POST', body: JSON.stringify(values) })
              .then(async () => {
                message.success('User created')
                setUserOpen(false)
                await load()
              })
              .catch((e) => message.error(String(e)))
              .finally(() => setBusy(false))
          }}
        >
          <Form.Item name="username" label="Username" rules={[{ required: true }]}>
            <Input className="mono" />
          </Form.Item>
          <Form.Item name="display_name" label="Display name">
            <Input />
          </Form.Item>
          <Form.Item name="password" label="Password" rules={[{ required: true, min: 8 }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="role_id" label="Role" rules={[{ required: true }]}>
            <Select options={roleOptions} />
          </Form.Item>
          <Form.Item name="is_active" label="Active" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editRole ? `Edit role — ${editRole.name}` : 'Create role'}
        open={roleOpen}
        onCancel={() => setRoleOpen(false)}
        width={720}
        confirmLoading={busy}
        onOk={() => roleForm.submit()}
        destroyOnHidden
      >
        <Form
          form={roleForm}
          layout="vertical"
          onFinish={(values) => {
            setBusy(true)
            const path = editRole ? `/api/access/roles/${editRole.id}` : '/api/access/roles'
            const method = editRole ? 'PUT' : 'POST'
            void api(path, { method, body: JSON.stringify(values) })
              .then(async () => {
                message.success('Role saved')
                setRoleOpen(false)
                await load()
              })
              .catch((e) => message.error(String(e)))
              .finally(() => setBusy(false))
          }}
        >
          <Form.Item name="name" label="Name" rules={[{ required: true }]}>
            <Input disabled={editRole?.slug === 'superadmin'} />
          </Form.Item>
          {!editRole ? (
            <Form.Item name="slug" label="Slug" extra="Optional; auto from name">
              <Input className="mono" placeholder="operator-custom" />
            </Form.Item>
          ) : null}
          <Form.Item name="description" label="Description">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Typography.Text strong>Module permissions</Typography.Text>
          <div style={{ marginTop: 8, maxHeight: 360, overflow: 'auto' }}>
            {catalog.map((m) => (
              <div
                key={m.key}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  gap: 12,
                  padding: '6px 0',
                  borderBottom: '1px solid var(--la-panel-border)',
                }}
              >
                <div>
                  <div>{m.label}</div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {m.group} · <span className="mono">{m.key}</span>
                  </Typography.Text>
                </div>
                <Form.Item
                  name={['permissions', m.key]}
                  style={{ margin: 0, minWidth: 140 }}
                  initialValue={rolePerms?.[m.key] || 'none'}
                >
                  <Select
                    options={LEVELS}
                    disabled={editRole?.slug === 'superadmin'}
                  />
                </Form.Item>
              </div>
            ))}
          </div>
        </Form>
      </Modal>

      <Modal
        title="Create API key"
        open={keyOpen}
        onCancel={() => setKeyOpen(false)}
        confirmLoading={busy}
        onOk={() => keyForm.submit()}
        destroyOnHidden
      >
        <Form
          form={keyForm}
          layout="vertical"
          onFinish={(values) => {
            setBusy(true)
            void api<{ token: string; warning: string }>('/api/access/api-keys', {
              method: 'POST',
              body: JSON.stringify(values),
            })
              .then(async (res) => {
                setKeyOpen(false)
                await load()
                Modal.info({
                  title: 'Copy your API key',
                  width: 560,
                  content: (
                    <div>
                      <Alert type="warning" showIcon message={res.warning} style={{ marginBottom: 12 }} />
                      <Input.TextArea className="mono" value={res.token} rows={3} readOnly />
                    </div>
                  ),
                })
              })
              .catch((e) => message.error(String(e)))
              .finally(() => setBusy(false))
          }}
        >
          <Form.Item name="name" label="Name" rules={[{ required: true }]}>
            <Input placeholder="ci-monitoring" />
          </Form.Item>
          <Form.Item name="user_id" label="Owner user" rules={[{ required: true }]}>
            <Select
              options={users.map((u) => ({ value: u.id, label: u.username }))}
              disabled={!profile?.is_superadmin}
            />
          </Form.Item>
          <Form.Item name="expires_days" label="Expires in days (optional)">
            <InputNumber style={{ width: '100%' }} min={1} max={3650} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
