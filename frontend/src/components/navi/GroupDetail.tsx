import { useId } from 'react'
import { Link } from 'react-router-dom'
import { coursesInFrame, findFrame, frameLabel, nextFrames, prevFrames } from '../../navi/graph'
import type { Origin, PcTab, TrailEntry } from '../../navi/state'
import { useNavi } from '../../navi/state'
import type { Frame } from '../../navi/types'
import { groupViews } from '../../navi/views'
import Crumbs from './Crumbs'
import { ProposalCard } from './ProposalCard'

interface GroupDetailProps {
  frameId: string
  origin: Origin
  trail: TrailEntry[]
  tab: PcTab
}

/** 枠を学年ごとにまとめて書く（例 1年「化学工学・エネルギー・基礎数理系」「無機・基礎化学系」） */
function framesText(frames: Frame[]): string {
  if (frames.length === 0) return 'ありません'
  const years = [...new Set(frames.map((f) => f.year))].sort((a, b) => a - b)
  return years
    .map((y) => `${y}年${frames.filter((f) => f.year === y).map((f) => `「${f.name}」`).join('')}`)
    .join('、')
}

/** 枠の科目（W13。PC は右ペイン）。並びの決め方を画面に書く（UX 仕様 C24） */
export default function GroupDetail({ frameId, origin, trail, tab }: GroupDetailProps) {
  const { dept } = useNavi()
  const titleId = useId()
  const frame = findFrame(dept, frameId)
  if (frame === undefined) {
    return (
      <section aria-labelledby={titleId}>
        <h1 className="d-title" id={titleId}>
          この枠は見つかりませんでした
        </h1>
        <p className="body-s">
          <Link to="/navi">さがすに戻る</Link>
        </p>
      </section>
    )
  }
  const courses = coursesInFrame(dept, frame.id)
  // 枠のカードから詳細へ進んだときも道筋を続ける
  const views = groupViews(dept, frame, courses, origin, tab).map((v) => ({
    ...v,
    linkState: { trail: [...trail, { label: v.name, href: v.href }], tab },
  }))

  return (
    <article aria-labelledby={titleId}>
      <Crumbs trail={trail} tab={tab} />
      <h1 className="d-title" id={titleId}>
        {frameLabel(frame)}の枠（{courses.length}科目）
      </h1>
      <dl className="g-rel">
        <div>
          <dt>この枠へ線が入ってくる枠</dt>
          <dd>{framesText(prevFrames(dept, frame.id))}</dd>
        </div>
        <div>
          <dt>この枠から線が出ていく枠</dt>
          <dd>{framesText(nextFrames(dept, frame.id))}</dd>
        </div>
      </dl>
      <p className="note route-note">
        並び: 学期→系統図の記載順（関係の強さの順ではありません。同じ枠の科目は、系統図の上では同じ関係です）
      </p>
      <ol className="cards g-cards">
        {views.map((v) => (
          <li key={v.code}>
            <ProposalCard item={v} />
          </li>
        ))}
      </ol>
      <p className="note route-note">必修・選択の区分はまだ出せません（詳細のシラバス原文で確かめてください）</p>
    </article>
  )
}
