import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { Button, Spin, Tooltip } from 'antd'
import {
  DownloadOutlined,
  MinusOutlined,
  PlusOutlined,
  CompressOutlined,
} from '@ant-design/icons'
import { renderAsync } from 'docx-preview'
import ExcelJS from 'exceljs'
import { apiDownload } from '../api/client'
import { formatBytes } from '../utils/format'
import { FileGlyph } from './FileGlyph'

const OFFICE_PREVIEW_CAP = 8 * 1024 * 1024
const XLSX_MAX_ROWS = 200
const XLSX_MAX_COLS = 40
const ZOOM_MIN = 0.4
const ZOOM_MAX = 2.5
const ZOOM_STEP = 0.1

type OfficeEntry = {
  name: string
  rel: string
  size: number | null
  ext: string
  preview: string
}

type SheetView = {
  name: string
  rows: string[][]
  truncated: boolean
  totalRows: number
  totalCols: number
}

function officeError(e: unknown): string {
  if (e instanceof Error && e.message) {
    if (/Failed to fetch dynamically imported module|Loading chunk|Importing a module script failed/i.test(e.message)) {
      return 'Preview libraries failed to load. Hard-refresh the page (Ctrl+Shift+R) and try again.'
    }
    try {
      const parsed = JSON.parse(e.message) as { detail?: unknown }
      if (typeof parsed.detail === 'string') return parsed.detail
    } catch {
      return e.message
    }
    return e.message
  }
  return 'Could not open this file for preview'
}

function cellText(value: unknown): string {
  if (value == null || value === '') return ''
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  if (value instanceof Date) return value.toLocaleString()
  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>
    if ('richText' in obj && Array.isArray(obj.richText)) {
      return obj.richText.map((part) => String((part as { text?: string }).text ?? '')).join('')
    }
    if ('text' in obj && typeof obj.text === 'string') return obj.text
    if ('result' in obj) return cellText(obj.result)
    if ('formula' in obj) return cellText(obj.result ?? '')
    if ('sharedFormula' in obj) return cellText(obj.result ?? '')
    if ('error' in obj) return String(obj.error)
    if ('hyperlink' in obj) return cellText(obj.text ?? obj.hyperlink)
  }
  return String(value)
}

function clampZoom(value: number) {
  const snapped = Math.round(value * 100) / 100
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, snapped))
}

function ZoomBar({
  zoom,
  onZoom,
  onFit,
}: {
  zoom: number
  onZoom: (next: number) => void
  onFit: () => void
}) {
  return (
    <div className="fm-zoom-bar" role="toolbar" aria-label="Zoom">
      <Tooltip title="Zoom out">
        <Button
          size="small"
          type="text"
          icon={<MinusOutlined />}
          disabled={zoom <= ZOOM_MIN}
          onClick={() => onZoom(clampZoom(zoom - ZOOM_STEP))}
          aria-label="Zoom out"
        />
      </Tooltip>
      <button type="button" className="fm-zoom-pct" onClick={() => onZoom(1)} title="Reset to 100%">
        {Math.round(zoom * 100)}%
      </button>
      <Tooltip title="Zoom in">
        <Button
          size="small"
          type="text"
          icon={<PlusOutlined />}
          disabled={zoom >= ZOOM_MAX}
          onClick={() => onZoom(clampZoom(zoom + ZOOM_STEP))}
          aria-label="Zoom in"
        />
      </Tooltip>
      <Tooltip title="Fit to width">
        <Button size="small" type="text" icon={<CompressOutlined />} onClick={onFit} aria-label="Fit to width" />
      </Tooltip>
    </div>
  )
}

export function OfficePreview({
  rootId,
  entry,
  onDownload,
}: {
  rootId: string
  entry: OfficeEntry
  onDownload: (entry: OfficeEntry) => void
}) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tooLarge, setTooLarge] = useState(false)
  const [sheets, setSheets] = useState<SheetView[]>([])
  const [sheetIndex, setSheetIndex] = useState(0)
  const [docxBlob, setDocxBlob] = useState<Blob | null>(null)
  const [zoom, setZoom] = useState(1)
  const [ready, setReady] = useState(false)
  const docRef = useRef<HTMLDivElement | null>(null)
  const stageRef = useRef<HTMLDivElement | null>(null)
  const zoomRef = useRef(zoom)
  zoomRef.current = zoom
  const naturalRef = useRef(0)
  const pinchRef = useRef<{ dist: number; zoom: number } | null>(null)
  const supportsZoom =
    typeof CSS !== 'undefined' && typeof CSS.supports === 'function' ? CSS.supports('zoom', '1') : true

  const fitWidth = useCallback(() => {
    const stage = stageRef.current
    if (!stage) return
    const pad = 24
    const available = Math.max(120, stage.clientWidth - pad)
    let natural = naturalRef.current
    if (!natural) {
      if (entry.preview === 'docx') {
        const page = docRef.current?.querySelector('.docx-wrapper > section.docx, section.docx') as HTMLElement | null
        natural = page?.scrollWidth || page?.offsetWidth || 0
      } else {
        const table = stage.querySelector('.fm-xlsx-table') as HTMLElement | null
        natural = table ? table.scrollWidth / (zoomRef.current || 1) : 0
      }
      naturalRef.current = natural
    }
    if (natural > 0) setZoom(clampZoom(available / natural))
  }, [entry.preview])

  function zoomStyle(value: number): CSSProperties {
    if (supportsZoom) return { zoom: value } as CSSProperties
    return {
      transform: `scale(${value})`,
      transformOrigin: entry.preview === 'docx' ? 'top center' : 'top left',
      width: entry.preview === 'docx' ? undefined : `${100 / value}%`,
    }
  }

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      setLoading(true)
      setError('')
      setTooLarge(false)
      setSheets([])
      setSheetIndex(0)
      setDocxBlob(null)
      setReady(false)
      setZoom(1)
      naturalRef.current = 0
      let handoffDocx = false
      try {
        if (entry.size != null && entry.size > OFFICE_PREVIEW_CAP) {
          if (!cancelled) setTooLarge(true)
          return
        }
        const { blob } = await apiDownload(
          `/api/files/raw?root_id=${encodeURIComponent(rootId)}&rel=${encodeURIComponent(entry.rel)}`,
        )
        if (cancelled) return
        if (blob.size > OFFICE_PREVIEW_CAP) {
          setTooLarge(true)
          return
        }
        if (entry.preview === 'docx') {
          setDocxBlob(blob)
          handoffDocx = true
          return
        }
        if (entry.preview === 'xlsx') {
          const workbook = new ExcelJS.Workbook()
          await workbook.xlsx.load(await blob.arrayBuffer())
          if (cancelled) return
          const next: SheetView[] = workbook.worksheets.map((sheet) => {
            const totalRows = Math.max(sheet.rowCount || 0, sheet.actualRowCount || 0)
            const totalCols = Math.max(sheet.columnCount || 0, sheet.actualColumnCount || 0)
            const rowLimit = Math.min(totalRows, XLSX_MAX_ROWS)
            const colLimit = Math.min(Math.max(totalCols, 1), XLSX_MAX_COLS)
            const rows: string[][] = []
            for (let r = 1; r <= rowLimit; r += 1) {
              const row = sheet.getRow(r)
              const cells: string[] = []
              for (let c = 1; c <= colLimit; c += 1) {
                cells.push(cellText(row.getCell(c).value))
              }
              rows.push(cells)
            }
            return {
              name: sheet.name || `Sheet ${sheet.id}`,
              rows,
              truncated: totalRows > XLSX_MAX_ROWS || totalCols > XLSX_MAX_COLS,
              totalRows,
              totalCols,
            }
          })
          setSheets(next.length ? next : [{ name: 'Sheet1', rows: [], truncated: false, totalRows: 0, totalCols: 0 }])
          setReady(true)
        }
      } catch (e) {
        if (!cancelled) setError(officeError(e))
      } finally {
        if (!cancelled && !handoffDocx) setLoading(false)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [entry.rel, entry.preview, entry.size, rootId])

  useEffect(() => {
    if (!docxBlob || entry.preview !== 'docx') return
    let cancelled = false
    const host = docRef.current
    if (!host) return
    host.innerHTML = ''
    void (async () => {
      try {
        if (cancelled || !docRef.current) return
        await renderAsync(docxBlob, docRef.current, undefined, {
          className: 'fm-docx-doc',
          inWrapper: true,
          ignoreWidth: false,
          ignoreHeight: false,
          breakPages: true,
          renderHeaders: true,
          renderFooters: true,
        })
        if (!cancelled) {
          const page = docRef.current?.querySelector(
            '.docx-wrapper > section.docx, section.docx',
          ) as HTMLElement | null
          naturalRef.current = page?.scrollWidth || page?.offsetWidth || 0
          setReady(true)
          requestAnimationFrame(() => {
            if (!cancelled) fitWidth()
          })
        }
      } catch (e) {
        if (!cancelled) setError(officeError(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [docxBlob, entry.preview, fitWidth])

  useEffect(() => {
    if (!ready || entry.preview !== 'xlsx') return
    naturalRef.current = 0
    requestAnimationFrame(() => {
      const table = stageRef.current?.querySelector('.fm-xlsx-table') as HTMLElement | null
      if (table) naturalRef.current = table.scrollWidth / (zoomRef.current || 1)
      fitWidth()
    })
  }, [ready, entry.preview, sheetIndex, fitWidth])

  useEffect(() => {
    const stage = stageRef.current
    if (!stage || !ready) return

    const onWheel = (event: WheelEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return
      event.preventDefault()
      const delta = event.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP
      setZoom((prev) => clampZoom(prev + delta))
    }

    const touchDist = (a: Touch, b: Touch) => {
      const dx = a.clientX - b.clientX
      const dy = a.clientY - b.clientY
      return Math.hypot(dx, dy)
    }

    const onTouchStart = (event: TouchEvent) => {
      if (event.touches.length !== 2) return
      pinchRef.current = {
        dist: touchDist(event.touches[0], event.touches[1]),
        zoom: zoomRef.current,
      }
    }

    const onTouchMove = (event: TouchEvent) => {
      if (event.touches.length !== 2 || !pinchRef.current) return
      event.preventDefault()
      const dist = touchDist(event.touches[0], event.touches[1])
      if (pinchRef.current.dist < 8) return
      setZoom(clampZoom(pinchRef.current.zoom * (dist / pinchRef.current.dist)))
    }

    const onTouchEnd = () => {
      pinchRef.current = null
    }

    stage.addEventListener('wheel', onWheel, { passive: false })
    stage.addEventListener('touchstart', onTouchStart, { passive: true })
    stage.addEventListener('touchmove', onTouchMove, { passive: false })
    stage.addEventListener('touchend', onTouchEnd)
    stage.addEventListener('touchcancel', onTouchEnd)
    return () => {
      stage.removeEventListener('wheel', onWheel)
      stage.removeEventListener('touchstart', onTouchStart)
      stage.removeEventListener('touchmove', onTouchMove)
      stage.removeEventListener('touchend', onTouchEnd)
      stage.removeEventListener('touchcancel', onTouchEnd)
    }
  }, [ready])

  if (tooLarge) {
    return (
      <div className="fm-center fm-empty-inline">
        <FileGlyph tone={entry.preview === 'xlsx' ? 'xlsx' : 'docx'} ext={entry.ext} size={72} />
        <div>
          This file is too large to preview
          {entry.size != null ? ` (${formatBytes(entry.size)})` : ''}. Limit is {formatBytes(OFFICE_PREVIEW_CAP)}.
        </div>
        <Button icon={<DownloadOutlined />} onClick={() => onDownload(entry)}>
          Download
        </Button>
      </div>
    )
  }

  if (error) {
    return (
      <div className="fm-center fm-empty-inline">
        <FileGlyph tone={entry.preview === 'xlsx' ? 'xlsx' : 'docx'} ext={entry.ext} size={72} />
        <div>{error}</div>
        <Button icon={<DownloadOutlined />} onClick={() => onDownload(entry)}>
          Download
        </Button>
      </div>
    )
  }

  if (entry.preview === 'docx') {
    return (
      <div className="fm-office-viewer">
        {!loading && ready ? <ZoomBar zoom={zoom} onZoom={setZoom} onFit={fitWidth} /> : null}
        <div className="fm-docx-stage" ref={stageRef}>
          {loading || !docxBlob ? (
            <div className="fm-center fm-docx-loading">
              <Spin />
            </div>
          ) : null}
          <div
            className={loading || !docxBlob ? 'fm-docx-host is-busy' : 'fm-docx-host'}
            style={zoomStyle(zoom)}
          >
            <div ref={docRef} />
          </div>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="fm-center">
        <Spin />
      </div>
    )
  }

  const active = sheets[sheetIndex] || sheets[0]
  return (
    <div className="fm-office-viewer">
      <div className="fm-xlsx-toolbar">
        {sheets.length > 1 ? (
          <div className="fm-xlsx-tabs">
            {sheets.map((sheet, index) => (
              <button
                key={`${sheet.name}-${index}`}
                type="button"
                className={index === sheetIndex ? 'is-on' : ''}
                onClick={() => setSheetIndex(index)}
              >
                {sheet.name}
              </button>
            ))}
          </div>
        ) : (
          <div />
        )}
        <ZoomBar zoom={zoom} onZoom={setZoom} onFit={fitWidth} />
      </div>
      {active?.truncated ? (
        <div className="fm-xlsx-note">
          Showing first {Math.min(active.totalRows, XLSX_MAX_ROWS)} rows and {Math.min(active.totalCols, XLSX_MAX_COLS)}{' '}
          columns of {active.totalRows} × {active.totalCols}.
        </div>
      ) : null}
      <div className="fm-xlsx-stage" ref={stageRef}>
        <div className="fm-xlsx-scroll" style={zoomStyle(zoom)}>
          {active && active.rows.length > 0 ? (
            <table className="fm-xlsx-table">
              <tbody>
                {active.rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    <th scope="row">{rowIndex + 1}</th>
                    {row.map((cell, colIndex) => (
                      <td key={colIndex}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="fm-center">This sheet is empty.</div>
          )}
        </div>
      </div>
    </div>
  )
}
