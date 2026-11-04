import { useEffect } from 'react'
import { useLocation, useParams, useSearchParams } from 'react-router-dom'
import { parseOrigin, readPaneState, useNavi } from '../../navi/state'
import { rootEntry } from '../../navi/views'
import CourseDetail from './CourseDetail'

/** 科目の詳細の画面（/navi/course/<科目コード>?from=…）。スマホは別の画面、PC は中央の段 */
export default function CourseScreen() {
  const { dept, isPc, track } = useNavi()
  const { code = '' } = useParams()
  const [params] = useSearchParams()
  const location = useLocation()
  const origin = parseOrigin(params.get('from'))
  const pane = readPaneState(location.state)
  const tab = pane?.tab ?? (origin.kind === 'tt' ? 'tt' : 'search')
  // 履歴の道筋の最後が今の画面。リンクから直接開いたときは、来た一覧だけを前に置く
  const ancestors = pane !== null && pane.trail.length >= 2 ? pane.trail.slice(0, -1) : [rootEntry(dept, origin)]

  // 詳細を開いた科目を調査の記録に数える（UX 仕様 8.7）
  useEffect(() => {
    if (code !== '') track({ type: 'detail', code })
  }, [code, track])

  const detail = <CourseDetail key={code} code={code} origin={origin} trail={ancestors} tab={tab} />
  return isPc ? detail : <main>{detail}</main>
}
