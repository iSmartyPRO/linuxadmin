import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Input, Modal, Spin, Switch, Tooltip } from 'antd'
import { ArrowLeftOutlined, SearchOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import { FileGlyph } from './FileGlyph'

type DirEntry = {
  name: string
  path: string
  symlink: boolean
  blocked: boolean
  reason: string | null
}

type BrowseResp = {
  path: string
  parent: string | null
  selectable: boolean
  reason: string | null
  truncated: boolean
  entries: DirEntry[]
}

function apiError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e)
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown }
    if (typeof parsed.detail === 'string') return parsed.detail
  } catch {
    /* plain text */
  }
  return raw
}

export function FolderPicker({
  open,
  initialPath,
  onClose,
  onSelect,
}: {
  open: boolean
  initialPath?: string
  onClose: () => void
  onSelect: (path: string, name: string) => void
}) {
  const [path, setPath] = useState('/')
  const [parent, setParent] = useState<string | null>(null)
  const [entries, setEntries] = useState<DirEntry[]>([])
  const [selectable, setSelectable] = useState(false)
  const [reason, setReason] = useState<string | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [picked, setPicked] = useState<DirEntry | null>(null)
  const [query, setQuery] = useState('')
  const [hidden, setHidden] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const pathRef = useRef('/')
  const seenOpen = useRef(false)
  pathRef.current = path

  const load = useCallback(async (next: string) => {
    setLoading(true)
    setError('')
    setPicked(null)
    try {
      const data = await api<BrowseResp>(
        `/api/files/browse?path=${encodeURIComponent(next || '/')}&hidden=${hidden}`,
      )
      setPath(data.path)
      setParent(data.parent)
      setEntries(data.entries)
      setSelectable(data.selectable)
      setReason(data.reason)
      setTruncated(data.truncated)
    } catch (e) {
      setError(apiError(e))
    } finally {
      setLoading(false)
    }
  }, [hidden])

  useEffect(() => {
    if (!open) {
      seenOpen.current = false
      return
    }
    const start = seenOpen.current
      ? pathRef.current
      : initialPath && initialPath.startsWith('/')
        ? initialPath
        : '/'
    seenOpen.current = true
    void load(start)
  }, [open, initialPath, load])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return entries
    return entries.filter((entry) => entry.name.toLowerCase().includes(q))
  }, [entries, query])

  const crumbs = path === '/' ? [] : path.split('/').filter(Boolean)
  const choice = picked?.path || (selectable ? path : '')
  const choiceName = picked?.name || (path === '/' ? '' : path.split('/').filter(Boolean).pop() || '')
  const choiceBlocked = picked ? picked.blocked : !selectable

  function confirm() {
    if (!choice || choiceBlocked) return
    onSelect(choice, choiceName)
  }

  return (
    <Modal
      className="fm-picker-modal"
      title="Choose a folder"
      open={open}
      onCancel={onClose}
      width={720}
      destroyOnHidden
      footer={
        <div className="fm-picker-footer">
          <div className="fm-picker-chosen">
            <span className="mono">{choice || path}</span>
            {choiceBlocked ? <em>{picked?.reason || reason || 'This folder cannot be mounted'}</em> : <em>This folder will be mounted</em>}
          </div>
          <div className="fm-picker-actions">
            <Button onClick={onClose}>Cancel</Button>
            <Button type="primary" disabled={!choice || choiceBlocked} onClick={confirm}>
              Select folder
            </Button>
          </div>
        </div>
      }
    >
      <div className="fm-picker">
        <div className="fm-picker-bar">
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            disabled={parent === null || loading}
            onClick={() => parent !== null && void load(parent)}
          />
          <div className="fm-crumbs">
            <button type="button" onClick={() => void load('/')}>
              /
            </button>
            {crumbs.map((part, index) => {
              const rel = '/' + crumbs.slice(0, index + 1).join('/')
              return (
                <span key={rel}>
                  <span className="fm-crumb-sep">/</span>
                  <button type="button" onClick={() => void load(rel)}>
                    {part}
                  </button>
                </span>
              )
            })}
          </div>
          <Tooltip title={hidden ? 'Hide dotfolders' : 'Show hidden folders'}>
            <Switch size="small" checked={hidden} onChange={setHidden} />
          </Tooltip>
        </div>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="Filter folders"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <div className="fm-picker-list">
          {loading ? (
            <div className="fm-center">
              <Spin />
            </div>
          ) : error ? (
            <div className="fm-center">{error}</div>
          ) : visible.length === 0 ? (
            <div className="fm-center">No folders here</div>
          ) : (
            visible.map((entry) => (
              <button
                key={entry.path + entry.name}
                type="button"
                className={`fm-picker-row ${picked?.path === entry.path ? 'is-selected' : ''} ${entry.blocked ? 'is-muted' : ''}`}
                onClick={() => setPicked(entry)}
                onDoubleClick={() => void load(entry.path)}
              >
                <FileGlyph tone="folder" size={28} />
                <span className="fm-picker-name">
                  {entry.name}
                  {entry.symlink ? <em> link</em> : null}
                </span>
                <span className="fm-picker-side">{entry.blocked ? 'unavailable' : 'folder'}</span>
              </button>
            ))
          )}
        </div>
        {truncated ? <div className="fm-note">Showing the first 2000 folders.</div> : null}
        <p className="fm-picker-hint">Click a folder to highlight it, double-click to open it. Select mounts the highlighted folder, or the folder you are in.</p>
      </div>
    </Modal>
  )
}
