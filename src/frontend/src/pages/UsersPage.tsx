import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Col,
  Descriptions,
  Drawer,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  LockOutlined,
  UnlockOutlined,
  PlusOutlined,
  DeleteOutlined,
  ReloadOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { tablePagination } from '../utils/tablePagination'

type SysUser = {
  username: string
  uid: number
  gid: number
  primary_group: string
  gecos: string
  home: string
  shell: string
  locked: boolean | null
  groups: string[]
  system: boolean
}

type SysGroup = {
  name: string
  gid: number
  members: string[]
  members_count: number
  system: boolean
  primary_members?: string[]
}

type Overview = {
  available: boolean
  disabled?: boolean
  error?: string
  users: SysUser[]
  groups: SysGroup[]
  shells?: string[]
  allow_mutations?: boolean
  can_read_shadow?: boolean
  min_uid?: number
}

export function UsersPage() {
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [userDrawer, setUserDrawer] = useState<SysUser | null>(null)
  const [groupDrawer, setGroupDrawer] = useState<SysGroup | null>(null)
  const [createUserOpen, setCreateUserOpen] = useState(false)
  const [createGroupOpen, setCreateGroupOpen] = useState(false)
  const [userForm] = Form.useForm()
  const [groupForm] = Form.useForm()
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    void api<Overview>('/api/users')
      .then(setData)
      .catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const users = useMemo(() => {
    const q = filter.trim().toLowerCase()
    const rows = data?.users || []
    if (!q) return rows
    return rows.filter(
      (u) =>
        u.username.toLowerCase().includes(q) ||
        u.home.toLowerCase().includes(q) ||
        u.shell.toLowerCase().includes(q) ||
        String(u.uid).includes(q) ||
        u.groups.some((g) => g.toLowerCase().includes(q)),
    )
  }, [data, filter])

  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase()
    const rows = data?.groups || []
    if (!q) return rows
    return rows.filter(
      (g) =>
        g.name.toLowerCase().includes(q) ||
        String(g.gid).includes(q) ||
        g.members.some((m) => m.toLowerCase().includes(q)),
    )
  }, [data, filter])

  const runMut = async (fn: () => Promise<any>, okMsg: string) => {
    setBusy(true)
    try {
      const res = await fn()
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

  const openUser = async (username: string) => {
    try {
      const detail = await api<{ available: boolean; user?: SysUser; error?: string }>(
        `/api/users/${encodeURIComponent(username)}`,
      )
      if (detail.user) setUserDrawer(detail.user)
      else message.error(detail.error || 'Not found')
    } catch (e) {
      message.error(String(e))
    }
  }

  const openGroup = async (name: string) => {
    try {
      const detail = await api<{ available: boolean; group?: SysGroup; error?: string }>(
        `/api/users/groups/${encodeURIComponent(name)}`,
      )
      if (detail.group) setGroupDrawer(detail.group)
      else message.error(detail.error || 'Not found')
    } catch (e) {
      message.error(String(e))
    }
  }

  if (error) return <Alert type="error" message={error} showIcon />
  if (!data) return <Typography.Text type="secondary">Loading…</Typography.Text>

  if (data.disabled || data.available === false) {
    return (
      <div className="la-page">
        <PageHeader title="Users & Groups" />
        <Alert type="warning" showIcon message={data.error || 'Module unavailable'} />
      </div>
    )
  }

  return (
    <div className="la-page">
      <PageHeader
        title="Users & Groups"
        subtitle="Host system users and groups — view and manage"
        extra={
          <Space wrap>
            <Input.Search
              allowClear
              placeholder="Search…"
              style={{ width: 220 }}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <Button icon={<ReloadOutlined />} onClick={load}>
              Refresh
            </Button>
            {data.allow_mutations ? (
              <>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateUserOpen(true)}>
                  User
                </Button>
                <Button icon={<PlusOutlined />} onClick={() => setCreateGroupOpen(true)}>
                  Group
                </Button>
              </>
            ) : null}
          </Space>
        }
      />

      {!data.allow_mutations ? (
        <Alert
          type="info"
          showIcon
          message="Read-only mode"
          description="To create/modify users, enable “Allow changes” in Settings → Modules → Users and configure sudoers (see README)."
        />
      ) : null}

      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Panel title="Users">
            <div className="mono display" style={{ fontSize: 32, fontWeight: 700 }}>
              {data.users?.length || 0}
            </div>
          </Panel>
        </Col>
        <Col xs={12} md={6}>
          <Panel title="Groups">
            <div className="mono display" style={{ fontSize: 32, fontWeight: 700 }}>
              {data.groups?.length || 0}
            </div>
          </Panel>
        </Col>
        <Col xs={12} md={6}>
          <Panel title="Shadow">
            <Tag color={data.can_read_shadow ? 'success' : 'default'}>
              {data.can_read_shadow ? 'available' : 'no access'}
            </Tag>
          </Panel>
        </Col>
        <Col xs={12} md={6}>
          <Panel title="Mutations">
            <Tag color={data.allow_mutations ? 'success' : 'warning'}>
              {data.allow_mutations ? 'allowed' : 'denied'}
            </Tag>
          </Panel>
        </Col>
      </Row>

      <Panel padded={false} bodyStyle={{ padding: '4px 12px 12px' }}>
        <Tabs
          items={[
            {
              key: 'users',
              label: (
                <span>
                  <UserOutlined /> Users ({users.length})
                </span>
              ),
              children: (
                <Table
                  size="small"
                  rowKey="username"
                  pagination={tablePagination(25)}
                  dataSource={users}
                  onRow={(r) => ({
                    onClick: () => void openUser(r.username),
                    style: { cursor: 'pointer' },
                  })}
                  columns={[
                    {
                      title: 'User',
                      dataIndex: 'username',
                      render: (v, r) => (
                        <Space>
                          <span className="mono" style={{ fontWeight: 600 }}>
                            {v}
                          </span>
                          {r.system ? <Tag>system</Tag> : null}
                        </Space>
                      ),
                    },
                    {
                      title: 'UID',
                      dataIndex: 'uid',
                      width: 80,
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'Groups',
                      dataIndex: 'groups',
                      ellipsis: true,
                      render: (v: string[]) => (
                        <span className="mono" style={{ fontSize: 12 }}>
                          {(v || []).slice(0, 4).join(', ')}
                          {(v || []).length > 4 ? '…' : ''}
                        </span>
                      ),
                    },
                    {
                      title: 'Home',
                      dataIndex: 'home',
                      ellipsis: true,
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'Shell',
                      dataIndex: 'shell',
                      width: 140,
                      ellipsis: true,
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'Lock',
                      dataIndex: 'locked',
                      width: 90,
                      render: (v) =>
                        v == null ? (
                          <Tag>—</Tag>
                        ) : v ? (
                          <Tag color="error" icon={<LockOutlined />}>
                            lock
                          </Tag>
                        ) : (
                          <Tag color="success" icon={<UnlockOutlined />}>
                            ok
                          </Tag>
                        ),
                    },
                  ]}
                />
              ),
            },
            {
              key: 'groups',
              label: (
                <span>
                  <TeamOutlined /> Groups ({groups.length})
                </span>
              ),
              children: (
                <Table
                  size="small"
                  rowKey="name"
                  pagination={tablePagination(25)}
                  dataSource={groups}
                  onRow={(r) => ({
                    onClick: () => void openGroup(r.name),
                    style: { cursor: 'pointer' },
                  })}
                  columns={[
                    {
                      title: 'Group',
                      dataIndex: 'name',
                      render: (v, r) => (
                        <Space>
                          <span className="mono" style={{ fontWeight: 600 }}>
                            {v}
                          </span>
                          {r.system ? <Tag>system</Tag> : null}
                        </Space>
                      ),
                    },
                    {
                      title: 'GID',
                      dataIndex: 'gid',
                      width: 80,
                      render: (v) => <span className="mono">{v}</span>,
                    },
                    {
                      title: 'Members',
                      dataIndex: 'members_count',
                      width: 100,
                    },
                    {
                      title: 'List',
                      dataIndex: 'members',
                      ellipsis: true,
                      render: (v: string[]) => (
                        <span className="mono" style={{ fontSize: 12 }}>
                          {(v || []).join(', ') || '—'}
                        </span>
                      ),
                    },
                  ]}
                />
              ),
            },
          ]}
        />
      </Panel>

      <Drawer
        title={userDrawer ? `User · ${userDrawer.username}` : 'User'}
        open={!!userDrawer}
        onClose={() => setUserDrawer(null)}
        width={480}
        destroyOnHidden
      >
        {userDrawer ? (
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="UID">
                <span className="mono">{userDrawer.uid}</span>
              </Descriptions.Item>
              <Descriptions.Item label="GID / primary">
                <span className="mono">
                  {userDrawer.gid} · {userDrawer.primary_group}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="GECOS">{userDrawer.gecos || '—'}</Descriptions.Item>
              <Descriptions.Item label="Home">
                <span className="mono">{userDrawer.home}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Shell">
                <span className="mono">{userDrawer.shell}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Groups">
                <Space wrap>
                  {(userDrawer.groups || []).map((g) => (
                    <Tag key={g} className="mono">
                      {g}
                    </Tag>
                  ))}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="Locked">
                {userDrawer.locked == null
                  ? 'n/a'
                  : userDrawer.locked
                    ? 'yes'
                    : 'no'}
              </Descriptions.Item>
            </Descriptions>

            {data.allow_mutations ? (
              <Space wrap>
                <Button
                  icon={userDrawer.locked ? <UnlockOutlined /> : <LockOutlined />}
                  loading={busy}
                  onClick={() =>
                    void runMut(
                      () =>
                        api(`/api/users/${encodeURIComponent(userDrawer.username)}/lock`, {
                          method: 'POST',
                          body: JSON.stringify({ locked: !userDrawer.locked }),
                        }),
                      userDrawer.locked ? 'Unlocked' : 'Locked',
                    ).then((ok) => {
                      if (ok) void openUser(userDrawer.username)
                    })
                  }
                >
                  {userDrawer.locked ? 'Unlock' : 'Lock'}
                </Button>
                <Select
                  style={{ width: 200 }}
                  placeholder="Change shell"
                  options={(data.shells || []).map((s) => ({ value: s, label: s }))}
                  onChange={(shell) =>
                    void runMut(
                      () =>
                        api(`/api/users/${encodeURIComponent(userDrawer.username)}/shell`, {
                          method: 'POST',
                          body: JSON.stringify({ shell }),
                        }),
                      'Shell updated',
                    ).then((ok) => {
                      if (ok) void openUser(userDrawer.username)
                    })
                  }
                />
                <Button
                  loading={busy}
                  onClick={() => {
                    let pwd = ''
                    Modal.confirm({
                      title: `Password · ${userDrawer.username}`,
                      content: (
                        <Input.Password
                          placeholder="New password"
                          onChange={(e) => {
                            pwd = e.target.value
                          }}
                        />
                      ),
                      onOk: () =>
                        runMut(
                          () =>
                            api(
                              `/api/users/${encodeURIComponent(userDrawer.username)}/password`,
                              {
                                method: 'POST',
                                body: JSON.stringify({ password: pwd }),
                              },
                            ),
                          'Password updated',
                        ),
                    })
                  }}
                >
                  Password
                </Button>
                <Select
                  mode="multiple"
                  style={{ minWidth: 220 }}
                  placeholder="Groups"
                  value={userDrawer.groups}
                  options={(data.groups || []).map((g) => ({ value: g.name, label: g.name }))}
                  onChange={(groups) =>
                    void runMut(
                      () =>
                        api(`/api/users/${encodeURIComponent(userDrawer.username)}/groups`, {
                          method: 'POST',
                          body: JSON.stringify({ groups }),
                        }),
                      'Groups updated',
                    ).then((ok) => {
                      if (ok) void openUser(userDrawer.username)
                    })
                  }
                />
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  loading={busy}
                  onClick={() => {
                    Modal.confirm({
                      title: `Delete ${userDrawer.username}?`,
                      content: 'You can also remove the home directory.',
                      okText: 'Delete',
                      okType: 'danger',
                      onOk: () =>
                        runMut(
                          () =>
                            api(
                              `/api/users/${encodeURIComponent(userDrawer.username)}?remove_home=false`,
                              { method: 'DELETE' },
                            ),
                          'Deleted',
                        ).then((ok) => {
                          if (ok) setUserDrawer(null)
                        }),
                    })
                  }}
                >
                  Delete
                </Button>
                <Button
                  danger
                  loading={busy}
                  onClick={() => {
                    Modal.confirm({
                      title: `Delete ${userDrawer.username} including home?`,
                      okText: 'Delete with home',
                      okType: 'danger',
                      onOk: () =>
                        runMut(
                          () =>
                            api(
                              `/api/users/${encodeURIComponent(userDrawer.username)}?remove_home=true`,
                              { method: 'DELETE' },
                            ),
                          'Deleted with home',
                        ).then((ok) => {
                          if (ok) setUserDrawer(null)
                        }),
                    })
                  }}
                >
                  Delete + home
                </Button>
              </Space>
            ) : null}
          </Space>
        ) : null}
      </Drawer>

      <Drawer
        title={groupDrawer ? `Group · ${groupDrawer.name}` : 'Group'}
        open={!!groupDrawer}
        onClose={() => setGroupDrawer(null)}
        width={440}
        destroyOnHidden
      >
        {groupDrawer ? (
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="GID">
                <span className="mono">{groupDrawer.gid}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Members">
                <Space wrap>
                  {(groupDrawer.members || []).map((m) => (
                    <Tag key={m} className="mono">
                      {m}
                    </Tag>
                  ))}
                  {!groupDrawer.members?.length ? '—' : null}
                </Space>
              </Descriptions.Item>
              {groupDrawer.primary_members?.length ? (
                <Descriptions.Item label="Primary for">
                  <Space wrap>
                    {groupDrawer.primary_members.map((m) => (
                      <Tag key={m} className="mono">
                        {m}
                      </Tag>
                    ))}
                  </Space>
                </Descriptions.Item>
              ) : null}
            </Descriptions>

            {data.allow_mutations ? (
              <Space wrap>
                <Select
                  showSearch
                  style={{ width: 200 }}
                  placeholder="Add user"
                  options={(data.users || []).map((u) => ({
                    value: u.username,
                    label: u.username,
                  }))}
                  onChange={(username) =>
                    void runMut(
                      () =>
                        api(`/api/users/groups/${encodeURIComponent(groupDrawer.name)}/members`, {
                          method: 'POST',
                          body: JSON.stringify({ username }),
                        }),
                      'Added',
                    ).then((ok) => {
                      if (ok) void openGroup(groupDrawer.name)
                    })
                  }
                />
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  loading={busy}
                  onClick={() => {
                    Modal.confirm({
                      title: `Delete group ${groupDrawer.name}?`,
                      okType: 'danger',
                      onOk: () =>
                        runMut(
                          () =>
                            api(`/api/users/groups/${encodeURIComponent(groupDrawer.name)}`, {
                              method: 'DELETE',
                            }),
                          'Group deleted',
                        ).then((ok) => {
                          if (ok) setGroupDrawer(null)
                        }),
                    })
                  }}
                >
                  Delete group
                </Button>
              </Space>
            ) : null}
          </Space>
        ) : null}
      </Drawer>

      <Modal
        title="New user"
        open={createUserOpen}
        onCancel={() => setCreateUserOpen(false)}
        onOk={() => userForm.submit()}
        confirmLoading={busy}
        destroyOnHidden
      >
        <Form
          form={userForm}
          layout="vertical"
          initialValues={{ shell: '/bin/bash', create_home: true }}
          onFinish={(values) =>
            void runMut(
              () =>
                api('/api/users', {
                  method: 'POST',
                  body: JSON.stringify(values),
                }),
              'User created',
            ).then((ok) => {
              if (ok) {
                setCreateUserOpen(false)
                userForm.resetFields()
              }
            })
          }
        >
          <Form.Item name="username" label="Username" rules={[{ required: true }]}>
            <Input autoFocus />
          </Form.Item>
          <Form.Item name="password" label="Password">
            <Input.Password />
          </Form.Item>
          <Form.Item name="shell" label="Shell">
            <Select options={(data.shells || []).map((s) => ({ value: s, label: s }))} />
          </Form.Item>
          <Form.Item name="home" label="Home (optional)">
            <Input placeholder="/home/username" />
          </Form.Item>
          <Form.Item name="groups" label="Extra groups">
            <Select
              mode="multiple"
              options={(data.groups || []).map((g) => ({ value: g.name, label: g.name }))}
            />
          </Form.Item>
          <Form.Item name="comment" label="GECOS / comment">
            <Input />
          </Form.Item>
          <Form.Item name="create_home" label="Create home" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="New group"
        open={createGroupOpen}
        onCancel={() => setCreateGroupOpen(false)}
        onOk={() => groupForm.submit()}
        confirmLoading={busy}
        destroyOnHidden
      >
        <Form
          form={groupForm}
          layout="vertical"
          onFinish={(values) =>
            void runMut(
              () =>
                api('/api/users/groups', {
                  method: 'POST',
                  body: JSON.stringify(values),
                }),
              'Group created',
            ).then((ok) => {
              if (ok) {
                setCreateGroupOpen(false)
                groupForm.resetFields()
              }
            })
          }
        >
          <Form.Item name="name" label="Group name" rules={[{ required: true }]}>
            <Input autoFocus />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
