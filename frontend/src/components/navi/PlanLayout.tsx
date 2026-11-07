import { useEffect, useId, useRef, useState } from 'react'
import { Outlet, useLocation, useMatch } from 'react-router-dom'
import '../../navi/plan.css'
import type { WorkingPlan } from '../../navi/diagnose'
import { LEDGER_QUERY, useMediaQuery } from '../../navi/hooks'
import { useResearchLog } from '../../navi/research'
import { DIAGNOSE_HREF, useNavi } from '../../navi/state'
import { checkpointPayload, resultsPayload } from '../../navi/status'
import { inTerm, resolveCourse, sameTerm, termsOf } from '../../navi/timetable'
import { useDiagnose } from '../../navi/useDiagnose'
import { useLedger } from '../../navi/useLedger'
import { Checklist, LedgerStatus, StatusBand } from './Ledger'

/**
 * 診断の変種（diagnose=quiz）の外枠（デザインのコンペの U-a「左で作り、右で確かめる」）。
 * - 作る場所（左）: プラン・科目の詳細・AI の欄・さがす のどれか1つ（Outlet）
 * - 確かめる場所: 履修状況とチェック。640px 以上は右の列に常に出し（上に貼りつき、長ければ右だけ流れる）、
 *   それより狭いと上に貼りつく帯にする。チェックの一覧はプランの下に置き、ほかの画面では帯の［要確認］から開く
 * プランがまだ無いあいだ（診断に答える前）は、確かめるものが無いので作る場所だけを出す。
 */
export default function PlanLayout() {
  const { working } = useDiagnose()
  if (working === null) {
    return (
      <div className="pl is-solo">
        <main className="pl-work">
          <Outlet />
        </main>
      </div>
    )
  }
  return <PlanFrame plan={working} />
}

function PlanFrame({ plan }: { plan: WorkingPlan }) {
  const wide = useMediaQuery(LEDGER_QUERY)
  const { dept, placement, focusTerm, setFocusTerm } = useNavi()
  const { phase } = useDiagnose()
  const { log } = useResearchLog()
  const location = useLocation()
  const view = useLedger(plan)
  const courseMatch = useMatch('/navi/course/:code')
  const focusCode = courseMatch?.params.code === undefined ? null : decodeURIComponent(courseMatch.params.code)
  const onPlan = useMatch(DIAGNOSE_HREF) !== null && phase === 'plan'
  const checksId = useId()
  const checksRef = useRef<HTMLDivElement>(null)
  /** スマホで、プラン以外の画面でチェックの一覧を開いた画面（移ったら閉じる） */
  const [openAt, setOpenAt] = useState<string | null>(null)
  const checksOpen = onPlan || openAt === location.key

  // 共有の学期がプランの学期に無いときは、見ている学期（プランの最初の学期）に合わせる
  const viewTerm = view.term
  useEffect(() => {
    if (!sameTerm(viewTerm, focusTerm)) setFocusTerm(viewTerm)
  }, [viewTerm, focusTerm, setFocusTerm])

  // 詳細で見ている科目がほかの学期（プランの学期）の科目なら、その学期の時間割を出す。
  // 詳細を開いたときに1回だけ合わせる（そのあと利用者が学期を変えたら、それに従う）
  const terms = view.terms
  const followed = useRef<string | null>(null)
  useEffect(() => {
    if (focusCode === null) {
      followed.current = null
      return
    }
    if (followed.current === focusCode) return
    const course = resolveCourse(dept, focusCode, placement)
    if (course === undefined) return
    followed.current = focusCode
    if (inTerm(course, focusTerm)) return
    const target = termsOf(course).find((t) => terms.some((x) => sameTerm(x, t)))
    if (target !== undefined) setFocusTerm(target)
  }, [dept, focusCode, focusTerm, placement, setFocusTerm, terms])

  // スマホで一覧を開いたら、一覧まで送る
  useEffect(() => {
    if (openAt !== null && openAt === location.key) checksRef.current?.scrollIntoView({ block: 'start' })
  }, [openAt, location.key])

  if (wide) {
    return (
      <div className="pl">
        <main className="pl-work">
          <Outlet />
        </main>
        <aside className="pl-ledger" aria-label="履修状況とチェック">
          <LedgerStatus view={view} focusCode={focusCode} />
          <Checklist view={view} id={checksId} />
        </aside>
      </div>
    )
  }

  // 帯の［要確認］で一覧を開いた（status_open は利用者が開いたときだけ。PC で常に見えている一覧では出さない）
  const onChecks = () => {
    if (onPlan || openAt !== location.key) {
      log('status_open', {
        how: 'band',
        target: 'plan',
        checkpoint_ids: view.checkpoints.map((c) => c.id),
        checkpoints: view.checkpoints.map(checkpointPayload),
        results: resultsPayload([...view.here.results, ...view.planResults]),
        total_credits: view.status.totalCredits,
      })
    }
    if (onPlan) {
      checksRef.current?.scrollIntoView({ block: 'start' })
      return
    }
    setOpenAt(openAt === location.key ? null : location.key)
  }
  return (
    <div className="pl is-narrow">
      <StatusBand view={view} focusCode={focusCode} onChecks={onChecks} checksId={checksId} checksOpen={checksOpen} />
      <main className="pl-work">
        <Outlet />
      </main>
      {checksOpen && (
        <div className="pl-checks" ref={checksRef}>
          <Checklist view={view} id={checksId} />
        </div>
      )}
    </div>
  )
}
