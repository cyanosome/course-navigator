import { Fragment, useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { findCourse, findFrame, gapNotices, hasEdge, sortCourses, termLabel } from '../../navi/graph'
import { courseHref, groupHref, useNavi } from '../../navi/state'
import type { Course, Department } from '../../navi/types'
import { rootState } from '../../navi/views'

interface ShortlistContentProps {
  variant: 'mobile' | 'pc'
  /** PC の右ペインに出している候補 */
  currentCode?: string
}

function frameName(dept: Department, c: Course): string {
  return findFrame(dept, c.frameId)?.name ?? ''
}

/** 候補どうしが系統図の線でつながるときの1行（UX 仕様 C14） */
function lineText(dept: Department, a: Course, b: Course): string | null {
  if (!hasEdge(dept, a.frameId, b.frameId)) return null
  return `系統図の線あり（${a.year}年「${frameName(dept, a)}」→ ${b.year}年「${frameName(dept, b)}」）`
}

function copyText(dept: Department, courses: Course[]): string {
  const lines = courses.map((c) => `${termLabel(c)} ${c.name}（${c.code}） 枠: ${frameName(dept, c)}`)
  return [`候補（コースナビ・${dept.name}）`, ...lines, '履修登録はされていません。'].join('\n')
}

/** 候補（W4。PC は W12 の左ペイン）。学期と系統図の線で並べる */
export default function ShortlistContent({ variant, currentCode }: ShortlistContentProps) {
  const { dept, shortlist, assumedYear, removeKeep } = useNavi()
  const [copyState, setCopyState] = useState<'idle' | 'done' | 'failed'>('idle')
  const headId = useId()
  const courses = sortCourses(
    dept,
    shortlist.map((code) => findCourse(dept, code)).filter((c): c is Course => c !== undefined),
  )
  const now = courses.filter((c) => c.year <= assumedYear)
  const later = courses.filter((c) => c.year > assumedYear)
  const gaps = gapNotices(dept, later, assumedYear)
  const pc = variant === 'pc'

  const copy = () => {
    navigator.clipboard
      .writeText(copyText(dept, courses))
      .then(() => setCopyState('done'))
      .catch((err: unknown) => {
        console.error('候補をコピーできませんでした', err)
        setCopyState('failed')
      })
  }

  const row = (c: Course) => {
    const href = courseHref(c.code, { kind: 'shortlist' })
    return (
      <div key={c.code} className="sl-row" aria-current={pc && c.code === currentCode ? 'true' : undefined}>
        <p className="sl-row__term">{termLabel(c)}</p>
        <h3 className="sl-row__name">{c.name}</h3>
        <p className="note">枠: {frameName(dept, c)}</p>
        <div className="sl-row__acts">
          <Link className="btn btn--ink" to={href} state={rootState(c.name, href, 'shortlist')} aria-label={`${c.name}の理由と出典`}>
            理由と出典
          </Link>
          <button className="btn" type="button" onClick={() => removeKeep(c.code)} aria-label={`${c.name}を外す`}>
            外す
          </button>
        </div>
      </div>
    )
  }

  /** 並びの1つ前の候補と線でつながるときは、行の間に書く */
  const rowsWithLines = (list: Course[]) =>
    list.map((c) => {
      const i = courses.indexOf(c)
      const prev = i > 0 ? courses[i - 1] : undefined
      const line = prev === undefined ? null : lineText(dept, prev, c)
      return (
        <Fragment key={c.code}>
          {line !== null && <p className="sl-line">{line}</p>}
          {row(c)}
        </Fragment>
      )
    })

  return (
    <>
      <div className="sl-head">
        <h1 className="h-sec" id={headId}>
          候補 {courses.length}件
        </h1>
        <p className="note">学期と系統図の線で並べています。</p>
        <p className="note">履修登録はされません。</p>
      </div>

      {courses.length === 0 && (
        <p className="body-s sl-empty">候補はまだありません。提案の[候補に入れる]で残せます。</p>
      )}

      {now.length > 0 && (
        <section className="sl-group" aria-label="想定の学年の候補">
          <h2 className="h-sec">{assumedYear}年（想定の学年）の候補</h2>
          <div className="sl-list">{rowsWithLines(now)}</div>
        </section>
      )}

      {later.length > 0 && (
        <section className="sl-group" aria-label="先の学年の候補">
          <h2 className="h-sec">先の学年の候補</h2>
          <p className="note">（見通しとして残した科目。いま登録するものではありません）</p>
          <div className="sl-list">{rowsWithLines(later)}</div>
          {gaps.map((g) => (
            <div key={`${g.later.id}-${g.missing.id}`} className="sl-gap">
              <p>
                {g.later.year}年「{g.later.name}」の前には、{g.missing.year}年「{g.missing.name}」の枠もあります。この枠からは候補がありません。
              </p>
              <Link className="all" to={groupHref(g.missing.id, { kind: 'shortlist' })}>
                この枠の科目を見る
              </Link>
            </div>
          ))}
        </section>
      )}

      {courses.length > 0 && (
        <section className="sl-group" aria-label="学期が分からない科目">
          <h2 className="h-sec">学期が分からない科目</h2>
          <p className="body-s">（なし）</p>
        </section>
      )}

      <div className="sl-copy">
        {courses.length > 0 && (
          <button className="btn" type="button" onClick={copy}>
            候補を文字でコピー
          </button>
        )}
        <p className="note" role="status">
          {copyState === 'done' && 'コピーしました。'}
          {copyState === 'failed' && 'コピーできませんでした。この画面の科目名を書き写してください。'}
        </p>
        <p className="note">この端末のこのブラウザにだけ保存されます。</p>
      </div>
    </>
  )
}
