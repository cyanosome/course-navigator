import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { Link, useLocation, useNavigate, useNavigationType } from 'react-router-dom'
import { readPaneState, useNavi } from '../../navi/state'
import type { PcTab } from '../../navi/state'
import Glyph from './Glyph'
import WaitLine from './WaitLine'

interface NaviShellProps {
  children: ReactNode
}

type Place = 'search' | 'shortlist' | 'detail' | 'page' | 'study'

function placeOf(pathname: string): Place {
  if (pathname === '/navi' || pathname === '/navi/' || pathname.startsWith('/navi/ask/')) return 'search'
  if (pathname.startsWith('/navi/shortlist')) return 'shortlist'
  if (pathname.startsWith('/navi/course/') || pathname.startsWith('/navi/group/')) return 'detail'
  if (pathname.startsWith('/navi/study')) return 'study'
  return 'page'
}

/** 見出し・調査モードの帯・待ちの1行・下部ナビ（スマホ）・元に戻すを、どの画面にも同じ場所に出す */
export default function NaviShell({ children }: NaviShellProps) {
  const { dept, isPc, shortlist, study, ask, toast, dismissToast, lastDir, endStudy } = useNavi()
  const location = useLocation()
  const navigate = useNavigate()
  const navigationType = useNavigationType()
  const place = placeOf(location.pathname)

  // 別の画面へ進んだら上から見せる。ブラウザの戻る（POP）はブラウザの位置の復元に任せる
  useEffect(() => {
    if (navigationType !== 'POP') window.scrollTo(0, 0)
  }, [location.pathname, location.search, navigationType])
  const pane = readPaneState(location.state)
  const fromShortlist = new URLSearchParams(location.search).get('from') === 'shortlist'
  const tab: PcTab | null =
    place === 'search'
      ? 'search'
      : place === 'shortlist'
        ? 'shortlist'
        : place === 'detail'
          ? (pane?.tab ?? (fromShortlist ? 'shortlist' : 'search'))
          : null
  const searchHref = lastDir === 'default' ? '/navi' : `/navi?dir=${encodeURIComponent(lastDir)}`
  const inStudy = study !== null
  const minimal = place === 'study'

  // 自由記述の状態の1行（UX 仕様 C08）。スマホは一覧に待ちの表示があるので、さがすの画面では出さない
  const askPending = ask !== null && (ask.status === 'waiting' || !ask.seen)
  const showWait = askPending && !minimal && (isPc || place !== 'search')

  const finish = () => {
    endStudy()
    navigate('/navi/study/end')
  }

  const band = inStudy && !minimal && (
    <div className="band" role="region" aria-label="調査モード">
      <p>
        <strong>研究のための試用版です</strong>
        {isPc && `（調査 ${study.surveyId}）使いにくいところを見つけるのが目的です。`}
      </p>
      <button className="btn" type="button" onClick={finish}>
        使い終わった
      </button>
    </div>
  )

  const deptName = inStudy || minimal ? (
    <span className="dept dept--fixed">
      <span className="dept__name">{dept.name}</span>
    </span>
  ) : (
    <Link className="dept" to="/navi/departments" aria-label={`学科を変える（いまは${dept.name}）`}>
      <span className="dept__name">{dept.name}</span>
      <Glyph name="down" />
    </Link>
  )

  const toastView = (
    <div
      className={`toast${toast !== null ? ' is-shown' : ''}${!isPc && showWait ? ' toast--above-wait' : ''}`}
      role="status"
      aria-live="polite"
    >
      <span>{toast?.text ?? ''}</span>
      {toast !== null && (
        <button
          className="btn btn--on-ink"
          type="button"
          onClick={() => {
            toast.undo()
            dismissToast()
          }}
        >
          元に戻す
        </button>
      )}
    </div>
  )

  if (isPc) {
    return (
      <div className="p-shell">
        <header>
          {band}
          <div className="p-head">
            <p className="brand">コースナビ</p>
            {deptName}
            {!minimal && (
              <nav className="tabs" aria-label="行き先">
                <Link to={searchHref} aria-current={tab === 'search' ? 'page' : undefined}>
                  さがす
                </Link>
                <Link to="/navi/shortlist" aria-current={tab === 'shortlist' ? 'page' : undefined}>
                  候補 <span className="count">{shortlist.length}</span>
                </Link>
              </nav>
            )}
            <Link className="btn btn--quiet p-head__end" to="/navi/about">
              このAIについて
            </Link>
          </div>
        </header>
        {showWait && <WaitLine />}
        {children}
        {toastView}
      </div>
    )
  }

  return (
    <div className={showWait ? 'm-shell m-shell--waiting' : 'm-shell'}>
      {band}
      <header className="m-head">
        <div>
          <p className="brand">コースナビ</p>
          {deptName}
        </div>
        <Link className="btn btn--quiet" to="/navi/about">
          このAIについて
        </Link>
      </header>
      {children}
      {showWait && (
        <div className="m-wait">
          <WaitLine />
        </div>
      )}
      {!minimal && (
        <nav className="m-nav" aria-label="行き先">
          <Link to={searchHref} aria-current={place === 'search' ? 'page' : undefined}>
            さがす
          </Link>
          <Link to="/navi/shortlist" aria-current={place === 'shortlist' ? 'page' : undefined}>
            候補 <span className="count">{shortlist.length}</span>
          </Link>
        </nav>
      )}
      {toastView}
    </div>
  )
}
