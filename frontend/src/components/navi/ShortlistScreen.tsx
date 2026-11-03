import { findCourse, findFrame, frameLabel, hasEdge, sortCourses, termLabel } from '../../navi/graph'
import { useNavi } from '../../navi/state'
import type { Course } from '../../navi/types'
import EvidenceLabel from './EvidenceLabel'
import Panes from './Panes'
import ShortlistContent from './ShortlistContent'

/** 候補の画面（/navi/shortlist。スマホは W4、PC は W12） */
export default function ShortlistScreen() {
  const { isPc } = useNavi()
  if (!isPc) {
    return (
      <main className="m-main">
        <ShortlistContent variant="mobile" />
      </main>
    )
  }
  return (
    <Panes tab="shortlist">
      <ShortlistMap />
    </Panes>
  )
}

/** PC で候補を選んでいないとき、候補どうしの系統図の線を大きく出す（UX 仕様 W12） */
function ShortlistMap() {
  const { dept, shortlist } = useNavi()
  const courses = sortCourses(
    dept,
    shortlist.map((code) => findCourse(dept, code)).filter((c): c is Course => c !== undefined),
  )
  if (courses.length === 0) {
    return <p className="body-s">候補に入れた科目が、ここに系統図の線つきで並びます。</p>
  }
  return (
    <section className="sl-map" aria-labelledby="sl-map-h">
      <h1 className="h-sec" id="sl-map-h">
        候補どうしの系統図の線
        <EvidenceLabel kind="route" />
      </h1>
      <p className="note">左の候補を選ぶと、ここに詳細が出ます。</p>
      <ol className="route">
        {courses.map((c, i) => {
          const frame = findFrame(dept, c.frameId)
          const prev = i > 0 ? courses[i - 1] : undefined
          const linked = prev !== undefined && hasEdge(dept, prev.frameId, c.frameId)
          return (
            <li key={c.code} className="route__stop">
              <p className="route__kind">
                {linked ? '前の候補の枠から線あり' : i === 0 ? 'はじめの候補' : '前の候補の枠とは線なし'}
              </p>
              <p className="frame__name">
                {termLabel(c)} {c.name}
              </p>
              {frame !== undefined && <p className="note">枠: {frameLabel(frame)}</p>}
            </li>
          )
        })}
      </ol>
      <p className="note route-note">線は枠どうしを結んでいます。枠の中のどの科目が直接の前提かまでは、系統図に書かれていません。</p>
    </section>
  )
}
