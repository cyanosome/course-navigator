/**
 * 意味を持つ線の印（DESIGN.md 5章）。既成のアイコン集は使わず、見本と同じ形を手で描いた。
 * どの印も文字のラベルと並べて使い、読み上げは文字で行う（aria-hidden）。
 */
export type GlyphName =
  | 'route'
  | 'syllabus'
  | 'ai'
  | 'plus'
  | 'check'
  | 'next'
  | 'down'
  | 'external'
  | 'warn'
  | 'back'

interface GlyphProps {
  name: GlyphName
}

export default function Glyph({ name }: GlyphProps) {
  switch (name) {
    case 'route':
      return (
        <svg className="glyph" viewBox="0 0 16 14" aria-hidden="true">
          <rect x="1" y="4" width="5" height="6" fill="currentColor" />
          <rect x="10" y="4" width="5" height="6" fill="currentColor" />
          <path d="M6 7h4" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      )
    case 'syllabus':
      return (
        <svg className="glyph" viewBox="0 0 16 14" aria-hidden="true">
          <path d="M3.5 1.5h6l3 3v8h-9z" fill="none" stroke="currentColor" strokeWidth="1.4" />
          <path d="M5.5 7h5M5.5 9.75h5" stroke="currentColor" strokeWidth="1.2" />
        </svg>
      )
    case 'ai':
      return (
        <svg className="glyph" viewBox="0 0 16 14" aria-hidden="true">
          <circle cx="8" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2.2 1.8" />
        </svg>
      )
    case 'plus':
      return (
        <svg className="glyph" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.75" />
        </svg>
      )
    case 'check':
      return (
        <svg className="glyph" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M3 8.5 6.5 12 13 4.5" fill="none" stroke="currentColor" strokeWidth="2" />
        </svg>
      )
    case 'next':
      return (
        <svg className="glyph" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" strokeWidth="1.75" />
        </svg>
      )
    case 'back':
      return (
        <svg className="glyph" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M10 3.5 5.5 8 10 12.5" fill="none" stroke="currentColor" strokeWidth="1.75" />
        </svg>
      )
    case 'down':
      return (
        <svg className="glyph" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      )
    case 'external':
      return (
        <svg className="glyph" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M9 2.5h4.5V7M13.5 2.5 7.5 8.5M11.5 9.5v4h-9v-9h4" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      )
    case 'warn':
      return (
        <svg className="glyph err-mark" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M8 1.5 15 14H1z" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <path d="M8 6v4M8 11.5v1.5" stroke="currentColor" strokeWidth="1.6" />
        </svg>
      )
  }
}
