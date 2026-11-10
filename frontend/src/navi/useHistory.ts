/**
 * 学期ごとの利用と履修の記録の状態（学期のコンペの T-a）。純関数は navi/history.ts。
 * NaviRoot で1つ作り（useHistoryState）、HistoryContext で配る（useHistory）。
 * 診断の変種（diagnose=quiz）で、調査のモードでないときだけ使う（enabled）。調査のモードでは読みも書きもせず、
 * 学期の表・履歴を出さず、診断と AI に履修の状況を送らない（事前登録 study1 の調査の動きを変えない）。
 * 端末の localStorage にだけ置く（storage.ts の 'local'）。学科ごとに持つ（学科が変われば空から）。
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { WorkingPlan } from './diagnose'
import {
  addTaken,
  clearRecord,
  currentIndex,
  emptyHistory,
  isStoredHistory,
  registeredIds,
  removeTaken,
  setRecord,
  setRegistered,
  termAt,
  withCurrent,
} from './history'
import type { StoredHistory, TakenCourse } from './history'
import { KEYS, readJson, writeJson } from './storage'
import type { TermKey } from './timetable'
import { termIndex } from './timetable'

export interface HistoryState {
  /** 学期の表と履歴を使うか（診断の変種で、調査のモードでないとき） */
  enabled: boolean
  stored: StoredHistory
  /** 今の学期（まだ選んでいなければ null） */
  current: TermKey | null
  currentIdx: number | null
  /** 学期の切り替わり（切り替わりを済ませた学期 → 今の学期）。無ければ null */
  change: { from: TermKey; to: TermKey } | null
  /** 初めに今の学期を選ぶ */
  pick: (t: TermKey) => void
  /** メニューから今の学期を直す。今より後の学期にしたら、前の今の学期の切り替わりを出す */
  fixCurrent: (t: TermKey) => void
  /** 切り替わりで「前の学期のままにする」 */
  stay: () => void
  /** 切り替わりで［あとで］（今の学期は進め、前の学期は未記入のまま） */
  later: () => void
  /** 切り替わりで記録して進む（前の学期の記録を taken にする。carry は今の学期の登録済みに足す科目） */
  finishChange: (taken: TakenCourse[], carry: string[]) => void
  /** その学期の記録を置き換える（空なら「取っていない」） */
  record: (t: TermKey, courses: TakenCourse[]) => void
  add: (t: TermKey, courses: TakenCourse[]) => void
  remove: (t: TermKey, name: string) => void
  /** 未記入に戻す */
  clear: (t: TermKey) => void
  setRegistered: (t: TermKey, ids: string[]) => void
  /** プランから外れた登録済みの科目を落とす（プランの足し外しのあと） */
  pruneRegistered: (plan: WorkingPlan) => void
  /** この端末の記録（取った科目と登録済み）を消す。今の学期は残す */
  clearAll: () => void
}

interface HistoryDeps {
  deptId: string
  enabled: boolean
}

export function useHistoryState({ deptId, enabled }: HistoryDeps): HistoryState {
  const [now] = useState(() => new Date())
  // 読むのは enabled によらない（旗はサーバーから後で届くので、最初の描画では enabled が false のことがある。
  // そのとき空で始めると、旗が届いた後に空で上書きしてしまう）。書くのは enabled のときだけ。
  // 調査のモードでは 'local' が sessionStorage なので、ここには何も無い
  const [stored, setStored] = useState<StoredHistory>(() => {
    const saved = readJson('local', KEYS.history, isStoredHistory)
    return saved !== null && saved.deptId === deptId ? saved : emptyHistory(deptId)
  })
  const fresh = useMemo(() => emptyHistory(deptId), [deptId])
  const cur = stored.deptId === deptId ? stored : fresh
  useEffect(() => {
    if (enabled) writeJson('local', KEYS.history, cur)
  }, [cur, enabled])

  const update = useCallback(
    (f: (h: StoredHistory) => StoredHistory) => setStored((s) => f(s.deptId === deptId ? s : emptyHistory(deptId))),
    [deptId],
  )

  const idx = enabled ? currentIndex(cur, now) : null
  const current = idx === null ? null : termAt(idx)
  const change = useMemo(() => {
    if (idx === null || cur.seen === null || idx <= cur.seen) return null
    return { from: termAt(cur.seen), to: termAt(idx) }
  }, [cur.seen, idx])

  const pick = useCallback((t: TermKey) => update((h) => withCurrent(h, t, now, termIndex(t))), [now, update])
  const fixCurrent = useCallback(
    (t: TermKey) =>
      update((h) => {
        const before = currentIndex(h, now)
        const next = termIndex(t)
        return withCurrent(h, t, now, before !== null && next > before ? before : next)
      }),
    [now, update],
  )
  const stay = useCallback(
    () =>
      update((h) => {
        if (h.seen === null) return h
        return withCurrent(h, termAt(h.seen), now, h.seen)
      }),
    [now, update],
  )
  const later = useCallback(
    () =>
      update((h) => {
        const at = currentIndex(h, now)
        return at === null ? h : { ...h, registered: registeredFrom(h, at), seen: at }
      }),
    [now, update],
  )
  const finishChange = useCallback(
    (taken: TakenCourse[], carry: string[]) =>
      update((h) => {
        const at = currentIndex(h, now)
        if (h.seen === null || at === null) return h
        const recorded = { ...setRecord(h, termAt(h.seen), taken), registered: registeredFrom(h, at) }
        const to = termAt(at)
        const registered = carry.length === 0 ? recorded : setRegistered(recorded, to, [...registeredIds(recorded, to), ...carry])
        return { ...registered, seen: at }
      }),
    [now, update],
  )
  const record = useCallback((t: TermKey, courses: TakenCourse[]) => update((h) => setRecord(h, t, courses)), [update])
  const add = useCallback((t: TermKey, courses: TakenCourse[]) => update((h) => addTaken(h, t, courses)), [update])
  const remove = useCallback((t: TermKey, name: string) => update((h) => removeTaken(h, t, name)), [update])
  const clear = useCallback((t: TermKey) => update((h) => clearRecord(h, t)), [update])
  const setReg = useCallback((t: TermKey, ids: string[]) => update((h) => setRegistered(h, t, ids)), [update])
  const pruneRegistered = useCallback(
    (plan: WorkingPlan) =>
      update((h) => {
        let changed = false
        const registered = h.registered
          .map((r) => {
            const inPlan = plan.terms.find((t) => t.year === r.year && t.term === r.term)?.courses.map((c) => c.syllabus_id) ?? []
            const ids = r.ids.filter((id) => inPlan.includes(id))
            if (ids.length !== r.ids.length) changed = true
            return { ...r, ids }
          })
          .filter((r) => r.ids.length > 0)
        return changed ? { ...h, registered } : h
      }),
    [update],
  )
  const clearAll = useCallback(() => update((h) => ({ ...h, records: [], registered: [] })), [update])

  return {
    enabled,
    stored: cur,
    current,
    currentIdx: idx,
    change,
    pick,
    fixCurrent,
    stay,
    later,
    finishChange,
    record,
    add,
    remove,
    clear,
    setRegistered: setReg,
    pruneRegistered,
    clearAll,
  }
}

/** 今の学期から先の登録済みの科目だけ（学期が進んだら、前の学期の登録済みの印は要らない） */
function registeredFrom(h: StoredHistory, current: number): StoredHistory['registered'] {
  return h.registered.filter((r) => termIndex({ year: r.year, half: r.term }) >= current)
}

export const HistoryContext = createContext<HistoryState | null>(null)

export function useHistory(): HistoryState {
  const value = useContext(HistoryContext)
  if (value === null) throw new Error('useHistory は NaviApp の中で使ってください')
  return value
}
