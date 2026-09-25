import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import {
  Button,
  Empty,
  Input,
  Modal,
  Select,
  Spin,
  Switch,
  Tooltip,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  FolderAddOutlined,
  FileAddOutlined,
  ReloadOutlined,
  SearchOutlined,
  UploadOutlined,
  AppstoreOutlined,
  UnorderedListOutlined,
  EyeOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { api, apiDownload } from '../api/client'
import { useAccess } from '../api/access'
import { useAppSettings } from '../api/settings'
import { PageHeader } from '../components/PageHeader'
import { FileGlyph, glyphTone } from '../components/FileGlyph'
import { SimpleMarkdown } from '../components/SimpleMarkdown'
import { formatBytes } from '../utils/format'

type FmEntry = {
  name: string
  rel: string
  kind: 'dir' | 'file' | 'symlink' | 'other'
  hidden: boolean
  size: number | null
  mtime: string
  symlink: boolean
  escaped: boolean
  broken: boolean
  link_rel: string | null
  link_dir: boolean
  ext: string
  preview: 'image' | 'pdf' | 'markdown' | 'text' | 'audio' | 'video' | 'none'
  editable: boolean
}

type FmRoot = {
  id: string
  name: string
  path: string
  read_only: boolean
  writable: boolean
}

type ListResp = {
  root: FmRoot
  rel: string
  parent: string | null
  truncated: boolean
  entries: FmEntry[]
}

type Mount = { id: string; name: string; path: string; read_only?: boolean }

function apiError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e)
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown }
    if (typeof parsed.detail === 'string') return parsed.detail
  } catch {
    /* response body is already plain text */
  }
  return raw
}

function isDir(entry: FmEntry) {
  return entry.kind === 'dir' || entry.link_dir
}

/** Normalize API/path forms like ".", "./foo", "foo/bar/" → "", "foo", "foo/bar". */
function normRel(rel: string | null | undefined): string {
  let value = (rel || '').replace(/\\/g, '/').trim()
  while (value.startsWith('./')) value = value.slice(2)
  if (value === '.' || value === '/') return ''
  if (value.endsWith('/') && value.length > 1) value = value.slice(0, -1)
  return value
}

function parentRel(rel: string) {
  const clean = normRel(rel)
  const i = clean.lastIndexOf('/')
  return i === -1 ? '' : clean.slice(0, i)
}

function destOf(entry: FmEntry) {
  if (entry.link_dir && entry.link_rel) return normRel(entry.link_rel)
  return normRel(entry.rel)
}

/** "", "a", "a/b" for cwd "a/b". */
function ancestorRels(rel: string): string[] {
  const clean = normRel(rel)
  if (!clean) return ['']
  const parts = clean.split('/')
  const out = ['']
  for (let i = 0; i < parts.length; i += 1) out.push(parts.slice(0, i + 1).join('/'))
  return out
}

function isSelfOrDescendant(src: string, dest: string) {
  const from = normRel(src)
  const to = normRel(dest)
  if (!from) return true
  return to === from || to.startsWith(`${from}/`)
}

export function FileManagerPage() {
  const { rootId = '' } = useParams()
  const { moduleOpts } = useAppSettings()
  const { can } = useAccess()
  const filesMod = moduleOpts('files')
  const mounts = (Array.isArray(filesMod.roots) ? filesMod.roots : []) as Mount[]
  const mount = mounts.find((item) => item.id === rootId)

  if (!rootId && mounts[0]) return <Navigate to={`/files/${mounts[0].id}`} replace />
  if (!mounts.length) return <Unmounted />
  if (!mount) {
    return (
      <div className="la-page">
        <PageHeader title="Files" subtitle="This folder is no longer mounted." docsKey="files" />
        <div className="la-panel fm-empty">
          <Empty description="Choose another folder from the menu, or mount one in settings." />
          {can('settings_modules', 'read') ? (
            <Link to="/settings/module/files">
              <Button type="primary">File Manager settings</Button>
            </Link>
          ) : null}
        </div>
      </div>
    )
  }

  return <Explorer rootId={mount.id} mountName={mount.name} showHiddenDefault={!!filesMod.show_hidden} />
}

function Unmounted() {
  const { can } = useAccess()
  return (
    <div className="la-page">
      <PageHeader
        title="Files"
        subtitle="Mount a directory to browse it here. Each folder you add shows up in the menu under its own name."
        docsKey="files"
      />
      <div className="la-panel fm-empty">
        <FileGlyph tone="folder" size={72} />
        <h2 className="display">No folders mounted</h2>
        <p>Open module settings and attach one or more absolute paths. Names you set become the sidebar entries.</p>
        {can('settings_modules', 'read') ? (
          <Link to="/settings/module/files">
            <Button type="primary">Mount a folder</Button>
          </Link>
        ) : (
          <p>Ask an administrator to mount a folder.</p>
        )}
      </div>
    </div>
  )
}

function Explorer({
  rootId,
  mountName,
  showHiddenDefault,
}: {
  rootId: string
  mountName: string
  showHiddenDefault: boolean
}) {
  const { canMutate } = useAccess()
  const [cwd, setCwd] = useState('')
  const [parent, setParent] = useState<string | null>(null)
  const [rootMeta, setRootMeta] = useState<FmRoot | null>(null)
  const [entries, setEntries] = useState<FmEntry[]>([])
  const [tree, setTree] = useState<Record<string, FmEntry[]>>({})
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(['']))
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [truncated, setTruncated] = useState(false)
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<'name' | 'mtime' | 'size' | 'kind'>('name')
  const [view, setView] = useState<'grid' | 'list'>(() => (localStorage.getItem('lnxadmin_fm_view') === 'list' ? 'list' : 'grid'))
  const [showHidden, setShowHidden] = useState(showHiddenDefault)
  const [selected, setSelected] = useState<string | null>(null)
  const [openFile, setOpenFile] = useState<FmEntry | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [dropRel, setDropRel] = useState<string | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number; entry: FmEntry } | null>(null)
  const [dialog, setDialog] = useState<{ mode: 'mkdir' | 'touch' | 'rename'; value: string; rel: string } | null>(null)
  const [mover, setMover] = useState<{ entry: FmEntry; browse: string; rows: FmEntry[] } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const cwdRef = useRef('')
  cwdRef.current = cwd

  const canWrite = !!rootMeta?.writable && canMutate('files')

  const loadDir = useCallback(
    async (rel: string) => {
      const target = normRel(rel)
      setLoading(true)
      try {
        const chain = ancestorRels(target)
        const nextTree: Record<string, FmEntry[]> = {}
        let current: ListResp | null = null

        // Prefetch every ancestor so the left tree shows the path and stays expanded.
        for (const key of chain) {
          const data = await api<ListResp>(
            `/api/files/list?root_id=${encodeURIComponent(rootId)}&rel=${encodeURIComponent(key)}&hidden=${showHidden}`,
          )
          const normalized = normRel(data.rel)
          nextTree[normalized] = data.entries.filter(isDir).map((entry) => ({
            ...entry,
            rel: normRel(entry.rel),
            link_rel: entry.link_rel ? normRel(entry.link_rel) : null,
          }))
          if (normalized === target) current = { ...data, rel: normalized, parent: data.parent == null ? null : normRel(data.parent) }
        }

        if (!current) {
          message.error('Folder not found')
          return null
        }

        setCwd(current.rel)
        setParent(current.parent)
        setRootMeta(current.root)
        setEntries(
          current.entries.map((entry) => ({
            ...entry,
            rel: normRel(entry.rel),
            link_rel: entry.link_rel ? normRel(entry.link_rel) : null,
          })),
        )
        setTruncated(current.truncated)
        setTree((prev) => ({ ...prev, ...nextTree }))
        setExpanded((prev) => {
          const next = new Set(prev)
          chain.forEach((key) => next.add(key))
          return next
        })
        return current
      } catch (e) {
        message.error(apiError(e))
        return null
      } finally {
        setLoading(false)
      }
    },
    [rootId, showHidden],
  )

  const refresh = useCallback(async () => {
    const current = cwdRef.current
    const keys = new Set<string>(['', current])
    setExpanded((prev) => {
      prev.forEach((key) => keys.add(key))
      return prev
    })
    const next: Record<string, FmEntry[]> = {}
    for (const key of keys) {
      try {
        const data = await api<ListResp>(
          `/api/files/list?root_id=${encodeURIComponent(rootId)}&rel=${encodeURIComponent(key)}&hidden=${showHidden}`,
        )
        next[data.rel] = data.entries.filter(isDir)
        if (key === current) {
          setCwd(data.rel)
          setParent(data.parent)
          setRootMeta(data.root)
          setEntries(data.entries)
          setTruncated(data.truncated)
        }
      } catch {
        /* keep the rest of the tree if one folder disappeared */
      }
    }
    setTree(next)
  }, [rootId, showHidden])

  useEffect(() => {
    setTree({})
    setExpanded(new Set(['']))
    setSelected(null)
    setOpenFile(null)
    setQuery('')
    void loadDir('')
  }, [loadDir])

  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    window.addEventListener('click', close)
    window.addEventListener('scroll', close, true)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('scroll', close, true)
    }
  }, [menu])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    const rows = entries.filter((entry) => !q || entry.name.toLowerCase().includes(q))
    rows.sort((a, b) => {
      const rank = Number(isDir(a)) - Number(isDir(b))
      if (rank) return -rank
      if (sort === 'size') return (b.size || 0) - (a.size || 0)
      if (sort === 'mtime') return b.mtime.localeCompare(a.mtime)
      if (sort === 'kind') return a.ext.localeCompare(b.ext) || a.name.localeCompare(b.name)
      return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
    })
    return rows
  }, [entries, query, sort])

  async function uploadFiles(list: File[], dest: string) {
    if (!list.length || !canWrite) return
    setBusy(true)
    try {
      for (const file of list) {
        const body = new FormData()
        body.append('root_id', rootId)
        body.append('rel', dest)
        body.append('file', file, file.name)
        await api('/api/files/upload', { method: 'POST', body })
      }
      message.success(list.length === 1 ? 'Uploaded' : `Uploaded ${list.length} files`)
      await refresh()
    } catch (e) {
      message.error(apiError(e))
    } finally {
      setBusy(false)
    }
  }

  async function moveEntry(rel: string, dest: string, name?: string) {
    setBusy(true)
    try {
      await api('/api/files/move', {
        method: 'POST',
        body: JSON.stringify({ root_id: rootId, rel, dest_rel: dest, name: name || null }),
      })
      message.success(name ? 'Renamed' : 'Moved')
      if (openFile?.rel === rel) setOpenFile(null)
      await refresh()
    } catch (e) {
      message.error(apiError(e))
    } finally {
      setBusy(false)
    }
  }

  function askDelete(entry: FmEntry) {
    Modal.confirm({
      title: `Delete “${entry.name}”?`,
      content: isDir(entry) ? 'The folder and everything inside it will be removed from disk.' : 'This file will be removed from disk.',
      okText: 'Delete',
      okButtonProps: { danger: true },
      cancelText: 'Cancel',
      onOk: async () => {
        await api(`/api/files/entry?root_id=${encodeURIComponent(rootId)}&rel=${encodeURIComponent(entry.rel)}`, {
          method: 'DELETE',
        })
        if (openFile?.rel === entry.rel) setOpenFile(null)
        setSelected(null)
        await refresh()
      },
    })
  }

  function openEntry(entry: FmEntry) {
    if (entry.escaped || entry.broken) {
      message.warning(entry.broken ? 'This link is broken' : 'This link points outside the mounted folder')
      return
    }
    if (isDir(entry)) {
      void loadDir(destOf(entry))
      return
    }
    setSelected(entry.rel)
    setOpenFile(entry)
    setPreviewOpen(true)
  }

  async function onDrop(event: DragEvent, destRaw: string) {
    event.preventDefault()
    event.stopPropagation()
    setDropRel(null)
    const dest = normRel(destRaw)
    const from = normRel(event.dataTransfer.getData('application/x-fm-rel') || event.dataTransfer.getData('text/plain'))
    if (from) {
      if (!canWrite) return
      if (parentRel(from) === dest) {
        message.info('Already in this folder')
        return
      }
      if (isSelfOrDescendant(from, dest)) {
        message.warning('Cannot move a folder into itself')
        return
      }
      await moveEntry(from, dest)
      return
    }
    const files = Array.from(event.dataTransfer.files || [])
    if (files.length) await uploadFiles(files, dest)
  }

  function allowDrop(event: DragEvent, relRaw: string) {
    if (!canWrite) return
    const rel = normRel(relRaw)
    const dragging = event.dataTransfer.types.includes('application/x-fm-rel') || event.dataTransfer.types.includes('text/plain')
    if (dragging) {
      // Native types do not expose the value during dragover; still accept and validate on drop.
      event.preventDefault()
      event.dataTransfer.dropEffect = 'move'
      setDropRel(rel)
      return
    }
    if (event.dataTransfer.types.includes('Files')) {
      event.preventDefault()
      event.dataTransfer.dropEffect = 'copy'
      setDropRel(rel)
    }
  }

  async function submitDialog() {
    if (!dialog) return
    const name = dialog.value.trim()
    if (!name) return
    setBusy(true)
    try {
      if (dialog.mode === 'rename') {
        await api('/api/files/move', {
          method: 'POST',
          body: JSON.stringify({ root_id: rootId, rel: dialog.rel, dest_rel: parentRel(dialog.rel), name }),
        })
        message.success('Renamed')
      } else {
        const created = await api<{ rel: string }>(dialog.mode === 'mkdir' ? '/api/files/mkdir' : '/api/files/touch', {
          method: 'POST',
          body: JSON.stringify({ root_id: rootId, rel: cwd, name }),
        })
        message.success(dialog.mode === 'mkdir' ? 'Folder created' : 'File created')
        if (dialog.mode === 'touch') {
          setPreviewOpen(true)
          setOpenFile({
            name,
            rel: created.rel,
            kind: 'file',
            hidden: name.startsWith('.'),
            size: 0,
            mtime: new Date().toISOString(),
            symlink: false,
            escaped: false,
            broken: false,
            link_rel: null,
            link_dir: false,
            ext: name.includes('.') ? name.split('.').pop() || '' : '',
            preview: name.endsWith('.md') ? 'markdown' : 'text',
            editable: true,
          })
        }
      }
      setDialog(null)
      await refresh()
    } catch (e) {
      message.error(apiError(e))
    } finally {
      setBusy(false)
    }
  }

  async function openMover(entry: FmEntry) {
    try {
      const data = await api<ListResp>(
        `/api/files/list?root_id=${encodeURIComponent(rootId)}&rel=&hidden=${showHidden}`,
      )
      setMover({ entry, browse: data.rel, rows: data.entries.filter(isDir) })
    } catch (e) {
      message.error(apiError(e))
    }
  }

  async function browseMover(rel: string) {
    if (!mover) return
    const data = await api<ListResp>(
      `/api/files/list?root_id=${encodeURIComponent(rootId)}&rel=${encodeURIComponent(rel)}&hidden=${showHidden}`,
    )
    setMover({ ...mover, browse: data.rel, rows: data.entries.filter(isDir) })
  }

  async function download(entry: FmEntry) {
    try {
      const { blob, filename } = await apiDownload(
        `/api/files/raw?root_id=${encodeURIComponent(rootId)}&rel=${encodeURIComponent(entry.rel)}`,
      )
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename || entry.name
      link.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      message.error(apiError(e))
    }
  }

  function copyPath(entry: FmEntry | null) {
    const base = rootMeta?.path || ''
    const rel = entry?.rel || cwd
    const full = rel ? `${base}/${rel}` : base
    void navigator.clipboard.writeText(full).then(
      () => message.success('Path copied'),
      () => message.error('Could not copy'),
    )
  }

  const keyRef = useRef({ entries, selected, parent, canWrite, openEntry, loadDir, askDelete })
  keyRef.current = { entries, selected, parent, canWrite, openEntry, loadDir, askDelete }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const typing = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)
      if (typing) return
      const cur = keyRef.current
      const entry = cur.entries.find((item) => item.rel === cur.selected) || null
      if (event.key === 'Enter' && entry) {
        event.preventDefault()
        cur.openEntry(entry)
      } else if (event.key === 'Backspace' && cur.parent !== null) {
        event.preventDefault()
        void cur.loadDir(cur.parent)
      } else if (event.key === 'F2' && entry && cur.canWrite) {
        event.preventDefault()
        setDialog({ mode: 'rename', value: entry.name, rel: entry.rel })
      } else if (event.key === 'Delete' && entry && cur.canWrite) {
        event.preventDefault()
        cur.askDelete(entry)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const crumbs = cwd ? cwd.split('/') : []
  const abs = rootMeta ? (cwd ? `${rootMeta.path}/${cwd}` : rootMeta.path) : ''

  return (
    <div className="la-page fm-page">
      <PageHeader
        title={mountName}
        subtitle={abs || 'Loading folder…'}
        docsKey="files"
        extra={
          <>
            <Tooltip title="Refresh">
              <Button icon={<ReloadOutlined />} onClick={() => void refresh()} />
            </Tooltip>
            {canWrite ? (
              <>
                <Button icon={<FolderAddOutlined />} onClick={() => setDialog({ mode: 'mkdir', value: '', rel: cwd })}>
                  Folder
                </Button>
                <Button icon={<FileAddOutlined />} onClick={() => setDialog({ mode: 'touch', value: '', rel: cwd })}>
                  File
                </Button>
                <Button type="primary" icon={<UploadOutlined />} onClick={() => fileRef.current?.click()}>
                  Upload
                </Button>
              </>
            ) : null}
          </>
        }
      />

      {!canWrite ? (
        <div className="fm-banner">
          {rootMeta?.read_only
            ? 'This folder is mounted read-only.'
            : canMutate('files')
              ? 'Changes are off. Turn on Allow changes in File Manager settings to create, edit, and delete.'
              : 'You can browse and preview. Editing needs the File Manager full permission.'}
        </div>
      ) : null}

      <div className={`fm-shell ${previewOpen ? 'has-preview' : ''}`}>
        <aside className="fm-tree la-panel">
          <div className="fm-tree-head">Folders</div>
          <div className="fm-tree-scroll">
            <TreeRow
              label={mountName}
              depth={0}
              active={cwd === ''}
              inPath={cwd !== ''}
              open={expanded.has('')}
              drop={dropRel === ''}
              onOpen={() => void loadDir('')}
              onToggle={() =>
                setExpanded((prev) => {
                  const next = new Set(prev)
                  if (next.has('')) next.delete('')
                  else next.add('')
                  return next
                })
              }
              onDragOver={(event) => allowDrop(event, '')}
              onDrop={(event) => void onDrop(event, '')}
              onDragLeave={() => setDropRel(null)}
            />
            {expanded.has('') ? (
              <TreeBranch
                parent=""
                depth={1}
                tree={tree}
                expanded={expanded}
                cwd={cwd}
                dropRel={dropRel}
                onOpen={(rel) => void loadDir(rel)}
                onToggle={async (rel) => {
                  const willOpen = !expanded.has(rel)
                  setExpanded((prev) => {
                    const next = new Set(prev)
                    if (next.has(rel)) next.delete(rel)
                    else next.add(rel)
                    return next
                  })
                  if (willOpen && !tree[rel]) {
                    try {
                      const data = await api<ListResp>(
                        `/api/files/list?root_id=${encodeURIComponent(rootId)}&rel=${encodeURIComponent(rel)}&hidden=${showHidden}`,
                      )
                      const key = normRel(data.rel)
                      setTree((prev) => ({
                        ...prev,
                        [key]: data.entries.filter(isDir).map((entry) => ({
                          ...entry,
                          rel: normRel(entry.rel),
                          link_rel: entry.link_rel ? normRel(entry.link_rel) : null,
                        })),
                      }))
                    } catch (e) {
                      message.error(apiError(e))
                    }
                  }
                }}
                onDragOver={allowDrop}
                onDrop={(event, rel) => void onDrop(event, rel)}
                onDragLeave={() => setDropRel(null)}
              />
            ) : null}
          </div>
        </aside>

        <section
          className={`fm-main la-panel ${dropRel === cwd ? 'is-drop' : ''}`}
          onDragOver={(event) => allowDrop(event, cwd)}
          onDrop={(event) => void onDrop(event, cwd)}
          onDragLeave={(event) => {
            const next = event.relatedTarget
            if (!(next instanceof Node) || !event.currentTarget.contains(next)) setDropRel(null)
          }}
        >
          <div className="fm-toolbar">
            <Button
              type="text"
              icon={<ArrowLeftOutlined />}
              disabled={parent === null}
              onClick={() => parent !== null && void loadDir(parent)}
            />
            <div className="fm-crumbs">
              <button type="button" onClick={() => void loadDir('')}>
                {mountName}
              </button>
              {crumbs.map((part, index) => {
                const rel = crumbs.slice(0, index + 1).join('/')
                return (
                  <span key={rel}>
                    <span className="fm-crumb-sep">/</span>
                    <button type="button" onClick={() => void loadDir(rel)}>
                      {part}
                    </button>
                  </span>
                )
              })}
            </div>
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder="Filter"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              style={{ width: 180 }}
            />
            <Select
              size="middle"
              value={sort}
              onChange={setSort}
              style={{ width: 130 }}
              options={[
                { value: 'name', label: 'Name' },
                { value: 'mtime', label: 'Modified' },
                { value: 'size', label: 'Size' },
                { value: 'kind', label: 'Type' },
              ]}
            />
            <Tooltip title={showHidden ? 'Hide dotfiles' : 'Show hidden files'}>
              <Switch checked={showHidden} onChange={setShowHidden} />
            </Tooltip>
            <div className="fm-seg">
              <button
                type="button"
                className={view === 'grid' ? 'is-on' : ''}
                onClick={() => {
                  setView('grid')
                  localStorage.setItem('lnxadmin_fm_view', 'grid')
                }}
                aria-label="Grid"
              >
                <AppstoreOutlined />
              </button>
              <button
                type="button"
                className={view === 'list' ? 'is-on' : ''}
                onClick={() => {
                  setView('list')
                  localStorage.setItem('lnxadmin_fm_view', 'list')
                }}
                aria-label="List"
              >
                <UnorderedListOutlined />
              </button>
            </div>
          </div>

          {truncated ? <div className="fm-note">Showing the first 4000 entries.</div> : null}

          <div className="fm-scroll">
            {loading && !entries.length ? (
              <div className="fm-center">
                <Spin />
              </div>
            ) : visible.length === 0 ? (
              <div className="fm-center fm-empty-inline">
                <FileGlyph tone="folder" size={64} />
                <div>{query ? 'Nothing matches this filter' : 'This folder is empty'}</div>
              </div>
            ) : view === 'grid' ? (
              <div className="fm-grid">
                {visible.map((entry) => (
                  <Tile
                    key={entry.rel}
                    entry={entry}
                    selected={selected === entry.rel}
                    drop={dropRel === destOf(entry)}
                    canWrite={canWrite}
                    onSelect={() => {
                      setSelected(entry.rel)
                      if (previewOpen && !isDir(entry)) setOpenFile(entry)
                    }}
                    onOpen={() => openEntry(entry)}
                    onContext={(event) => {
                      event.preventDefault()
                      setSelected(entry.rel)
                      setMenu({ x: event.clientX, y: event.clientY, entry })
                    }}
                    onDragOver={isDir(entry) ? (event) => allowDrop(event, destOf(entry)) : undefined}
                    onDrop={isDir(entry) ? (event) => void onDrop(event, destOf(entry)) : undefined}
                  />
                ))}
              </div>
            ) : (
              <div className="fm-list">
                <div className="fm-list-head">
                  <span>Name</span>
                  <span>Modified</span>
                  <span>Size</span>
                  <span>Kind</span>
                </div>
                {visible.map((entry) => (
                  <div
                    key={entry.rel}
                    className={`fm-list-row ${selected === entry.rel ? 'is-selected' : ''} ${dropRel === destOf(entry) ? 'is-drop' : ''}`}
                    draggable={canWrite}
                    onClick={() => {
                      setSelected(entry.rel)
                      if (previewOpen && !isDir(entry)) setOpenFile(entry)
                    }}
                    onDoubleClick={() => openEntry(entry)}
                    onContextMenu={(event) => {
                      event.preventDefault()
                      setSelected(entry.rel)
                      setMenu({ x: event.clientX, y: event.clientY, entry })
                    }}
                    onDragStart={(event) => {
                      event.dataTransfer.setData('application/x-fm-rel', entry.rel)
                      event.dataTransfer.setData('text/plain', entry.rel)
                      event.dataTransfer.effectAllowed = 'move'
                    }}
                    onDragOver={isDir(entry) ? (event) => allowDrop(event, destOf(entry)) : undefined}
                    onDrop={isDir(entry) ? (event) => void onDrop(event, destOf(entry)) : undefined}
                  >
                    <span className="fm-name">
                      <FileGlyph tone={glyphTone(entry)} ext={entry.ext} size={28} />
                      <span>
                        {entry.name}
                        {entry.symlink ? <em> link</em> : null}
                      </span>
                    </span>
                    <span className="fm-meta">{dayjs(entry.mtime).format('D MMM YYYY, HH:mm')}</span>
                    <span className="fm-meta">{isDir(entry) ? '—' : formatBytes(entry.size)}</span>
                    <span className="fm-meta">{kindLabel(entry)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="fm-status">
            <span>
              {visible.length} item{visible.length === 1 ? '' : 's'}
            </span>
            <span>Double-click to open · drag onto a folder to move</span>
          </div>
        </section>

        {previewOpen ? (
          <PreviewPane
            rootId={rootId}
            entry={openFile}
            canWrite={canWrite}
            onClose={() => {
              setPreviewOpen(false)
              setOpenFile(null)
            }}
            onSaved={() => void refresh()}
            onDownload={(entry) => void download(entry)}
          />
        ) : null}
      </div>

      <input
        ref={fileRef}
        type="file"
        multiple
        hidden
        onChange={(event) => {
          const list = Array.from(event.target.files || [])
          event.target.value = ''
          void uploadFiles(list, cwd)
        }}
      />

      {menu ? (
        <div
          className="fm-menu"
          style={{
            top: Math.min(menu.y, window.innerHeight - 240),
            left: Math.min(menu.x, window.innerWidth - 200),
          }}
          onClick={(event) => event.stopPropagation()}
        >
          <button type="button" onClick={() => { openEntry(menu.entry); setMenu(null) }}>
            <EyeOutlined /> {isDir(menu.entry) ? 'Open' : 'Preview'}
          </button>
          {!isDir(menu.entry) ? (
            <button type="button" onClick={() => { void download(menu.entry); setMenu(null) }}>
              <DownloadOutlined /> Download
            </button>
          ) : null}
          <button type="button" onClick={() => { copyPath(menu.entry); setMenu(null) }}>
            <CopyOutlined /> Copy path
          </button>
          {canWrite ? (
            <>
              <button
                type="button"
                onClick={() => {
                  setDialog({ mode: 'rename', value: menu.entry.name, rel: menu.entry.rel })
                  setMenu(null)
                }}
              >
                <EditOutlined /> Rename
              </button>
              <button type="button" onClick={() => { void openMover(menu.entry); setMenu(null) }}>
                <FolderAddOutlined /> Move to…
              </button>
              <button type="button" className="is-danger" onClick={() => { askDelete(menu.entry); setMenu(null) }}>
                <DeleteOutlined /> Delete
              </button>
            </>
          ) : null}
        </div>
      ) : null}

      <Modal
        title={dialog?.mode === 'mkdir' ? 'New folder' : dialog?.mode === 'touch' ? 'New file' : 'Rename'}
        open={!!dialog}
        okText={dialog?.mode === 'rename' ? 'Rename' : 'Create'}
        confirmLoading={busy}
        onOk={() => void submitDialog()}
        onCancel={() => setDialog(null)}
        destroyOnHidden
      >
        <Input
          autoFocus
          placeholder={dialog?.mode === 'touch' ? 'notes.md' : 'Name'}
          value={dialog?.value || ''}
          onChange={(event) => dialog && setDialog({ ...dialog, value: event.target.value })}
        />
      </Modal>

      <Modal
        title={`Move “${mover?.entry.name || ''}”`}
        open={!!mover}
        okText="Move here"
        confirmLoading={busy}
        onOk={() => {
          if (!mover) return
          void moveEntry(mover.entry.rel, mover.browse).then(() => setMover(null))
        }}
        onCancel={() => setMover(null)}
        destroyOnHidden
      >
        {mover ? (
          <div className="fm-mover">
            <div className="fm-mover-path">{mover.browse ? `${mountName} / ${mover.browse}` : mountName}</div>
            {mover.browse ? (
              <button type="button" className="fm-mover-row" onClick={() => void browseMover(parentRel(mover.browse))}>
                <ArrowLeftOutlined /> Up
              </button>
            ) : null}
            {mover.rows.length === 0 ? <div className="fm-mover-empty">No subfolders</div> : null}
            {mover.rows.map((row) => (
              <button key={row.rel} type="button" className="fm-mover-row" onClick={() => void browseMover(destOf(row))}>
                <FileGlyph tone="folder" size={22} /> {row.name}
              </button>
            ))}
          </div>
        ) : null}
      </Modal>

      {busy ? <div className="fm-busy">Working…</div> : null}
    </div>
  )
}

function kindLabel(entry: FmEntry) {
  if (entry.broken) return 'Broken link'
  if (entry.escaped) return 'External link'
  if (isDir(entry)) return entry.symlink ? 'Folder link' : 'Folder'
  if (entry.preview === 'markdown') return 'Markdown'
  if (entry.preview === 'pdf') return 'PDF'
  if (entry.preview === 'image') return 'Image'
  if (entry.preview === 'audio') return 'Audio'
  if (entry.preview === 'video') return 'Video'
  if (entry.preview === 'text') return 'Text'
  if (entry.ext) return entry.ext.toUpperCase()
  return 'File'
}

function Tile({
  entry,
  selected,
  drop,
  canWrite,
  onSelect,
  onOpen,
  onContext,
  onDragOver,
  onDrop,
}: {
  entry: FmEntry
  selected: boolean
  drop: boolean
  canWrite: boolean
  onSelect: () => void
  onOpen: () => void
  onContext: (event: React.MouseEvent) => void
  onDragOver?: (event: DragEvent) => void
  onDrop?: (event: DragEvent) => void
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      className={`fm-tile ${selected ? 'is-selected' : ''} ${drop ? 'is-drop' : ''} ${entry.escaped || entry.broken ? 'is-muted' : ''}`}
      draggable={canWrite}
      onClick={onSelect}
      onDoubleClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpen()
        }
      }}
      onContextMenu={onContext}
      onDragStart={(event) => {
        event.dataTransfer.setData('application/x-fm-rel', entry.rel)
        event.dataTransfer.setData('text/plain', entry.rel)
        event.dataTransfer.effectAllowed = 'move'
      }}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <FileGlyph tone={glyphTone(entry)} ext={isDir(entry) ? undefined : entry.ext} size={52} />
      <span className="fm-tile-name">{entry.name}</span>
      <span className="fm-tile-meta">
        {isDir(entry) ? kindLabel(entry) : formatBytes(entry.size)}
        {entry.symlink && !isDir(entry) ? ' · link' : ''}
      </span>
    </div>
  )
}

function TreeRow({
  label,
  depth,
  active,
  inPath = false,
  open,
  drop,
  onOpen,
  onToggle,
  onDragOver,
  onDrop,
  onDragLeave,
}: {
  label: string
  depth: number
  active: boolean
  inPath?: boolean
  open: boolean
  drop: boolean
  onOpen: () => void
  onToggle: () => void
  onDragOver: (event: DragEvent) => void
  onDrop: (event: DragEvent) => void
  onDragLeave: () => void
}) {
  return (
    <div
      className={`fm-tree-row ${active ? 'is-active' : inPath ? 'is-path' : ''} ${drop ? 'is-drop' : ''}`}
      style={{ paddingLeft: 8 + depth * 14 }}
      onClick={onOpen}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragLeave={onDragLeave}
    >
      <button
        type="button"
        className={`fm-chevron ${open ? 'is-open' : ''}`}
        aria-label={open ? 'Collapse' : 'Expand'}
        onClick={(event) => {
          event.stopPropagation()
          onToggle()
        }}
      />
      <FileGlyph tone="folder" size={18} />
      <span>{label}</span>
    </div>
  )
}

function TreeBranch({
  parent,
  depth,
  tree,
  expanded,
  cwd,
  dropRel,
  onOpen,
  onToggle,
  onDragOver,
  onDrop,
  onDragLeave,
}: {
  parent: string
  depth: number
  tree: Record<string, FmEntry[]>
  expanded: Set<string>
  cwd: string
  dropRel: string | null
  onOpen: (rel: string) => void
  onToggle: (rel: string) => void
  onDragOver: (event: DragEvent, rel: string) => void
  onDrop: (event: DragEvent, rel: string) => void
  onDragLeave: () => void
}) {
  const nodes = tree[parent] || []
  return (
    <>
      {nodes.map((node) => {
        const rel = destOf(node)
        const opened = expanded.has(rel) || expanded.has(node.rel)
        return (
          <div key={node.rel}>
            <TreeRow
              label={node.name}
              depth={depth}
              active={cwd === rel || cwd === node.rel}
              inPath={!!cwd && cwd !== rel && cwd.startsWith(`${rel}/`)}
              open={opened}
              drop={dropRel === rel}
              onOpen={() => onOpen(rel)}
              onToggle={() => onToggle(rel)}
              onDragOver={(event) => onDragOver(event, rel)}
              onDrop={(event) => onDrop(event, rel)}
              onDragLeave={onDragLeave}
            />
            {opened ? (
              <TreeBranch
                parent={rel}
                depth={depth + 1}
                tree={tree}
                expanded={expanded}
                cwd={cwd}
                dropRel={dropRel}
                onOpen={onOpen}
                onToggle={onToggle}
                onDragOver={onDragOver}
                onDrop={onDrop}
                onDragLeave={onDragLeave}
              />
            ) : null}
          </div>
        )
      })}
    </>
  )
}

function PreviewPane({
  rootId,
  entry,
  canWrite,
  onClose,
  onSaved,
  onDownload,
}: {
  rootId: string
  entry: FmEntry | null
  canWrite: boolean
  onClose: () => void
  onSaved: () => void
  onDownload: (entry: FmEntry) => void
}) {
  const [draft, setDraft] = useState('')
  const [saved, setSaved] = useState('')
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sourceMode, setSourceMode] = useState(false)
  const [mdMode, setMdMode] = useState<'split' | 'edit' | 'preview'>('split')
  const blobRef = useRef<string | null>(null)

  function replaceUrl(next: string | null) {
    if (blobRef.current) URL.revokeObjectURL(blobRef.current)
    blobRef.current = next
    setBlobUrl(next)
  }

  useEffect(() => () => replaceUrl(null), [])

  useEffect(() => {
    setSourceMode(false)
    setMdMode('split')
  }, [entry?.rel])

  const wantsText =
    !!entry &&
    (entry.preview === 'markdown' ||
      entry.preview === 'text' ||
      (sourceMode && entry.editable) ||
      (entry.editable && entry.preview !== 'image' && entry.preview !== 'pdf' && entry.preview !== 'audio' && entry.preview !== 'video'))

  useEffect(() => {
    if (!entry) {
      replaceUrl(null)
      setDraft('')
      setSaved('')
      setError('')
      return
    }
    let cancelled = false
    const run = async () => {
      setLoading(true)
      setError('')
      try {
        if (wantsText) {
          const res = await api<{ text: string }>(
            `/api/files/text?root_id=${encodeURIComponent(rootId)}&rel=${encodeURIComponent(entry.rel)}`,
          )
          if (cancelled) return
          setDraft(res.text)
          setSaved(res.text)
          replaceUrl(null)
        } else if (entry.preview === 'image' || entry.preview === 'pdf' || entry.preview === 'audio' || entry.preview === 'video') {
          const { blob } = await apiDownload(
            `/api/files/raw?root_id=${encodeURIComponent(rootId)}&rel=${encodeURIComponent(entry.rel)}`,
          )
          const url = URL.createObjectURL(blob)
          if (cancelled) {
            URL.revokeObjectURL(url)
            return
          }
          replaceUrl(url)
        } else {
          replaceUrl(null)
        }
      } catch (e) {
        if (!cancelled) setError(apiError(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
    // replaceUrl is stable enough for this pane; blob revocation is ref-based.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry, rootId, wantsText])

  const dirty = draft !== saved

  function requestClose() {
    if (dirty) {
      Modal.confirm({
        title: 'Discard unsaved edits?',
        okText: 'Discard',
        okButtonProps: { danger: true },
        onOk: onClose,
      })
      return
    }
    onClose()
  }

  async function save() {
    if (!entry) return
    try {
      await api('/api/files/text', {
        method: 'PUT',
        body: JSON.stringify({ root_id: rootId, rel: entry.rel, content: draft }),
      })
      setSaved(draft)
      message.success('Saved')
      onSaved()
    } catch (e) {
      message.error(apiError(e))
    }
  }

  return (
    <aside className="fm-preview la-panel">
      <div className="fm-preview-bar">
        <div className="fm-preview-title">
          {entry ? <FileGlyph tone={glyphTone(entry)} ext={entry.ext} size={22} /> : <EyeOutlined />}
          <span>{entry?.name || 'Preview'}</span>
        </div>
        <div className="fm-preview-actions">
          {entry?.preview === 'markdown' ? (
            <div className="fm-seg">
              {(['preview', 'split', 'edit'] as const).map((mode) => (
                <button key={mode} type="button" className={mdMode === mode ? 'is-on' : ''} onClick={() => setMdMode(mode)}>
                  {mode}
                </button>
              ))}
            </div>
          ) : null}
          {entry?.editable && entry.preview === 'image' ? (
            <Button size="small" onClick={() => setSourceMode((value) => !value)}>
              {sourceMode ? 'Show image' : 'Edit source'}
            </Button>
          ) : null}
          {entry && wantsText && canWrite ? (
            <Button size="small" type="primary" icon={<SaveOutlined />} disabled={!dirty} onClick={() => void save()}>
              Save
            </Button>
          ) : null}
          {entry && !isDir(entry) ? (
            <Button size="small" icon={<DownloadOutlined />} onClick={() => onDownload(entry)} />
          ) : null}
          <Button size="small" type="text" onClick={requestClose}>
            Close
          </Button>
        </div>
      </div>
      <div className="fm-preview-body">
        {!entry ? (
          <div className="fm-center">Select a file to preview it.</div>
        ) : loading ? (
          <div className="fm-center">
            <Spin />
          </div>
        ) : error ? (
          <div className="fm-center">{error}</div>
        ) : entry.preview === 'image' && blobUrl && !sourceMode ? (
          <div className="fm-image-stage">
            <img src={blobUrl} alt={entry.name} />
          </div>
        ) : entry.preview === 'pdf' && blobUrl ? (
          <iframe title={entry.name} src={blobUrl} className="fm-frame" />
        ) : entry.preview === 'audio' && blobUrl ? (
          <div className="fm-center">
            <FileGlyph tone="audio" ext={entry.ext} size={72} />
            <audio controls src={blobUrl} />
          </div>
        ) : entry.preview === 'video' && blobUrl ? (
          <video controls src={blobUrl} className="fm-video" />
        ) : entry.preview === 'markdown' && !sourceMode ? (
          <div className={`fm-md fm-md-${mdMode}`}>
            {mdMode !== 'preview' ? (
              <textarea
                className="fm-editor"
                value={draft}
                readOnly={!canWrite}
                spellCheck={false}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if ((event.metaKey || event.ctrlKey) && event.key === 's') {
                    event.preventDefault()
                    if (canWrite && dirty) void save()
                  }
                }}
              />
            ) : null}
            {mdMode !== 'edit' ? (
              <div className="fm-md-render">
                <SimpleMarkdown text={draft} />
              </div>
            ) : null}
          </div>
        ) : wantsText ? (
          <textarea
            className="fm-editor"
            value={draft}
            readOnly={!canWrite}
            spellCheck={false}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === 's') {
                event.preventDefault()
                if (canWrite && dirty) void save()
              }
            }}
          />
        ) : (
          <div className="fm-center fm-empty-inline">
            <FileGlyph tone={glyphTone(entry)} ext={entry.ext} size={72} />
            <div>No inline preview for this file.</div>
            <Button icon={<DownloadOutlined />} onClick={() => onDownload(entry)}>
              Download
            </Button>
          </div>
        )}
      </div>
    </aside>
  )
}
