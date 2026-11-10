/**
 * 履修状況とチェックの状態（どの変種でも同じものを出す）。
 * - useCheckpointsState: 利用者が足し外しするチェックの一覧（端末に保存。KEYS.checkpoints）と記録。NaviRoot で1つ作り、
 *   CheckpointsContext で配る。
 * - useCourseStatus: 候補かプランの科目一覧から、履修状況（status.ts の buildStatus）とチェックの結果を計算する。
 * 判定そのものは status.ts の純関数。画面の部品はこのフックの値と関数だけを使う。
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { WorkingPlan } from './diagnose'
import type { ResearchLog } from './research'
import { useNavi } from './state'
import {
  buildStatus,
  checkpointPayload,
  DEFAULT_CHECKPOINTS,
  evaluateCheckpoints,
  isCheckpointList,
  kindsAvailable,
  statusCoursesFromPlan,
  statusCoursesFromShortlist,
} from './status'
import type { Checkpoint, CheckResult, CourseStatus } from './status'
import { KEYS, readJson, writeJson } from './storage'
import type { TermKey } from './timetable'
import { useDiagnose } from './useDiagnose'
import { useFlags } from './variant'

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never

/** 足すときの形（id は足すときに付ける） */
export type NewCheckpoint = DistributiveOmit<Checkpoint, 'id'>

export interface CheckpointsState {
  checkpoints: Checkpoint[]
  add: (cp: NewCheckpoint) => void
  remove: (id: string) => void
}

function newId(kind: string, list: Checkpoint[]): string {
  let n = list.length + 1
  while (list.some((c) => c.id === `${kind}-${n}`)) n += 1
  return `${kind}-${n}`
}

export function useCheckpointsState(log: ResearchLog['log']): CheckpointsState {
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>(
    () => readJson('local', KEYS.checkpoints, isCheckpointList) ?? [...DEFAULT_CHECKPOINTS],
  )
  useEffect(() => writeJson('local', KEYS.checkpoints, checkpoints), [checkpoints])

  const add = useCallback(
    (draft: NewCheckpoint) => {
      const cp = { ...draft, id: newId(draft.kind, checkpoints) } as Checkpoint
      const next = [...checkpoints, cp]
      setCheckpoints(next)
      log('checkpoint_add', { checkpoint: checkpointPayload(cp), checkpoint_ids: next.map((c) => c.id) })
    },
    [checkpoints, log],
  )
  const remove = useCallback(
    (id: string) => {
      const target = checkpoints.find((c) => c.id === id)
      if (target === undefined) return
      const next = checkpoints.filter((c) => c.id !== id)
      setCheckpoints(next)
      log('checkpoint_remove', { checkpoint: checkpointPayload(target), checkpoint_ids: next.map((c) => c.id) })
    },
    [checkpoints, log],
  )
  return { checkpoints, add, remove }
}

export const CheckpointsContext = createContext<CheckpointsState | null>(null)

export function useCheckpoints(): CheckpointsState {
  const value = useContext(CheckpointsContext)
  if (value === null) throw new Error('useCheckpoints は NaviApp の中で使ってください')
  return value
}

export type StatusTarget = { kind: 'shortlist' } | { kind: 'plan'; plan: WorkingPlan }

export interface CourseStatusView {
  status: CourseStatus
  results: CheckResult[]
  /** 学期ごとのチェックで見た学期 */
  terms: TermKey[]
}

/**
 * 候補かプランの履修状況とチェックの結果。学期ごとのチェックで見る学期は、診断の設定があればその学期（プランが埋める学期）、
 * プランならプランの学期、どちらも無ければ科目のある学期。候補には時間割と同じく、旗 requirements=shown なら学科の必修を入れる
 */
export function useCourseStatus(target: StatusTarget): CourseStatusView {
  const { dept, shortlist, placement } = useNavi()
  const { checkpoints } = useCheckpoints()
  const { config, working } = useDiagnose()
  const flags = useFlags()
  const scopeTerms = useMemo<TermKey[]>(
    () => (config?.status === 'ready' ? config.value.scope.terms.map((t) => ({ year: t.year, half: t.term })) : []),
    [config],
  )
  const plan = target.kind === 'plan' ? target.plan : null
  // 系統図に無い科目は、時間割と同じ引き方（科目の入れ物 → プランの科目）で引く
  const lookup = placement.lookup
  return useMemo(() => {
    const find = (code: string) => lookup?.(code)
    const courses =
      plan !== null
        ? statusCoursesFromPlan(dept, plan, find)
        : statusCoursesFromShortlist(dept, shortlist, find, working, flags.requirements === 'shown')
    const terms = plan !== null ? plan.terms.map((t) => ({ year: t.year, half: t.term })) : scopeTerms
    const status = buildStatus(courses)
    // 区分を出さない変種（requirements=hidden）では、必修のチェックを出さない
    const shown = flags.requirements === 'shown' ? checkpoints : checkpoints.filter((c) => c.kind !== 'required')
    const results = evaluateCheckpoints(shown, status, {
      dept,
      terms,
      kindsAvailable: flags.requirements === 'shown' && kindsAvailable(dept),
    })
    return { status, results, terms }
  }, [checkpoints, dept, flags.requirements, lookup, plan, scopeTerms, shortlist, working])
}
