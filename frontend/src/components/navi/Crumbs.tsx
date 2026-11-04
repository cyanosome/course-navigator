import { Fragment } from 'react'
import { Link } from 'react-router-dom'
import type { PcTab, TrailEntry } from '../../navi/state'
import Icon from './Icon'

interface CrumbsProps {
  /** 今の画面より前にたどった道筋（trail[0] は来た一覧） */
  trail: TrailEntry[]
  /** 今の画面の名前 */
  current: string
  tab: PcTab
}

/**
 * PC の中央の段の上のパンくず（E1 6章。例 おすすめ ＞ 無機化学）。前後の科目をたどると段が増え、
 * どの段にも1クリックで戻れる（UX 仕様 C03）。スマホでは使わない（戻るの文字を来た場所の名前にする）。
 */
export default function Crumbs({ trail, current, tab }: CrumbsProps) {
  return (
    <nav className="crumbs" aria-label="現在地">
      {trail.map((entry, i) => (
        <Fragment key={`${entry.href}-${i}`}>
          <Link to={entry.href} state={i === 0 ? undefined : { trail: trail.slice(0, i + 1), tab }}>
            {entry.label}
          </Link>
          <Icon name="next" small />
        </Fragment>
      ))}
      <span aria-current="page">{current}</span>
    </nav>
  )
}
