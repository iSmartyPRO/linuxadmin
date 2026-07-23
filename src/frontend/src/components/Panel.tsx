import type { CSSProperties, ReactNode } from 'react'

type Props = {
  children: ReactNode
  title?: ReactNode
  extra?: ReactNode
  className?: string
  style?: CSSProperties
  bodyStyle?: CSSProperties
  padded?: boolean
}

export function Panel({
  children,
  title,
  extra,
  className,
  style,
  bodyStyle,
  padded = true,
}: Props) {
  return (
    <section className={`la-panel ${className || ''}`.trim()} style={style}>
      {title || extra ? (
        <header
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            padding: '16px 18px 0',
          }}
        >
          {typeof title === 'string' ? <h3 className="la-panel-title">{title}</h3> : title}
          {extra}
        </header>
      ) : null}
      <div style={{ padding: padded ? 18 : 0, ...bodyStyle }}>{children}</div>
    </section>
  )
}
