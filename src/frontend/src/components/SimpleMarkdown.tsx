import type { ReactNode } from 'react'

/** Minimal markdown renderer for in-app docs (headings, lists, code, tables). */
export function SimpleMarkdown({ text }: { text: string }) {
  const lines = (text || '').replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const line = lines[i]
    if (line.startsWith('```')) {
      const lang = line.slice(3).trim()
      const buf: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) {
        buf.push(lines[i])
        i++
      }
      i++
      blocks.push(
        <pre
          key={key++}
          className="mono"
          style={{
            padding: 12,
            borderRadius: 8,
            background: 'var(--la-paper)',
            border: '1px solid var(--la-panel-border)',
            overflow: 'auto',
            fontSize: 12,
          }}
          data-lang={lang}
        >
          {buf.join('\n')}
        </pre>,
      )
      continue
    }
    if (line.startsWith('## ')) {
      blocks.push(
        <h3 key={key++} style={{ marginTop: 20, marginBottom: 8 }}>
          {line.slice(3)}
        </h3>,
      )
      i++
      continue
    }
    if (line.startsWith('# ')) {
      blocks.push(
        <h2 key={key++} style={{ marginTop: 16, marginBottom: 8 }}>
          {line.slice(2)}
        </h2>,
      )
      i++
      continue
    }
    if (line.startsWith('|') && line.includes('|')) {
      const rows: string[][] = []
      while (i < lines.length && lines[i].startsWith('|')) {
        const cells = lines[i]
          .split('|')
          .slice(1, -1)
          .map((c) => c.trim())
        if (!/^\s*:?-+:?\s*$/.test(cells.join(''))) rows.push(cells)
        i++
      }
      blocks.push(
        <table
          key={key++}
          style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginBottom: 12 }}
        >
          <tbody>
            {rows.map((r, ri) => (
              <tr key={ri}>
                {r.map((c, ci) => (
                  <td
                    key={ci}
                    style={{
                      border: '1px solid var(--la-panel-border)',
                      padding: '6px 8px',
                      fontWeight: ri === 0 ? 600 : 400,
                    }}
                  >
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      )
      continue
    }
    if (line.startsWith('- ')) {
      const items: string[] = []
      while (i < lines.length && lines[i].startsWith('- ')) {
        items.push(lines[i].slice(2))
        i++
      }
      blocks.push(
        <ul key={key++} style={{ paddingLeft: 20, marginBottom: 12 }}>
          {items.map((it, idx) => (
            <li key={idx} style={{ marginBottom: 4 }}>
              {formatInline(it)}
            </li>
          ))}
        </ul>,
      )
      continue
    }
    if (!line.trim()) {
      i++
      continue
    }
    blocks.push(
      <p key={key++} style={{ marginBottom: 10, lineHeight: 1.55 }}>
        {formatInline(line)}
      </p>,
    )
    i++
  }

  return <div>{blocks}</div>
}

function formatInline(text: string): ReactNode {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g)
  return parts.map((part, i) => {
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={i} className="mono" style={{ fontSize: 12 }}>
          {part.slice(1, -1)}
        </code>
      )
    }
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>
    }
    return <span key={i}>{part}</span>
  })
}
