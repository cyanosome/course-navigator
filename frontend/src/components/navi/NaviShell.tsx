import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useLocation, useNavigate, useNavigationType } from 'react-router-dom'
import { markVariantApplied, useResearchLog } from '../../navi/research'
import { DIAGNOSE_HREF, listHref, parseOrigin, readPaneState, TIMETABLE_HREF, useNavi } from '../../navi/state'
import type { PcTab } from '../../navi/state'
import { termCredits, termLabel } from '../../navi/timetable'
import '../../navi/plan.css'
import { useFlags } from '../../navi/variant'
import { rootEntry } from '../../navi/views'
import Icon from './Icon'
import Menu from './Menu'
import TaskCard from './TaskCard'
import Toast from './Toast'
import WaitLine from './WaitLine'

interface NaviShellProps {
  children: ReactNode
}

type Place = 'search' | 'tt' | 'detail' | 'page' | 'study' | 'plan'
/** 行き先のタブ（プランは旗 diagnose=quiz のときだけ） */
type NavTab = PcTab | 'plan'
type Pop = 'menu'

const MENU_ID = 'navi-menu'

function placeOf(pathname: string): Place {
  if (pathname === '/navi' || pathname === '/navi/' || pathname.startsWith('/navi/ask/')) return 'search'
  if (pathname.startsWith('/navi/timetable')) return 'tt'
  if (pathname.startsWith('/navi/course/') || pathname.startsWith('/navi/group/')) return 'detail'
  if (pathname.startsWith('/navi/study')) return 'study'
  if (pathname.startsWith(DIAGNOSE_HREF)) return 'plan'
  return 'page'
}

/**
 * 上の帯・メニュー・下のタブ（スマホ）・調査モードの帯・待ちの1行・知らせ・読み上げ用の領域を、
 * どの画面にも同じ場所に出す（E1 4章・6章）。自分の言葉で探す欄は、さがすの一覧のいちばん上に置く（SearchList。入口の案 a）。
 * 調査のセッション中（/navi/s/<トークン> から始めたとき）は、帯の場所に課題（TaskCard）を出し、メニューは出さない
 * （学科を変える・このAIについては、どの条件でも開けないようにする）。
 */
export default function NaviShell({ children }: NaviShellProps) {
  const { dept, isPc, shortlist, placement, focusTerm, study, ask, lastDir, endStudy, announcement } = useNavi()
  const flags = useFlags()
  const { active: researching, log } = useResearchLog()
  const location = useLocation()
  const navigate = useNavigate()
  const navigationType = useNavigationType()
  const place = placeOf(location.pathname)
  const minimal = place === 'study'

  // 画面が使った旗を、ブロックごとに1回記録する（variant_applied）
  useEffect(() => {
    if (researching) markVariantApplied(flags)
  }, [researching, flags])

  // 時間割のタブを開いたら記録する（timetable_open。同じ画面の中で学期を変えても重ねない）
  const ttLoggedRef = useRef<string | null>(null)
  useEffect(() => {
    if (place !== 'tt') {
      ttLoggedRef.current = null
      return
    }
    if (ttLoggedRef.current === location.key) return
    ttLoggedRef.current = location.key
    log('timetable_open', { term: termLabel(focusTerm) })
  }, [place, location.key, focusTerm, log])

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
  const tab: NavTab | null =
    place === 'plan'
      ? 'plan'
      : place === 'search'
        ? 'search'
        : place === 'tt'
          ? 'tt'
          : place === 'detail'
            ? (pane?.tab ?? (origin.kind === 'tt' ? 'tt' : 'search'))
            : null
  const showPlanTab = flags.diagnose === 'quiz'
  const searchHref = listHref(lastDir)
  const credits = termCredits(dept, shortlist, focusTerm, placement)

  // 自由記述の状態の1行（UX 仕様 C08）。スマホは一覧に待ちの表示があるので、さがすの画面では出さない。AI の欄が無い変種では出さない
  const askPending = flags.assistant === 'on' && ask !== null && (ask.status === 'waiting' || !ask.seen)
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
  const showMenu = !minimal && !researching
  const task = researching && <TaskCard />

  const live = (
    <p className="vh" aria-live="polite">
      {announcement}
    </p>
  )

  // 診断の変種（デザインのコンペの U-a）: 上の帯は コースナビ・プラン・さがす・メニュー だけ。時間割のタブと下のタブは無く、
  // 時間割は確かめる場所（PlanLayout）の一部。戻るは作る場所の上（BackLink）に置く
  if (flags.diagnose === 'quiz') {
    const fromPlan = origin.kind === 'plan' || origin.kind === 'refine' || origin.kind === 'status'
    const onPlan = place === 'plan' || (place === 'detail' && fromPlan)
    const onSearch = place === 'search' || (place === 'detail' && !fromPlan)
    return (
      <div className="ps">
        {band}
        {task}
        <header className="ps-bar">
          <span className="brand">コースナビ</span>
          {!minimal && (
            <nav className="ps-tabs" aria-label="行き先">
              <Link to={DIAGNOSE_HREF} aria-current={onPlan ? 'page' : undefined}>
                プラン
              </Link>
              <Link to={searchHref} aria-current={onSearch ? 'page' : undefined}>
                さがす
              </Link>
            </nav>
          )}
          <div className="spacer" />
          {showMenu && menuButton}
          {menu}
        </header>
        {askPending && !minimal && place !== 'search' && <WaitLine />}
        {children}
        <Toast />
        {live}
      </div>
    )
  }

  if (isPc) {
    return (
      <div className="pc">
        {band}
        {task}
        <header className="pc-bar">
          <span className="brand">コースナビ</span>
          {!minimal && (
            <nav className="pc-tabs" aria-label="行き先">
              {showPlanTab && (
                <Link to={DIAGNOSE_HREF} aria-current={tab === 'plan' ? 'page' : undefined}>
                  プラン
                </Link>
              )}
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
          {showMenu && menuButton}
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
      {task}
      <header className="bar">
        {back === null ? (
          <span className="brand">コースナビ</span>
        ) : (
          <button className="back" type="button" onClick={goBack}>
            <Icon name="back" />
            <span>{back.label}</span>
          </button>
        )}
        {showMenu && (
          <div className="bar-actions">
            {menuButton}
          </div>
        )}
        {menu}
      </header>
      {children}
      {showWait && <WaitLine />}
      {!minimal && (
        <nav className={showPlanTab ? 'tabs is-3' : 'tabs'} aria-label="行き先">
          {showPlanTab && (
            <Link className="tab" to={DIAGNOSE_HREF} aria-current={tab === 'plan' ? 'page' : undefined}>
              <Icon name="check" />
              <span>プラン</span>
            </Link>
          )}
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
