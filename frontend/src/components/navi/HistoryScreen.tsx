import { useEffect, useId, useRef, useState } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import '../../navi/plan.css'
import '../../navi/term.css'
import type { WorkingPlan } from '../../navi/diagnose'
import { creditsOf, graphCoursesIn, recordOf, takenFromGraph, takenFromPlan, termParam } from '../../navi/history'
import type { TakenCourse } from '../../navi/history'
import { DIAGNOSE_HREF, useNavi } from '../../navi/state'
import type { TermKey } from '../../navi/timetable'
import { ALL_TERMS, termLabel } from '../../navi/timetable'
import { useDiagnose } from '../../navi/useDiagnose'
import { useHistory } from '../../navi/useHistory'
import AddOthers from './AddOthers'
import BackLink from './BackLink'
import TakenRow from './TakenRow'

const ROOT = { label: 'プラン', href: DIAGNOSE_HREF }

/** 名前の重ならない並び（先に来たものを残す） */
function uniqueByName(list: TakenCourse[]): TakenCourse[] {
  const seen = new Set<string>()
  return list.filter((c) => {
    if (seen.has(c.name)) return false
    seen.add(c.name)
    return true
  })
}

/**
 * 取った科目（/navi/history。学期のコンペの T-a の (b)）。今の学期より前の学期ごとの節を並べる。
 * 未記入の節は開き、［プランのとおり入れる］［系統図のN科目を入れる］［この学期は取っていない］と［ほかの科目を足す］。
 * 記入済みの節は1行に畳み、開くとチェックの行（外すと記録から外れる）と［未記入に戻す］。押すたびに端末に保存する。
 * ?from=pick（初めに今の学期を選んだ直後）は［あとで］と［プランを作る］を出す。?term=1-秋 はその節を開いて送る
 */
export default function HistoryScreen() {
  const history = useHistory()
  const { working } = useDiagnose()
  const [params] = useSearchParams()
  const titleId = useId()
  if (!history.enabled || history.currentIdx === null) return <Navigate to={DIAGNOSE_HREF} replace />
  const fromPick = params.get('from') === 'pick'
  const target = params.get('term')
  const past = ALL_TERMS.slice(0, history.currentIdx)
  return (
    <div className="page pl-page">
      <section aria-labelledby={titleId}>
        {!fromPick && <BackLink entry={ROOT} />}
        <div className="hs-head">
          <h1 className="pl-title" id={titleId}>
            取った科目
          </h1>
          {fromPick && (
            <Link className="pl-tbtn" to={DIAGNOSE_HREF}>
              あとで
            </Link>
          )}
        </div>
        <p className="hs-note">履歴はこの端末にだけ保存します。プランを作るときに送りますが、サーバーには残りません。</p>
        {past.length === 0 ? (
          <p className="pl-empty">今の学期より前の学期はありません。</p>
        ) : (
          <div data-role="history">
            {past.map((t) => (
              <TermSection key={termParam(t)} term={t} plan={working} focus={target === termParam(t)} />
            ))}
          </div>
        )}
        {fromPick ? (
          <div className="hs-next">
            <Link className="pl-primary" to={DIAGNOSE_HREF}>
              プランを作る
            </Link>
          </div>
        ) : (
          <ClearAll />
        )}
      </section>
    </div>
  )
}

interface TermSectionProps {
  term: TermKey
  plan: WorkingPlan | null
  /** ?term= で来た節（開いて送る） */
  focus: boolean
}

function TermSection({ term, plan, focus }: TermSectionProps) {
  const { dept } = useNavi()
  const history = useHistory()
  const rec = recordOf(history.stored, term)
  const [open, setOpen] = useState(() => focus || rec === undefined)
  /** この画面で外した科目（チェックを外しても行を消さず、また入れられるようにする） */
  const [removed, setRemoved] = useState<TakenCourse[]>([])
  const ref = useRef<HTMLElement>(null)
  const headId = useId()
  const bodyId = useId()
  useEffect(() => {
    if (focus) ref.current?.scrollIntoView({ block: 'start' })
  }, [focus])

  const graph = graphCoursesIn(dept, term).map(takenFromGraph)
  const planned = (plan?.terms.find((t) => t.year === term.year && t.term === term.half)?.courses ?? []).map(takenFromPlan)
  const state =
    rec === undefined ? '未記入' : rec.courses.length === 0 ? '取っていない' : `${rec.courses.length}科目 ${creditsOf(rec.courses)}単位`
  const inRecord = new Set(rec?.courses.map((c) => c.name) ?? [])
  const rows = rec === undefined ? [] : uniqueByName([...rec.courses, ...planned, ...graph, ...removed])
  const toggle = (c: TakenCourse) => {
    if (inRecord.has(c.name)) {
      history.remove(term, c.name)
      setRemoved((prev) => (prev.some((x) => x.name === c.name) ? prev : [...prev, c]))
      return
    }
    history.add(term, [c])
  }

  return (
    <section className="hs-sec" ref={ref} aria-labelledby={headId}>
      <div className="hs-sec-head">
        <h2 className="hs-term" id={headId}>
          {termLabel(term)}
        </h2>
        <span className="hs-state">{state}</span>
        <button className="pl-tbtn" type="button" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen((o) => !o)}>
          {open ? '閉じる' : '開く'}
        </button>
      </div>
      <div id={bodyId} hidden={!open}>
        {open &&
          (rec === undefined ? (
            <>
              <div className="hs-acts">
                {planned.length > 0 && (
                  <button className="pl-line" type="button" onClick={() => history.record(term, planned)}>
                    プランのとおり入れる
                  </button>
                )}
                {graph.length > 0 && (
                  <button className="pl-line" type="button" onClick={() => history.add(term, graph)}>
                    系統図の{graph.length}科目を入れる
                  </button>
                )}
                <button className="pl-tbtn" type="button" onClick={() => history.record(term, [])}>
                  この学期は取っていない
                </button>
              </div>
              <AddOthers term={term} exclude={inRecord} onAdd={(courses) => history.add(term, courses)} />
            </>
          ) : (
            <>
              {rec.courses.length > 0 && <p className="hs-hint">取らなかった科目・落とした科目はチェックを外す</p>}
              <ul className="hc-list">
                {rows.map((c) => (
                  <TakenRow key={c.name} course={c} checked={inRecord.has(c.name)} onToggle={() => toggle(c)} />
                ))}
              </ul>
              <AddOthers term={term} exclude={new Set(rows.map((c) => c.name))} onAdd={(courses) => history.add(term, courses)} />
              <div className="hs-undo">
                <button className="pl-tbtn" type="button" onClick={() => history.clear(term)}>
                  未記入に戻す
                </button>
              </div>
            </>
          ))}
      </div>
    </section>
  )
}

/** この端末の記録を消す（2回押す。今の学期は残す） */
function ClearAll() {
  const history = useHistory()
  const [asking, setAsking] = useState(false)
  if (history.stored.records.length === 0 && history.stored.registered.length === 0) return null
  return (
    <div className="hs-clear">
      {asking ? (
        <>
          <p>取った科目と登録済みの印を、この端末から消します。</p>
          <div className="ai-acts">
            <button
              className="pl-line"
              type="button"
              onClick={() => {
                history.clearAll()
                setAsking(false)
              }}
            >
              消す
            </button>
            <button className="pl-tbtn" type="button" onClick={() => setAsking(false)}>
              やめる
            </button>
          </div>
        </>
      ) : (
        <button className="pl-tbtn" type="button" onClick={() => setAsking(true)}>
          取った科目をこの端末から消す
        </button>
      )}
    </div>
  )
}
