import { useId, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../../navi/study.css'
import { findCourse } from '../../navi/graph'
import { rememberedCourseName } from '../../navi/keyword'
import { currentTaskId, useStudy } from '../../navi/research'
import { useNavi } from '../../navi/state'
import { blockLabel, DRAFT_MARK, TASKS } from '../../navi/studyConfig'
import type { TaskDef } from '../../navi/studyConfig'
import { submitTask } from '../../navi/studyFlow'
import { WIDE_SPACE } from '../../navi/views'
import Icon from './Icon'

interface TaskBriefProps {
  taskId: string
  task: TaskDef | undefined
}

/** ペルソナの文と課題の文（調査の入口の課題の前の画面と、画面の上の課題の帯で同じものを出す） */
export function TaskBrief({ taskId, task }: TaskBriefProps) {
  if (task === undefined) {
    return <p className="text">課題「{taskId}」の文が設定にありません。研究者に知らせてください。</p>
  }
  return (
    <>
      <p className="task-persona">
        {task.persona}
        {task.draft && <span className="draft">{DRAFT_MARK}</span>}
      </p>
      <p className="task-prompt">{task.prompt}</p>
    </>
  )
}

/**
 * 課題の帯（調査中、画面の上の帯の場所に出す）。ペルソナと課題の文、［答える］で答えの欄を開く。
 * 答えは候補（＋で入れた科目）から選び、課題によって文も書く。送ると task_submit を記録して調査の入口へ戻る。
 */
export default function TaskCard() {
  const study = useStudy()
  const { dept, shortlist, ask } = useNavi()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [text, setText] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const formId = useId()

  if (study === null || study.phase.kind !== 'task' || study.plan === null) return null
  const { block, taskIndex } = study.phase
  const taskId = currentTaskId(study) ?? ''
  const task = TASKS[taskId]
  const picks = task?.picks ?? 0
  const textAnswer = task?.text ?? null
  const gatePath = study.gatePath
  const chosen = selected.filter((code) => shortlist.includes(code))

  const nameOf = (code: string) =>
    findCourse(dept, code)?.name ?? rememberedCourseName(code) ?? ask?.result?.sources.find((s) => s.code === code)?.title ?? code

  const toggle = (code: string) => {
    setProblem(null)
    if (picks === 1) {
      setSelected([code])
      return
    }
    setSelected((cur) => (cur.includes(code) ? cur.filter((c) => c !== code) : [...cur, code]))
  }

  const send = (gaveUp: boolean) => {
    if (!gaveUp && chosen.length !== picks) {
      setProblem(`候補から${picks}つ選んでください。`)
      return
    }
    if (!gaveUp && textAnswer !== null && text.trim() === '') {
      setProblem(`${textAnswer.label}を書いてください。`)
      return
    }
    submitTask({
      selected: chosen,
      texts: { ...(textAnswer === null ? {} : { [textAnswer.id]: text.trim() }), ...(gaveUp ? { gave_up: 'true' } : {}) },
    })
    navigate(gatePath)
  }

  return (
    <section className="task-band" aria-label="課題">
      <div className="task-head">
        <p className="task-label">
          {blockLabel(block)}{WIDE_SPACE}課題{taskIndex + 1}/{study.plan.task_ids.length}
        </p>
        <button className="band-btn" type="button" aria-expanded={open} aria-controls={formId} onClick={() => setOpen((o) => !o)}>
          {open ? '答えを閉じる' : '答える'}
        </button>
      </div>
      <TaskBrief taskId={taskId} task={task} />
      <div id={formId} hidden={!open} className="task-answer">
        {picks > 0 && (
          <fieldset className="q-item">
            <legend className="q-legend">候補から{picks}つ選ぶ</legend>
            {shortlist.length === 0 ? (
              <p className="text">まだ候補がありません。科目の＋で候補に入れてください。</p>
            ) : (
              <ul className="pick-list">
                {shortlist.map((code) => (
                  <li key={code}>
                    <label>
                      <input
                        type={picks === 1 ? 'radio' : 'checkbox'}
                        name={`${formId}-pick`}
                        checked={chosen.includes(code)}
                        onChange={() => toggle(code)}
                      />
                      <span>{nameOf(code)}</span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </fieldset>
        )}
        {textAnswer !== null && (
          <label className="q-text">
            <span className="q-legend">{textAnswer.label}</span>
            <textarea
              value={text}
              onChange={(e) => {
                setText(e.target.value)
                setProblem(null)
              }}
            />
          </label>
        )}
        {problem !== null && (
          <p className="msg-line q-problem" role="alert">
            <span className="ic-wrap">
              <Icon name="warn" small />
            </span>
            <span>{problem}</span>
          </p>
        )}
        <div className="page-acts">
          <button className="primary" type="button" onClick={() => send(false)}>
            答えを送る
          </button>
          <button className="text-btn" type="button" onClick={() => send(true)}>
            見つからないまま送る
          </button>
        </div>
      </div>
    </section>
  )
}
