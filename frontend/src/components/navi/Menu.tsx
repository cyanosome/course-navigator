import { useEffect, useRef, useState } from 'react'
import type { Ref } from 'react'
import { Link } from 'react-router-dom'
import { useNavi } from '../../navi/state'
import { timetableText } from '../../navi/timetable'

interface MenuProps {
  id: string
  /** 外を押したら閉じる判定に使う（NaviShell） */
  ref: Ref<HTMLDivElement>
}

/**
 * メニュー（二次的な行き先だけ。E1 6章）。このAIについて、学科を変える、想定の時点、時間割を文字でコピー。
 * 主な行き先（さがす・時間割）はスマホは下のタブ、PC は上のタブに常に見えている。
 * 調査モードの［使い終わった］はメニューに入れず、帯で出す。
 */
export default function Menu({ id, ref }: MenuProps) {
  const { dept, shortlist, placement, study, assumedYear } = useNavi()
  const [copyState, setCopyState] = useState<'idle' | 'done' | 'failed'>('idle')
  const firstRef = useRef<HTMLAnchorElement>(null)

  // 開いたら最初の項目へ移る（閉じたときに押したボタンへ戻すのは NaviShell）
  useEffect(() => {
    firstRef.current?.focus()
  }, [])

  const copy = () => {
    navigator.clipboard
      .writeText(timetableText(dept, shortlist, placement))
      .then(() => setCopyState('done'))
      .catch((err: unknown) => {
        console.error('時間割をコピーできませんでした', err)
        setCopyState('failed')
      })
  }

  return (
    <div ref={ref} className="menu" id={id}>
      <Link ref={firstRef} className="menu-item" to="/navi/about">
        このAIについて
      </Link>
      {study === null ? (
        <Link className="menu-item" to="/navi/departments">
          学科を変える<span className="sub">{dept.name}</span>
        </Link>
      ) : (
        <p className="menu-item">
          学科<span className="sub">{dept.name}</span>
        </p>
      )}
      <p className="menu-item">
        想定の時点<span className="sub">{assumedYear === 1 ? '1年の入学直後' : `${assumedYear}年の春`}</span>
      </p>
      <button className="menu-item" type="button" onClick={copy}>
        時間割を文字でコピー
        <span className="sub" role="status">
          {copyState === 'done' && 'コピーしました'}
          {copyState === 'failed' && 'コピーできませんでした。時間割の画面を書き写してください'}
        </span>
      </button>
    </div>
  )
}
