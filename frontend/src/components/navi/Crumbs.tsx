import { Fragment } from 'react'
import { Link } from 'react-router-dom'
import type { PcTab, TrailEntry } from '../../navi/state'
import Glyph from './Glyph'

interface CrumbsProps {
  trail: TrailEntry[]
  tab: PcTab
}

/**
 * PC の右ペインでたどった道筋（UX 仕様 C03。例: 無機化学 > 2年 物理化学系の枠 > 物理化学I）。
 * どの段も1クリックで戻れる。前後の枠や別の科目へ移ったときだけ出す。
 */
export default function Crumbs({ trail, tab }: CrumbsProps) {
  if (trail.length < 2) return null
  return (
    <nav className="crumbs" aria-label="たどった道筋">
      {trail.map((entry, i) => {
        const last = i === trail.length - 1
        return (
          <Fragment key={`${entry.href}-${i}`}>
            {i > 0 && <Glyph name="next" />}
            {last ? (
              <span aria-current="page">{entry.label}</span>
            ) : (
              <Link to={entry.href} state={{ trail: trail.slice(0, i + 1), tab }}>
                {entry.label}
              </Link>
            )}
          </Fragment>
        )
      })}
    </nav>
  )
}
