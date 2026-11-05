import { Fragment, useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { interestGroups } from '../../navi/graph'
import { useKeywordQuery } from '../../navi/keyword'
import { useResearchLog } from '../../navi/research'
import { TIMETABLE_HREF, useNavi } from '../../navi/state'
import type { Origin } from '../../navi/state'
import { isRequired, placedInTerm, termLabel } from '../../navi/timetable'
import type { Interest } from '../../navi/types'
import { useFlags } from '../../navi/variant'
import { defaultList, listInterest, rootEntry, rowView } from '../../navi/views'
import type { ListContext } from '../../navi/views'
import AskResults from './AskResults'
import CourseRow from './CourseRow'
import Icon from './Icon'
import InterestChips from './InterestChips'
import KeywordResults from './KeywordResults'
import SearchField from './SearchField'

interface SearchListProps {
  dirId: string
  /** PC の左の段（W11） */
  pc: boolean
  /** PC の中央に出している科目 */
  currentCode?: string
}

/**
 * さがす（W1 おすすめ・W2 興味関心・W5 自分の言葉で探した結果）の一覧。スマホは画面の本体、PC は左の段。
 * 見出しと説明文は置かない。自分の言葉で探す欄、チップ、状況の1行、科目の行、「ほかに N 科目」だけ（E1 0章・4章、入口の案 a）。
 * 欄にカーソルがあるか、送っていない文が入っているあいだは、興味関心のチップを隠す（オーナーの指示 2026-11-04）。
 * 変種の旗（ab-variants.md 2 章）で出すものを変え、画面の差は旗の差だけにする（計画 4.1）:
 * - search: kw なら上の欄はキーワード検索（結果は KeywordResults）。off なら AI だけの欄（assistant=off なら欄を出さない）
 * - graph: off なら興味関心のチップと、興味関心からの一覧を出さない
 * - recommend: off なら「おすすめ」を出さず、最初の一覧は全科目（キーワード検索の空の語）
 * - assistant: on のときだけ［AIに聞く］と AI の結果
 */
export default function SearchList({ dirId, pc, currentCode }: SearchListProps) {
  const { dept, shortlist, focusTerm, assumedTerm, ask, askDraft, askDraftUnsent } = useNavi()
  const flags = useFlags()
  const [keyword, setKeyword] = useKeywordQuery()
  const navigate = useNavigate()
  const [askFocused, setAskFocused] = useState(false)
  /** 欄の文を、AI にもキーワード検索にも送っていないか（キーワードで探した後の欄の文は、送った文に数える） */
  const draftUnsent = askDraftUnsent && askDraft.trim() !== keyword
  /** 注意と［探す］を出し、チップを隠すあいだ。送っていない文は共有の状態から決まるので、詳細から戻って作り直されても隠れたまま */
  const askOpen = askFocused || draftUnsent
  /** 一度隠したチップは、戻すときに開閉の中身と同じフェードで出す（最初から出ているときは動かさない） */
  const [chipsWereHidden, setChipsWereHidden] = useState(draftUnsent)
  const ctx: ListContext = { dept, shortlist, focusTerm, assumedTerm, flags }
  const interest = listInterest(ctx, dirId)
  const required = placedInTerm(dept, shortlist, focusTerm).filter(isRequired)
  const showField = flags.search !== 'off' || flags.assistant === 'on'
  const searching = flags.search !== 'off' && keyword !== ''
  /** キーワード検索の結果を出しているあいだは、どのチップも選ばない */
  const selectedChip = searching ? '' : interest === undefined ? 'default' : interest.id

  const onAskFocusChange = (focused: boolean) => {
    setAskFocused(focused)
    if (focused) setChipsWereHidden(true)
  }
  const onSent = (localId: string) => navigate(`/navi/ask/${encodeURIComponent(localId)}`)

  let body: ReactNode
  if (searching) body = <KeywordResults ctx={ctx} query={keyword} currentCode={currentCode} />
  else if (interest !== undefined) body = <InterestRows ctx={ctx} interest={interest} currentCode={currentCode} />
  else if (flags.recommend !== 'off') body = <DefaultRows ctx={ctx} currentCode={currentCode} />
  else body = <KeywordResults ctx={ctx} query="" currentCode={currentCode} />

  return (
    <>
      {!pc && <h1 className="vh">さがす</h1>}
      {showField && <SearchField open={askOpen} onFocusChange={onAskFocusChange} onSearch={setKeyword} onSent={onSent} />}
      {flags.graph === 'on' && !askOpen && <InterestChips selected={selectedChip} reveal={chipsWereHidden} />}
      {required.length > 0 && (
        <Link className="status" to={TIMETABLE_HREF}>
          {termLabel(focusTerm)}の必修 {required.length}科目は、時間割に入れてあります
          <Icon name="next" small />
        </Link>
      )}
      {flags.assistant === 'on' && ask !== null && <AskResults session={ask} currentCode={currentCode} />}
      {body}
    </>
  )
}

interface DefaultRowsProps {
  ctx: ListContext
  currentCode?: string
}

function splitCodes(codes: string): string[] {
  return codes === '' ? [] : codes.split(',')
}

/** おすすめ（W1）。3科目と「ほかに N 科目」。並びの説明は開いた先に1文で書く（E1 2章） */
function DefaultRows({ ctx, currentCode }: DefaultRowsProps) {
  const { log } = useResearchLog()
  const [open, setOpen] = useState(false)
  const moreId = useId()
  const list = defaultList(ctx)
  const origin: Origin = { kind: 'default' }
  const root = rootEntry(ctx.dept, origin)
  const ranked = [...list.rows, ...list.more].map((p) => p.course.code)
  const row = (p: (typeof list.rows)[number]) => {
    const r = rowView(ctx, p.course, origin, p.why, p.source)
    return (
      <CourseRow
        key={r.code}
        row={r}
        current={r.code === currentCode}
        linkState={{ trail: [root, { label: r.name, href: r.href }], tab: 'search' }}
        onOpen={() => log('result_click', { syllabus_id: r.code, rank: ranked.indexOf(r.code) + 1, list: 'recommend' })}
      />
    )
  }

  // 出したおすすめを、並びが変わったときに1回記録する（開発の StrictMode で効果が2回走っても重ねない）
  const recommend = ctx.flags?.recommend ?? 'reach'
  const term = termLabel(ctx.assumedTerm)
  const shownCodes = list.rows.map((p) => p.course.code).join(',')
  const moreCodes = list.more.map((p) => p.course.code).join(',')
  const tieBreak = list.tieBreak
  const loggedRef = useRef<string | null>(null)
  useEffect(() => {
    const signature = `${recommend}|${term}|${shownCodes}|${moreCodes}`
    if (loggedRef.current === signature) return
    loggedRef.current = signature
    log('recommend_shown', {
      recommend,
      term,
      items: splitCodes(shownCodes),
      more: splitCodes(moreCodes),
      tie_break: tieBreak,
      seed: null,
    })
  }, [recommend, term, shownCodes, moreCodes, tieBreak, log])

  if (list.rows.length === 0) {
    return <p className="foot">この学期には、おすすめできる科目がありません。上の興味関心から選んでください。</p>
  }
  return (
    <>
      <ul className="list">{list.rows.map(row)}</ul>
      {list.more.length === 0 ? (
        <p className="foot">{list.foot}</p>
      ) : (
        <div className={open ? 'more is-open' : 'more'}>
          <button className="more-btn" type="button" aria-expanded={open} aria-controls={moreId} onClick={() => setOpen((o) => !o)}>
            <span>{open ? '閉じる' : `ほかに${list.more.length}科目`}</span>
            <Icon name="down" />
          </button>
          <div className="acc-body" id={moreId}>
            {open && (
              <>
                <ul className="list">{list.more.map(row)}</ul>
                <p className="foot">{list.foot}</p>
              </>
            )}
          </div>
        </div>
      )}
    </>
  )
}

interface InterestRowsProps {
  ctx: ListContext
  interest: Interest
  currentCode?: string
}

/** 興味関心を選んだあと（W2）。取る順に、学年ごとに並べる。並びの説明は一覧の最後に1文（E1 7章） */
function InterestRows({ ctx, interest, currentCode }: InterestRowsProps) {
  const { log } = useResearchLog()
  const origin: Origin = { kind: 'dir', dirId: interest.id }
  const root = rootEntry(ctx.dept, origin)
  const groups = interestGroups(ctx.dept, interest)
  const order = groups.flatMap((g) => g.rows.map((p) => p.course.code))
  return (
    <>
      {groups.map((g) => (
        <Fragment key={g.year}>
          <h2 className="group-label">{g.year}年</h2>
          <ul className="list">
            {g.rows.map((p) => {
              const r = rowView(ctx, p.course, origin, p.why, p.source)
              return (
                <CourseRow
                  key={r.code}
                  row={r}
                  current={r.code === currentCode}
                  linkState={{ trail: [root, { label: r.name, href: r.href }], tab: 'search' }}
                  onOpen={() =>
                    log('result_click', { syllabus_id: r.code, rank: order.indexOf(r.code) + 1, list: 'interest', interest_id: interest.id })
                  }
                />
              )
            })}
          </ul>
        </Fragment>
      ))}
      <p className="foot">取る順に、1年から並べています（履修系統図）。系統図の線はまとまりどうしを結ぶもので、直接の前提とは限りません。</p>
    </>
  )
}
