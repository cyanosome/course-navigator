import type { ReactNode } from 'react'
import { useNavi } from '../../navi/state'
import type { PcTab } from '../../navi/state'
import type { Course } from '../../navi/types'
import SearchList from './SearchList'
import ShortlistContent from './ShortlistContent'

interface PanesProps {
  tab: PcTab
  /** 右ペインに出している科目（左の一覧の印） */
  currentCode?: string
  /** 右ペインの科目（W6-1 の科目ごとの案内） */
  contextCourse?: Course
  /** 左ペインの方向（既定は最後に選んだ方向） */
  dirId?: string
  children: ReactNode
}

/** PC の一覧と詳細の2ペイン（UX 仕様 5.3、W11・W12）。右ペインを移っても左の一覧はそのまま */
export default function Panes({ tab, currentCode, contextCourse, dirId, children }: PanesProps) {
  const { lastDir } = useNavi()
  return (
    <div className="panes">
      <aside className="pane-list" aria-label={tab === 'search' ? '方向と提案の一覧' : '候補の一覧'}>
        {tab === 'search' ? (
          <SearchList dirId={dirId ?? lastDir} variant="pc" currentCode={currentCode} contextCourse={contextCourse} />
        ) : (
          <ShortlistContent variant="pc" currentCode={currentCode} />
        )}
      </aside>
      <main className="pane-detail">{children}</main>
    </div>
  )
}
