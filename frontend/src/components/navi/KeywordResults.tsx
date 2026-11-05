import { useEffect, useState } from 'react'
import type { CourseSummary } from '../../navi/apiTypes'
import { findCourse } from '../../navi/graph'
import {
  PAGE_SIZE,
  rememberCourseNames,
  searchCourses,
  searchErrorText,
  setKeywordQuery,
  takeKeywordSubmission,
  useKeywordSubmissions,
} from '../../navi/keyword'
import { useResearchLog } from '../../navi/research'
import { useNavi } from '../../navi/state'
import type { Origin } from '../../navi/state'
import { rootEntry, rowView, summaryRowView, WIDE_SPACE } from '../../navi/views'
import type { ListContext } from '../../navi/views'
import CourseRow from './CourseRow'
import Icon from './Icon'

interface KeywordResultsProps {
  ctx: ListContext
  /** 探す語。空なら全科目（おすすめを出さない変種の最初の一覧。ab-variants.md F03 の off） */
  query: string
  /** PC の中央に出している科目 */
  currentCode?: string
}

/** search_query に残す上位の件数 */
const LOGGED_TOP = 10
/** 詳細へ進んだとき、来た一覧の名前（パンくず・スマホの戻る）は「さがす」にする */
const ORIGIN: Origin = { kind: 'none' }

type Load =
  | { status: 'loading' }
  | { status: 'error'; text: string }
  | { status: 'done'; total: number; items: CourseSummary[]; more: boolean }

/**
 * キーワード検索の結果（D4 GET /api/courses。旗 search=kw）。語を送ったときと、おすすめを出さない変種の最初の一覧。
 * 行は一覧と同じ形で、「なぜ」は付けない。並びは D4 の決まった並び（科目名が全部の語を含むものを先に、次に科目コードの順）。
 * 20 件ずつ読み、［さらに表示］で続きを足す。
 */
export default function KeywordResults({ ctx, query, currentCode }: KeywordResultsProps) {
  const { dept } = useNavi()
  const { log } = useResearchLog()
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  /** 足していく続きの読み込み（null は最初のページ） */
  const [moreOffset, setMoreOffset] = useState<number | null>(null)
  const [retry, setRetry] = useState(0)
  const submissions = useKeywordSubmissions()

  // 語が変わったか、同じ語をもう一度送ったら、最初のページから
  const [shownFor, setShownFor] = useState({ query, deptId: dept.id, submissions })
  if (shownFor.query !== query || shownFor.deptId !== dept.id || shownFor.submissions !== submissions) {
    setShownFor({ query, deptId: dept.id, submissions })
    setLoad({ status: 'loading' })
    setMoreOffset(null)
  }

  useEffect(() => {
    const control = new AbortController()
    const offset = moreOffset ?? 0
    searchCourses(dept, { q: query, limit: PAGE_SIZE, offset }, control.signal)
      .then((page) => {
        // 見本のデータ源は signal を見ないので、捨てた読み込みの結果はここで捨てる
        if (control.signal.aborted) return
        rememberCourseNames(page.items)
        setLoad((cur) => {
          const before = offset > 0 && cur.status === 'done' ? cur.items : []
          const items = [...before, ...page.items]
          return { status: 'done', total: page.total, items, more: items.length < page.total }
        })
        log('search_query', {
          q: query,
          filters: {},
          total: page.total,
          top: page.items.slice(0, LOGGED_TOP).map((i) => i.syllabus_id),
          page: Math.floor(offset / PAGE_SIZE) + 1,
          offset,
          trigger: offset > 0 ? 'more' : takeKeywordSubmission() ? 'user' : query === '' ? 'initial' : 'redisplay',
        })
      })
      .catch((err: unknown) => {
        if (control.signal.aborted) return
        console.error('キーワード検索の結果を受け取れませんでした', err)
        log('client_error', { kind: 'search', message: String(err) })
        setLoad({ status: 'error', text: searchErrorText(err) })
      })
    return () => control.abort()
  }, [dept, query, moreOffset, retry, submissions, log])

  const heading = query === '' ? '科目の一覧' : `「${query}」で探した結果`

  if (load.status === 'error') {
    return (
      <section className="kw" aria-label={heading}>
        <div className="msg">
          <p className="msg-line" role="status">
            <span className="ic-wrap">
              <Icon name="warn" small />
            </span>
            <span>{load.text}</span>
          </p>
        </div>
        <div className="ask-acts">
          <button className="text-btn" type="button" onClick={() => setRetry((n) => n + 1)}>
            もう一度探す
          </button>
          {query !== '' && (
            <button className="text-btn" type="button" onClick={() => setKeywordQuery('')}>
              閉じる
            </button>
          )}
        </div>
      </section>
    )
  }

  if (load.status === 'loading' && moreOffset === null) {
    return (
      <section className="kw" aria-label={heading} aria-busy="true">
        <p className="foot" role="status">
          探しています。
        </p>
      </section>
    )
  }

  const items = load.status === 'done' ? load.items : []
  const total = load.status === 'done' ? load.total : items.length
  /** ［さらに表示］を押して、続きがまだ届いていない */
  const pendingMore = moreOffset !== null && items.length <= moreOffset
  const root = rootEntry(dept, ORIGIN)

  return (
    <section className="kw" aria-label={heading}>
      <h2 className="group-label">
        {heading}{WIDE_SPACE}{total}件
      </h2>
      {items.length === 0 ? (
        <p className="foot">{query === '' ? '科目がありません。' : `「${query}」を含む科目は見つかりませんでした。言葉を変えてください。`}</p>
      ) : (
        <ul className="list">
          {items.map((item, i) => {
            const course = findCourse(dept, item.syllabus_id)
            const r = course === undefined ? summaryRowView(item, ORIGIN, ctx.focusTerm) : rowView(ctx, course, ORIGIN, null, null)
            return (
              <CourseRow
                key={r.code}
                row={r}
                current={r.code === currentCode}
                linkState={{ trail: [root, { label: r.name, href: r.href }], tab: 'search' }}
                onOpen={() => log('result_click', { syllabus_id: r.code, rank: i + 1, list: 'search', q: query })}
              />
            )
          })}
        </ul>
      )}
      {load.status === 'done' && load.more && !pendingMore && (
        <button className="more-btn" type="button" onClick={() => setMoreOffset(items.length)}>
          <span>さらに表示（残り{load.total - items.length}件）</span>
          <Icon name="down" />
        </button>
      )}
      {pendingMore && (
        <p className="foot" role="status">
          続きを読んでいます。
        </p>
      )}
      {items.length > 0 && (
        <p className="foot">{query === '' ? '科目コードの順に並べています。' : '科目名に言葉を含む科目を先に、あとは科目コードの順に並べています。'}</p>
      )}
      {query !== '' && (
        <div className="ask-acts">
          <button className="text-btn" type="button" onClick={() => setKeywordQuery('')}>
            この結果を閉じる
          </button>
        </div>
      )}
    </section>
  )
}
