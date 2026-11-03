const ISMARTY_URL = 'https://www.ismarty.pro'

type Props = {
  className?: string
  style?: React.CSSProperties
}

/** Footer credit: Powered by iSmartyPRO® */
export function PoweredBy({ className, style }: Props) {
  return (
    <div className={['la-powered-by', className].filter(Boolean).join(' ')} style={style}>
      Powered by{' '}
      <a href={ISMARTY_URL} target="_blank" rel="noopener noreferrer">
        iSmartyPRO
      </a>
      ®
    </div>
  )
}
