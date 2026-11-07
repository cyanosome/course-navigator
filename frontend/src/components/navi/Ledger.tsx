import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import '../../navi/plan.css'
import '../../navi/term.css'
import { historyHref } from '../../navi/history'
import { checkDetail, checkShortLabel, checkValue, CHECK_STATUS_WORD, ledgerGrid } from '../../navi/ledger'
import type { ClassMove, LedgerGrid } from '../../navi/ledger'
import { useResearchLog } from '../../navi/research'
import { courseHref, DIAGNOSE_HREF, useNavi } from '../../navi/state'
import type { Checkpoint, CheckResult, CourseStatus, StatusCourse } from '../../navi/status'
import { inTerm, resolveCourse, sameTerm, termLabel } from '../../navi/timetable'
import type { TermKey } from '../../navi/timetable'
import { useClassMoves } from '../../navi/useClassMoves'
import { useDiagnose } from '../../navi/useDiagnose'
import { TERM_WORD } from '../../navi/useLedger'
import type { LedgerView, RepeatCourse } from '../../navi/useLedger'
import { useCheckpoints } from '../../navi/useStatus'
import { WIDE_SPACE } from '../../navi/views'
import Icon from './Icon'
import { CheckpointForm } from './StatusPanel'
import { TermTable } from './TermTable'

/*
 * 診断の変種の「確かめる場所」（デザインのコンペの U-a）。履修状況（学期・単位・時間割）とチェックの一覧。
 * PC の半分の幅（640px 以上）は右の列に、スマホは上に貼りつく帯（StatusBand）とプランの下の一覧に出す。
 * どの画面でも、どの変種でも同じものを出す。AI の案を入れた場合の値はここには出さない（AI の欄の中だけ）。
 */

/** スマホの帯で学期名のすぐ後ろに置く状態の語（短く） */
const BAND_WORD: Record<keyof typeof TERM_WORD, string> = {
  past: '取った',
  unrecorded: '未記入',
  current: '今',
  planned: '予定',
  none: 'プランなし',
}

interface CellView {
  className: string
  text: string
  label: string
}

/** 詳細で見ている科目（プランに無ければ、空いたマスに入る先を破線で出す） */
interface FocusCourse {
  code: string
  name: string
  short: string
  slots: string[]
  inPlan: boolean
}

function useFocusCourse(code: string | null, term: TermKey, status: CourseStatus): FocusCourse | null {
  const { dept, placement } = useNavi()
  if (code === null) return null
  const course = resolveCourse(dept, code, placement)
  if (course === undefined) return null
  const inPlan = status.courses.some((c) => c.code === code)
  if (!inPlan && !inTerm(course, term)) return null
  return { code, name: course.name, short: course.short ?? course.name, slots: course.slots, inPlan }
}

function useShortName(): (c: StatusCourse) => string {
  const { dept, placement } = useNavi()
  return (c) => resolveCourse(dept, c.code, placement)?.short ?? c.name
}

function cellOf(grid: LedgerGrid, slot: string, focus: FocusCourse | null, shortOf: (c: StatusCourse) => string): CellView {
  const here = grid.cells.get(slot) ?? []
  const first = here[0]
  const cur = focus !== null && focus.inPlan && here.some((c) => c.code === focus.code) ? ' is-cur' : ''
  if (here.length > 1) {
    return { className: `lg-cell is-clash${cur}`, text: '重なり', label: `${slot}、${here.map((c) => c.name).join('と')}が重なっています` }
  }
  if (first !== undefined) return { className: `lg-cell is-in${cur}`, text: shortOf(first), label: `${slot}、${first.name}` }
  if (focus !== null && !focus.inPlan && focus.slots.includes(slot)) {
    return { className: 'lg-cell is-preview', text: focus.short, label: `${slot}、${focus.name}を入れるとここに入ります` }
  }
  return { className: 'lg-cell', text: '', label: `${slot}、空き` }
}

interface GridTableProps {
  view: LedgerView
  grid: LedgerGrid
  focus: FocusCourse | null
}

/** 時間割の表（曜日×時限）。マスには略称か「重なり」だけを書き、科目の名前は読み上げで言う */
function GridTable({ view, grid, focus }: GridTableProps) {
  const shortOf = useShortName()
  return (
    <table className={grid.days.length > 5 ? 'lg-tt is-6' : 'lg-tt'}>
      <caption className="vh">{termLabel(view.term)}の時間割</caption>
      <thead>
        <tr>
          <th scope="col">
            <span className="vh">時限</span>
          </th>
          {grid.days.map((d) => (
            <th key={d} scope="col">
              {d}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {grid.periods.map((p) => (
          <tr key={p}>
            <th scope="row">{p}</th>
            {grid.days.map((d) => {
              const cell = cellOf(grid, `${d}${p}`, focus, shortOf)
              return (
                <td key={d}>
                  <span className={cell.className} role="img" aria-label={cell.label}>
                    <span aria-hidden="true">{cell.text}</span>
                  </span>
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** 表に置けない科目（曜限なし）と、単位の分からない科目の数 */
function GridNotes({ view, grid }: { view: LedgerView; grid: LedgerGrid }) {
  const unknown = view.here.status.unknownCredits
  if (grid.offGrid.length === 0 && unknown === 0) return null
  return (
    <div className="lg-notes">
      {grid.offGrid.length > 0 && (
        <p>
          曜限なし{WIDE_SPACE}{grid.offGrid.map((c) => c.name).join('、')}
        </p>
      )}
      {unknown > 0 && <p>単位の分からない科目 {unknown}</p>}
    </div>
  )
}

interface TermToggle {
  open: boolean
  controls: string
  onToggle: () => void
}

/**
 * 学期の切り替え（プランの学期の中で前後へ。取った科目を記録しているときは1年春〜4年秋）。
 * toggle があれば、学期名を押すと学期の表が開く（スマホの帯）。学期名のすぐ後ろに状態の語を置く
 */
function TermNav({ view, toggle }: { view: LedgerView; toggle?: TermToggle }) {
  const { setFocusTerm } = useNavi()
  const word = view.history === null ? null : BAND_WORD[view.history.viewKind]
  const i = view.terms.findIndex((t) => sameTerm(t, view.term))
  const prev = i > 0 ? view.terms[i - 1] : undefined
  const next = i >= 0 ? view.terms[i + 1] : undefined
  return (
    <div className="lg-term">
      <button
        className="icon-btn"
        type="button"
        aria-label={prev === undefined ? '前の学期' : `前の学期（${termLabel(prev)}）`}
        disabled={prev === undefined}
        onClick={() => prev !== undefined && setFocusTerm(prev)}
      >
        <Icon name="back" />
      </button>
      {toggle === undefined ? (
        <span className="lg-term-name" aria-live="polite">
          {termLabel(view.term)}
        </span>
      ) : (
        <button className="lg-term-btn" type="button" aria-expanded={toggle.open} aria-controls={toggle.controls} onClick={toggle.onToggle}>
          <span aria-live="polite">
            {termLabel(view.term)}
            {word !== null && <span className="lg-word">{word}</span>}
          </span>
          <Icon name="down" />
        </button>
      )}
      <button
        className="icon-btn"
        type="button"
        aria-label={next === undefined ? '次の学期' : `次の学期（${termLabel(next)}）`}
        disabled={next === undefined}
        onClick={() => next !== undefined && setFocusTerm(next)}
      >
        <Icon name="next" />
      </button>
    </div>
  )
}

function Units({ view }: { view: LedgerView }) {
  return (
    <p className="lg-units">
      <span className="num">{view.here.status.terms[0]?.credits ?? 0}</span>
      <span className="u">単位</span>
    </p>
  )
}

interface LedgerStatusProps {
  view: LedgerView
  /** 詳細で見ている科目（時間割のマスに輪か破線を付ける） */
  focusCode: string | null
}

/** 右の列の履修状況（PC の半分の幅から） */
export function LedgerStatus({ view, focusCode }: LedgerStatusProps) {
  const { setFocusTerm } = useNavi()
  const grid = ledgerGrid(view.here.status, view.checkpoints)
  const focus = useFocusCourse(focusCode, view.term, view.status)
  const history = view.history
  if (history !== null) {
    // 取った科目を記録しているとき: 学期の表（切り替えと履歴の目次）と、見ている学期の名前・状態の語・単位。
    // 今の学期より前の学期は時間割を出さない（クラスの分からない科目がある）
    return (
      <section className="lg-status" data-role="status" aria-label="履修状況">
        <TermTable
          cells={history.cells}
          view={view.term}
          onPick={setFocusTerm}
          takenCredits={history.takenCredits}
          unrecorded={history.unrecorded.length}
        />
        <div className="lg-now">
          <p>
            <span className="lg-now-name">{termLabel(view.term)}</span>
            <span className="lg-word">{TERM_WORD[history.viewKind]}</span>
          </p>
          {history.viewKind !== 'unrecorded' && <Units view={view} />}
        </div>
        {!history.past && (
          <>
            <GridTable view={view} grid={grid} focus={focus} />
            <GridNotes view={view} grid={grid} />
          </>
        )}
      </section>
    )
  }
  return (
    <section className="lg-status" data-role="status" aria-label="履修状況">
      <div className="lg-status-head">
        <TermNav view={view} />
        <Units view={view} />
      </div>
      <GridTable view={view} grid={grid} focus={focus} />
      <GridNotes view={view} grid={grid} />
    </section>
  )
}

interface StatusBandProps {
  view: LedgerView
  focusCode: string | null
  /** 帯の［要確認］を押したとき（チェックの一覧へ） */
  onChecks: () => void
  checksId: string
  checksOpen: boolean
}

/** スマホの上に貼りつく帯。学期・単位・要確認の数・小さな時間割（押すと表が広がる） */
export function StatusBand({ view, focusCode, onChecks, checksId, checksOpen }: StatusBandProps) {
  const { setFocusTerm } = useNavi()
  const [gridOpen, setGridOpen] = useState(false)
  const [termsOpen, setTermsOpen] = useState(false)
  const gridId = useId()
  const termsId = useId()
  const history = view.history
  /** 今の学期より前の学期は時間割を出さない */
  const showGrid = history === null || !history.past
  const grid = ledgerGrid(view.here.status, view.checkpoints)
  const focus = useFocusCourse(focusCode, view.term, view.status)
  const shortOf = useShortName()
  const sum: ReactNode =
    view.unmet > 0 ? (
      <>
        <Icon name="warn" small />
        要確認 {view.unmet}
      </>
    ) : view.others.length > 0 ? (
      <>
        <Icon name="warn" small />
        ほかの学期
      </>
    ) : (
      <>
        <Icon name="check" small />
        すべて満たす
      </>
    )
  return (
    <section
      className={`lg-band${gridOpen && showGrid ? ' is-open' : ''}${history !== null ? ' has-terms' : ''}`}
      data-role="status"
      aria-label="履修状況"
    >
      {history === null ? (
        <TermNav view={view} />
      ) : (
        <TermNav view={view} toggle={{ open: termsOpen, controls: termsId, onToggle: () => setTermsOpen((o) => !o) }} />
      )}
      <div className="lg-band-line">
        {history?.viewKind !== 'unrecorded' && <Units view={view} />}
        <button
          className={view.unmet > 0 || view.others.length > 0 ? 'lg-sum is-ng' : 'lg-sum'}
          type="button"
          aria-controls={checksId}
          aria-expanded={checksOpen}
          onClick={onChecks}
        >
          {sum}
        </button>
      </div>
      {showGrid && (
        <button
          className={grid.days.length > 5 ? 'lg-mini is-6' : 'lg-mini'}
          type="button"
          aria-controls={gridId}
          aria-expanded={gridOpen}
          aria-label={gridOpen ? '時間割を閉じる' : '時間割を広げる'}
          onClick={() => setGridOpen((o) => !o)}
        >
          {grid.periods.flatMap((p) =>
            grid.days.map((d) => {
              const cell = cellOf(grid, `${d}${p}`, focus, shortOf)
              return <i key={`${d}${p}`} className={cell.className.replace('lg-cell', 'lg-m')} />
            }),
          )}
        </button>
      )}
      {history !== null && (
        <div className="lg-band-terms" id={termsId} hidden={!termsOpen}>
          {termsOpen && (
            <TermTable
              cells={history.cells}
              view={view.term}
              onPick={(t) => {
                setFocusTerm(t)
                setTermsOpen(false)
              }}
              takenCredits={history.takenCredits}
              unrecorded={history.unrecorded.length}
            />
          )}
        </div>
      )}
      {showGrid && (
        <div className="lg-band-tt" id={gridId} hidden={!gridOpen}>
          {gridOpen && (
            <>
              <GridTable view={view} grid={grid} focus={focus} />
              <GridNotes view={view} grid={grid} />
            </>
          )}
        </div>
      )}
    </section>
  )
}

const MARK = { met: 'check', unmet: 'warn', unknown: 'dash' } as const

interface CheckRowProps {
  cp: Checkpoint
  r: CheckResult
  status: CourseStatus
  removing: boolean
  move: ClassMove | undefined
  /** 判定できない理由が未記入の学期のとき、取った科目を入れる画面へ（取った科目を記録しているときだけ） */
  fillHref?: string
}

/**
 * チェックの1行。押すと開き、理由と原因の科目（詳細へのリンク）を出す（開いたら status_open を記録する）。
 * 満たさない行には、原因の科目の名前と、見つかれば直し方（同じ名前の別のクラスへ移す）を添える
 */
function CheckRow({ cp, r, status, removing, move, fillHref }: CheckRowProps) {
  const { dept } = useNavi()
  const { remove } = useCheckpoints()
  const { log } = useResearchLog()
  const [open, setOpen] = useState(false)
  const bodyId = useId()
  const label = checkShortLabel(cp, dept)
  const detail = checkDetail(cp, r, status)
  const causes = r.codes.map((code) => ({ code, name: status.courses.find((c) => c.code === code)?.name ?? code }))
  const toggle = () => {
    if (!open) log('status_open', { how: 'row', checkpoint_id: cp.id, kind: cp.kind, status: r.status })
    setOpen((o) => !o)
  }
  return (
    <li className={`lg-chk is-${r.status}`}>
      <button className="lg-chk-btn" type="button" aria-expanded={open} aria-controls={bodyId} onClick={toggle}>
        <Icon name={MARK[r.status]} small />
        <span className="lg-chk-l">
          {label}
          <span className="vh">、{CHECK_STATUS_WORD[r.status]}</span>
        </span>
        <span className="lg-chk-v">{checkValue(cp, r, status)}</span>
      </button>
      {removing && (
        <button className="lg-chk-x" type="button" aria-label={`「${label}」のチェックを外す`} onClick={() => remove(cp.id)}>
          外す
        </button>
      )}
      <div className="lg-chk-body" id={bodyId}>
        {open ? (
          <>
            <p className="lg-chk-d">{r.reason}</p>
            {causes.length > 0 && cp.kind !== 'required' && (
              <ul className="lg-causes">
                {causes.map((c) => {
                  const href = courseHref(c.code, { kind: 'status' })
                  return (
                    <li key={c.code}>
                      <Link to={href} state={{ trail: [{ label: 'プラン', href: DIAGNOSE_HREF }, { label: c.name, href }], tab: 'search' }}>
                        {c.name}
                      </Link>
                    </li>
                  )
                })}
              </ul>
            )}
          </>
        ) : fillHref !== undefined ? (
          <p className="lg-fix">
            <span>{detail}</span>
            <Link className="lg-tbtn" to={fillHref}>
              入れる
            </Link>
          </p>
        ) : (
          detail !== '' && <p className="lg-chk-d">{detail}</p>
        )}
        {move !== undefined && <MoveFix cp={cp} move={move} />}
      </div>
    </li>
  )
}

/** 直し方の1行（例 ソフトボールは木2のクラスへ［移す］）。新しいクラスを入れてから、元のクラスを外す */
function MoveFix({ cp, move }: { cp: Checkpoint; move: ClassMove }) {
  const { announce } = useNavi()
  const { addToPlan, removeFromPlan } = useDiagnose()
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const where = move.toSlots.join('・')
  const run = async () => {
    setBusy(true)
    setFailed(false)
    const detail = { via: 'status', checkpoint_id: cp.id, moved_from: move.fromCode, moved_to: move.toCode }
    const r = await addToPlan(move.toCode, 'check_fix', detail)
    setBusy(false)
    if (r !== 'added' && r !== 'already') {
      setFailed(true)
      return
    }
    removeFromPlan(move.fromCode, 'check_fix', detail)
    announce(`${move.fromName}を${where}のクラスへ移しました。`)
  }
  return (
    <p className="lg-fix">
      <span>{failed ? `${where}のクラスを入れられませんでした` : `${move.fromName}は${where}のクラスへ`}</span>
      <button className="lg-tbtn" type="button" disabled={busy} onClick={() => void run()}>
        移す
      </button>
    </p>
  )
}

/**
 * チェック「もう取った科目」（取った科目を記録しているときだけ）。見ている学期のプランに、取った科目と同じ名前の科目が
 * あれば、その科目と取った学期と［外す］を出す。利用者が足し外しするチェックではない（調査のモードでは出ない）
 */
function RepeatRow({ repeats }: { repeats: RepeatCourse[] }) {
  const { announce } = useNavi()
  const { removeFromPlan } = useDiagnose()
  const ok = repeats.length === 0
  return (
    <li className={`lg-chk is-${ok ? 'met' : 'unmet'}`}>
      <div className="lg-chk-row">
        <Icon name={ok ? 'check' : 'warn'} small />
        <span className="lg-chk-l">
          もう取った科目<span className="vh">、{ok ? CHECK_STATUS_WORD.met : CHECK_STATUS_WORD.unmet}</span>
        </span>
        <span className="lg-chk-v">{ok ? 'なし' : repeats.length}</span>
      </div>
      {!ok && (
        <div className="lg-chk-body">
          {repeats.map((r) => (
            <p key={r.code} className="lg-fix">
              <span>
                {r.name}は{termLabel(r.takenIn)}に取った
              </span>
              <button
                className="lg-tbtn"
                type="button"
                aria-label={`${r.name}をプランから外す`}
                onClick={() => {
                  removeFromPlan(r.code, 'manual', { via: 'status' })
                  announce(`${r.name}をプランから外しました。`)
                }}
              >
                外す
              </button>
            </p>
          ))}
        </div>
      )}
    </li>
  )
}

interface ChecklistProps {
  view: LedgerView
  id?: string
}

/** チェックの一覧。いま見ている学期の分・ほかの学期の要確認・プラン全体の分。外す・足すは見出しと最後のボタンから */
export function Checklist({ view, id }: ChecklistProps) {
  const { setFocusTerm } = useNavi()
  const headingId = useId()
  const [removing, setRemoving] = useState(false)
  const [adding, setAdding] = useState(false)
  const pairs = (results: CheckResult[]) =>
    results.flatMap((r) => {
      const cp = view.checkpoints.find((c) => c.id === r.id)
      return cp === undefined ? [] : [{ cp, r }]
    })
  const here = pairs(view.here.results)
  const whole = pairs(view.planResults)
  const moves = useClassMoves(view)
  const history = view.history
  // 取った科目を記録しているときは、今の学期より前の学期に学期ごとのチェックを出さない
  const showTerm = history === null ? here.length > 0 || view.others.length > 0 : !history.past
  /** 前のまとまりの抜けが未記入の学期で判定できないとき、理由に挙がった最初の未記入の学期へ（取った科目の画面） */
  const fillHref = (r: CheckResult): string | undefined => {
    if (history === null || r.kind !== 'prerequisite' || r.status !== 'unknown') return undefined
    const term = history.unrecorded.find((t) => r.reason.includes(termLabel(t)))
    return term === undefined ? undefined : historyHref(term)
  }
  return (
    <section className="lg-checks" id={id} data-role="checklist" aria-labelledby={headingId}>
      <div className="lg-checks-head">
        <h2 id={headingId}>チェック</h2>
        {view.checkpoints.length > 0 && (
          <button className="lg-tbtn" type="button" aria-pressed={removing} onClick={() => setRemoving((v) => !v)}>
            {removing ? '外し終わる' : 'チェックを外す'}
          </button>
        )}
      </div>
      {showTerm && (
        <>
          <h3 className="lg-scope">{termLabel(view.term)}</h3>
          <ul>
            {here.map(({ cp, r }) => (
              <CheckRow key={cp.id} cp={cp} r={r} status={view.here.status} removing={removing} move={moves.get(cp.id)} />
            ))}
            {history !== null && <RepeatRow repeats={history.repeats} />}
            {view.others.length > 0 && (
              <li className="lg-chk lg-other is-unmet">
                <Icon name="warn" small />
                <span className="lg-chk-l">
                  ほかの学期<span className="vh">、要確認</span>
                </span>
                <span className="lg-chk-v">
                  {view.others.map((o) => (
                    <button key={termLabel(o.term)} className="lg-go" type="button" onClick={() => setFocusTerm(o.term)}>
                      {termLabel(o.term)} {o.unmet}件
                    </button>
                  ))}
                </span>
              </li>
            )}
          </ul>
        </>
      )}
      {whole.length > 0 && (
        <>
          <h3 className="lg-scope">{history === null ? 'プラン全体' : '取った科目とプラン'}</h3>
          <ul>
            {whole.map(({ cp, r }) => (
              <CheckRow
                key={cp.id}
                cp={cp}
                r={r}
                status={view.status}
                removing={removing}
                move={undefined}
                fillHref={fillHref(r)}
              />
            ))}
          </ul>
        </>
      )}
      {view.checkpoints.length === 0 && <p className="lg-empty">チェックはありません。</p>}
      {adding ? (
        <div className="lg-form">
          <CheckpointForm onAdded={() => setAdding(false)} onCancel={() => setAdding(false)} />
        </div>
      ) : (
        <button className="lg-add" type="button" onClick={() => setAdding(true)}>
          <Icon name="plus" small />
          チェックを足す
        </button>
      )}
    </section>
  )
}
