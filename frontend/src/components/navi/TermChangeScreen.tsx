import { useId, useState } from 'react'
import '../../navi/plan.css'
import '../../navi/term.css'
import { creditsOf, graphCoursesIn, takenFromGraph, takenFromPlan } from '../../navi/history'
import type { TakenCourse } from '../../navi/history'
import { slotOrder } from '../../navi/ledger'
import { useNavi } from '../../navi/state'
import type { TermKey } from '../../navi/timetable'
import { resolveCourse, termLabel } from '../../navi/timetable'
import { useDiagnose } from '../../navi/useDiagnose'
import { useHistory } from '../../navi/useHistory'
import AddOthers from './AddOthers'
import TakenRow from './TakenRow'

/** 答え直しを勧める学年（3年はまとまりが分かれ、答えでプランが大きく変わる。T-a） */
const RETAKE_YEAR = 3

interface TermChangeScreenProps {
  from: TermKey
  to: TermKey
}

/**
 * 学期の切り替わり（学期のコンペの T-a の (c)）。今の学期が日付で進んだあと、最初に開いたときに1回出す。
 * 前の学期のプランの科目をチェックを入れた状態で並べ、その下に系統図のほかの科目（チェックなし）と［ほかの科目を足す］。
 * ［記録して2年秋へ］の1回で、チェックした科目を前の学期の記録にする。［あとで］は今の学期を進め、前の学期は未記入のまま
 * （プランは消さない）。「2年春のままにする（休学など）」は今の学期を戻す。3年春へ進むときは［記録して答え直す］も出す。
 * 春のプランの通年の科目を同じ年の秋へ進むときは、記録にせず秋の登録済みにする（backend の決まり）
 */
export default function TermChangeScreen({ from, to }: TermChangeScreenProps) {
  const { dept, placement, setFocusTerm } = useNavi()
  const history = useHistory()
  const { working, retake, moveInPlan } = useDiagnose()
  const titleId = useId()
  // 曜限の順（プランの画面と同じ並び）
  const planned = (working?.terms.find((t) => t.year === from.year && t.term === from.half)?.courses ?? [])
    .map(takenFromPlan)
    .sort((a, b) => slotOrder(a.slots) - slotOrder(b.slots))
  const plannedNames = new Set(planned.map((c) => c.name))
  const graph = graphCoursesIn(dept, from)
    .map(takenFromGraph)
    .filter((c) => !plannedNames.has(c.name))
  const [checked, setChecked] = useState<ReadonlySet<string>>(() => new Set(plannedNames))
  const [extra, setExtra] = useState<TakenCourse[]>([])
  const continues = (c: TakenCourse) =>
    from.half === '春' && to.half === '秋' && to.year === from.year && resolveCourse(dept, c.syllabus_id, placement)?.term === '通年'

  const listed = [...planned, ...graph, ...extra]
  const toggle = (c: TakenCourse) =>
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(c.name)) next.delete(c.name)
      else next.add(c.name)
      return next
    })

  const record = (then: 'retake' | null) => {
    const chosen = listed.filter((c) => checked.has(c.name))
    const carry = chosen.filter(continues)
    for (const c of carry) moveInPlan(c.syllabus_id, { year: to.year, term: to.half })
    history.finishChange(
      chosen.filter((c) => !continues(c)),
      carry.map((c) => c.syllabus_id),
    )
    setFocusTerm(to)
    if (then === 'retake') retake()
  }
  const later = () => {
    history.later()
    setFocusTerm(to)
  }
  const stay = () => {
    history.stay()
    setFocusTerm(from)
  }

  const fromLabel = termLabel(from)
  const toLabel = termLabel(to)
  return (
    <section aria-labelledby={titleId}>
      <h1 className="pl-title" id={titleId}>
        {fromLabel}から{toLabel}へ
      </h1>
      <p className="tc-sub">チェックした科目を、取った科目に残します。落とした科目は外してください。</p>
      {planned.length > 0 && (
        <>
          <p className="tc-label">
            <span>{fromLabel}のプラン</span>
            <span>
              {planned.length}科目 {creditsOf(planned)}単位
            </span>
          </p>
          <ul className="hc-list" data-role="history">
            {planned.map((c) => (
              <TakenRow
                key={c.name}
                course={c}
                checked={checked.has(c.name)}
                onToggle={() => toggle(c)}
                note={continues(c) ? '通年。秋も続く' : undefined}
              />
            ))}
          </ul>
        </>
      )}
      {graph.length + extra.length > 0 && (
        <>
          <p className="tc-label">
            <span>{planned.length > 0 ? '系統図のほかの科目・足した科目' : `${fromLabel}の系統図の科目`}</span>
          </p>
          <ul className="hc-list">
            {[...graph, ...extra].map((c) => (
              <TakenRow key={c.name} course={c} checked={checked.has(c.name)} onToggle={() => toggle(c)} />
            ))}
          </ul>
        </>
      )}
      <AddOthers
        term={from}
        exclude={new Set(listed.map((c) => c.name))}
        onAdd={(courses) => {
          setExtra((prev) => [...prev, ...courses.filter((c) => !prev.some((x) => x.name === c.name))])
          setChecked((prev) => new Set([...prev, ...courses.map((c) => c.name)]))
        }}
      />
      <div className="tc-foot">
        <button className="pl-primary" type="button" onClick={() => record(null)}>
          記録して{toLabel}へ
        </button>
        <button className="pl-tbtn" type="button" onClick={later}>
          あとで
        </button>
      </div>
      <div className="tc-more">
        {to.year >= RETAKE_YEAR && to.half === '春' && from.year < to.year && (
          <button className="pl-tbtn" type="button" onClick={() => record('retake')}>
            記録して{to.year}年から答え直す
          </button>
        )}
        <button className="pl-tbtn" type="button" onClick={stay}>
          {fromLabel}のままにする（休学など）
        </button>
      </div>
    </section>
  )
}
