/**
 * 線のアイコン14種（E1 11章の13種と、判定できないチェックの横線）。24 の格子に線 1.5、端は四角、角は直角。既成のアイコン集は使わない。
 * どれも文字と並べ、読み上げは文字か aria-label で行う（印は aria-hidden）。
 */
export type IconName =
  | 'menu'
  | 'search'
  | 'plus'
  | 'check'
  | 'why'
  | 'back'
  | 'next'
  | 'down'
  | 'ext'
  | 'list'
  | 'grid'
  | 'warn'
  | 'close'
  | 'dash'

interface IconProps {
  name: IconName
  /** 16px（文の横に並べる小さい印）。既定は 24px */
  small?: boolean
}

function Paths({ name }: { name: IconName }) {
  switch (name) {
    case 'menu':
      return <path d="M4 7h16M4 12h16M4 17h16" />
    case 'search':
      return (
        <>
          <circle cx="10.5" cy="10.5" r="6" />
          <path d="M15 15l5 5" />
        </>
      )
    case 'plus':
      return <path d="M12 5v14M5 12h14" />
    case 'check':
      return <path d="M5 12.5l4.5 4.5L19 7.5" />
    case 'why':
      return (
        <>
          <path d="M7 4v8h11" />
          <path d="M15 9l3 3-3 3" />
        </>
      )
    case 'back':
      return <path d="M15 5l-7 7 7 7" />
    case 'next':
      return <path d="M9 5l7 7-7 7" />
    case 'down':
      return <path d="M5 9l7 7 7-7" />
    case 'ext':
      return <path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6" />
    case 'list':
      return (
        <>
          <path d="M10 6h10M10 12h10M10 18h10" />
          <path d="M4 5h2v2H4zM4 11h2v2H4zM4 17h2v2H4z" />
        </>
      )
    case 'grid':
      return <path d="M4 4h16v16H4zM9.5 4v16M14.5 4v16M4 9.5h16M4 14.5h16" />
    case 'warn':
      return (
        <>
          <path d="M12 4l9 16H3z" />
          <path d="M12 10v5M12 17v1.5" />
        </>
      )
    case 'close':
      return <path d="M6 6l12 12M18 6L6 18" />
    case 'dash':
      return <path d="M6 12h12" />
  }
}

export default function Icon({ name, small = false }: IconProps) {
  return (
    <svg
      className={small ? 'ic-s' : 'ic'}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden="true"
      focusable="false"
    >
      <Paths name={name} />
    </svg>
  )
}
