/**
 * 診断の変種の「確かめる場所」（PC は右の列、スマホは上の帯）に出す、プランの履修状況とチェックの結果。
 * 履修状況は useCourseStatus（プラン）、判定は status.ts、学期ごとの分け方は ledger.ts。どの変種でも同じものを出す
 * （AI の案を入れた場合は、ここでは計算しない。AI の欄の中だけで出す）。
 * 取った科目を記録しているとき（navi/useHistory の enabled。調査のモードでは使わない）は、学期は1年春〜4年秋の8つで、
 * 履修状況は「取った科目（今の学期より前）＋プランの今の学期から先」。未記入の学期が関わる前のまとまりの抜けは
 * 「判定できない」、今の学期から先のプランに取った科目と同じ名前があれば「もう取った科目」に出す。
 */
import { useMemo } from 'react'
import type { WorkingPlan } from './diagnose'
import { plansFrom } from './diagnose'
import { creditsOf, recordOf, takenNames, takenStatusCourses, unrecordedTerms } from './history'
import { ledgerTerms, planChecks, termChecks, termStatus, unmetCount } from './ledger'
import type { TermChecks } from './ledger'
import { useNavi } from './state'
import { buildStatus, kindsAvailable, statusCoursesFromPlan } from './status'
import type { Checkpoint, CheckResult, CourseStatus } from './status'
import type { TermKey } from './timetable'
import { ALL_TERMS, sameTerm, termIndex } from './timetable'
import { useHistory } from './useHistory'
import { useCheckpoints, useCourseStatus } from './useStatus'
import { useFlags } from './variant'

/** 学期の表のマスの状態（past: 記入済み、unrecorded: 未記入、current: 今、planned: 予定、none: プランの無い先の学期） */
export type TermCellKind = 'past' | 'unrecorded' | 'current' | 'planned' | 'none'

/** 状態の語（学期の表の読み上げ・右の列の見出し） */
export const TERM_WORD: Record<TermCellKind, string> = {
  past: '取った科目',
  unrecorded: '未記入',
  current: '今の学期',
  planned: '予定',
  none: 'プランなし',
}

export interface TermCell {
  term: TermKey
  kind: TermCellKind
  /** past は取った単位、current はプランの単位。ほかは null */
  credits: number | null
}

/** 今の学期から先のプランにある、取った科目と同じ名前の科目 */
export interface RepeatCourse {
  code: string
  name: string
  /** 取った学期 */
  takenIn: TermKey
}

export interface LedgerHistory {
  current: TermKey
  /** 見ている学期が今の学期より前か（取った科目の一覧を出し、時間割は出さない） */
  past: boolean
  /** 見ている学期の状態 */
  viewKind: TermCellKind
  cells: TermCell[]
  takenCredits: number
  /** 今の学期より前で、記録の無い学期 */
  unrecorded: TermKey[]
  /** 見ている学期（今の学期から先）のプランの、取った科目と同じ名前の科目 */
  repeats: RepeatCourse[]
}

export interface LedgerView {
  /** プラン全体の履修状況（取った科目を記録しているときは、取った科目＋プランの今の学期から先） */
  status: CourseStatus
  /** 切り替えられる学期 */
  terms: TermKey[]
  /** プランを作れる学期（取った科目を記録しているときは今の学期から先。ほかは terms と同じ） */
  planTerms: TermKey[]
  /** いま見ている学期（共有の学期がプランの学期に無ければ、プランの最初の学期） */
  term: TermKey
  /** いま見ている学期の履修状況とチェック（今の学期より前の学期は、チェックなし） */
  here: TermChecks
  /** ほかの学期のうち、満たさないチェックがある学期と、その数 */
  others: { term: TermKey; unmet: number }[]
  /** プラン全体で見るチェックの結果 */
  planResults: CheckResult[]
  /** 出すチェック（区分を出さない変種では必修を除く） */
  checkpoints: Checkpoint[]
  /** いま見ている学期とプラン全体の、満たさないチェックの数（ほかの学期は数えない） */
  unmet: number
  /** 学期ごとのチェックの計算（AI の欄で、案を入れた場合と比べるのに使う） */
  checkTerm: (status: CourseStatus, term: TermKey) => CheckResult[]
  /** プランの履修状況（status と同じ作り方。AI の欄で、案を入れた場合の状況を作るのに使う） */
  statusOf: (plan: WorkingPlan) => CourseStatus
  /** 取った科目を記録しているときだけ（調査のモードでは null） */
  history: LedgerHistory | null
}

export function useLedger(plan: WorkingPlan): LedgerView {
  const { dept, focusTerm, placement } = useNavi()
  const { checkpoints } = useCheckpoints()
  const flags = useFlags()
  const history = useHistory()
  const { status: planStatus } = useCourseStatus({ kind: 'plan', plan })
  const { enabled, stored, current, currentIdx } = history
  return useMemo(() => {
    const shown = flags.requirements === 'shown' ? checkpoints : checkpoints.filter((c) => c.kind !== 'required')
    const base = { dept, kindsAvailable: flags.requirements === 'shown' && kindsAvailable(dept) }
    const checkTerm = (st: CourseStatus, t: TermKey) => termChecks(st, t, shown, base).results

    if (!enabled || current === null || currentIdx === null) {
      const terms = ledgerTerms(
        plan.terms.map((t) => ({ year: t.year, half: t.term })),
        planStatus,
      )
      const term = terms.find((t) => sameTerm(t, focusTerm)) ?? terms[0] ?? focusTerm
      const here = termChecks(planStatus, term, shown, base)
      const others = terms
        .filter((t) => !sameTerm(t, term))
        .map((t) => ({ term: t, unmet: unmetCount(checkTerm(planStatus, t)) }))
        .filter((o) => o.unmet > 0)
      const planResults = planChecks(planStatus, shown, { ...base, terms })
      return {
        status: planStatus,
        terms,
        planTerms: terms,
        term,
        here,
        others,
        planResults,
        checkpoints: shown,
        unmet: unmetCount(here.results) + unmetCount(planResults),
        checkTerm,
        statusOf: (p: WorkingPlan) => buildStatus(statusCoursesFromPlan(dept, p, placement.lookup)),
        history: null,
      }
    }

    const start = { year: current.year, term: current.half }
    const taken = takenStatusCourses(stored, dept)
    const statusOf = (p: WorkingPlan) => buildStatus([...taken, ...statusCoursesFromPlan(dept, plansFrom(p, start), placement.lookup)])
    const status = statusOf(plan)
    const terms = ALL_TERMS
    const planTerms = terms.slice(currentIdx)
    const term = terms.find((t) => sameTerm(t, focusTerm)) ?? current
    const past = termIndex(term) < currentIdx
    const unrecorded = unrecordedTerms(stored, currentIdx)
    const ctx = { ...base, unrecorded }
    const here = past ? { term, status: termStatus(status, term), results: [] } : termChecks(status, term, shown, ctx)
    const others = planTerms
      .filter((t) => !sameTerm(t, term))
      .map((t) => ({ term: t, unmet: unmetCount(checkTerm(status, t)) }))
      .filter((o) => o.unmet > 0)
    // プラン全体のチェック（必修など）で見る学期: 記入済みの学期と、プランにある今の学期から先の学期
    // （未記入の学期と、プランの無い先の学期（診断の範囲の外）は見ない）
    const checkTerms = terms.filter((t, i) =>
      i < currentIdx ? recordOf(stored, t) !== undefined : plan.terms.some((x) => x.year === t.year && x.term === t.half),
    )
    const planResults = planChecks(status, shown, { ...ctx, terms: checkTerms })

    const names = takenNames(stored)
    const viewPlan = plan.terms.find((t) => t.year === term.year && t.term === term.half)
    const repeats: RepeatCourse[] = past
      ? []
      : (viewPlan?.courses ?? []).flatMap((c) => {
          const takenIn = names.get(c.name)
          return takenIn === undefined ? [] : [{ code: c.syllabus_id, name: c.name, takenIn }]
        })
    const cells = terms.map((t, i): TermCell => {
      if (i < currentIdx) {
        const rec = recordOf(stored, t)
        return rec === undefined ? { term: t, kind: 'unrecorded', credits: null } : { term: t, kind: 'past', credits: creditsOf(rec.courses) }
      }
      const inPlan = plan.terms.find((x) => x.year === t.year && x.term === t.half)
      if (i === currentIdx) return { term: t, kind: 'current', credits: termStatus(status, t).terms[0]?.credits ?? 0 }
      return { term: t, kind: inPlan !== undefined && inPlan.courses.length > 0 ? 'planned' : 'none', credits: null }
    })
    const viewKind = cells.find((c) => sameTerm(c.term, term))?.kind ?? 'current'
    return {
      status,
      terms,
      planTerms,
      term,
      here,
      others,
      planResults,
      checkpoints: shown,
      unmet: unmetCount(here.results) + unmetCount(planResults) + (repeats.length > 0 ? 1 : 0),
      checkTerm,
      statusOf,
      history: {
        current,
        past,
        viewKind,
        cells,
        takenCredits: taken.reduce((n, c) => n + (c.credits ?? 0), 0),
        unrecorded,
        repeats,
      },
    }
  }, [checkpoints, current, currentIdx, dept, enabled, flags.requirements, focusTerm, placement.lookup, plan, planStatus, stored])
}
