import { useId } from 'react'
import { useNavigate } from 'react-router-dom'
import '../../navi/term.css'
import { DIAGNOSE_HREF, useNavi } from '../../navi/state'
import type { TermKey } from '../../navi/timetable'
import { ALL_TERMS, MAX_YEAR, sameTerm, termIndex, termLabel } from '../../navi/timetable'
import { TERM_WORD } from '../../navi/useLedger'
import type { TermCell } from '../../navi/useLedger'
import { useHistory } from '../../navi/useHistory'

const YEARS = Array.from({ length: MAX_YEAR }, (_, i) => i + 1)
const HALVES = ['春', '秋'] as const

function cellText(c: TermCell): string {
  switch (c.kind) {
    case 'past':
      return String(c.credits ?? 0)
    case 'unrecorded':
      return '未記入'
    case 'current':
      return `今 ${c.credits ?? 0}`
    case 'planned':
      return '予定'
    case 'none':
      return '—'
  }
}

interface TermTableProps {
  cells: TermCell[]
  /** 見ている学期（輪を付ける） */
  view: TermKey
  onPick: (t: TermKey) => void
  takenCredits: number
  unrecorded: number
}

/**
 * 学期の表（1〜4年 × 春・秋の8マス。学期のコンペの T-a）。過去は取った単位（未記入は破線と「未記入」）、今は緑の地と
 * 「今」とプランの単位、先は「予定」（プランの無い学期は —）。押すと見る学期が変わる（今の学期は変わらない）
 */
export function TermTable({ cells, view, onPick, takenCredits, unrecorded }: TermTableProps) {
  return (
    <div className="tt8" data-role="term-switch">
      <table className="tt8-grid">
        <caption className="vh">学期の表</caption>
        <thead>
          <tr>
            <th scope="col">
              <span className="vh">学期</span>
            </th>
            {YEARS.map((y) => (
              <th key={y} scope="col">
                {y}年
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {HALVES.map((half) => (
            <tr key={half}>
              <th scope="row">{half}</th>
              {YEARS.map((year) => {
                const c = cells.find((x) => x.term.year === year && x.term.half === half)
                if (c === undefined) return <td key={year} />
                const on = sameTerm(c.term, view)
                return (
                  <td key={year}>
                    <button
                      className={`tt8-c is-${c.kind}${on ? ' is-view' : ''}`}
                      type="button"
                      aria-pressed={on}
                      aria-label={`${termLabel(c.term)}、${TERM_WORD[c.kind]}${c.credits !== null ? `、${c.credits}単位` : ''}`}
                      onClick={() => onPick(c.term)}
                    >
                      {cellText(c)}
                    </button>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="tt8-sum">
        <span>
          取った単位<span className="num">{takenCredits}</span>
        </span>
        {unrecorded > 0 && <span>未記入 {unrecorded}学期</span>}
      </p>
    </div>
  )
}

interface TermPickerProps {
  /** first: 初めに今の学期を選ぶ、fix: メニューから今の学期を直す */
  mode: 'first' | 'fix'
}

/**
 * 今の学期をえらぶ（初めに1回。メニューの「今の学期を直す」からも）。学期の表と同じ形の8つのボタンを1回押す。
 * 初めに1年春より後を選んだら、続けて取った科目の画面へ（［あとで］で飛ばせる）
 */
export function TermPicker({ mode }: TermPickerProps) {
  const { setFocusTerm } = useNavi()
  const history = useHistory()
  const navigate = useNavigate()
  const choose = (t: TermKey) => {
    setFocusTerm(t)
    if (mode === 'fix') {
      history.fixCurrent(t)
      navigate(DIAGNOSE_HREF)
      return
    }
    history.pick(t)
    if (termIndex(t) > 0) navigate('/navi/history?from=pick')
  }
  const current = history.current
  const titleId = useId()
  return (
    <section className="tp" aria-labelledby={titleId}>
      <h1 className="pl-title" id={titleId}>
        {mode === 'first' ? 'どの学期の時間割を組みますか' : '今の学期を直す'}
      </h1>
      <table className="tt8-grid tp-grid" data-role="term-switch">
        <caption className="vh">学期</caption>
        <thead>
          <tr>
            <th scope="col">
              <span className="vh">学期</span>
            </th>
            {YEARS.map((y) => (
              <th key={y} scope="col">
                {y}年
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {HALVES.map((half) => (
            <tr key={half}>
              <th scope="row">{half}</th>
              {YEARS.map((year) => {
                const t = ALL_TERMS.find((x) => x.year === year && x.half === half) ?? { year, half }
                const on = current !== null && sameTerm(current, t)
                return (
                  <td key={year}>
                    <button className={on ? 'tt8-c is-current' : 'tt8-c'} type="button" aria-pressed={on} onClick={() => choose(t)}>
                      {termLabel(t)}
                    </button>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
