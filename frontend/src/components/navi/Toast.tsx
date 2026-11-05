import { useEffect, useState } from 'react'
import { findCourse } from '../../navi/graph'
import { useNavi } from '../../navi/state'
import type { ToastState } from '../../navi/state'
import { DAYS, gridSlots, isOnGrid, isRequired, PERIODS, placedInTerm, slotMap, termsOf } from '../../navi/timetable'
import type { Course } from '../../navi/types'
import { addedNotice } from '../../navi/views'

/** 候補に入れた知らせを出しておく時間（E1 5章: 160ms で出て 2.4 秒、240ms で消える） */
const ADDED_MS = 2_400
/** 動きを減らす設定では、動かさずに長めに出す */
const ADDED_REDUCED_MS = 4_000
/** ［元に戻す］つきの知らせ（E1 10章: 5 秒） */
const REMOVED_MS = 5_000
const LEAVE_MS = 240

/** 一瞬だけ出る知らせ。id が変わるたびに出し直す */
export default function Toast() {
  const { toast } = useNavi()
  if (toast === null) return null
  return <ToastView key={toast.id} toast={toast} />
}

interface ToastViewProps {
  toast: ToastState
}

function ToastView({ toast }: ToastViewProps) {
  const { dept, shortlist, focusTerm, reducedMotion, clearToast, undoRemove } = useNavi()
  const [leaving, setLeaving] = useState(false)
  /** ［元に戻す］にフォーカスやマウスがあるあいだは消さない（押す前に消えないように） */
  const [held, setHeld] = useState(false)
  const stay = toast.kind === 'removed' ? REMOVED_MS : reducedMotion ? ADDED_REDUCED_MS : ADDED_MS

  useEffect(() => {
    if (held) return
    const timer = setTimeout(() => setLeaving(true), stay)
    return () => clearTimeout(timer)
  }, [held, stay])

  useEffect(() => {
    if (!leaving) return
    const timer = setTimeout(() => clearToast(toast.id), reducedMotion ? 0 : LEAVE_MS)
    return () => clearTimeout(timer)
  }, [leaving, reducedMotion, clearToast, toast.id])

  const course = findCourse(dept, toast.code)
  if (course === undefined) return null
  const className = leaving ? 'toast is-leaving' : 'toast'

  if (toast.kind === 'removed') {
    return (
      <div
        className={className}
        onMouseEnter={() => setHeld(true)}
        onMouseLeave={() => setHeld(false)}
        onFocus={() => setHeld(true)}
        onBlur={() => setHeld(false)}
      >
        <p className="toast-text">{course.name}を外しました</p>
        <button className="toast-undo" type="button" onClick={() => undoRemove(toast)}>
          元に戻す
        </button>
      </div>
    )
  }

  const notice = addedNotice(dept, shortlist, course, focusTerm)
  return (
    // 状態は読み上げ用の領域で1回だけ言うので、知らせそのものは読み上げない（E1 5章）
    <div className={className} aria-hidden="true">
      {isOnGrid(course) && <MiniTimetable course={course} />}
      <div className="toast-text">
        <span>{notice.main}</span>
        <span className="toast-sub">{notice.sub}</span>
      </div>
    </div>
  )
}

interface MiniTimetableProps {
  course: Course
}

/** 知らせの中の小さな時間割（5日×5限）。必修は灰、いま入れたマスは緑、ほかの候補は緑の輪、空きは枠だけ */
function MiniTimetable({ course }: MiniTimetableProps) {
  const { dept, shortlist } = useNavi()
  const term = termsOf(course)[0]
  if (term === undefined) return null
  const map = slotMap(placedInTerm(dept, shortlist, term))
  const mine = new Set(gridSlots(course))
  return (
    <div className="mini">
      {DAYS.map((d) => (
        <span key={d} className="d">
          {d}
        </span>
      ))}
      {PERIODS.flatMap((p) =>
        DAYS.map((d) => {
          const slot = `${d}${p}`
          const here = map.get(slot) ?? []
          const cls = mine.has(slot)
            ? 'm new'
            : here.some(isRequired)
              ? 'm req'
              : here.length > 0
                ? 'm cand'
                : 'm'
          return <i key={slot} className={cls} />
        }),
      )}
    </div>
  )
}
