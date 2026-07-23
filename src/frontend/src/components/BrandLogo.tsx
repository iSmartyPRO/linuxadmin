import type { CSSProperties } from 'react'

type Props = {
  size?: number
  className?: string
  style?: CSSProperties
  alt?: string
}

/** Project logo (Tux admin mark) from /brand/logo.png */
export function BrandLogo({ size = 36, className, style, alt = 'Linux Admin' }: Props) {
  return (
    <img
      src="/brand/logo.png"
      srcSet="/brand/logo-64.png 64w, /brand/logo-128.png 128w, /brand/logo-192.png 192w, /brand/logo.png 616w"
      sizes={`${size}px`}
      width={size}
      height={size}
      alt={alt}
      draggable={false}
      className={className ? `la-brand-logo ${className}` : 'la-brand-logo'}
      style={{ width: size, height: size, ...style }}
    />
  )
}
