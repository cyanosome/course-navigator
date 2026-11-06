import { findCourse } from '../../navi/graph'
import { useNavi } from '../../navi/state'
import { clashesOf, courseTermLabel, gridSlots, inTerm, isRequired, termCredits, termLabel } from '../../navi/timetable'
import type { TermKey } from '../../navi/timetable'
import type { Course, Department } from '../../navi/types'
import TimetableGrid from './TimetableGrid'

interface TimetableSideProps {
  /** 中央で見ている科目（入る前の下見を描く） */
  previewCode: string | null
}

/**
 * PC の右の段（E1 4章 W11）。いま見ている学期の時間割に、中央で見ている科目が入るマスを緑の破線で先に描き、
 * 下に1文で「月2は空いています。入れると7単位です。」のように書く。1199px 以下では隠す（CSS）。
 */
export default function TimetableSide({ previewCode }: TimetableSideProps) {
  const { dept, shortlist, focusTerm, isKept } = useNavi()
  const credits = termCredits(dept, shortlist, focusTerm)
  const course = previewCode === null ? undefined : findCourse(dept, previewCode)
  const kept = course !== undefined && isKept(course.code)
  const canPreview = course !== undefined && !kept && !isRequired(course) && inTerm(course, focusTerm)
  return (
    <>
      <div className="pc-tt-h">
        <h2>{termLabel(focusTerm)}の時間割</h2>
        <p className="term-sum">
          <span>
            <span className="num">{credits}</span>単位
          </span>
          {dept.requirements !== null && <span>上限 {dept.requirements.termCap}</span>}
        </p>
      </div>
      <ul className="legend" aria-hidden="true">
        <li>
          <i className="sw req" />
          必修
        </li>
        <li>
          <i className="sw cand" />
          候補
        </li>
      </ul>
      <TimetableGrid term={focusTerm} previewCode={canPreview ? course.code : null} pc tab="search" />
      {course !== undefined && <p className="pc-tt-note">{sideNote(dept, shortlist, focusTerm, course, kept, credits)}</p>}
    </>
  )
}

function sideNote(dept: Department, shortlist: string[], focusTerm: TermKey, course: Course, kept: boolean, credits: number): string {
  if (!inTerm(course, focusTerm)) return `${course.name}は${courseTermLabel(course)}の科目です。この表は${termLabel(focusTerm)}です。`
  const where = gridSlots(course).join('・')
  if (isRequired(course)) return `${course.name}は必修なので、${where === '' ? '曜限なし' : where}に入れてあります。`
  if (kept) return `${course.name}は${where === '' ? '曜限なし' : where}に入っています。`
  const clash = clashesOf(dept, shortlist, course)[0]
  if (clash !== undefined) return `${clash.slot}は${clash.other.name}と重なります。`
  const after = credits + (course.credits ?? 0)
  if (where === '') return `${course.name}は曜限がありません。入れると${after}単位です。`
  return `${where}は空いています。入れると${after}単位です。`
}
