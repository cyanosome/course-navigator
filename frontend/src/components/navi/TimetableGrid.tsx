import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { findCourse } from '../../navi/graph'
import { courseHref, TIMETABLE_HREF, useNavi } from '../../navi/state'
import type { PcTab } from '../../navi/state'
import { DAYS, gridSlots, isRequired, PERIODS, placedInTerm, shortName, slotMap, termLabel } from '../../navi/timetable'
import type { TermKey } from '../../navi/timetable'
import type { Course } from '../../navi/types'

interface TimetableGridProps {
  term: TermKey
  /** 入れる前の下見（緑の破線。E1 5章・W11）。空いたマスにだけ描く */
  previewCode?: string | null
  /** PC の右の段（マスを低くする） */
  pc?: boolean
  /** マスを押して詳細へ進むときに積むタブ */
  tab: PcTab
}

/**
 * 時間割の表（曜日×時限。E1 5章）。必修は灰の地と灰の文字、候補は薄い緑の地、重なりは赤い枠で2科目の略称を縦に並べる。
 * 空きは細い枠だけ。マスを押すとその科目の詳細へ。
 */
export default function TimetableGrid({ term, previewCode = null, pc = false, tab }: TimetableGridProps) {
  const { dept, shortlist } = useNavi()
  const map = slotMap(placedInTerm(dept, shortlist, term))
  const preview = previewCode === null ? undefined : findCourse(dept, previewCode)
  const previewSlots = new Set(preview === undefined ? [] : gridSlots(preview))

  const cellLink = (course: Course, className: string, label: string, children: ReactNode) => {
    const href = courseHref(course.code, { kind: 'tt' })
    return (
      <Link
        className={className}
        to={href}
        state={{ trail: [{ label: '時間割', href: TIMETABLE_HREF }, { label: course.name, href }], tab }}
        aria-label={label}
      >
        {children}
      </Link>
    )
  }

  return (
    <div className="tt-wrap">
      <table className={pc ? 'tt is-pc' : 'tt'}>
        <caption className="vh">{termLabel(term)}の時間割</caption>
        <colgroup>
          <col className="p" />
          {DAYS.map((d) => (
            <col key={d} />
          ))}
        </colgroup>
        <thead>
          <tr>
            <th scope="col">
              <span className="vh">時限</span>
            </th>
            {DAYS.map((d) => (
              <th key={d} scope="col">
                {d}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {PERIODS.map((p) => (
            <tr key={p}>
              <th scope="row">{p}</th>
              {DAYS.map((d) => {
                const slot = `${d}${p}`
                const here = map.get(slot) ?? []
                const first = here[0]
                if (here.length > 1 && first !== undefined) {
                  const target = here.find((c) => !isRequired(c)) ?? first
                  return (
                    <td key={slot}>
                      {cellLink(
                        target,
                        'cell clash',
                        `${slot}: ${here.map((c) => c.name).join('と')}が重なっています`,
                        here.map((c) => <span key={c.code}>{shortName(c)}</span>),
                      )}
                    </td>
                  )
                }
                if (first !== undefined) {
                  const req = isRequired(first)
                  return (
                    <td key={slot}>
                      {cellLink(first, req ? 'cell req' : 'cell cand', `${slot}: ${first.name}（${req ? '必修' : '候補'}）`, shortName(first))}
                    </td>
                  )
                }
                if (preview !== undefined && previewSlots.has(slot)) {
                  return (
                    <td key={slot}>
                      <div className="cell preview" aria-label={`${slot}: ${preview.name}を入れるとここに入ります`}>
                        {shortName(preview)}
                      </div>
                    </td>
                  )
                }
                return (
                  <td key={slot}>
                    <div className="cell" aria-label={`${slot}: 空き`} />
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
