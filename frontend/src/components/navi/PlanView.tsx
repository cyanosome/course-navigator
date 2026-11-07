import '../../navi/diagnose.css'
import { planCodes, planTermLabel, workingTermCredits } from '../../navi/diagnose'
import type { WorkingCourse, WorkingPlan } from '../../navi/diagnose'
import { findCourse } from '../../navi/graph'
import { useResearchLog } from '../../navi/research'
import { DIAGNOSE_HREF, useNavi } from '../../navi/state'
import type { Origin } from '../../navi/state'
import { useDiagnose } from '../../navi/useDiagnose'
import { useFlags } from '../../navi/variant'
import { planRowView, rowView, WIDE_SPACE } from '../../navi/views'
import type { ListContext, RowView } from '../../navi/views'
import Accordion from './Accordion'
import CourseRow from './CourseRow'
import PlanRefine from './PlanRefine'
import StatusPanel from './StatusPanel'

const ORIGIN: Origin = { kind: 'plan' }
const ROOT = { label: 'プラン', href: DIAGNOSE_HREF }

/**
 * 診断のプラン（仮の置き方。見た目はデザインのコンペで差し替える）。学期ごとに科目・単位・曜限・理由を出し、
 * 行から詳細を開く・＋で候補に入れる（既存の CourseRow）。プランのチェック（StatusPanel）は両方の条件で同じ。
 * 旗 assistant=on のときだけ、AI に頼んで直す欄（PlanRefine）を足す。状態は navi/useDiagnose.ts。
 */
export default function PlanView({ plan }: { plan: WorkingPlan }) {
  const { dept, shortlist, focusTerm, assumedTerm, keepAll } = useNavi()
  const { config, summary, retake } = useDiagnose()
  const flags = useFlags()
  const { log } = useResearchLog()
  const ctx: ListContext = { dept, shortlist, focusTerm, assumedTerm, flags }
  const cap = config?.status === 'ready' ? config.value.scope.credit_cap_per_term : null
  const codes = planCodes(plan)
  const notKept = codes.filter((c) => !shortlist.includes(c))

  const rowFor = (c: WorkingCourse): RowView => {
    const why = c.reasons.map((r) => r.text).join('・') || (c.origin === 'refine' ? 'AIに頼んで足した' : null)
    const source = c.origin === 'refine' ? 'AIの判断' : '診断'
    const course = findCourse(dept, c.syllabus_id)
    // 学期は見出しに出すので、行には書かない
    return course === undefined ? planRowView(c, ORIGIN, why, source) : { ...rowView(ctx, course, ORIGIN, why, source), termNote: null }
  }

  /** 一覧の中の順位（result_click の rank。学期をまたいで通しで数える） */
  const rankOf = new Map(codes.map((code, i) => [code, i + 1]))
  return (
    <div className="diag-plan">
      <h1 className="title">プラン</h1>
      {plan.terms.map((t) => {
        const { credits, unknown } = workingTermCredits(t)
        return (
          <section key={`${t.year}${t.term}`} aria-label={planTermLabel(t)}>
            <h2 className="group-label">
              {planTermLabel(t)}
              {WIDE_SPACE}
              {credits}単位{cap !== null && `（上限 ${cap}）`}
              {unknown > 0 && `${WIDE_SPACE}単位の分からない科目 ${unknown}`}
            </h2>
            {t.courses.length === 0 ? (
              <p className="text">この学期は空いています。</p>
            ) : (
              <ul className="list">
                {t.courses.map((c) => {
                  const r = rowFor(c)
                  return (
                    <CourseRow
                      key={c.syllabus_id}
                      row={r}
                      keepFrom="plan"
                      linkState={{ trail: [ROOT, { label: r.name, href: r.href }], tab: 'search' }}
                      onOpen={() => log('result_click', { syllabus_id: c.syllabus_id, rank: rankOf.get(c.syllabus_id) ?? null, list: 'plan' })}
                    />
                  )
                })}
              </ul>
            )}
          </section>
        )
      })}
      <div className="page-acts">
        <button className="primary" type="button" disabled={notKept.length === 0} onClick={() => keepAll(notKept, 'plan')}>
          {notKept.length === 0 ? '全部候補に入っています' : 'まとめて候補に入れる'}
        </button>
        <button className="text-btn" type="button" onClick={retake}>
          答え直す
        </button>
      </div>
      <div className="accs plan-answers">
        <Accordion label="あなたの答え" hint={`${summary.length}問`}>
          <dl className="kv">
            {summary.map((s) => (
              <div key={s.question_id} className="kv-row">
                <dt>{s.question}</dt>
                <dd>{s.answer}</dd>
              </div>
            ))}
          </dl>
        </Accordion>
      </div>
      <StatusPanel target={{ kind: 'plan', plan }} heading="このプランのチェック" frame="sec" />
      {flags.assistant === 'on' && <PlanRefine plan={plan} />}
      <p className="foot">プランは答えから決まった規則で選んでいます。候補は履修登録ではありません。</p>
    </div>
  )
}
