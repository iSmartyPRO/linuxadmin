import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Breadcrumb,
  Button,
  Col,
  Progress,
  Row,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  FolderOutlined,
  FileOutlined,
  LinkOutlined,
  ReloadOutlined,
  ArrowUpOutlined,
  HddOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'
import { useAppSettings } from '../api/settings'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { formatBytes, pctColor } from '../utils/format'
import { tablePagination } from '../utils/tablePagination'

type Partition = {
  device: string
  mountpoint: string
  fstype: string
  opts?: string
  total: number
  used: number
  free: number
  percent: number
  inodes_total?: number | null
  inodes_used?: number | null
  inodes_percent?: number | null
}

type IoDevice = {
  name: string
  read_bytes: number
  write_bytes: number
  read_count: number
  write_count: number
}

type DisksData = {
  available: boolean
  disabled?: boolean
  error?: string | null
  partitions: Partition[]
  count?: number
  io?: {
    read_bytes: number
    write_bytes: number
    read_count: number
    write_count: number
    devices: IoDevice[]
  }
}

type BrowseEntry = {
  name: string
  path: string
  kind: 'dir' | 'file' | 'symlink' | 'other'
  size: number | null
  size_truncated?: boolean
  mtime?: number
  mode?: string
  browsable?: boolean
}

type BrowseData = {
  available: boolean
  disabled?: boolean
  error?: string | null
  path?: string
  parent?: string | null
  mount_root?: string
  breadcrumb?: Array<{ name: string; path: string }>
  entries: BrowseEntry[]
  truncated?: boolean
  parent_size?: number | null
  disk?: { total: number; used: number; free: number; percent: number }
}

function kindIcon(kind: string) {
  if (kind === 'dir') return <FolderOutlined style={{ color: 'var(--la-accent-deep)' }} />
  if (kind === 'symlink') return <LinkOutlined style={{ color: 'var(--la-muted)' }} />
  return <FileOutlined style={{ color: 'var(--la-muted)' }} />
}

export function DisksPage() {
  const { moduleOpts } = useAppSettings()
  const opts = moduleOpts('disks')
  const [data, setData] = useState<DisksData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [browsePath, setBrowsePath] = useState<string | null>(null)
  const [browse, setBrowse] = useState<BrowseData | null>(null)
  const [browseLoading, setBrowseLoading] = useState(false)
  const [browseError, setBrowseError] = useState<string | null>(null)

  const load = useCallback(() => {
    void api<DisksData>('/api/disks')
      .then(setData)
      .catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [load])

  const loadBrowse = useCallback(
    (path: string) => {
      if (opts.allow_browse === false) return
      setBrowsePath(path)
      setBrowseLoading(true)
      setBrowseError(null)
      void api<BrowseData>(`/api/disks/browse?path=${encodeURIComponent(path)}`)
        .then((res) => {
          setBrowse(res)
          if (!res.available && res.error) setBrowseError(res.error)
        })
        .catch((e) => setBrowseError(String(e)))
        .finally(() => setBrowseLoading(false))
    },
    [opts.allow_browse],
  )

  const maxEntrySize = useMemo(() => {
    const sizes = (browse?.entries || []).map((e) => e.size || 0)
    return Math.max(1, ...sizes)
  }, [browse])

  if (error) return <Alert type="error" message={error} showIcon />
  if (!data) return <Typography.Text type="secondary">Loading…</Typography.Text>
  if (data.disabled) {
    return <Alert type="warning" message={data.error || 'Disks module disabled'} showIcon />
  }

  return (
    <div className="la-page">
      <PageHeader
        docsKey="disks"
        title="Disks"
        subtitle={
          data.partitions?.length
            ? `${data.partitions.length} volume(s) · I/O ↓ ${formatBytes(data.io?.read_bytes)} ↑ ${formatBytes(data.io?.write_bytes)}`
            : 'Partitions and disk usage analysis'
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={load}>
            Refresh
          </Button>
        }
      />

      <Row gutter={[16, 16]}>
        {(data.partitions || []).map((p) => (
          <Col xs={24} md={12} xl={8} key={`${p.device}:${p.mountpoint}`}>
            <Panel
              title={
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <HddOutlined />
                  <span className="mono">{p.mountpoint}</span>
                </span>
              }
              extra={
                opts.allow_browse !== false ? (
                  <Button
                    type="link"
                    size="small"
                    onClick={() => loadBrowse(p.mountpoint)}
                  >
                    Analyze
                  </Button>
                ) : null
              }
            >
              <div style={{ marginBottom: 10 }}>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    marginBottom: 6,
                    fontSize: 13,
                  }}
                >
                  <span style={{ color: 'var(--la-muted)' }}>
                    {formatBytes(p.used)} / {formatBytes(p.total)}
                  </span>
                  <span className="mono" style={{ color: pctColor(p.percent), fontWeight: 600 }}>
                    {p.percent.toFixed(1)}%
                  </span>
                </div>
                <Progress
                  percent={Math.min(100, p.percent)}
                  showInfo={false}
                  strokeColor={pctColor(p.percent)}
                  trailColor="color-mix(in srgb, var(--la-muted) 18%, transparent)"
                />
              </div>
              <Space wrap size={[8, 8]}>
                <Tag className="mono">{p.device}</Tag>
                <Tag>{p.fstype || '—'}</Tag>
                <Tag color="default">free {formatBytes(p.free)}</Tag>
                {p.inodes_percent != null ? (
                  <Tooltip title={`inodes ${p.inodes_used}/${p.inodes_total}`}>
                    <Tag>inodes {p.inodes_percent}%</Tag>
                  </Tooltip>
                ) : null}
              </Space>
              {p.opts ? (
                <div
                  className="mono"
                  style={{ marginTop: 10, fontSize: 11, color: 'var(--la-muted)', wordBreak: 'break-all' }}
                >
                  {p.opts}
                </div>
              ) : null}
            </Panel>
          </Col>
        ))}
      </Row>

      {data.io?.devices?.length ? (
        <Panel title="Disk I/O (cumulative)" style={{ marginTop: 16 }}>
          <Table
            size="small"
            rowKey="name"
            pagination={false}
            dataSource={data.io.devices}
            columns={[
              { title: 'Device', dataIndex: 'name', render: (v) => <span className="mono">{v}</span> },
              {
                title: 'Read',
                dataIndex: 'read_bytes',
                render: (v) => <span className="mono">{formatBytes(v)}</span>,
                sorter: (a, b) => a.read_bytes - b.read_bytes,
              },
              {
                title: 'Write',
                dataIndex: 'write_bytes',
                render: (v) => <span className="mono">{formatBytes(v)}</span>,
                sorter: (a, b) => a.write_bytes - b.write_bytes,
              },
              {
                title: 'Reads',
                dataIndex: 'read_count',
                render: (v) => <span className="mono">{v}</span>,
              },
              {
                title: 'Writes',
                dataIndex: 'write_count',
                render: (v) => <span className="mono">{v}</span>,
              },
            ]}
          />
        </Panel>
      ) : null}

      {opts.allow_browse !== false ? (
        <Panel
          title="Disk usage analysis"
          style={{ marginTop: 16 }}
          extra={
            browsePath ? (
              <Space>
                {browse?.parent ? (
                  <Button
                    size="small"
                    icon={<ArrowUpOutlined />}
                    onClick={() => loadBrowse(browse.parent!)}
                    disabled={browseLoading}
                  >
                    Up
                  </Button>
                ) : null}
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  loading={browseLoading}
                  onClick={() => browsePath && loadBrowse(browsePath)}
                >
                  Recalculate
                </Button>
              </Space>
            ) : null
          }
        >
          {!browsePath ? (
            <Typography.Text type="secondary">
              Click “Analyze” on a volume above or select a directory to see folder and
              file sizes.
            </Typography.Text>
          ) : (
            <>
              {browseError ? (
                <Alert type="error" message={browseError} showIcon style={{ marginBottom: 12 }} />
              ) : null}
              {browse?.truncated ? (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message="Listing or sizes were truncated by timeout/limit — very large trees may be incomplete."
                />
              ) : null}

              <div style={{ marginBottom: 12 }}>
                <Breadcrumb
                  items={(browse?.breadcrumb || [{ name: browsePath, path: browsePath }]).map(
                    (b) => ({
                      title: (
                        <a
                          onClick={(e) => {
                            e.preventDefault()
                            loadBrowse(b.path)
                          }}
                          className="mono"
                        >
                          {b.name}
                        </a>
                      ),
                    }),
                  )}
                />
                {browse?.disk ? (
                  <div style={{ marginTop: 8, fontSize: 12, color: 'var(--la-muted)' }}>
                    Volume {browse.mount_root}: {formatBytes(browse.disk.used)} /{' '}
                    {formatBytes(browse.disk.total)} ({browse.disk.percent}%) · in directory ≈{' '}
                    <span className="mono">{formatBytes(browse.parent_size)}</span>
                  </div>
                ) : null}
              </div>

              <Table
                size="small"
                loading={browseLoading}
                rowKey="path"
                dataSource={browse?.entries || []}
                pagination={tablePagination(50)}
                onRow={(row) => ({
                  onClick: () => {
                    if (row.browsable) loadBrowse(row.path)
                  },
                  style: row.browsable ? { cursor: 'pointer' } : undefined,
                })}
                columns={[
                  {
                    title: 'Name',
                    dataIndex: 'name',
                    render: (name, row) => (
                      <Space>
                        {kindIcon(row.kind)}
                        <span className={row.kind === 'dir' ? '' : 'mono'}>{name}</span>
                        {row.kind === 'dir' ? <Tag>dir</Tag> : null}
                        {row.kind === 'symlink' ? <Tag>link</Tag> : null}
                        {row.size_truncated ? <Tag color="warning">partial</Tag> : null}
                      </Space>
                    ),
                  },
                  {
                    title: 'Size',
                    dataIndex: 'size',
                    width: 280,
                    defaultSortOrder: 'descend',
                    sorter: (a, b) => (a.size || 0) - (b.size || 0),
                    render: (size: number | null, row) => {
                      const pct = size != null ? Math.round((100 * size) / maxEntrySize) : 0
                      return (
                        <div>
                          <div
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              gap: 8,
                              marginBottom: 2,
                            }}
                          >
                            <span className="mono">{formatBytes(size)}</span>
                            {browse?.parent_size && size != null ? (
                              <span style={{ fontSize: 11, color: 'var(--la-muted)' }}>
                                {((100 * size) / browse.parent_size).toFixed(1)}%
                              </span>
                            ) : null}
                          </div>
                          <Progress
                            percent={pct}
                            showInfo={false}
                            size="small"
                            strokeColor={
                              row.kind === 'dir' ? 'var(--la-accent)' : 'var(--la-muted)'
                            }
                          />
                        </div>
                      )
                    },
                  },
                  {
                    title: 'Modified',
                    dataIndex: 'mtime',
                    width: 160,
                    render: (v?: number) =>
                      v ? (
                        <span className="mono" style={{ fontSize: 12 }}>
                          {new Date(v * 1000).toLocaleString()}
                        </span>
                      ) : (
                        '—'
                      ),
                  },
                  {
                    title: 'mode',
                    dataIndex: 'mode',
                    width: 80,
                    render: (v) => <span className="mono">{v || '—'}</span>,
                  },
                ]}
              />
            </>
          )}
        </Panel>
      ) : (
        <Alert
          style={{ marginTop: 16 }}
          type="info"
          showIcon
          message="Directory browsing is disabled in Disks module settings"
        />
      )}
    </div>
  )
}
