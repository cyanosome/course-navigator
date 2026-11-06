import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useLocation, useNavigate, useNavigationType } from 'react-router-dom'
import { listHref, parseOrigin, readPaneState, TIMETABLE_HREF, useNavi } from '../../navi/state'
import type { PcTab } from '../../navi/state'
import { termCredits } from '../../navi/timetable'
import { rootEntry } from '../../navi/views'
import Icon from './Icon'
import Menu from './Menu'
import Toast from './Toast'
import WaitLine from './WaitLine'

interface NaviShellProps {
  children: ReactNode
}

type Place = 'search' | 'tt' | 'detail' | 'page' | 'study'
type Pop = 'menu'

const MENU_ID = 'navi-menu'

function placeOf(pathname: string): Place {
  if (pathname === '/navi' || pathname === '/navi/' || pathname.startsWith('/navi/ask/')) return 'search'
  if (pathname.startsWith('/navi/timetable')) return 'tt'
  if (pathname.startsWith('/navi/course/') || pathname.startsWith('/navi/group/')) return 'detail'
  if (pathname.startsWith('/navi/study')) return 'study'
  return 'page'
}

/**
 * 上の帯・メニュー・下のタブ（スマホ）・調査モードの帯・待ちの1行・知らせ・読み上げ用の領域を、
 * どの画面にも同じ場所に出す（E1 4章・6章）。自分の言葉で探す欄は、さがすの一覧のいちばん上に置く（SearchList。入口の案 a）。
 */
export default function NaviShell({ children }: NaviShellProps) {
  const { dept, isPc, shortlist, focusTerm, study, ask, lastDir, endStudy, announcement } = useNavi()
  const location = useLocation()
  const navigate = useNavigate()
  const navigationType = useNavigationType()
  const place = placeOf(location.pathname)
  const minimal = place === 'study'

  /** 開いているメニュー。開いた画面から移ったら閉じたことにする */
  const [pop, setPop] = useState<{ kind: Pop; key: string } | null>(null)
  const openPop = pop !== null && pop.key === location.key ? pop.kind : null
  const popRef = useRef<HTMLDivElement>(null)
  const menuBtnRef = useRef<HTMLButtonElement>(null)

  const toggle = (kind: Pop) => setPop(openPop === kind ? null : { kind, key: location.key })

  // Esc で閉じて押したボタンへ戻る。外を押しても閉じる
  useEffect(() => {
    if (openPop === null) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setPop(null)
      menuBtnRef.current?.focus()
    }
    const onDown = (e: PointerEvent) => {
      const target = e.target
      if (!(target instanceof Element)) return
      if (popRef.current?.contains(target) || target.closest('[data-pop-toggle]') !== null) return
      setPop(null)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onDown)
    }
  }, [openPop])

  // 別の画面へ進んだら上から見せる。ブラウザの戻る（POP）はブラウザの位置の復元に任せる
  useEffect(() => {
    if (navigationType !== 'POP') window.scrollTo(0, 0)
  }, [location.pathname, location.search, navigationType])

  const pane = readPaneState(location.state)
  const origin = parseOrigin(new URLSearchParams(location.search).get('from'))
  const tab: PcTab | null =
    place === 'search' ? 'search' : place === 'tt' ? 'tt' : place === 'detail' ? (pane?.tab ?? (origin.kind === 'tt' ? 'tt' : 'search')) : null
  const searchHref = listHref(lastDir)
  const credits = termCredits(dept, shortlist, focusTerm)

  // 自由記述の状態の1行（UX 仕様 C08）。スマホは一覧に待ちの表示があるので、さがすの画面では出さない
  const askPending = ask !== null && (ask.status === 'waiting' || !ask.seen)
  const showWait = askPending && !minimal && (isPc ? tab !== 'search' : place !== 'search')

  const finish = () => {
    endStudy()
    navigate('/navi/study/end')
  }

  const band = study !== null && !minimal && (
    <div className="band" role="region" aria-label="調査モード">
      <p>研究のための試用版です{isPc && `（調査 ${study.surveyId}）。使いにくいところを見つけるのが目的です`}</p>
      <button className="band-btn" type="button" onClick={finish}>
        使い終わった
      </button>
    </div>
  )

  const menuButton = (
    <button
      ref={menuBtnRef}
      className="icon-btn"
      type="button"
      data-pop-toggle=""
      aria-label="メニュー"
      aria-expanded={openPop === 'menu'}
      aria-controls={MENU_ID}
      onClick={() => toggle('menu')}
    >
      <Icon name="menu" />
    </button>
  )

  const menu = openPop === 'menu' && <Menu id={MENU_ID} ref={popRef} />

  const live = (
    <p className="vh" aria-live="polite">
      {announcement}
    </p>
  )

  if (isPc) {
    return (
      <div className="pc">
        {band}
        <header className="pc-bar">
          <span className="brand">コースナビ</span>
          {!minimal && (
            <nav className="pc-tabs" aria-label="行き先">
              <Link to={searchHref} aria-current={tab === 'search' ? 'page' : undefined}>
                さがす
              </Link>
              <Link to={TIMETABLE_HREF} aria-current={tab === 'tt' ? 'page' : undefined}>
                時間割 {credits}単位
              </Link>
            </nav>
          )}
          <div className="spacer" />
          <span className="dept">{dept.name}</span>
          {!minimal && menuButton}
          {menu}
        </header>
        {showWait && <WaitLine />}
        {children}
        <Toast />
        {live}
      </div>
    )
  }

  const back = place === 'detail' || place === 'page' ? backEntry() : null

  return (
    <div className={showWait ? 'sp has-wait' : 'sp'}>
      {band}
      <header className="bar">
        {back === null ? (
          <span className="brand">コースナビ</span>
        ) : (
          <button className="back" type="button" onClick={goBack}>
            <Icon name="back" />
            <span>{back.label}</span>
          </button>
        )}
        {!minimal && (
          <div className="bar-actions">
            {menuButton}
          </div>
        )}
        {menu}
      </header>
      {children}
      {showWait && <WaitLine />}
      {!minimal && (
        <nav className="tabs" aria-label="行き先">
          <Link className="tab" to={searchHref} aria-current={tab === 'search' ? 'page' : undefined}>
            <Icon name="list" />
            <span>さがす</span>
          </Link>
          <Link className="tab" to={TIMETABLE_HREF} aria-current={tab === 'tt' ? 'page' : undefined}>
            <Icon name="grid" />
            <span>時間割 {credits}単位</span>
          </Link>
        </nav>
      )}
      <Toast />
      {live}
    </div>
  )

  /** スマホの戻る（来た場所の名前で戻る。E1 6章） */
  function backEntry() {
    if (place === 'page') return { label: '戻る', href: '/navi' }
    const trail = pane?.trail
    const prev = trail !== undefined && trail.length >= 2 ? trail[trail.length - 2] : undefined
    return prev ?? rootEntry(dept, origin)
  }

  function goBack() {
    // このアプリの中で来た画面なら1つ前へ。リンクから直接開いたときは来た一覧へ
    if (location.key !== 'default') {
      navigate(-1)
      return
    }
    navigate(back?.href ?? '/navi')
  }
}
