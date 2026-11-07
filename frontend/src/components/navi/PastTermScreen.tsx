import { Link } from 'react-router-dom'
import '../../navi/plan.css'
import '../../navi/term.css'
import type { WorkingPlan } from '../../navi/diagnose'
import { creditsOf, historyHref, recordOf, takenFromPlan } from '../../navi/history'
import { useNavi } from '../../navi/state'
import { termLabel } from '../../navi/timetable'
import { useHistory } from '../../navi/useHistory'

/**
 * 今の学期より前の学期を見ているときの左（学期のコンペの T-a）。取った科目の一覧（曜限が分かる科目は曜限・科目名・単位）と
 * ［直す］。未記入なら、その学期のプランがあれば［プランのとおり記録する］（1回）、無ければ［取った科目を入れる］。
 * 時間割は出さない（クラスの分からない科目がある）。上に学期の名前を出す（審査の J1 M-5）
 */
export default function PastTermScreen({ plan }: { plan: WorkingPlan }) {
  const { focusTerm: term } = useNavi()
  const history = useHistory()
  const rec = recordOf(history.stored, term)
  const planned = (plan.terms.find((t) => t.year === term.year && t.term === term.half)?.courses ?? []).map(takenFromPlan)
  const state =
    rec === undefined ? '未記入' : rec.courses.length === 0 ? '取っていない' : `取った科目 ${rec.courses.length}科目 ${creditsOf(rec.courses)}単位`
  const href = historyHref(term)
  return (
    <div className="pl-plan">
      <div className="pt-head">
        <h1>
          <span className="pt-title">{termLabel(term)}</span>
          <span className="lg-word">{state}</span>
        </h1>
        {rec !== undefined && (
          <Link className="pl-tbtn" to={href}>
            直す
          </Link>
        )}
      </div>
      {rec === undefined ? (
        <div className="pt-acts">
          {planned.length > 0 && (
            <button className="pl-line" type="button" onClick={() => history.record(term, planned)}>
              プランのとおり記録する
            </button>
          )}
          <Link className="pl-tbtn" to={href}>
            取った科目を入れる
          </Link>
        </div>
      ) : rec.courses.length === 0 ? (
        <p className="pl-empty">この学期は取っていません。</p>
      ) : (
        <ul className="hc-list" data-role="history">
          {rec.courses.map((c) => (
            <li key={c.name} className="hc is-plain">
              <span className="hc-slot">{c.slots?.join('・') ?? ''}</span>
              <span>{c.name}</span>
              <span className="hc-cr">{c.credits === null ? '' : `${c.credits}単位`}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
