import '../../navi/term.css'
import type { TakenCourse } from '../../navi/history'

interface TakenRowProps {
  course: TakenCourse
  checked: boolean
  onToggle: () => void
  /** 科目名の下の灰の1行（例 3クラス、通年・秋も続く） */
  note?: string
}

/** 取った科目のチェックの行（チェック・曜限（分かるときだけ）・科目名・単位）。取った科目・学期の切り替わり・ほかの科目で使う */
export default function TakenRow({ course, checked, onToggle, note }: TakenRowProps) {
  return (
    <li>
      <label className="hc">
        <input type="checkbox" checked={checked} onChange={onToggle} />
        <span className="hc-slot">{course.slots?.join('・') ?? ''}</span>
        <span className="hc-body">
          <span>{course.name}</span>
          {note !== undefined && <span className="hc-sub">{note}</span>}
        </span>
        <span className="hc-cr">{course.credits === null ? '' : `${course.credits}単位`}</span>
      </label>
    </li>
  )
}
