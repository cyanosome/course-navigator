import { useEffect } from 'react'
import { useLocation, useParams, useSearchParams } from 'react-router-dom'
import { findCourse } from '../../navi/graph'
import { courseHref, parseOrigin, readPaneState, useNavi } from '../../navi/state'
import BackButton from './BackButton'
import CourseDetail from './CourseDetail'
import Panes from './Panes'

/** 科目の詳細の画面（/navi/course/<科目コード>?from=…）。スマホは別の画面、PC は右ペイン */
export default function CourseScreen() {
  const { dept, isPc, track } = useNavi()
  const { code = '' } = useParams()
  const [params] = useSearchParams()
  const location = useLocation()
  const origin = parseOrigin(params.get('from'))
  const pane = readPaneState(location.state)
  const course = findCourse(dept, code)
  const tab = pane?.tab ?? (origin.kind === 'shortlist' ? 'shortlist' : 'search')
  const trail = pane?.trail ?? [{ label: course?.name ?? code, href: courseHref(code, origin) }]

  // 詳細を開いた科目を調査の記録に数える（UX 仕様 8.7）
  useEffect(() => {
    if (code !== '') track({ type: 'detail', code })
  }, [code, track])

  if (!isPc) {
    return (
      <main className="m-main">
        <BackButton />
        <CourseDetail code={code} origin={origin} trail={[]} tab={tab} />
      </main>
    )
  }

  const rootCode = /\/navi\/course\/([^?]+)/.exec(trail[0]?.href ?? '')?.[1]
  return (
    <Panes tab={tab} currentCode={rootCode === undefined ? undefined : decodeURIComponent(rootCode)} contextCourse={course}>
      <CourseDetail code={code} origin={origin} trail={trail} tab={tab} />
    </Panes>
  )
}
