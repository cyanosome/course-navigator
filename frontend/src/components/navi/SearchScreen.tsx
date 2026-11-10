import { useEffect } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { findInterest } from '../../navi/graph'
import { useNavi } from '../../navi/state'
import type { Origin } from '../../navi/state'
import { firstListCode, rootEntry } from '../../navi/views'
import CourseDetail from './CourseDetail'
import SearchList from './SearchList'

/**
 * さがす（W1・W2・W5、PC は W11）。/navi、/navi?dir=<興味関心>、/navi/ask/<端末内の番号>。
 * スマホは一覧そのもの。PC は一覧を左の段（NaviLayout）に出し、ここは中央に一覧の1件目の詳細を出す（UX 仕様 S1 の PC、E1 RM8）。
 */
export default function SearchScreen() {
  const { dept, isPc, ask, lastDir, setLastDir, shortlist, focusTerm, assumedTerm } = useNavi()
  const { localId } = useParams()
  const [params] = useSearchParams()
  const dirParam = params.get('dir')
  const validDir = dirParam !== null && findInterest(dept, dirParam) !== undefined ? dirParam : 'default'
  const dirId = localId !== undefined ? lastDir : validDir

  useEffect(() => {
    if (localId === undefined) setLastDir(validDir)
  }, [localId, validDir, setLastDir])

  if (!isPc) {
    return (
      <main>
        <SearchList dirId={dirId} pc={false} />
      </main>
    )
  }

  const ctx = { dept, shortlist, focusTerm, assumedTerm }
  const code = firstListCode(ctx, dirId, ask, true)
  if (code === null) return <p className="hint">左の一覧から科目を選ぶと、ここに詳細が出ます。</p>
  const fromAsk = ask !== null && ask.status === 'done' && ask.result?.sources.some((s) => s.code === code) === true
  const origin: Origin = fromAsk
    ? { kind: 'ask', localId: ask.localId }
    : dirId === 'default'
      ? { kind: 'default' }
      : { kind: 'dir', dirId }
  const root = rootEntry(dept, origin)
  return <CourseDetail code={code} origin={origin} trail={[root]} tab="search" />
}
