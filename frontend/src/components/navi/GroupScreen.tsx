import { useEffect, useId, useRef } from 'react'
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { coursesInFrame, findFrame, nextFrames, prevFrames } from '../../navi/graph'
import { useResearchLog } from '../../navi/research'
import { groupHref, parseOrigin, readPaneState, useNavi } from '../../navi/state'
import type { Origin } from '../../navi/state'
import type { Frame } from '../../navi/types'
import { useFlags } from '../../navi/variant'
import { rootEntry, rowView } from '../../navi/views'
import CourseRow from './CourseRow'
import Crumbs from './Crumbs'

/** まとまりを学年ごとにまとめて書く（例 2年の「物理化学系」「分析・有機化学系」） */
function framesText(frames: Frame[]): string {
  const years = [...new Set(frames.map((f) => f.year))].sort((a, b) => a - b)
  return years.map((y) => `${y}年の${frames.filter((f) => f.year === y).map((f) => `「${f.name}」`).join('')}`).join('、')
}

/**
 * まとまりの科目（W13。/navi/group/<まとまりID>?from=…）。スマホは別の画面、PC は中央の段。
 * 見出しはまとまりの名前だけ。行は一覧と同じ形。線のつながりと並びの決め方は灰の文で添える（UX 仕様 C24）。
 * 系統図を出さない変種（graph=off）では、まとまりは無いものとして扱う（URL を直に開いても出さない）。
 */
export default function GroupScreen() {
  const { dept, isPc, shortlist, placement, focusTerm, assumedTerm } = useNavi()
  const flags = useFlags()
  const { log } = useResearchLog()
  const { frameId = '' } = useParams()
  const [params] = useSearchParams()
  const location = useLocation()
  const titleId = useId()
  const origin = parseOrigin(params.get('from'))
  const pane = readPaneState(location.state)
  const tab = pane?.tab ?? (origin.kind === 'tt' ? 'tt' : 'search')
  const ancestors = pane !== null && pane.trail.length >= 2 ? pane.trail.slice(0, -1) : [rootEntry(dept, origin)]
  const frame = flags.graph === 'on' ? findFrame(dept, frameId) : undefined
  const foundId = frame?.id ?? null

  // 開いたまとまりを1回だけ記録する（開発の StrictMode で効果が2回走っても重ねない）
  const loggedRef = useRef<string | null>(null)
  useEffect(() => {
    if (foundId === null || loggedRef.current === foundId) return
    loggedRef.current = foundId
    log('group_open', { group_id: foundId, from: origin.kind })
  }, [foundId, origin.kind, log])

  if (frame === undefined) {
    const missing = (
      <section className="detail" aria-labelledby={titleId}>
        <h1 className="title" id={titleId}>
          このまとまりは見つかりませんでした
        </h1>
        <p className="text">
          <Link to="/navi">さがすに戻る</Link>
        </p>
      </section>
    )
    return isPc ? missing : <main>{missing}</main>
  }

  const ctx = { dept, shortlist, focusTerm, assumedTerm, placement }
  const here = groupHref(frame.id, origin)
  const rowOrigin: Origin = { kind: 'group', frameId: frame.id }
  const courses = coursesInFrame(dept, frame.id)
  const prev = prevFrames(dept, frame.id)
  const next = nextFrames(dept, frame.id)

  const body = (
    <article className="detail" aria-labelledby={titleId}>
      {isPc && <Crumbs trail={ancestors} current={frame.name} tab={tab} />}
      <h1 className="title" id={titleId}>
        {frame.name}
      </h1>
      <p className="group-sub">
        {frame.year}年のまとまり、{courses.length}科目
      </p>
      <div className="group-list">
        <ul className="list">
          {courses.map((c, i) => {
            const r = rowView(ctx, c, rowOrigin, null, null)
            return (
              <CourseRow
                key={c.code}
                row={r}
                linkState={{ trail: [...ancestors, { label: frame.name, href: here }, { label: c.name, href: r.href }], tab }}
                onOpen={() => log('result_click', { syllabus_id: c.code, rank: i + 1, list: 'group', group_id: frame.id })}
              />
            )
          })}
        </ul>
      </div>
      {prev.length > 0 && <p className="detail-foot">{framesText(prev)}から、線が入っています。</p>}
      {next.length > 0 && <p className="detail-foot">{framesText(next)}へ、線が出ています。</p>}
      <p className="detail-foot">
        並びは学期と系統図の記載順で、関係の強さの順ではありません。同じまとまりの科目は、系統図の上では同じ関係です。
      </p>
    </article>
  )
  return isPc ? body : <main>{body}</main>
}
