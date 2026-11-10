import type { KeyboardEvent } from 'react'
import { Outlet, useLocation, useMatch, useSearchParams } from 'react-router-dom'
import { useKeywordQuery } from '../../navi/keyword'
import { parseOrigin, readPaneState, useNavi } from '../../navi/state'
import type { PcTab } from '../../navi/state'
import { useFlags } from '../../navi/variant'
import { firstListCode, listInterest } from '../../navi/views'
import SearchList from './SearchList'
import TimetablePanel from './TimetablePanel'
import TimetableSide from './TimetableSide'

const COURSE_IN_HREF = /\/navi\/course\/([^?]+)/

/**
 * さがす・詳細・まとまり・時間割の外枠。スマホは画面をそのまま出す。
 * PC は3列（E1 4章 W11）: 左 392px が一覧、中央が詳細、右 384px が時間割。時間割のタブでは左に時間割（W12）。
 * 中央を移っても左の一覧はそのまま（UX 仕様 C03）。
 */
export default function NaviLayout() {
  const { dept, isPc, lastDir, ask, shortlist, placement, focusTerm, assumedTerm } = useNavi()
  const flags = useFlags()
  const [keyword] = useKeywordQuery()
  const location = useLocation()
  const [params] = useSearchParams()
  const courseMatch = useMatch('/navi/course/:code')
  const askMatch = useMatch('/navi/ask/:localId')
  const ttMatch = useMatch('/navi/timetable')
  if (!isPc) return <Outlet />

  const pane = readPaneState(location.state)
  const origin = parseOrigin(params.get('from'))
  const tab: PcTab = ttMatch !== null ? 'tt' : (pane?.tab ?? (origin.kind === 'tt' ? 'tt' : 'search'))
  const ctx = { dept, shortlist, focusTerm, assumedTerm, flags, placement }

  if (tab === 'tt') {
    return (
      <div className="pc-body is-tt">
        <aside className="pc-list is-tt" aria-label="時間割">
          <TimetablePanel />
        </aside>
        <main className="pc-detail">
          <Outlet />
        </main>
      </div>
    )
  }

  const dirParam = params.get('dir')
  const onList = location.pathname === '/navi' || location.pathname === '/navi/' || askMatch !== null
  const validParam = dirParam !== null && listInterest(ctx, dirParam) !== undefined ? dirParam : null
  // 左の一覧の興味関心: 一覧の URL の指定 → 詳細の来た一覧（?from=dir:…）→ 最後に選んだもの
  const dirId =
    askMatch !== null
      ? lastDir
      : onList
        ? (validParam ?? 'default')
        : origin.kind === 'dir' && listInterest(ctx, origin.dirId) !== undefined
          ? origin.dirId
          : lastDir
  // 中央に出している科目（一覧の印と、右の時間割の下見に使う）
  const keywordActive = flags.search !== 'off' && keyword !== ''
  const centerCode = courseMatch?.params.code ?? (onList ? firstListCode(ctx, dirId, ask, flags.assistant === 'on', keywordActive) : null)
  // 一覧で選んだ科目（中央で前後の科目へ移っても、一覧の印は選んだ行に残す）
  const rootHref = pane?.trail[1]?.href
  const picked = rootHref === undefined ? undefined : COURSE_IN_HREF.exec(rootHref)?.[1]
  const currentCode = picked !== undefined ? decodeURIComponent(picked) : (centerCode ?? undefined)

  return (
    <div className="pc-body">
      <aside className="pc-list" aria-label="科目の一覧" onKeyDown={moveInList}>
        <SearchList dirId={dirId} pc currentCode={currentCode} />
      </aside>
      <main className="pc-detail">
        <Outlet />
      </main>
      <aside className="pc-tt" aria-label="時間割">
        <TimetableSide previewCode={centerCode} />
      </aside>
    </div>
  )
}

/** PC の一覧で ↑↓ を押すと、上下の科目へ移り、中央と右の段が替わる（E1 10章） */
function moveInList(e: KeyboardEvent<HTMLElement>) {
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
  const target = e.target
  if (!(target instanceof HTMLElement) || target.closest('input, textarea') !== null) return
  const links = Array.from(e.currentTarget.querySelectorAll<HTMLAnchorElement>('.row .row-link'))
  if (links.length === 0) return
  const ownRow = target.closest('.row')
  const fromRow = ownRow ?? e.currentTarget.querySelector('.row[aria-current="true"]')
  const link = fromRow?.querySelector<HTMLAnchorElement>('.row-link') ?? null
  const i = link === null ? -1 : links.indexOf(link)
  const step = e.key === 'ArrowDown' ? 1 : -1
  const next = links[Math.min(links.length - 1, Math.max(0, i + step))]
  if (next === undefined) return
  e.preventDefault()
  if (next !== link) next.click()
  next.focus()
}
