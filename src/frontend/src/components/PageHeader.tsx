import type { ReactNode } from 'react'
import { Space } from 'antd'
import { ModuleDocsButton } from './ModuleDocsButton'

type Props = {
  title: ReactNode
  subtitle?: ReactNode
  extra?: ReactNode
  live?: boolean
  /** Module doc key for the in-app documentation drawer */
  docsKey?: string
}

export function PageHeader({ title, subtitle, extra, live, docsKey }: Props) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 16,
        flexWrap: 'wrap',
      }}
    >
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <h1
            className="display"
            style={{
              margin: 0,
              fontSize: 30,
              fontWeight: 700,
              lineHeight: 1.15,
              letterSpacing: '-0.03em',
            }}
          >
            {title}
          </h1>
          {live ? (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 12,
                fontWeight: 600,
                color: 'var(--la-muted)',
                padding: '4px 10px',
                borderRadius: 999,
                border: '1px solid var(--la-panel-border)',
                background: 'color-mix(in srgb, var(--la-panel) 70%, transparent)',
              }}
            >
              <span className="la-live-dot" />
              live
            </span>
          ) : null}
        </div>
        {subtitle ? (
          <p style={{ margin: '8px 0 0', color: 'var(--la-muted)', fontSize: 14, maxWidth: 720 }}>
            {subtitle}
          </p>
        ) : null}
      </div>
      <Space wrap>
        {docsKey ? <ModuleDocsButton docKey={docsKey} /> : null}
        {extra}
      </Space>
    </div>
  )
}
