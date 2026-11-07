/**
 * 満たさないチェック（重なり・空ける曜日）に添える直し方「同じ名前の別のクラスへ移す」を探す。どの変種でも同じものを出す
 * （LLM は使わない。事前登録 study1 の 2.2）。原因の科目の名前でキーワード検索（D4）を引き、ledger.ts の pickClassMove で選ぶ。
 * 検索の結果は名前ごとに持ち、同じ名前は引き直さない。引けなかった名前は直し方を出さない（チェックそのものは出る）。
 */
import { useEffect, useState } from 'react'
import type { CourseSummary } from './apiTypes'
import { useNaviData } from './dataSource'
import { movableCauses, pickClassMove } from './ledger'
import type { ClassMove } from './ledger'
import { useNavi } from './state'
import type { LedgerView } from './useLedger'

/** 1つの名前で見る別のクラスの数の上限 */
const CLASS_LIMIT = 50

/** チェックの id → 移す先（見つかったものだけ） */
export function useClassMoves(view: LedgerView): ReadonlyMap<string, ClassMove> {
  const { dept } = useNavi()
  const { source } = useNaviData()
  const [found, setFound] = useState<ReadonlyMap<string, readonly CourseSummary[]>>(() => new Map())
  const termCourses = view.here.status.courses
  const targets = view.here.results.flatMap((r) => {
    const cp = view.checkpoints.find((c) => c.id === r.id)
    if (cp === undefined) return []
    return movableCauses(cp, r).flatMap((code) => {
      const cause = termCourses.find((c) => c.code === code)
      return cause === undefined ? [] : [{ id: r.id, cause }]
    })
  })
  const namesKey = [...new Set(targets.map((t) => t.cause.name))].sort().join('\n')

  useEffect(() => {
    if (namesKey === '') return
    const control = new AbortController()
    for (const name of namesKey.split('\n')) {
      source
        .searchCourses({ dept: dept.id, q: name, limit: CLASS_LIMIT }, control.signal)
        .then((page) => {
          if (!control.signal.aborted) setFound((prev) => new Map(prev).set(name, page.items))
        })
        .catch((err: unknown) => {
          if (control.signal.aborted) return
          console.error(`別のクラスを探せませんでした（${name}）`, err)
          setFound((prev) => new Map(prev).set(name, []))
        })
    }
    return () => control.abort()
  }, [dept.id, namesKey, source])

  const moves = new Map<string, ClassMove>()
  for (const t of targets) {
    if (moves.has(t.id)) continue
    const move = pickClassMove(t.cause, view.term, termCourses, found.get(t.cause.name) ?? [], view.checkpoints)
    if (move !== null) moves.set(t.id, move)
  }
  return moves
}
