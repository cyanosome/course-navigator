import type { MouseEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import type { TrailEntry } from '../../navi/state'
import Icon from './Icon'

/**
 * 診断の変種の作る場所の上の「＜ 来た場所」（デザインのコンペの U-a）。このアプリの中で来たなら1つ前へ戻り、
 * リンクから直接開いたときは来た場所の画面へ進む（スマホの上の帯の戻ると同じ決まり）。
 */
export default function BackLink({ entry }: { entry: TrailEntry }) {
  const location = useLocation()
  const navigate = useNavigate()
  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (location.key === 'default') return
    e.preventDefault()
    navigate(-1)
  }
  return (
    <Link className="pl-back" to={entry.href} onClick={onClick}>
      <Icon name="back" small />
      <span>{entry.label}</span>
    </Link>
  )
}
