import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import {
  Button,
  Dropdown,
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
  FileZipOutlined,
  FolderOpenOutlined,
  LeftOutlined,
  ExpandAltOutlined,
  CompressOutlined,
  SaveOutlined,
  EllipsisOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { api, apiDownload, apiNdjson, apiUpload, type StreamProgress } from '../api/client'
import { useAccess } from '../api/access'
import { useAppSettings } from '../api/settings'
import { PageHeader } from '../components/PageHeader'
import { FileGlyph, glyphTone } from '../components/FileGlyph'
import { SimpleMarkdown } from '../components/SimpleMarkdown'
import { formatBytes } from '../utils/format'
import { collectDroppedTree, treeFromFileList, type DroppedTree } from '../utils/fileDrop'

const OfficePreview = lazy(async () => {
  const mod = await import('../components/OfficePreview')
  return { default: mod.OfficePreview }
})

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
  preview: 'image' | 'pdf' | 'docx' | 'xlsx' | 'markdown' | 'text' | 'audio' | 'video' | 'none'
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

type JobView = {
  title: string
  detail: string
  pct: number
  meta: string
}

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

function isArchiveName(name: string) {
  const lower = name.toLowerCase()
  return ['.tar.gz', '.tar.bz2', '.tar.xz', '.tgz', '.tbz2', '.txz', '.zip', '.tar'].some((suffix) => lower.endsWith(suffix))
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

/** `/files/<mount>/<folder>/<nested>` so a refresh reopens the same directory. */
function filesPath(rootId: string, rel: string): string {
  const base = `/files/${encodeURIComponent(rootId)}`
  const clean = normRel(rel)
  if (!clean) return base
  return `${base}/${clean.split('/').map((part) => encodeURIComponent(part)).join('/')}`
}

function isSelfOrDescendant(src: string, dest: string) {
  const from = normRel(src)
  const to = normRel(dest)
  if (!from) return true
  return to === from || to.startsWith(`${from}/`)
}

function joinRel(base: string, extra: string) {
  const a = normRel(base)
  const b = normRel(extra)
  if (!a) return b
  if (!b) return a
  return `${a}/${b}`
}

/** In-app moves set a custom type. OS drags also carry text/plain, which is not a move. */
function internalDropRel(dt: DataTransfer): string {
  if (dt.types.includes('application/x-fm-rel')) return normRel(dt.getData('application/x-fm-rel'))
  if (dt.types.includes('Files')) return ''
  if (dt.types.includes('text/plain')) return normRel(dt.getData('text/plain'))
  return ''
}

function isInternalDrag(dt: DataTransfer): boolean {
  if (dt.types.includes('application/x-fm-rels') || dt.types.includes('application/x-fm-rel')) return true
  return dt.types.includes('text/plain') && !dt.types.includes('Files')
}

type OpenMode = 'single' | 'double'

function readOpenMode(fallback: OpenMode): OpenMode {
  const stored = localStorage.getItem('lnxadmin_fm_open')
  if (stored === 'single' || stored === 'double') return stored
  return fallback
}

/** Drop nested paths when a parent is already included, so a folder move or delete is not repeated. */
function topmostRels(rels: string[]): string[] {
  const sorted = [...new Set(rels.map((rel) => normRel(rel)).filter(Boolean))].sort(
    (a, b) => a.length - b.length || a.localeCompare(b),
  )
  const kept: string[] = []
  for (const rel of sorted) {
    if (kept.some((parent) => rel === parent || rel.startsWith(`${parent}/`))) continue
    kept.push(rel)
  }
  return kept
}

function dragRels(dt: DataTransfer): string[] {
  if (dt.types.includes('application/x-fm-rels')) {
    try {
      const parsed = JSON.parse(dt.getData('application/x-fm-rels'))
      if (Array.isArray(parsed)) {
        const rels = parsed.map((item) => normRel(String(item))).filter(Boolean)
        if (rels.length) return topmostRels(rels)
      }
    } catch {
      /* a single path is still on the transfer */
    }
  }
  const one = internalDropRel(dt)
  return one ? [one] : []
}

function writeDrag(dt: DataTransfer, rels: string[]) {
  const clean = topmostRels(rels)
  if (!clean.length) return
  dt.setData('application/x-fm-rels', JSON.stringify(clean))
  dt.setData('application/x-fm-rel', clean[0])
  dt.setData('text/plain', clean[0])
  dt.effectAllowed = 'move'
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

  return (
    <Explorer
      rootId={mount.id}
      mountName={mount.name}
      showHiddenDefault={!!filesMod.show_hidden}
      openClickDefault={filesMod.open_click === 'single' ? 'single' : 'double'}
    />
  )
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
  openClickDefault,
}: {
  rootId: string
  mountName: string
  showHiddenDefault: boolean
  openClickDefault: OpenMode
}) {
  const { canMutate } = useAccess()
  const navigate = useNavigate()
  const urlRel = normRel(useParams()['*'])
  const [cwd, setCwd] = useState('')
  const [parent, setParent] = useState<string | null>(null)
  const [rootMeta, setRootMeta] = useState<FmRoot | null>(null)
  const [entries, setEntries] = useState<FmEntry[]>([])
  const [tree, setTree] = useState<Record<string, FmEntry[]>>({})
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(['']))
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [busyNote, setBusyNote] = useState('Working…')
  const [job, setJob] = useState<JobView | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<'name' | 'mtime' | 'size' | 'kind'>('name')
  const [view, setView] = useState<'grid' | 'list'>(() => (localStorage.getItem('lnxadmin_fm_view') === 'list' ? 'list' : 'grid'))
  const [showHidden, setShowHidden] = useState(showHiddenDefault)
  const [openMode, setOpenMode] = useState<OpenMode>(() => readOpenMode(openClickDefault))
  const [picked, setPicked] = useState<string[]>([])
  const [focusRel, setFocusRel] = useState<string | null>(null)
  const [band, setBand] = useState<{ x: number; y: number; w: number; h: number } | null>(null)
  const [openFile, setOpenFile] = useState<FmEntry | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [treeOpen, setTreeOpen] = useState(() => {
    if (typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches) return false
    return localStorage.getItem('lnxadmin_fm_tree') !== '0'
  })
  const [narrow, setNarrow] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia('(max-width: 768px)').matches : false,
  )
  const [previewWide, setPreviewWide] = useState(() => localStorage.getItem('lnxadmin_fm_preview_wide') === '1')
  const [previewWidth, setPreviewWidth] = useState(() => {
    const raw = Number(localStorage.getItem('lnxadmin_fm_preview_w'))
    return Number.isFinite(raw) && raw >= 320 && raw <= 1100 ? raw : 440
  })
  const [resizing, setResizing] = useState(false)
  const [dropRel, setDropRel] = useState<string | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number; entry: FmEntry } | null>(null)
  const [dialog, setDialog] = useState<{ mode: 'mkdir' | 'touch' | 'rename'; value: string; rel: string } | null>(null)
  const [mover, setMover] = useState<{ rels: string[]; browse: string; rows: FmEntry[] } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const shellRef = useRef<HTMLDivElement>(null)
  const previewWidthRef = useRef(previewWidth)
  previewWidthRef.current = previewWidth
  const anchorRef = useRef<string | null>(null)
  const pickedRef = useRef<string[]>([])
  pickedRef.current = picked
  const cwdRef = useRef('')
  const loadSeq = useRef(0)
  cwdRef.current = cwd

  const canWrite = !!rootMeta?.writable && canMutate('files')

  const loadDir = useCallback(
    async (rel: string) => {
      const seq = ++loadSeq.current
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

        if (seq !== loadSeq.current) return null
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
        if (seq === loadSeq.current) message.error(apiError(e))
        return null
      } finally {
        if (seq === loadSeq.current) setLoading(false)
      }
    },
    [rootId, showHidden],
  )

  const openFolder = useCallback(
    (rel: string) => {
      const target = normRel(rel)
      if (window.matchMedia('(max-width: 768px)').matches) {
        setTreeOpen(false)
      }
      if (target === urlRel) {
        void loadDir(target)
        return
      }
      navigate(filesPath(rootId, target))
    },
    [loadDir, navigate, rootId, urlRel],
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
    setPicked([])
    setFocusRel(null)
    anchorRef.current = null
    setOpenFile(null)
    setPreviewOpen(false)
    setQuery('')
  }, [rootId])

  useEffect(() => {
    setCwd(urlRel)
    setParent(urlRel ? parentRel(urlRel) : null)
    setPicked([])
    setFocusRel(null)
    anchorRef.current = null
    void loadDir(urlRel)
  }, [loadDir, urlRel])

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

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)')
    const apply = () => {
      const next = mq.matches
      setNarrow(next)
      if (next) setTreeOpen(false)
    }
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

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

  function showJob(next: JobView) {
    setJob((prev) => ({
      ...next,
      pct: prev ? Math.max(prev.pct, next.pct) : next.pct,
    }))
  }

  async function uploadTree(dest: string, tree: DroppedTree) {
    if ((!tree.files.length && !tree.dirs.length) || !canWrite) return
    setBusy(true)
    setJob(null)
    const totalBytes = tree.files.reduce((sum, spec) => sum + spec.file.size, 0)
    showJob({
      title: tree.dirs.length && !tree.files.length ? 'Copying folder' : 'Uploading',
      detail: tree.files[0]?.file.name || tree.dirs[0] || 'Files',
      pct: 0,
      meta: tree.files.length > 1 ? `1 of ${tree.files.length}` : totalBytes ? formatBytes(totalBytes) : '',
    })
    try {
      const dirSteps = Math.max(1, Math.ceil(tree.dirs.length / 1000))
      for (let step = 0; step < tree.dirs.length; step += 1000) {
        showJob({
          title: 'Copying folder',
          detail: 'Creating folders',
          pct: tree.files.length ? Math.round(((step / 1000 + 1) / dirSteps) * 8) : Math.round(((step / 1000 + 1) / dirSteps) * 100),
          meta: '',
        })
        await api('/api/files/mkdirs', {
          method: 'POST',
          body: JSON.stringify({ root_id: rootId, rel: dest, paths: tree.dirs.slice(step, step + 1000) }),
        })
      }
      let completed = 0
      for (let index = 0; index < tree.files.length; index += 1) {
        const spec = tree.files[index]
        const label = spec.dir ? `${spec.dir}/${spec.file.name}` : spec.file.name
        const body = new FormData()
        body.append('root_id', rootId)
        body.append('rel', joinRel(dest, spec.dir))
        body.append('file', spec.file, spec.file.name)
        await apiUpload('/api/files/upload', body, (loaded, reported) => {
          const ratioInFile = reported > 0 ? Math.min(1, loaded / reported) : 0
          const doneBytes = completed + spec.file.size * ratioInFile
          const span = tree.dirs.length ? 92 : 100
          const base = tree.dirs.length ? 8 : 0
          const ratio = totalBytes > 0 ? doneBytes / totalBytes : (index + ratioInFile) / tree.files.length
          const count = tree.files.length > 1 ? `${index + 1} of ${tree.files.length}` : ''
          const bytes = totalBytes > 0 ? `${formatBytes(doneBytes)} of ${formatBytes(totalBytes)}` : ''
          showJob({
            title: 'Uploading',
            detail: label,
            pct: Math.min(99, base + Math.round(ratio * span)),
            meta: [count, bytes].filter(Boolean).join(' · '),
          })
        })
        completed += spec.file.size
      }
      showJob({
        title: tree.files.length ? 'Uploading' : 'Copying folder',
        detail: tree.files.length === 1 ? tree.files[0].file.name : 'Finished',
        pct: 100,
        meta: tree.files.length > 1 ? `${tree.files.length} of ${tree.files.length}` : '',
      })
      if (!tree.files.length) message.success(tree.dirs.length === 1 ? 'Folder uploaded' : 'Folders uploaded')
      else if (tree.dirs.length) message.success(tree.files.length === 1 ? 'Folder uploaded' : `Uploaded ${tree.files.length} files`)
      else message.success(tree.files.length === 1 ? 'Uploaded' : `Uploaded ${tree.files.length} files`)
      await refresh()
      await holdJobDone()
    } catch (e) {
      message.error(apiError(e))
      await refresh()
    } finally {
      setBusy(false)
      setBusyNote('Working…')
      setJob(null)
    }
  }

  async function moveMany(rels: string[], dest: string) {
    const unique = topmostRels(rels)
    const blocked = unique.filter((rel) => isSelfOrDescendant(rel, dest))
    const targets = unique.filter((rel) => parentRel(rel) !== dest && !isSelfOrDescendant(rel, dest))
    if (blocked.length) message.warning('Cannot move a folder into itself')
    if (!targets.length) {
      if (!blocked.length) message.info('Already in this folder')
      return
    }
    setBusy(true)
    try {
      for (const rel of targets) {
        await api('/api/files/move', {
          method: 'POST',
          body: JSON.stringify({ root_id: rootId, rel, dest_rel: dest, name: null }),
        })
        if (openFile && (openFile.rel === rel || isSelfOrDescendant(rel, openFile.rel))) setOpenFile(null)
      }
      message.success(targets.length === 1 ? 'Moved' : `Moved ${targets.length} items`)
      setPicked([])
      setFocusRel(null)
      anchorRef.current = null
      await refresh()
    } catch (e) {
      message.error(apiError(e))
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  function askDelete(list: FmEntry[]) {
    const targets = topmostRels(list.map((entry) => entry.rel))
      .map((rel) => list.find((entry) => entry.rel === rel))
      .filter((entry): entry is FmEntry => !!entry)
    if (!targets.length) return
    const title = targets.length === 1 ? `Delete “${targets[0].name}”?` : `Delete ${targets.length} items?`
    const content = targets.length === 1
      ? isDir(targets[0])
        ? 'The folder and everything inside it will be removed from disk.'
        : 'This file will be removed from disk.'
      : 'Selected files and folders will be removed from disk. A folder takes its contents with it.'
    Modal.confirm({
      title,
      content,
      okText: 'Delete',
      okButtonProps: { danger: true },
      cancelText: 'Cancel',
      onOk: async () => {
        const ordered = [...targets].sort((a, b) => b.rel.length - a.rel.length)
        for (const entry of ordered) {
          await api(`/api/files/entry?root_id=${encodeURIComponent(rootId)}&rel=${encodeURIComponent(entry.rel)}`, {
            method: 'DELETE',
          })
          if (openFile && (openFile.rel === entry.rel || isSelfOrDescendant(entry.rel, openFile.rel))) setOpenFile(null)
        }
        setPicked([])
        setFocusRel(null)
        anchorRef.current = null
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
      openFolder(destOf(entry))
      return
    }
    setPicked([entry.rel])
    setFocusRel(entry.rel)
    anchorRef.current = entry.rel
    setOpenFile(entry)
    setPreviewOpen(true)
  }

  async function onDrop(event: DragEvent, destRaw: string) {
    event.preventDefault()
    event.stopPropagation()
    setDropRel(null)
    const dest = normRel(destRaw)
    const from = dragRels(event.dataTransfer)
    const incoming = from.length ? null : collectDroppedTree(event.dataTransfer)
    if (from.length) {
      if (!canWrite) return
      await moveMany(from, dest)
      return
    }
    try {
      const tree = await incoming
      if (tree && (tree.files.length || tree.dirs.length)) await uploadTree(dest, tree)
    } catch (e) {
      message.error(apiError(e))
    }
  }

  function allowDrop(event: DragEvent, relRaw: string) {
    if (!canWrite) return
    const rel = normRel(relRaw)
    if (isInternalDrag(event.dataTransfer)) {
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
        const nextRel = joinRel(parentRel(dialog.rel), name)
        setPicked([nextRel])
        setFocusRel(nextRel)
        anchorRef.current = nextRel
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

  async function openMover(rels: string[]) {
    const targets = topmostRels(rels)
    if (!targets.length) return
    try {
      const data = await api<ListResp>(
        `/api/files/list?root_id=${encodeURIComponent(rootId)}&rel=&hidden=${showHidden}`,
      )
      setMover({ rels: targets, browse: data.rel, rows: data.entries.filter(isDir) })
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

  function archiveSlice(title: string, index: number, count: number, event: StreamProgress, fallback: string) {
    const part = Math.min(99, event.pct || 0) / 100
    const done = event.done || 0
    const total = event.total || 0
    const bytes = total > 0 ? `${formatBytes(done)} of ${formatBytes(total)}` : ''
    const place = count > 1 ? `${index + 1} of ${count}` : ''
    showJob({
      title,
      detail: event.label || fallback,
      pct: Math.min(99, Math.round(((index + part) / count) * 100)),
      meta: [place, bytes].filter(Boolean).join(' · '),
    })
  }

  async function packEntries(list: FmEntry[], format: 'zip' | 'tar.gz') {
    if (!list.length) return
    setBusy(true)
    setJob(null)
    showJob({
      title: 'Packing',
      detail: list[0].name,
      pct: 0,
      meta: list.length > 1 ? `1 of ${list.length}` : format === 'tar.gz' ? 'tar.gz' : 'Zip',
    })
    const created: { name: string; rel: string }[] = []
    try {
      for (let index = 0; index < list.length; index += 1) {
        const entry = list[index]
        const result = await apiNdjson<{ name: string; rel: string }>('/api/files/pack', {
          root_id: rootId,
          rel: entry.rel,
          format,
        }, (event) => archiveSlice('Packing', index, list.length, event, entry.name))
        created.push(result)
      }
      const last = created[created.length - 1]
      showJob({ title: 'Packing', detail: last?.name || 'Finished', pct: 100, meta: '' })
      message.success(created.length === 1 ? `Packed ${created[0].name}` : `Packed ${created.length} archives`)
      if (last) {
        setPicked([last.rel])
        setFocusRel(last.rel)
        anchorRef.current = last.rel
      }
      await refresh()
      await holdJobDone()
    } catch (e) {
      message.error(apiError(e))
      await refresh()
    } finally {
      setBusy(false)
      setJob(null)
    }
  }

  async function extractEntries(list: FmEntry[]) {
    if (!list.length) return
    setBusy(true)
    setJob(null)
    showJob({ title: 'Extracting', detail: list[0].name, pct: 0, meta: list.length > 1 ? `1 of ${list.length}` : '' })
    const created: { name: string; rel: string; skipped?: number; renamed?: number }[] = []
    try {
      for (let index = 0; index < list.length; index += 1) {
        const entry = list[index]
        const result = await apiNdjson<{ name: string; rel: string; skipped?: number; renamed?: number }>('/api/files/extract', {
          root_id: rootId,
          rel: entry.rel,
        }, (event) => archiveSlice('Extracting', index, list.length, event, entry.name))
        created.push(result)
      }
      const last = created[created.length - 1]
      const skipped = created.reduce((sum, item) => sum + (item.skipped || 0), 0)
      const renamed = created.reduce((sum, item) => sum + (item.renamed || 0), 0)
      showJob({ title: 'Extracting', detail: last?.name || 'Finished', pct: 100, meta: '' })
      if (skipped || renamed) {
        const notes = [`Extracted ${created.length} archive${created.length === 1 ? '' : 's'}`]
        if (renamed) notes.push(`${renamed} long name${renamed === 1 ? '' : 's'} shortened`)
        if (skipped) notes.push(`${skipped} link${skipped === 1 ? '' : 's'} skipped`)
        message.warning(notes.join('. '))
      } else if (created.length === 1) message.success(`Extracted to ${created[0].name}`)
      else message.success(`Extracted ${created.length} archives`)
      await refresh()
      if (last) {
        setPicked(created.map((item) => item.rel))
        setFocusRel(last.rel)
        anchorRef.current = last.rel
      }
      await holdJobDone()
      askAfterExtract(list)
    } catch (e) {
      message.error(apiError(e))
      await refresh()
    } finally {
      setBusy(false)
      setJob(null)
    }
  }

  function askAfterExtract(archives: FmEntry[]) {
    if (!archives.length) return
    const one = archives.length === 1
    Modal.confirm({
      title: one ? `Delete “${archives[0].name}”?` : `Delete ${archives.length} archives?`,
      content: one
        ? 'The archive was unpacked. Delete it, or keep it?'
        : 'The archives were unpacked. Delete them, or keep them?',
      okText: 'Delete',
      okButtonProps: { danger: true },
      cancelText: 'Keep',
      onOk: async () => {
        const ordered = [...archives].sort((a, b) => b.rel.length - a.rel.length)
        for (const entry of ordered) {
          await api(`/api/files/entry?root_id=${encodeURIComponent(rootId)}&rel=${encodeURIComponent(entry.rel)}`, {
            method: 'DELETE',
          })
        }
        message.success(one ? 'Archive deleted' : `Deleted ${archives.length} archives`)
        setPicked([])
        setFocusRel(null)
        anchorRef.current = null
        await refresh()
      },
    })
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

  function copyPaths(list: FmEntry[]) {
    const base = rootMeta?.path || ''
    const rels = list.length ? list.map((entry) => entry.rel) : [cwd]
    const text = rels.map((rel) => (rel ? `${base}/${rel}` : base)).join('\n')
    void navigator.clipboard.writeText(text).then(
      () => message.success(rels.length > 1 ? 'Paths copied' : 'Path copied'),
      () => message.error('Could not copy'),
    )
  }

  function chooseOnly(rel: string) {
    anchorRef.current = rel
    setFocusRel(rel)
    setPicked([rel])
  }

  function applyClick(event: { shiftKey: boolean; ctrlKey: boolean; metaKey: boolean }, entry: FmEntry) {
    const rel = entry.rel
    setFocusRel(rel)
    if (event.shiftKey) {
      const anchor = anchorRef.current && visible.some((row) => row.rel === anchorRef.current) ? anchorRef.current : rel
      const a = Math.max(0, visible.findIndex((row) => row.rel === anchor))
      const b = Math.max(0, visible.findIndex((row) => row.rel === rel))
      const lo = Math.min(a, b)
      const hi = Math.max(a, b)
      const range = visible.slice(lo, hi + 1).map((row) => row.rel)
      if (!anchorRef.current) anchorRef.current = anchor
      setPicked(event.ctrlKey || event.metaKey ? [...new Set([...pickedRef.current, ...range])] : range)
      return 'range' as const
    }
    if (event.ctrlKey || event.metaKey) {
      anchorRef.current = rel
      setPicked((prev) => (prev.includes(rel) ? prev.filter((item) => item !== rel) : [...prev, rel]))
      return 'toggle' as const
    }
    chooseOnly(rel)
    return 'plain' as const
  }

  function beginDrag(event: { dataTransfer: DataTransfer | null }, entry: FmEntry) {
    if (!event.dataTransfer) return
    const current = pickedRef.current.includes(entry.rel) ? pickedRef.current : [entry.rel]
    if (!pickedRef.current.includes(entry.rel)) chooseOnly(entry.rel)
    writeDrag(event.dataTransfer, current)
  }

  function onItemContext(event: React.MouseEvent, entry: FmEntry) {
    event.preventDefault()
    if (!pickedRef.current.includes(entry.rel)) chooseOnly(entry.rel)
    else setFocusRel(entry.rel)
    setMenu({ x: event.clientX, y: event.clientY, entry })
  }

  function onPaneMouseDown(event: React.MouseEvent) {
    if (event.button !== 0) return
    const target = event.target as HTMLElement | null
    if (!target || target.closest('.fm-tile, .fm-list-row, button, a, input')) return
    const startX = event.clientX
    const startY = event.clientY
    const additive = event.shiftKey || event.ctrlKey || event.metaKey
    const base = additive ? pickedRef.current : []
    let moved = false
    const move = (ev: MouseEvent) => {
      const dx = ev.clientX - startX
      const dy = ev.clientY - startY
      if (!moved && Math.hypot(dx, dy) < 4) return
      moved = true
      setBand({
        x: Math.min(startX, ev.clientX),
        y: Math.min(startY, ev.clientY),
        w: Math.abs(dx),
        h: Math.abs(dy),
      })
    }
    const up = (ev: MouseEvent) => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      setBand(null)
      if (!moved) {
        if (!additive) {
          setPicked([])
          setFocusRel(null)
          anchorRef.current = null
        }
        return
      }
      const box = {
        left: Math.min(startX, ev.clientX),
        top: Math.min(startY, ev.clientY),
        right: Math.max(startX, ev.clientX),
        bottom: Math.max(startY, ev.clientY),
      }
      const hits: string[] = []
      scrollRef.current?.querySelectorAll<HTMLElement>('[data-rel]').forEach((el) => {
        const rect = el.getBoundingClientRect()
        const rel = el.dataset.rel
        if (!rel) return
        if (rect.left < box.right && rect.right > box.left && rect.top < box.bottom && rect.bottom > box.top) hits.push(rel)
      })
      const order = new Map(visible.map((row, index) => [row.rel, index]))
      hits.sort((a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0))
      const next = additive ? [...new Set([...base, ...hits])] : hits
      setPicked(next)
      const last = hits[hits.length - 1] || null
      if (last) {
        setFocusRel(last)
        if (!additive || !anchorRef.current) anchorRef.current = hits[0] || last
      }
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  const selection = entries.filter((entry) => picked.includes(entry.rel))
  const one = selection.length === 1 ? selection[0] : null
  const canChangeSelection = canWrite && selection.length > 0 && selection.every((entry) => !entry.broken && !entry.escaped)
  const archiveSelection = selection.length > 0 && selection.every((entry) => !isDir(entry) && isArchiveName(entry.name))

  const keyRef = useRef({
    visible,
    selection,
    parent,
    canWrite,
    focusRel,
    menu: !!menu,
    blocked: !!dialog || !!mover,
    openEntry,
    openFolder,
    askDelete,
  })
  keyRef.current = {
    visible,
    selection,
    parent,
    canWrite,
    focusRel,
    menu: !!menu,
    blocked: !!dialog || !!mover,
    openEntry,
    openFolder,
    askDelete,
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const typing = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)
      if (typing || target?.closest('.fm-preview, .ant-modal')) return
      const cur = keyRef.current
      if (cur.blocked) return
      if (cur.menu && event.key !== 'Escape') return
      if (event.key === 'Escape') {
        if (cur.menu) {
          setMenu(null)
          return
        }
        setPicked([])
        setFocusRel(null)
        anchorRef.current = null
        return
      }
      const rows = cur.visible
      const focusEntry = rows.find((item) => item.rel === cur.focusRel) || (cur.selection.length === 1 ? cur.selection[0] : null)
      if ((event.key === 'a' || event.key === 'A') && (event.ctrlKey || event.metaKey)) {
        event.preventDefault()
        setPicked(rows.map((row) => row.rel))
        if (rows[0] && !anchorRef.current) anchorRef.current = rows[0].rel
        if (rows[0] && !cur.focusRel) setFocusRel(rows[0].rel)
        return
      }
      if (event.key === 'Enter' && focusEntry) {
        event.preventDefault()
        cur.openEntry(focusEntry)
        return
      }
      if (event.key === 'Backspace' && cur.parent !== null && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault()
        cur.openFolder(cur.parent)
        return
      }
      if (event.key === 'F2' && cur.selection.length === 1 && cur.canWrite && !cur.selection[0].broken && !cur.selection[0].escaped) {
        event.preventDefault()
        setDialog({ mode: 'rename', value: cur.selection[0].name, rel: cur.selection[0].rel })
        return
      }
      if (event.key === 'Delete' && cur.selection.length && cur.canWrite) {
        event.preventDefault()
        cur.askDelete(cur.selection)
        return
      }
      const cols = (() => {
        const grid = scrollRef.current?.querySelector('.fm-grid')
        if (!grid) return 1
        const tiles = [...grid.querySelectorAll<HTMLElement>('.fm-tile')]
        if (tiles.length < 2) return 1
        const top = tiles[0].getBoundingClientRect().top
        let count = 1
        for (let index = 1; index < tiles.length; index += 1) {
          if (Math.abs(tiles[index].getBoundingClientRect().top - top) > 8) break
          count += 1
        }
        return count
      })()
      let delta = 0
      if (event.key === 'ArrowLeft') delta = -1
      else if (event.key === 'ArrowRight') delta = 1
      else if (event.key === 'ArrowUp') delta = -cols
      else if (event.key === 'ArrowDown') delta = cols
      else if (event.key === 'Home') delta = -rows.length
      else if (event.key === 'End') delta = rows.length
      else return
      if (!rows.length) return
      event.preventDefault()
      const current = rows.findIndex((row) => row.rel === cur.focusRel)
      let nextIndex: number
      if (current < 0) nextIndex = event.key === 'ArrowUp' || event.key === 'ArrowLeft' || event.key === 'End' ? rows.length - 1 : 0
      else if (event.key === 'Home') nextIndex = 0
      else if (event.key === 'End') nextIndex = rows.length - 1
      else nextIndex = Math.max(0, Math.min(rows.length - 1, current + delta))
      const rel = rows[nextIndex].rel
      setFocusRel(rel)
      if (event.shiftKey) {
        const anchor = anchorRef.current && rows.some((row) => row.rel === anchorRef.current) ? anchorRef.current : rel
        if (!anchorRef.current) anchorRef.current = anchor
        const a = Math.max(0, rows.findIndex((row) => row.rel === anchor))
        const lo = Math.min(a, nextIndex)
        const hi = Math.max(a, nextIndex)
        setPicked(rows.slice(lo, hi + 1).map((row) => row.rel))
      } else {
        anchorRef.current = rel
        setPicked([rel])
      }
      scrollRef.current?.querySelector(`[data-rel="${CSS.escape(rel)}"]`)?.scrollIntoView({ block: 'nearest' })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  const menuGroup = menu
    ? selection.some((entry) => entry.rel === menu.entry.rel) ? selection : [menu.entry]
    : []
  const menuWritable = !!menu && canWrite && menuGroup.every((entry) => !entry.broken && !entry.escaped)
  const menuArchives = menuGroup.length > 0 && menuGroup.every((entry) => !isDir(entry) && isArchiveName(entry.name))
  const treeCol = treeOpen ? '248px' : '48px'
  const shellColumns = !previewOpen || previewWide
    ? `${treeCol} minmax(0, 1fr)`
    : `${treeCol} minmax(280px, 1fr) ${Math.round(previewWidth)}px`

  function setFoldersOpen(open: boolean) {
    setTreeOpen(open)
    localStorage.setItem('lnxadmin_fm_tree', open ? '1' : '0')
  }

  function setPreviewExpanded(open: boolean) {
    setPreviewWide(open)
    localStorage.setItem('lnxadmin_fm_preview_wide', open ? '1' : '0')
  }

  function startPreviewResize(event: React.MouseEvent) {
    event.preventDefault()
    const startX = event.clientX
    const pane = shellRef.current?.querySelector('.fm-preview')
    const startW = pane instanceof HTMLElement ? pane.clientWidth : previewWidthRef.current
    const wasWide = previewWide
    let moved = false
    setResizing(true)
    const move = (ev: MouseEvent) => {
      if (!moved) {
        if (Math.abs(ev.clientX - startX) < 3) return
        moved = true
        if (wasWide) setPreviewExpanded(false)
      }
      const shellW = shellRef.current?.clientWidth ?? window.innerWidth
      const treeW = treeOpen ? 248 : 48
      const max = Math.max(360, shellW - treeW - 300)
      const next = Math.round(Math.min(max, Math.max(320, startW + (startX - ev.clientX))))
      previewWidthRef.current = next
      setPreviewWidth(next)
    }
    const up = () => {
      setResizing(false)
      if (moved) localStorage.setItem('lnxadmin_fm_preview_w', String(previewWidthRef.current))
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }
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
                  <span className="fm-header-label">Folder</span>
                </Button>
                <Button icon={<FileAddOutlined />} onClick={() => setDialog({ mode: 'touch', value: '', rel: cwd })}>
                  <span className="fm-header-label">File</span>
                </Button>
                <Button type="primary" icon={<UploadOutlined />} onClick={() => fileRef.current?.click()}>
                  <span className="fm-header-label">Upload</span>
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

      <div
        ref={shellRef}
        className={`fm-shell ${previewOpen ? 'has-preview' : ''} ${treeOpen ? '' : 'is-tree-off'} ${previewOpen && previewWide ? 'is-preview-wide' : ''} ${resizing ? 'is-resizing' : ''}`}
        style={{ gridTemplateColumns: shellColumns }}
      >
        {narrow && treeOpen ? (
          <button type="button" className="fm-tree-scrim" aria-label="Close folders" onClick={() => setFoldersOpen(false)} />
        ) : null}
        <aside className={`fm-tree la-panel ${treeOpen ? '' : 'is-collapsed'}`}>
          {treeOpen ? (
            <div className="fm-tree-head">
              <span>Folders</span>
              <Tooltip title="Hide folders">
                <button type="button" className="fm-pane-btn" aria-label="Hide folders" onClick={() => setFoldersOpen(false)}>
                  <LeftOutlined />
                </button>
              </Tooltip>
            </div>
          ) : (
            <button type="button" className="fm-rail" aria-label="Show folders" onClick={() => setFoldersOpen(true)}>
              <FolderOpenOutlined />
              <span>Folders</span>
            </button>
          )}
          {treeOpen ? (
          <div className="fm-tree-scroll">
            <TreeRow
              label={mountName}
              depth={0}
              active={cwd === ''}
              inPath={cwd !== ''}
              open={expanded.has('')}
              drop={dropRel === ''}
              onOpen={() => openFolder('')}
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
                onOpen={(rel) => openFolder(rel)}
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
          ) : null}
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
            {narrow ? (
              <Tooltip title="Folders">
                <Button
                  type="text"
                  icon={<FolderOpenOutlined />}
                  onClick={() => setFoldersOpen(true)}
                  aria-label="Folders"
                />
              </Tooltip>
            ) : null}
            <Button
              type="text"
              icon={<ArrowLeftOutlined />}
              disabled={parent === null}
              onClick={() => parent !== null && openFolder(parent)}
            />
            <div className="fm-crumbs">
              <button type="button" onClick={() => openFolder('')}>
                {mountName}
              </button>
              {crumbs.map((part, index) => {
                const rel = crumbs.slice(0, index + 1).join('/')
                return (
                  <span key={rel}>
                    <span className="fm-crumb-sep">/</span>
                    <button type="button" onClick={() => openFolder(rel)}>
                      {part}
                    </button>
                  </span>
                )
              })}
            </div>
            <Input
              allowClear
              className="fm-filter-input"
              prefix={<SearchOutlined />}
              placeholder="Filter"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              style={{ width: 180 }}
            />
            <Select
              className="fm-desk-only"
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
              <Switch className="fm-desk-only" checked={showHidden} onChange={setShowHidden} />
            </Tooltip>
            <Select
              className="fm-desk-only"
              size="middle"
              value={openMode}
              aria-label="Open behavior"
              onChange={(value: OpenMode) => {
                setOpenMode(value)
                localStorage.setItem('lnxadmin_fm_open', value)
              }}
              style={{ width: 148 }}
              options={[
                { value: 'double', label: 'Double click' },
                { value: 'single', label: 'Single click' },
              ]}
            />
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
            {narrow ? (
              <Dropdown
                menu={{
                  items: [
                    {
                      key: 'sort',
                      label: 'Sort',
                      children: [
                        { key: 'name', label: 'Name' },
                        { key: 'mtime', label: 'Modified' },
                        { key: 'size', label: 'Size' },
                        { key: 'kind', label: 'Type' },
                      ],
                    },
                    {
                      key: 'hidden',
                      label: showHidden ? 'Hide dotfiles' : 'Show hidden',
                    },
                    {
                      key: 'open',
                      label: openMode === 'single' ? 'Use double click' : 'Use single click',
                    },
                  ],
                  onClick: ({ key }) => {
                    if (key === 'name' || key === 'mtime' || key === 'size' || key === 'kind') setSort(key)
                    if (key === 'hidden') setShowHidden((value) => !value)
                    if (key === 'open') {
                      const next: OpenMode = openMode === 'single' ? 'double' : 'single'
                      setOpenMode(next)
                      localStorage.setItem('lnxadmin_fm_open', next)
                    }
                  },
                }}
              >
                <Button type="text" icon={<EllipsisOutlined />} aria-label="More options" />
              </Dropdown>
            ) : null}
          </div>

          <div className="fm-actions">
            <span className="fm-actions-name" title={one?.name || ''}>
              {selection.length === 0 ? 'Select a file or folder' : selection.length === 1 ? selection[0].name : `${selection.length} selected`}
            </span>
            <Button size="small" icon={<EyeOutlined />} disabled={!one} onClick={() => one && openEntry(one)}>
              {one && isDir(one) ? 'Open' : 'Preview'}
            </Button>
            <Button
              size="small"
              icon={<DownloadOutlined />}
              disabled={!one || isDir(one) || !!one.broken}
              onClick={() => one && void download(one)}
            >
              Download
            </Button>
            <Button size="small" icon={<CopyOutlined />} disabled={selection.length === 0} onClick={() => copyPaths(selection)}>
              Copy path
            </Button>
            {canWrite ? (
              <>
                <Button
                  size="small"
                  icon={<EditOutlined />}
                  disabled={!one || !canChangeSelection}
                  onClick={() => one && setDialog({ mode: 'rename', value: one.name, rel: one.rel })}
                >
                  Rename
                </Button>
                <Button size="small" icon={<FolderAddOutlined />} disabled={!canChangeSelection} onClick={() => void openMover(selection.map((entry) => entry.rel))}>
                  Move
                </Button>
                {canChangeSelection ? (
                  <Dropdown
                    menu={{
                      items: [
                        { key: 'zip', label: 'Zip (.zip)' },
                        { key: 'tar.gz', label: 'tar.gz' },
                      ],
                      onClick: ({ key }) => {
                        if (key === 'zip' || key === 'tar.gz') void packEntries(selection, key)
                      },
                    }}
                  >
                    <Button size="small" icon={<FileZipOutlined />}>Pack</Button>
                  </Dropdown>
                ) : (
                  <Button size="small" icon={<FileZipOutlined />} disabled>Pack</Button>
                )}
                <Button
                  size="small"
                  icon={<FolderOpenOutlined />}
                  disabled={!canChangeSelection || !archiveSelection}
                  onClick={() => void extractEntries(selection)}
                >
                  Extract
                </Button>
                <Button size="small" danger icon={<DeleteOutlined />} disabled={!canChangeSelection} onClick={() => askDelete(selection)}>
                  Delete
                </Button>
              </>
            ) : null}
          </div>

          <div className={`fm-mobile-dock ${selection.length === 0 ? 'is-empty' : ''}`}>
            <div className="fm-mobile-dock-copy">
              <div className="fm-mobile-dock-kicker">{selection.length > 1 ? `${selection.length} selected` : 'Selected'}</div>
              <div className="fm-mobile-dock-name" title={one?.name || ''}>
                {one?.name || `${selection.length} items`}
              </div>
            </div>
            <Button
              type="primary"
              icon={<EyeOutlined />}
              disabled={!one}
              onClick={() => one && openEntry(one)}
            >
              {one && isDir(one) ? 'Open' : 'Preview'}
            </Button>
            <Dropdown
              menu={{
                items: [
                  {
                    key: 'download',
                    icon: <DownloadOutlined />,
                    label: 'Download',
                    disabled: !one || isDir(one) || !!one.broken,
                  },
                  {
                    key: 'copy',
                    icon: <CopyOutlined />,
                    label: 'Copy path',
                    disabled: selection.length === 0,
                  },
                  ...(canWrite
                    ? [
                        {
                          key: 'rename',
                          icon: <EditOutlined />,
                          label: 'Rename',
                          disabled: !one || !canChangeSelection,
                        },
                        {
                          key: 'move',
                          icon: <FolderAddOutlined />,
                          label: 'Move',
                          disabled: !canChangeSelection,
                        },
                        {
                          key: 'pack-zip',
                          icon: <FileZipOutlined />,
                          label: 'Pack zip',
                          disabled: !canChangeSelection,
                        },
                        {
                          key: 'pack-tar',
                          icon: <FileZipOutlined />,
                          label: 'Pack tar.gz',
                          disabled: !canChangeSelection,
                        },
                        {
                          key: 'extract',
                          icon: <FolderOpenOutlined />,
                          label: 'Extract',
                          disabled: !canChangeSelection || !archiveSelection,
                        },
                        {
                          type: 'divider' as const,
                        },
                        {
                          key: 'delete',
                          icon: <DeleteOutlined />,
                          label: 'Delete',
                          danger: true,
                          disabled: !canChangeSelection,
                        },
                      ]
                    : []),
                ],
                onClick: ({ key }) => {
                  if (key === 'download' && one) void download(one)
                  if (key === 'copy') copyPaths(selection)
                  if (key === 'rename' && one) setDialog({ mode: 'rename', value: one.name, rel: one.rel })
                  if (key === 'move') void openMover(selection.map((entry) => entry.rel))
                  if (key === 'pack-zip') void packEntries(selection, 'zip')
                  if (key === 'pack-tar') void packEntries(selection, 'tar.gz')
                  if (key === 'extract') void extractEntries(selection)
                  if (key === 'delete') askDelete(selection)
                },
              }}
            >
              <Button icon={<EllipsisOutlined />} aria-label="More actions" />
            </Dropdown>
          </div>

          {truncated ? <div className="fm-note">Showing the first 4000 entries.</div> : null}

          <div
            className={`fm-scroll ${band ? 'is-marquee' : ''}`}
            ref={scrollRef}
            onMouseDown={onPaneMouseDown}
          >
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
                    selected={picked.includes(entry.rel)}
                    current={selection.length > 1 && focusRel === entry.rel}
                    drop={dropRel === destOf(entry)}
                    canWrite={canWrite}
                    onSelect={(event) => {
                      if (event.shiftKey) event.preventDefault()
                      const kind = applyClick(event, entry)
                      if (kind !== 'plain') return
                      if (openMode === 'single') openEntry(entry)
                      else if (previewOpen && !isDir(entry)) setOpenFile(entry)
                    }}
                    onOpen={() => openEntry(entry)}
                    onContext={(event) => onItemContext(event, entry)}
                    onDragStart={(event) => beginDrag(event, entry)}
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
                    data-rel={entry.rel}
                    aria-selected={picked.includes(entry.rel)}
                    className={`fm-list-row ${picked.includes(entry.rel) ? 'is-selected' : ''} ${selection.length > 1 && focusRel === entry.rel ? 'is-current' : ''} ${dropRel === destOf(entry) ? 'is-drop' : ''}`}
                    draggable={canWrite}
                    onClick={(event) => {
                      if (event.shiftKey) event.preventDefault()
                      const kind = applyClick(event, entry)
                      if (kind !== 'plain') return
                      if (openMode === 'single') openEntry(entry)
                      else if (previewOpen && !isDir(entry)) setOpenFile(entry)
                    }}
                    onDoubleClick={() => openEntry(entry)}
                    onContextMenu={(event) => onItemContext(event, entry)}
                    onDragStart={(event) => beginDrag(event, entry)}
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
              {selection.length ? ` · ${selection.length} selected` : ''}
            </span>
            <span>
              {openMode === 'single' ? 'Click to open' : 'Double-click to open'}
              {' · Shift+click or drag to select · Shift+arrows to extend'}
            </span>
          </div>
        </section>

        {previewOpen ? (
          <PreviewPane
            rootId={rootId}
            entry={openFile}
            canWrite={canWrite}
            wide={previewWide}
            onToggleWide={() => setPreviewExpanded(!previewWide)}
            onResizeStart={startPreviewResize}
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
          void uploadTree(cwd, treeFromFileList(list))
        }}
      />

      {menu ? (
        <div
          className="fm-menu"
          style={{
            top: Math.min(menu.y, window.innerHeight - 380),
            left: Math.min(menu.x, window.innerWidth - 200),
          }}
          onClick={(event) => event.stopPropagation()}
        >
          <button type="button" onClick={() => { openEntry(menu.entry); setMenu(null) }}>
            <EyeOutlined /> {isDir(menu.entry) ? 'Open' : 'Preview'}
          </button>
          {menuGroup.length === 1 && !isDir(menu.entry) ? (
            <button type="button" onClick={() => { void download(menu.entry); setMenu(null) }}>
              <DownloadOutlined /> Download
            </button>
          ) : null}
          <button type="button" onClick={() => { copyPaths(menuGroup); setMenu(null) }}>
            <CopyOutlined /> {menuGroup.length > 1 ? 'Copy paths' : 'Copy path'}
          </button>
          {menuWritable ? (
            <>
              <button type="button" onClick={() => { void packEntries(menuGroup, 'zip'); setMenu(null) }}>
                <FileZipOutlined /> {menuGroup.length > 1 ? `Pack ${menuGroup.length} as zip` : 'Pack as zip'}
              </button>
              <button type="button" onClick={() => { void packEntries(menuGroup, 'tar.gz'); setMenu(null) }}>
                <FileZipOutlined /> {menuGroup.length > 1 ? `Pack ${menuGroup.length} as tar.gz` : 'Pack as tar.gz'}
              </button>
              {menuArchives ? (
                <button type="button" onClick={() => { void extractEntries(menuGroup); setMenu(null) }}>
                  <FolderOpenOutlined /> {menuGroup.length > 1 ? `Extract ${menuGroup.length}` : 'Extract'}
                </button>
              ) : null}
              {menuGroup.length === 1 ? (
                <button
                  type="button"
                  onClick={() => {
                    setDialog({ mode: 'rename', value: menu.entry.name, rel: menu.entry.rel })
                    setMenu(null)
                  }}
                >
                  <EditOutlined /> Rename
                </button>
              ) : null}
              <button type="button" onClick={() => { void openMover(menuGroup.map((entry) => entry.rel)); setMenu(null) }}>
                <FolderAddOutlined /> {menuGroup.length > 1 ? `Move ${menuGroup.length} to…` : 'Move to…'}
              </button>
              <button type="button" className="is-danger" onClick={() => { askDelete(menuGroup); setMenu(null) }}>
                <DeleteOutlined /> {menuGroup.length > 1 ? `Delete ${menuGroup.length}` : 'Delete'}
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
        title={mover && mover.rels.length > 1 ? `Move ${mover.rels.length} items` : `Move “${entries.find((entry) => entry.rel === mover?.rels[0])?.name || ''}”`}
        open={!!mover}
        okText="Move here"
        confirmLoading={busy}
        onOk={() => {
          if (!mover) return
          void moveMany(mover.rels, mover.browse).then(() => setMover(null))
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

      {band ? <div className="fm-marquee" style={{ left: band.x, top: band.y, width: band.w, height: band.h }} /> : null}
      {job ? <JobCard job={job} /> : busy ? <div className="fm-busy">{busyNote}</div> : null}
    </div>
  )
}

function holdJobDone() {
  return new Promise<void>((resolve) => window.setTimeout(resolve, 720))
}

function JobCard({ job }: { job: JobView }) {
  const pct = Math.max(0, Math.min(100, Math.round(job.pct)))
  return (
    <div className={`fm-job ${pct >= 100 ? 'is-done' : ''}`} role="status" aria-live="polite">
      <div className="fm-job-top">
        <div className="fm-job-copy">
          <div className="fm-job-kicker">{job.title}</div>
          <div className="fm-job-name" title={job.detail}>{job.detail}</div>
          {job.meta ? <div className="fm-job-meta">{job.meta}</div> : null}
        </div>
        <div className="fm-job-pct" aria-hidden>
          {pct}
          <span>%</span>
        </div>
      </div>
      <div
        className="fm-job-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label={job.title}
      >
        <div className="fm-job-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function kindLabel(entry: FmEntry) {
  if (entry.broken) return 'Broken link'
  if (entry.escaped) return 'External link'
  if (isDir(entry)) return entry.symlink ? 'Folder link' : 'Folder'
  if (entry.preview === 'markdown') return 'Markdown'
  if (entry.preview === 'pdf') return 'PDF'
  if (entry.preview === 'docx') return 'Word'
  if (entry.preview === 'xlsx') return 'Excel'
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
  current,
  drop,
  canWrite,
  onSelect,
  onOpen,
  onContext,
  onDragStart,
  onDragOver,
  onDrop,
}: {
  entry: FmEntry
  selected: boolean
  current: boolean
  drop: boolean
  canWrite: boolean
  onSelect: (event: React.MouseEvent) => void
  onOpen: () => void
  onContext: (event: React.MouseEvent) => void
  onDragStart: (event: DragEvent) => void
  onDragOver?: (event: DragEvent) => void
  onDrop?: (event: DragEvent) => void
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      data-rel={entry.rel}
      aria-selected={selected}
      className={`fm-tile ${selected ? 'is-selected' : ''} ${current ? 'is-current' : ''} ${drop ? 'is-drop' : ''} ${entry.escaped || entry.broken ? 'is-muted' : ''}`}
      draggable={canWrite}
      onClick={onSelect}
      onDoubleClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          event.stopPropagation()
          onOpen()
        }
      }}
      onContextMenu={onContext}
      onDragStart={onDragStart}
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
  wide,
  onToggleWide,
  onResizeStart,
  onClose,
  onSaved,
  onDownload,
}: {
  rootId: string
  entry: FmEntry | null
  canWrite: boolean
  wide: boolean
  onToggleWide: () => void
  onResizeStart: (event: React.MouseEvent) => void
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
      (entry.editable &&
        entry.preview !== 'image' &&
        entry.preview !== 'pdf' &&
        entry.preview !== 'docx' &&
        entry.preview !== 'xlsx' &&
        entry.preview !== 'audio' &&
        entry.preview !== 'video'))

  const wantsOffice = !!entry && (entry.preview === 'docx' || entry.preview === 'xlsx')

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
        if (wantsOffice) {
          replaceUrl(null)
        } else if (wantsText) {
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
  }, [entry, rootId, wantsText, wantsOffice])

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
      <button
        type="button"
        className="fm-split-handle"
        aria-label={wide ? 'Restore preview width' : 'Drag to resize preview. Double-click to expand.'}
        onMouseDown={onResizeStart}
        onDoubleClick={(event) => {
          event.preventDefault()
          onToggleWide()
        }}
      />
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
          <Tooltip title={wide ? 'Show the file list again' : 'Use the full area for this file'}>
            <Button
              size="small"
              type={wide ? 'default' : 'text'}
              icon={wide ? <CompressOutlined /> : <ExpandAltOutlined />}
              aria-label={wide ? 'Show the file list' : 'Expand preview'}
              onClick={onToggleWide}
            >
              {wide ? 'Files' : 'Expand'}
            </Button>
          </Tooltip>
          <Button size="small" type="text" onClick={requestClose}>
            Close
          </Button>
        </div>
      </div>
      <div className="fm-preview-body">
        {!entry ? (
          <div className="fm-center">Select a file to preview it.</div>
        ) : wantsOffice ? (
          <Suspense
            fallback={
              <div className="fm-center">
                <Spin />
              </div>
            }
          >
            <OfficePreview rootId={rootId} entry={entry} onDownload={() => onDownload(entry)} />
          </Suspense>
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
