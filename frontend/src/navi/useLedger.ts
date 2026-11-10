/**
 * 診断の変種の「確かめる場所」（PC は右の列、スマホは上の帯）に出す、プランの履修状況とチェックの結果。
 * 履修状況は useCourseStatus（プラン）、判定は status.ts、学期ごとの分け方は ledger.ts。どの変種でも同じものを出す
 * （AI の案を入れた場合は、ここでは計算しない。AI の欄の中だけで出す）。
 */
import { useMemo } from 'react'
import type { WorkingPlan } from './diagnose'
import { ledgerTerms, planChecks, termChecks, unmetCount } from './ledger'
import type { TermChecks } from './ledger'
import { useNavi } from './state'
import { kindsAvailable } from './status'
import type { Checkpoint, CheckResult, CourseStatus } from './status'
import type { TermKey } from './timetable'
import { sameTerm } from './timetable'
import { useCheckpoints, useCourseStatus } from './useStatus'
import { useFlags } from './variant'

export interface LedgerView {
  /** プラン全体の履修状況 */
  status: CourseStatus
  /** 切り替えられる学期 */
  terms: TermKey[]
  /** いま見ている学期（共有の学期がプランの学期に無ければ、プランの最初の学期） */
  term: TermKey
  /** いま見ている学期の履修状況とチェック */
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
}

export function useLedger(plan: WorkingPlan): LedgerView {
  const { dept, focusTerm } = useNavi()
  const { checkpoints } = useCheckpoints()
  const flags = useFlags()
  const { status } = useCourseStatus({ kind: 'plan', plan })
  return useMemo(() => {
    const shown = flags.requirements === 'shown' ? checkpoints : checkpoints.filter((c) => c.kind !== 'required')
    const base = { dept, kindsAvailable: flags.requirements === 'shown' && kindsAvailable(dept) }
    const terms = ledgerTerms(
      plan.terms.map((t) => ({ year: t.year, half: t.term })),
      status,
    )
    const term = terms.find((t) => sameTerm(t, focusTerm)) ?? terms[0] ?? focusTerm
    const checkTerm = (st: CourseStatus, t: TermKey) => termChecks(st, t, shown, base).results
    const here = termChecks(status, term, shown, base)
    const others = terms
      .filter((t) => !sameTerm(t, term))
      .map((t) => ({ term: t, unmet: unmetCount(checkTerm(status, t)) }))
      .filter((o) => o.unmet > 0)
    const planResults = planChecks(status, shown, { ...base, terms })
    return {
      status,
      terms,
      term,
      here,
      others,
      planResults,
      checkpoints: shown,
      unmet: unmetCount(here.results) + unmetCount(planResults),
      checkTerm,
    }
  }, [checkpoints, dept, flags.requirements, focusTerm, plan.terms, status])
}
