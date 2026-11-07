import { useCallback, useId, useState } from 'react'
import '../../navi/term.css'
import type { CourseSummary } from '../../navi/apiTypes'
import { useNaviData } from '../../navi/dataSource'
import type { TakenCourse } from '../../navi/history'
import { useNavi } from '../../navi/state'
import type { TermKey } from '../../navi/timetable'
import { useLoadable } from '../../navi/useLoadable'
import type { Loadable } from '../../navi/useLoadable'
import Icon from './Icon'
import TakenRow from './TakenRow'

/** D4 の1回の上限（backend の limit の最大）と、1学期ぶんを読む回数の上限 */
const PAGE_SIZE = 100
const MAX_PAGES = 10
/** しぼる前に出す行の数 */
const ROWS_SHOWN = 8
/** その学期に無い名前を全学期から引くのは、この字数から */
const GLOBAL_MIN_CHARS = 2
const GLOBAL_LIMIT = 50
/** 英数字で始まる科目名（英語で開く科目。並びの後ろに回す） */
const LATIN_HEAD = /^[A-Za-z0-9]/

/** 科目名ごとの1行（同じ名前の別クラスはまとめる。クラスは問わない） */
interface OfferRow {
  name: string
  /** 記録に使う科目（最初のクラス） */
  code: string
  credits: number | null
  classes: number
  /** クラスが1つのときだけ曜限（クラスが分からない科目は出さない） */
  slots: string[] | null
}

function groupByName(items: readonly CourseSummary[]): OfferRow[] {
  const rows = new Map<string, OfferRow>()
  for (const c of items) {
    const row = rows.get(c.name)
    if (row === undefined) {
      rows.set(c.name, { name: c.name, code: c.syllabus_id, credits: c.credits, classes: 1, slots: c.slots })
      continue
    }
    rows.set(c.name, { ...row, classes: row.classes + 1, slots: null })
  }
  // 日本語の名前を先に（英語で開く科目は後ろ）、それぞれ五十音・アルファベットの順
  return [...rows.values()].sort((a, b) => Number(LATIN_HEAD.test(a.name)) - Number(LATIN_HEAD.test(b.name)) || a.name.localeCompare(b.name, 'ja'))
}

/** その学期の配当の科目（D4 の year・term を全部のページ）。term が null なら読まない */
function useTermOffer(deptId: string, term: TermKey | null): Loadable<OfferRow[]> | null {
  const { source } = useNaviData()
  const year = term?.year ?? 0
  const half = term?.half ?? '春'
  const load = useCallback(
    async (signal: AbortSignal): Promise<OfferRow[]> => {
      const items: CourseSummary[] = []
      for (let page = 0; page < MAX_PAGES; page++) {
        const got = await source.searchCourses({ dept: deptId, year, term: half, limit: PAGE_SIZE, offset: page * PAGE_SIZE }, signal)
        items.push(...got.items)
        if (items.length >= got.total || got.items.length === 0) break
      }
      return groupByName(items)
    },
    [deptId, half, source, year],
  )
  return useLoadable(term === null ? null : `${deptId}|${year}${half}`, load, 'その学期の科目')
}

/** 名前で全学期から引く（query が null なら引かない） */
function useNameSearch(deptId: string, query: string | null): Loadable<OfferRow[]> | null {
  const { source } = useNaviData()
  const q = query ?? ''
  const load = useCallback(
    async (signal: AbortSignal): Promise<OfferRow[]> => groupByName((await source.searchCourses({ dept: deptId, q, limit: GLOBAL_LIMIT }, signal)).items),
    [deptId, q, source],
  )
  return useLoadable(query === null ? null : `${deptId}|q|${q}`, load, '科目の検索')
}

function toTaken(r: OfferRow): TakenCourse {
  return { syllabus_id: r.code, name: r.name, credits: r.credits, slots: r.slots }
}

interface AddOthersProps {
  term: TermKey
  /** もう並んでいる・記録にある科目の名前（一覧に出さない） */
  exclude: ReadonlySet<string>
  onAdd: (courses: TakenCourse[]) => void
}

/**
 * ［ほかの科目を足す］（審査の J1 M-1・J2 M-1 の直し。T-b の「ほかの科目を足す欄」を学期の配当で絞った形）。
 * 開くと、その学期の配当（D4 の year・term）の科目を名前ごとに1行で並べる。チェックで複数選び、
 * ［選んだN科目を入れる］の1回で入れる。上の欄で名前をしぼれ、その学期に無い名前は全学期から引く
 */
export default function AddOthers({ term, exclude, onAdd }: AddOthersProps) {
  const { dept, announce } = useNavi()
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [picked, setPicked] = useState<ReadonlyMap<string, TakenCourse>>(() => new Map())
  const bodyId = useId()

  const offer = useTermOffer(dept.id, open ? term : null)

  const query = filter.trim()
  const rows = offer?.status === 'ready' ? offer.value.filter((r) => !exclude.has(r.name)) : []
  const hits = query === '' ? rows : rows.filter((r) => r.name.includes(query))
  const needGlobal = open && offer?.status === 'ready' && query.length >= GLOBAL_MIN_CHARS && hits.length === 0
  const global = useNameSearch(dept.id, needGlobal ? query : null)
  const globalRows = global?.status === 'ready' ? global.value.filter((r) => !exclude.has(r.name)) : []
  const list = needGlobal ? globalRows : hits
  const shown = query !== '' || showAll ? list : list.slice(0, ROWS_SHOWN)
  const rest = list.length - shown.length

  const toggle = (r: OfferRow) =>
    setPicked((prev) => {
      const next = new Map(prev)
      if (next.has(r.name)) next.delete(r.name)
      else next.set(r.name, toTaken(r))
      return next
    })
  const add = () => {
    const courses = [...picked.values()].filter((c) => !exclude.has(c.name))
    if (courses.length === 0) return
    onAdd(courses)
    setPicked(new Map())
    announce(`${courses.length}科目を入れました。`)
  }

  return (
    <div className="ao">
      <button className="pl-more" type="button" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen((o) => !o)}>
        <span>ほかの科目を足す</span>
        <Icon name="down" small />
      </button>
      <div className="ao-body" id={bodyId} hidden={!open}>
        {open && (
          <>
            <label className="field">
              <Icon name="search" />
              <span className="vh">科目名でしぼる</span>
              <input type="text" value={filter} placeholder="科目名でしぼる" autoComplete="off" onChange={(e) => setFilter(e.target.value)} />
            </label>
            {offer?.status === 'loading' && <p className="ao-msg">読み込んでいます</p>}
            {offer?.status === 'failed' && <p className="ao-msg">科目を読み込めませんでした。</p>}
            {needGlobal && global?.status === 'loading' && <p className="ao-msg">ほかの学期から探しています</p>}
            {needGlobal && global?.status === 'ready' && <p className="ao-msg">この学期に無いので、ほかの学期の科目を出しています</p>}
            {offer?.status === 'ready' && list.length === 0 && !(needGlobal && global?.status === 'loading') && (
              <p className="ao-msg">{query === '' ? 'この学期に足せる科目はほかにありません。' : '見つかりませんでした。'}</p>
            )}
            {shown.length > 0 && (
              <ul className="hc-list">
                {shown.map((r) => (
                  <TakenRow
                    key={r.name}
                    course={toTaken(r)}
                    checked={picked.has(r.name)}
                    onToggle={() => toggle(r)}
                    note={r.classes > 1 ? `${r.classes}クラス` : undefined}
                  />
                ))}
              </ul>
            )}
            {rest > 0 && (
              <button className="pl-more" type="button" onClick={() => setShowAll(true)}>
                <span>ほかに{rest}科目</span>
                <Icon name="down" small />
              </button>
            )}
            <div className="ao-acts">
              <button className="pl-line" type="button" disabled={picked.size === 0} onClick={add}>
                {picked.size === 0 ? '選んだ科目を入れる' : `選んだ${picked.size}科目を入れる`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
