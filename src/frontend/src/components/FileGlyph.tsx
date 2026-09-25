import { useId } from 'react'

export type GlyphTone = 'folder' | 'pdf' | 'image' | 'markdown' | 'text' | 'audio' | 'video' | 'archive' | 'file'

const STOPS: Record<GlyphTone, [string, string]> = {
  folder: ['#ffe08a', '#e39b16'],
  pdf: ['#fda4af', '#e11d48'],
  image: ['#ddd6fe', '#7c3aed'],
  markdown: ['#99f6e4', '#0f766e'],
  text: ['#bae6fd', '#0284c7'],
  audio: ['#fbcfe8', '#db2777'],
  video: ['#ddd6fe', '#6d28d9'],
  archive: ['#fed7aa', '#c2410c'],
  file: ['#e2e8f0', '#64748b'],
}

const ARCHIVE = new Set(['zip', 'gz', 'tgz', 'bz2', 'xz', '7z', 'rar', 'tar'])

export function glyphTone(entry: {
  kind: string
  link_dir?: boolean
  preview: string
  ext: string
}): GlyphTone {
  if (entry.kind === 'dir' || entry.link_dir) return 'folder'
  if (entry.preview === 'pdf') return 'pdf'
  if (entry.preview === 'image') return 'image'
  if (entry.preview === 'markdown') return 'markdown'
  if (entry.preview === 'audio') return 'audio'
  if (entry.preview === 'video') return 'video'
  if (entry.preview === 'text') return 'text'
  if (ARCHIVE.has(entry.ext)) return 'archive'
  return 'file'
}

export function FileGlyph({
  tone,
  ext,
  size = 46,
}: {
  tone: GlyphTone
  ext?: string
  size?: number
}) {
  const raw = useId().replace(/:/g, '')
  const [a, b] = STOPS[tone]
  const label = (ext || '').slice(0, 4).toUpperCase()
  if (tone === 'folder') {
    return (
      <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
        <defs>
          <linearGradient id={`${raw}-f`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor={a} />
            <stop offset="1" stopColor={b} />
          </linearGradient>
        </defs>
        <path
          d="M8 22c0-3.3 2.5-6 5.8-6h11.2l3.6 4.2H50c3.3 0 6 2.7 6 6V48c0 3.3-2.7 6-6 6H14c-3.3 0-6-2.7-6-6V22z"
          fill={`url(#${raw}-f)`}
        />
        <path
          d="M8 28h48v20c0 3.3-2.7 6-6 6H14c-3.3 0-6-2.7-6-6V28z"
          fill="#fff"
          opacity="0.28"
        />
      </svg>
    )
  }
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <defs>
        <linearGradient id={`${raw}-d`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={a} />
          <stop offset="1" stopColor={b} />
        </linearGradient>
      </defs>
      <path
        d="M16 8h22l12 12v34c0 2.2-1.8 4-4 4H16c-2.2 0-4-1.8-4-4V12c0-2.2 1.8-4 4-4z"
        fill={`url(#${raw}-d)`}
      />
      <path d="M38 8v10c0 1.1.9 2 2 2h10" fill="#fff" opacity="0.55" />
      {label ? (
        <text
          x="32"
          y="42"
          textAnchor="middle"
          fontFamily="Manrope, sans-serif"
          fontSize={label.length > 3 ? 9 : 11}
          fontWeight="700"
          fill="#fff"
        >
          {label}
        </text>
      ) : null}
    </svg>
  )
}
