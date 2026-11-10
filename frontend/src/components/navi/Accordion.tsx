import { useState } from 'react'
import type { ReactNode } from 'react'
import Icon from './Icon'

interface AccordionProps {
  label: string
  /** 行の右の灰の文字（例 15回、記載なし）。開けなくても中身の有無が分かるようにする（E1 8章） */
  hint: string
  children: ReactNode
}

/** 開け閉めする補足（E1 3章: 最初は畳む）。開閉の印の回転と中身のフェードは、動きを減らす設定では止める */
export default function Accordion({ label, hint, children }: AccordionProps) {
  const [open, setOpen] = useState(false)
  return (
    <details className="acc" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        <span>{label}</span>
        <span className="acc-hint">{hint}</span>
        <Icon name="down" />
      </summary>
      <div className="acc-body">{children}</div>
    </details>
  )
}
