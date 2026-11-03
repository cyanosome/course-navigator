import { useEffect } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { directionStages, findCourse, findDirection } from '../../navi/graph'
import { useNavi } from '../../navi/state'
import type { Origin } from '../../navi/state'
import { askViews, defaultViews } from '../../navi/views'
import CourseDetail from './CourseDetail'
import Panes from './Panes'
import SearchList from './SearchList'

interface FirstItem {
  code: string
  origin: Origin
}

/**
 * さがす（W1・W2、PC は W11）。/navi、/navi?dir=<方向>、/navi/ask/<端末内の番号>。
 * PC は開いた時点で、一覧の1件目の詳細が右ペインに出ている（UX 仕様 S1 の PC）。
 */
export default function SearchScreen() {
  const { dept, isPc, ask, lastDir, setLastDir, assumedYear } = useNavi()
  const { localId } = useParams()
  const [params] = useSearchParams()
  const dirParam = params.get('dir')
  const validDir = dirParam !== null && findDirection(dept, dirParam) !== undefined ? dirParam : 'default'
  const dirId = localId !== undefined ? lastDir : validDir

  useEffect(() => {
    if (localId === undefined) setLastDir(validDir)
  }, [localId, validDir, setLastDir])

  if (!isPc) {
    return (
      <main className="m-main">
        <h1 className="sr-only">さがす</h1>
        <SearchList dirId={dirId} variant="mobile" />
      </main>
    )
  }

  const first = firstItem()
  const course = first === null ? undefined : findCourse(dept, first.code)
  return (
    <Panes tab="search" dirId={dirId} currentCode={first?.code} contextCourse={course}>
      {first === null ? (
        <p className="body-s">左の一覧から科目を選ぶと、ここに詳細が出ます。</p>
      ) : (
        <CourseDetail code={first.code} origin={first.origin} trail={[]} tab="search" />
      )}
    </Panes>
  )

  function firstItem(): FirstItem | null {
    if (ask !== null && ask.status === 'done') {
      const v = askViews(dept, ask, 'search')[0]
      if (v !== undefined) return { code: v.code, origin: { kind: 'ask', localId: ask.localId } }
    }
    const direction = findDirection(dept, dirId)
    if (direction !== undefined && direction.targets.length > 0) {
      const c = directionStages(dept, direction)
        .flatMap((s) => s.frames)
        .flatMap((f) => f.shown)[0]
      return c === undefined ? null : { code: c.code, origin: { kind: 'dir', dirId: direction.id } }
    }
    const d = defaultViews(dept, assumedYear)[0]
    return d === undefined ? null : { code: d.code, origin: { kind: 'default' } }
  }
}
